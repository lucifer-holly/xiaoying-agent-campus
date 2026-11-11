"""演示服务的防护：口令、限流、每日上限、并发、输入校验。用 Mock 模型，不调用真实接口。"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

import server
from agent.mock_llm import PolicyMockLLM


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_ACCESS_CODE", "test-code")
    monkeypatch.setenv("DEMO_RATE_LIMIT", "2/600")
    monkeypatch.setenv("DEMO_DAILY_LIMIT", "3")
    instance = server.App(tmp_path)
    instance.llm = PolicyMockLLM()
    return instance


def error_code(fn, *args):
    with pytest.raises(server.ApiError) as info:
        fn(*args)
    return info.value.code, info.value.fallback


def test_access_code_and_lockout(app):
    assert error_code(app.run, "1.1.1.1", {"case_id": "01-normal-free-slot", "access_code": "wrong"}) == ("ACCESS_DENIED", True)
    for _ in range(9):
        error_code(app.run, "1.1.1.1", {"case_id": "01-normal-free-slot", "access_code": "wrong"})
    assert error_code(app.run, "1.1.1.1", {"case_id": "01-normal-free-slot", "access_code": "test-code"})[0] == "ACCESS_LOCKED"


def test_rate_limit_daily_limit_and_persistence(app, tmp_path):
    ok = {"case_id": "01-normal-free-slot", "access_code": "test-code"}
    assert app.run("1.1.1.1", ok)["output"]["status"] == "completed"
    app.run("1.1.1.1", ok)
    assert error_code(app.run, "1.1.1.1", ok) == ("RATE_LIMITED", True)  # 每 IP 2 次
    app.run("2.2.2.2", ok)
    assert error_code(app.run, "3.3.3.3", ok) == ("DAILY_LIMIT", True)   # 每日 3 次
    restarted = server.Guard(server.DemoConfig.from_env(tmp_path))      # 重启后计数还在
    assert restarted.quota()["used_today"] == 3


def test_busy_when_all_slots_taken(app):
    for _ in range(app.cfg.max_concurrency):
        assert app.guard.try_acquire()
    assert error_code(app.run, "1.1.1.1", {"case_id": "01-normal-free-slot", "access_code": "test-code"})[0] == "BUSY"


def test_live_request_validation(app):
    bad = {"asset_id": "M01", "channel": "tiktok", "publish_at": "明天"}
    assert error_code(server.build_live_case, {"request": bad}, app.presets)[0] == "BAD_REQUEST"
    assert error_code(server.build_live_case, {"case_id": "01-normal-free-slot", "fault_injection": {"publish": "error"}}, app.presets)[0] == "BAD_REQUEST"
    assert error_code(server.build_live_case, {"case_id": "01-normal-free-slot", "request": {"note": "长" * 201}}, app.presets)[0] == "BAD_REQUEST"
    case = server.build_live_case({"case_id": "06-duplicate-submission"}, app.presets)
    assert case["options"]["repeat"] == 2 and case["request"]["request_id"].startswith("LIVE-")


def test_live_runs_without_code_when_none_configured(app):
    app.cfg.access_code = ""
    assert app.live_enabled and not app.access_code_required
    assert app.run("1.1.1.1", {"case_id": "01-normal-free-slot"})["output"]["status"] == "completed"
    app.llm = None  # 没有模型密钥时才关闭实时运行
    assert error_code(app.run, "1.1.1.1", {"case_id": "01-normal-free-slot"}) == ("LIVE_DISABLED", True)


def test_http_routes(app):
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_address[1]}"
    try:
        health = json.loads(urllib.request.urlopen(base + "/api/health").read())
        assert health["ok"] and health["live_enabled"] and "base_url" not in json.dumps(health)
        assert b"window.Q1_REPLAY" in urllib.request.urlopen(base + "/data/replay.js").read()
        for path in ("/../src/config.py", "/%2e%2e/.env", "/api/nope"):
            with pytest.raises(urllib.error.HTTPError) as info:
                urllib.request.urlopen(base + path)
            assert info.value.code == 404
        req = urllib.request.Request(base + "/api/run", data=b"not json", method="POST")
        with pytest.raises(urllib.error.HTTPError) as info:
            urllib.request.urlopen(req)
        assert info.value.code == 400
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_live_request_accepts_short_instructions_only(app):
    case = server.build_live_case({"case_id": "01-normal-free-slot", "request": {"instructions": "优先排到 20:00 以后"}}, app.presets)
    assert case["request"]["instructions"] == "优先排到 20:00 以后"
    too_long = {"case_id": "01-normal-free-slot", "request": {"instructions": "长" * 301}}
    assert error_code(server.build_live_case, too_long, app.presets)[0] == "BAD_REQUEST"


def test_live_request_rejects_impossible_dates(app):
    """格式对但日期不存在（13 月、2 月 30 日、25 点）要在调用模型之前拒绝。"""
    for bad in ("2026-13-45 99:99", "2026-02-30 18:00", "2026-11-13 25:00"):
        with pytest.raises(server.ApiError) as info:
            server.build_live_case({"case_id": "01-normal-free-slot", "request": {"publish_at": bad}}, app.presets)
        assert info.value.code == "BAD_REQUEST" and "publish_at" in info.value.message
    ok = server.build_live_case({"case_id": "01-normal-free-slot", "request": {"publish_at": "2026-11-14 09:00"}}, app.presets)
    assert ok["request"]["publish_at"] == "2026-11-14 09:00"


def _raw_exchange(port: int, payload: bytes, timeout: float = 3.0) -> bytes:
    """发原始字节，读到连接关闭或超时为止，返回收到的全部响应。"""
    import socket
    with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sock:
        sock.sendall(payload)
        chunks = []
        try:
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                chunks.append(data)
        except socket.timeout:
            chunks.append(b"<TIMEOUT>")
    return b"".join(chunks)


def test_malformed_or_oversized_posts_get_one_clean_answer(app, capsys):
    """Content-Length 非法、为负或超限时：只回一个错误响应并关闭连接，不挂起、不把剩下的请求体当成下一个请求写进日志。"""
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    port = httpd.server_address[1]
    head = "POST /api/run HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: {}\r\n\r\n"
    try:
        for length, status in (("abc", b" 400 "), ("-1", b" 400 ")):
            reply = _raw_exchange(port, head.format(length).encode() + b"{}")
            assert reply.count(b"HTTP/1.1 ") == 1 and status in reply.split(b"\r\n", 1)[0], reply[:120]
            assert b"<TIMEOUT>" not in reply
        big = b'{"note": "' + b"x" * (server.MAX_BODY + 10) + b'"}'
        reply = _raw_exchange(port, head.format(len(big)).encode() + big)
        assert reply.count(b"HTTP/1.1 ") == 1 and b" 413 " in reply.split(b"\r\n", 1)[0]
        assert b"<TIMEOUT>" not in reply
        assert "x" * 400 not in capsys.readouterr().err  # 请求体内容没有进日志
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_client_leaving_mid_run_is_one_log_line_not_a_traceback(app, capsys, monkeypatch):
    """访客在运行途中关掉页面：结果写不回去时只记一行，不再回 500，也不把堆栈打进日志。"""
    import socket
    import struct
    import time
    real_run = app.run

    def slow_run(ip, body):
        time.sleep(0.3)
        return real_run(ip, body)

    monkeypatch.setattr(app, "run", slow_run)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), server.make_handler(app))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    body = json.dumps({"case_id": "01-normal-free-slot", "access_code": "test-code"}).encode()
    head = f"POST /api/run HTTP/1.1\r\nHost: x\r\nContent-Type: application/json\r\nContent-Length: {len(body)}\r\n\r\n"
    try:
        sock = socket.create_connection(("127.0.0.1", httpd.server_address[1]))
        sock.sendall(head.encode() + body)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        sock.close()  # 立即断开（RST），模拟关掉页面
        time.sleep(1.0)
        err = capsys.readouterr().err
        assert "Traceback" not in err and "INTERNAL_ERROR" not in err and " 500 " not in err, err[-600:]
        assert "断开" in err
    finally:
        httpd.shutdown()
        httpd.server_close()


def test_live_request_types_are_checked_before_any_quota_is_spent(app):
    """形状不对的请求在 build_live_case 里就拒绝（400），不会先扣掉一次额度再在运行中途报 500。"""
    base = {"case_id": "01-normal-free-slot", "access_code": "test-code"}
    bad_bodies = [
        {**base, "fault_injection": {"read_asset": "timeout_after_commit"}},  # 这个模式只适用于 save_draft
        {**base, "fault_injection": {"save_draft": ["error"]}},
        {**base, "repeat": 2.0},
        {**base, "repeat": True},
        {**base, "max_steps": True},
        {**base, "case_id": ["01-normal-free-slot"]},
        {**base, "request": {"constraints": "x"}},
        {**base, "request": {"note": "\ud800"}},          # 孤立代理项（JSON 里的 "\ud800"）：无法编码成 UTF-8
        {**base, "request": {"instructions": "坏\udc00字"}},
        {**base, "request": {"asset_id": 123}},
    ]
    for body in bad_bodies:
        before = app.health()["quota"]["used_today"]
        with pytest.raises(server.ApiError) as info:
            app.run("9.9.9.9", body)
        assert info.value.code == "BAD_REQUEST", (body, info.value.code)
        assert app.health()["quota"]["used_today"] == before, body
