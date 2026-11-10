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


def test_live_disabled_without_access_code(app):
    app.cfg.access_code = ""
    assert not app.live_enabled
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
