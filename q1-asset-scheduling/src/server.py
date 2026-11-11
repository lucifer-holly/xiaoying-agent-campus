"""演示服务：同一套 Agent 外包一层 HTTP API，并托管回放页（只用标准库，没有额外依赖）。

    python src/server.py --host 127.0.0.1 --port 8710

GET  /             回放页；服务端配置了模型和访问口令时，页面会多出“实时运行”
GET  /api/health   健康检查（不包含密钥、端点等任何私有信息）
POST /api/run      用真实模型跑一次排期申请

防护：按 IP 限流（DEMO_RATE_LIMIT，默认 5 次/600 秒）、每日调用上限（DEMO_DAILY_LIMIT，默认 50，跨重启累计）、
并发上限（DEMO_MAX_CONCURRENCY，默认 2）。访问口令（DEMO_ACCESS_CODE）可选：留空时任何人都能直接运行。
超限或未配置模型时返回 fallback=replay，页面自动切到回放。
每次运行都用独立的内存草稿库，只读合成数据；系统没有发布能力。
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.llm import LLMUnavailable, QwenLLM  # noqa: E402
from config import PROJECT_ROOT, llm_settings  # noqa: E402
from domain.faults import MODES, TOOLS  # noqa: E402
from domain.scheduling import CHANNEL_ALIASES, CHANNELS  # noqa: E402
from domain.store import DataStore  # noqa: E402
from main import load_case, run_case  # noqa: E402

CST = timezone(timedelta(hours=8))
DEMO_DIR = PROJECT_ROOT / "demo"
EXAMPLES = PROJECT_ROOT / "examples"
MAX_BODY = 16 * 1024
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml", ".png": "image/png", ".ico": "image/x-icon", ".txt": "text/plain; charset=utf-8",
}
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "X-Frame-Options": "DENY",
    "Content-Security-Policy": "default-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'",
}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, fallback: bool = False, retry_after: int | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.fallback, self.retry_after = status, code, message, fallback, retry_after

    def body(self) -> dict:
        err = {"code": self.code, "message": self.message}
        if self.fallback:
            err["fallback"] = "replay"
        if self.retry_after:
            err["retry_after_s"] = self.retry_after
        return {"ok": False, "error": err}


# ---- 配置与防护 ---------------------------------------------------------------
@dataclass
class DemoConfig:
    access_code: str
    rate_count: int
    rate_window_s: int
    daily_limit: int
    max_concurrency: int
    state_dir: Path

    @classmethod
    def from_env(cls, state_dir: Path) -> "DemoConfig":
        match = re.fullmatch(r"\s*(\d+)\s*/\s*(\d+)\s*", os.environ.get("DEMO_RATE_LIMIT", ""))
        count, window = (int(match.group(1)), int(match.group(2))) if match else (5, 600)
        return cls(
            access_code=os.environ.get("DEMO_ACCESS_CODE", "").strip(),
            rate_count=count,
            rate_window_s=window,
            daily_limit=int(os.environ.get("DEMO_DAILY_LIMIT") or 50),
            max_concurrency=max(1, int(os.environ.get("DEMO_MAX_CONCURRENCY") or 2)),
            state_dir=state_dir,
        )


class Guard:
    """访问口令、按 IP 限流、每日上限、并发上限。每日计数落盘，重启不清零。"""

    FAIL_LIMIT, FAIL_WINDOW_S = 10, 600

    def __init__(self, cfg: DemoConfig):
        self.cfg = cfg
        self._lock = threading.Lock()
        self._hits: dict[str, deque] = {}
        self._fails: dict[str, deque] = {}
        self._slots = threading.BoundedSemaphore(cfg.max_concurrency)
        self._quota_path = cfg.state_dir / "quota.json"
        self._quota = self._load_quota()

    @staticmethod
    def _today() -> str:
        return datetime.now(CST).strftime("%Y-%m-%d")

    def _load_quota(self) -> dict:
        try:
            data = json.loads(self._quota_path.read_text(encoding="utf-8"))
            if data.get("date") == self._today():
                return {"date": data["date"], "used": int(data.get("used", 0))}
        except (OSError, ValueError):
            pass
        return {"date": self._today(), "used": 0}

    def _save_quota(self) -> None:
        try:
            self.cfg.state_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.cfg.state_dir, prefix=".quota-")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self._quota, fh)
            os.replace(tmp, self._quota_path)
        except OSError as exc:  # 计数写不进去不影响服务，只是重启后会清零
            print(f"[warn] 每日计数写入失败：{exc}", file=sys.stderr, flush=True)

    @staticmethod
    def _window(store: dict, key: str, seconds: int, now: float) -> deque:
        q = store.setdefault(key, deque())
        while q and now - q[0] > seconds:
            q.popleft()
        return q

    def check_access(self, ip: str, code: str) -> None:
        now = time.time()
        with self._lock:
            fails = self._window(self._fails, ip, self.FAIL_WINDOW_S, now)
            if len(fails) >= self.FAIL_LIMIT:
                raise ApiError(429, "ACCESS_LOCKED", "口令错误次数过多，请 10 分钟后再试", fallback=True)
            if not hmac.compare_digest(code.encode("utf-8"), self.cfg.access_code.encode("utf-8")):
                fails.append(now)
                raise ApiError(403, "ACCESS_DENIED", "访问口令不正确", fallback=True)

    def reserve(self, ip: str) -> None:
        now = time.time()
        with self._lock:
            if self._quota["date"] != self._today():
                self._quota = {"date": self._today(), "used": 0}
            if self._quota["used"] >= self.cfg.daily_limit:
                raise ApiError(429, "DAILY_LIMIT", f"今天的实时调用次数已用完（{self.cfg.daily_limit} 次），已切换到回放", fallback=True)
            hits = self._window(self._hits, ip, self.cfg.rate_window_s, now)
            if len(hits) >= self.cfg.rate_count:
                wait = int(self.cfg.rate_window_s - (now - hits[0])) + 1
                raise ApiError(429, "RATE_LIMITED", f"请求太频繁（每 {self.cfg.rate_window_s} 秒最多 {self.cfg.rate_count} 次），已切换到回放", fallback=True, retry_after=wait)
            hits.append(now)
            self._quota["used"] += 1
            self._save_quota()

    def try_acquire(self) -> bool:
        return self._slots.acquire(blocking=False)

    def release(self) -> None:
        self._slots.release()

    def quota(self) -> dict:
        with self._lock:
            used = self._quota["used"] if self._quota["date"] == self._today() else 0
        return {"daily_limit": self.cfg.daily_limit, "used_today": used,
                "per_ip": f"{self.cfg.rate_count} 次 / {self.cfg.rate_window_s} 秒"}


# ---- 请求校验：实时运行只接受受限的申请单 --------------------------------------
_PUBLISH_AT = re.compile(r"^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}$")
_ASSET_ID = re.compile(r"^[A-Za-z0-9-]{1,12}$")


def build_live_case(body: dict, presets: dict[str, dict]) -> dict:
    if not isinstance(body, dict):
        raise ApiError(400, "BAD_REQUEST", "请求体必须是 JSON 对象")
    base = presets.get(body.get("case_id") or "")
    if body.get("case_id") and base is None:
        raise ApiError(400, "BAD_REQUEST", f"没有这个用例：{body.get('case_id')}")
    raw = body.get("request")
    if raw is None and base is None:
        raise ApiError(400, "BAD_REQUEST", "需要 case_id 或 request")
    req = copy.deepcopy(base["request"]) if base else {}
    if raw is not None:
        if not isinstance(raw, dict):
            raise ApiError(400, "BAD_REQUEST", "request 必须是对象")
        for key in ("asset_id", "channel", "publish_at", "requester", "note", "instructions"):
            if key in raw:
                req[key] = raw[key]
        if "constraints" in raw:
            req["constraints"] = {"date_fixed": bool((raw.get("constraints") or {}).get("date_fixed"))}
    problems = []
    if not isinstance(req.get("asset_id"), str) or not _ASSET_ID.match(req["asset_id"]):
        problems.append("asset_id 格式不对")
    if req.get("channel") not in CHANNELS and req.get("channel") not in CHANNEL_ALIASES:
        problems.append(f"channel 只能是 {', '.join(CHANNELS)}")
    if not isinstance(req.get("publish_at"), str) or not _PUBLISH_AT.match(req["publish_at"]):
        problems.append("publish_at 格式应为 YYYY-MM-DD HH:MM")
    for key, limit in (("note", 200), ("requester", 40), ("instructions", 300)):
        if key in req and (not isinstance(req[key], str) or len(req[key]) > limit):
            problems.append(f"{key} 必须是不超过 {limit} 字的字符串")
    faults = body.get("fault_injection", base.get("fault_injection") if base else {}) or {}
    if not isinstance(faults, dict) or any(k not in TOOLS or v not in MODES for k, v in faults.items()):
        problems.append("fault_injection 只能使用已定义的工具和模式")
    repeat = body.get("repeat", (base or {}).get("options", {}).get("repeat", 1))
    max_steps = body.get("max_steps", (base or {}).get("options", {}).get("max_steps", 8))
    if repeat not in (1, 2):
        problems.append("repeat 只能是 1 或 2")
    if not isinstance(max_steps, int) or not 1 <= max_steps <= 8:
        problems.append("max_steps 取值 1~8")
    if problems:
        raise ApiError(400, "BAD_REQUEST", "；".join(problems))
    req["request_id"] = "LIVE-" + secrets.token_hex(3).upper()
    return {
        "case": f"live-{body.get('case_id') or 'custom'}",
        "request": req,
        "fault_injection": faults,
        "options": {"repeat": repeat, "max_steps": max_steps},
    }


# ---- 应用 -------------------------------------------------------------------
class App:
    def __init__(self, state_dir: Path):
        self.cfg = DemoConfig.from_env(state_dir)
        self.guard = Guard(self.cfg)
        self.presets = {c["case"]: c for c in (load_case(p) for p in sorted(EXAMPLES.glob("*.input.json")))}
        try:
            self.llm = QwenLLM(llm_settings())
        except LLMUnavailable:
            self.llm = None
        self.started_at = datetime.now(CST).isoformat(timespec="seconds")
        self.version = self._version()

    @staticmethod
    def _version() -> str:
        path = PROJECT_ROOT / "VERSION"
        return path.read_text(encoding="utf-8").strip() if path.exists() else "dev"

    @property
    def live_enabled(self) -> bool:
        return self.llm is not None

    @property
    def access_code_required(self) -> bool:
        return bool(self.cfg.access_code)

    def health(self) -> dict:
        return {
            "ok": True,
            "service": "xiaoying-agent",
            "version": self.version,
            "started_at": self.started_at,
            "live_enabled": self.live_enabled,
            "access_code_required": self.access_code_required,
            "model": self.llm.model if self.llm else None,
            "quota": self.guard.quota(),
            "notice": "只保存排期草稿，不会真实发布；每次运行使用独立的内存草稿库",
        }

    def run(self, ip: str, body: dict) -> dict:
        if self.llm is None:
            raise ApiError(503, "LIVE_DISABLED", "服务端没有配置模型密钥，实时运行不可用，已切换到回放", fallback=True)
        if self.access_code_required:  # 只有配置了口令才校验；留空时任何人都能直接运行
            self.guard.check_access(ip, str(body.get("access_code") or ""))
        case = build_live_case(body, self.presets)
        if not self.guard.try_acquire():
            raise ApiError(503, "BUSY", "同时运行的人太多，请稍后再试，或先看回放", fallback=True, retry_after=15)
        try:
            self.guard.reserve(ip)
            started = time.monotonic()
            output, trace = run_case(case, llm=self.llm, store=DataStore())
            elapsed = round(time.monotonic() - started, 1)
        finally:
            self.guard.release()
        return {"ok": True, "case": case, "output": output, "trace": trace, "elapsed_s": elapsed, "quota": self.guard.quota()}


def make_handler(app: App):
    class Handler(BaseHTTPRequestHandler):
        server_version = "xiaoying-agent"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def _client_ip(self) -> str:
            peer = self.client_address[0]
            forwarded = self.headers.get("X-Forwarded-For")
            # 只信任本机反向代理（Caddy）带来的 X-Forwarded-For，取最右侧（代理看到的客户端地址）
            if forwarded and peer in ("127.0.0.1", "::1"):
                return forwarded.split(",")[-1].strip()
            return peer

        def _send(self, status: int, body: bytes, content_type: str, extra: dict | None = None) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            for k, v in {**SECURITY_HEADERS, **(extra or {})}.items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _json(self, status: int, payload: dict, extra: dict | None = None) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self._send(status, body, "application/json; charset=utf-8", {"Cache-Control": "no-store", **(extra or {})})

        def _static(self, path: str) -> None:
            rel = path.lstrip("/") or "index.html"
            target = (DEMO_DIR / rel).resolve()
            if target.is_dir():
                target = target / "index.html"
            if DEMO_DIR.resolve() not in target.parents or not target.is_file():
                return self._json(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "没有这个页面"}})
            # 文件都很小，统一 no-cache：部署后不会出现新数据配旧脚本的情况
            self._send(200, target.read_bytes(), CONTENT_TYPES.get(target.suffix, "application/octet-stream"), {"Cache-Control": "no-cache"})

        def do_GET(self) -> None:  # noqa: N802
            path = urlsplit(self.path).path
            if path == "/api/health":
                return self._json(200, app.health())
            if path.startswith("/api/"):
                return self._json(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "没有这个接口"}})
            return self._static(path)

        do_HEAD = do_GET

        def do_POST(self) -> None:  # noqa: N802
            if urlsplit(self.path).path != "/api/run":
                return self._json(404, {"ok": False, "error": {"code": "NOT_FOUND", "message": "没有这个接口"}})
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length > MAX_BODY:
                    raise ApiError(413, "TOO_LARGE", "请求体过大")
                try:
                    body = json.loads(self.rfile.read(length) or b"{}")
                except ValueError:
                    raise ApiError(400, "BAD_REQUEST", "请求体不是合法 JSON") from None
                result = app.run(self._client_ip(), body)
                self._json(200, result)
            except ApiError as exc:
                extra = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
                self._json(exc.status, exc.body(), extra)
            except Exception as exc:  # 兜底：不把堆栈暴露给访客
                print(f"[error] /api/run {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
                self._json(500, {"ok": False, "error": {"code": "INTERNAL_ERROR", "message": "服务内部错误，已切换到回放", "fallback": "replay"}})

        def log_message(self, fmt: str, *args) -> None:
            ip_tag = hashlib.sha256(self._client_ip().encode()).hexdigest()[:8]
            print(f"{datetime.now(CST).isoformat(timespec='seconds')} {ip_tag} {fmt % args}", file=sys.stderr, flush=True)

    return Handler


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Q1 演示服务")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT") or 8710))
    parser.add_argument("--state-dir", default=os.environ.get("DEMO_STATE_DIR") or str(PROJECT_ROOT / "state"))
    args = parser.parse_args(argv)
    app = App(Path(args.state_dir))
    server = ThreadingHTTPServer((args.host, args.port), make_handler(app))
    server.daemon_threads = True
    mode = ("实时运行已开启" + ("（需要访问口令）" if app.access_code_required else "（无需口令）")) if app.live_enabled else "仅回放（未配置模型密钥）"
    print(f"xiaoying-agent {app.version} 监听 http://{args.host}:{args.port}/ ，{mode}", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
