"""合成数据与草稿库。

素材、规则、版权库、发布日历都是只读的合成数据（data/*.json）。
草稿库是唯一可写的部分：默认只在内存里（每次运行互不影响）；传入 drafts_path 时落盘到 JSON 文件，
用来演示跨进程的“重复提交”。

并发约定：查重、查申请单、查时段占用和写入在同一个临界区内完成（线程锁 + 跨进程文件锁），
落盘模式下每次都从文件重新读取，不依赖进程启动时读到的旧数据；写盘失败时内存和文件都不变。
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any

try:  # 跨进程文件锁只在 POSIX 上可用；Windows 上退化为进程内线程锁
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

DATA_DIR = Path(__file__).resolve().parents[2] / "data"


class StorageError(Exception):
    """草稿库读写失败（磁盘、权限等）：调用方按“存储不可用”处理。"""


class DraftConflict(Exception):
    """写入前的检查没通过：同一申请单已有其他草稿，或时段已被占用。"""

    def __init__(self, code: str, detail: dict):
        super().__init__(code)
        self.code, self.detail = code, detail


def _load(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


class DataStore:
    def __init__(self, data_dir: Path = DATA_DIR, drafts_path: Path | None = None):
        self.data_dir = Path(data_dir)
        self.assets: dict[str, dict] = {a["asset_id"]: a for a in _load(self.data_dir / "assets.json")["assets"]}
        self.rules: dict = _load(self.data_dir / "rules.json")
        self.licenses: dict[str, dict] = {
            lic["license_id"]: lic for lic in _load(self.data_dir / "license_registry.json")["licenses"]
        }
        schedule = _load(self.data_dir / "schedule.json")
        self.slot_times: list[str] = schedule["slot_times"]
        self.bookings: list[dict] = schedule["bookings"]
        self.drafts_path = Path(drafts_path) if drafts_path else None
        self._lock = threading.RLock()
        self._memory: list[dict] = []

    # ---- 只读数据 -------------------------------------------------------
    def get_asset(self, asset_id: str) -> dict | None:
        asset = self.assets.get(asset_id)
        return copy.deepcopy(asset) if asset else None

    def channel(self, code: str) -> dict | None:
        return self.rules["channels"].get(code)

    def license(self, license_id: str | None) -> dict | None:
        return self.licenses.get(license_id) if license_id else None

    # ---- 临界区 ---------------------------------------------------------
    @contextmanager
    def _critical(self):
        with self._lock:
            if self.drafts_path is None:
                yield
                return
            try:
                self.drafts_path.parent.mkdir(parents=True, exist_ok=True)
                lock_file = open(self.drafts_path.with_name(self.drafts_path.name + ".lock"), "a+")
            except OSError as exc:
                raise StorageError(f"无法打开草稿库锁文件：{exc}") from exc
            with lock_file:
                if fcntl:
                    fcntl.flock(lock_file, fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    if fcntl:
                        fcntl.flock(lock_file, fcntl.LOCK_UN)

    def _read(self) -> list[dict]:
        if self.drafts_path is None:
            return self._memory
        if not self.drafts_path.exists():
            return []
        try:
            return _load(self.drafts_path).get("drafts", [])
        except (OSError, ValueError) as exc:
            raise StorageError(f"草稿库读取失败：{exc}") from exc

    def _write(self, drafts: list[dict]) -> None:
        if self.drafts_path is None:
            self._memory = drafts
            return
        payload = json.dumps({"drafts": drafts}, ensure_ascii=False, indent=2)
        tmp = None
        try:  # 先写临时文件再原子替换：失败时原文件不变
            fd, tmp = tempfile.mkstemp(dir=self.drafts_path.parent, prefix=".drafts-", suffix=".json")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp, self.drafts_path)
        except OSError as exc:
            if tmp and os.path.exists(tmp):
                os.unlink(tmp)
            raise StorageError(f"草稿库写入失败：{exc}") from exc

    # ---- 草稿库 ---------------------------------------------------------
    def drafts(self) -> list[dict]:
        with self._critical():
            return copy.deepcopy(self._read())

    def find_draft(self, *, draft_id: str | None = None, idempotency_key: str | None = None) -> dict | None:
        for d in self.drafts():
            if draft_id and d["draft_id"] == draft_id:
                return d
            if idempotency_key and d["idempotency_key"] == idempotency_key:
                return d
        return None

    def drafts_for_request(self, request_id: str) -> list[dict]:
        return [d for d in self.drafts() if d["request_id"] == request_id]

    def _occupant(self, drafts: list[dict], channel: str, date: str, time: str) -> dict | None:
        for b in self.bookings:
            if (b["channel"], b["date"], b["time"]) == (channel, date, time):
                return {"type": "booking", "asset_id": b["asset_id"], "title": b["title"]}
        for d in drafts:
            if d["channel"] == channel and d["publish_at"] == f"{date} {time}":
                return {"type": "draft", "asset_id": d["asset_id"], "draft_id": d["draft_id"],
                        "request_id": d["request_id"], "draft_status": d["status"]}
        return None

    def slot_occupant(self, channel: str, date: str, time: str) -> dict | None:
        """返回占用该时段的条目（已有排期或草稿），空闲时返回 None。"""
        with self._critical():
            return copy.deepcopy(self._occupant(self._read(), channel, date, time))

    def insert_draft(self, draft: dict) -> tuple[dict, bool]:
        """原子写入：同幂等键 → 返回已有草稿和 False；同申请单已有其他草稿 / 时段被占 → DraftConflict。"""
        date, time = draft["publish_at"].split(" ")
        with self._critical():
            drafts = self._read()
            for d in drafts:
                if d["idempotency_key"] == draft["idempotency_key"]:
                    return copy.deepcopy(d), False
            same_request = [d for d in drafts if d["request_id"] == draft["request_id"]]
            if same_request:
                raise DraftConflict("REQUEST_ALREADY_HAS_DRAFT", copy.deepcopy(same_request[0]))
            occupant = self._occupant(drafts, draft["channel"], date, time)
            if occupant:
                raise DraftConflict("SLOT_OCCUPIED", occupant)
            self._write(drafts + [copy.deepcopy(draft)])
            return copy.deepcopy(draft), True
