"""业务工具与代码边界：这些约束不依赖模型自觉，由工具层强制执行。"""
from __future__ import annotations

import json

from conftest import BASE_REQUEST, call
from domain.rules import evaluate
from domain.scheduling import SchedulingSession
from domain.store import DataStore


def save(session, publish_at, requires_confirmation=False, **extra):
    return call(session, "save_draft", asset_id=session.request["asset_id"], channel=session.request["channel"],
                publish_at=publish_at, requires_confirmation=requires_confirmation, **extra)


def checked(session):
    assert call(session, "check_rules", asset_id=session.request["asset_id"], channel=session.request["channel"])["ok"]
    return session


# ---- 读取与查询 -------------------------------------------------------------
def test_read_asset_reports_missing_fields_and_unknown_id(make_session):
    s = make_session(asset_id="M02")
    data = call(s, "read_asset", asset_id="M02")["data"]
    assert data["missing_fields"] == ["caption", "cover_url"] and data["complete"] is False
    assert call(s, "read_asset", asset_id="M99")["error"]["code"] == "ASSET_NOT_FOUND"


def test_query_slots_single_slot_and_full_day(make_session):
    s = make_session()
    one = call(s, "query_slots", channel="douyin", date="2026-11-12", time="18:00")["data"]
    assert one["slots"][0]["status"] == "occupied" and one["slots"][0]["occupied_by"]["asset_id"] == "M22"
    day = call(s, "query_slots", channel="douyin", date="2026-11-12")["data"]
    assert day["free_slots"] == ["09:00", "19:00", "21:00"]
    assert call(s, "query_slots", channel="douyin", date="2026-11-12", time="18:30")["error"]["code"] == "INVALID_SLOT"


def test_bad_arguments_come_back_as_observations(make_session):
    reg = make_session().registry
    assert reg.execute("query_slots", '{"channel": "douyin"').result["error"]["code"] == "INVALID_ARGUMENTS"  # 坏 JSON
    missing_note = reg.execute("query_slots", {"channel": "douyin", "date": "2026-11-12"}).result
    assert missing_note["error"]["code"] == "INVALID_ARGUMENTS" and "decision_note" in missing_note["error"]["message"]
    wrong_enum = reg.execute("query_slots", {"channel": "抖音", "date": "2026-11-12", "decision_note": "x"}).result
    assert wrong_enum["error"]["code"] == "INVALID_ARGUMENTS"


def test_there_is_no_publish_tool(make_session):
    reg = make_session().registry
    assert reg.names == ["read_asset", "check_rules", "query_slots", "save_draft", "finish"]
    assert reg.execute("publish", {"asset_id": "M01"}).result["error"]["code"] == "UNKNOWN_TOOL"


# ---- 规则 -------------------------------------------------------------------
def test_rule_verdicts(store):
    expected = {
        ("M01", "douyin"): "pass",
        ("M02", "douyin"): "incomplete",
        ("M03", "xiaohongshu"): "block",          # R02 绝对化用语
        ("M03", "wechat_channels"): "block",      # R04 视频号不支持图文
        ("M04", "wechat_channels"): "needs_verification",  # R03 授权审批中
        ("M07", "douyin"): "block",               # R03 无授权 + R04 超时长
    }
    for (asset_id, channel), verdict in expected.items():
        assert evaluate(store.get_asset(asset_id), channel, store)["verdict"] == verdict, (asset_id, channel)
    hits = evaluate(store.get_asset("M03"), "xiaohongshu", store)["findings"][0]["evidence"]
    assert {"销量第一", "史上最"} <= set(hits)


def test_deep_check_resolves_pending_license(store):
    result = evaluate(store.get_asset("M04"), "wechat_channels", store, deep=True)
    assert result["verdict"] == "pass" and result["resolved"][0]["rule_id"] == "R03"


# ---- save_draft 的边界 ------------------------------------------------------
def test_save_requires_a_passing_rule_check(make_session, store):
    s = make_session()
    assert save(s, "2026-11-13 18:00")["error"]["code"] == "RULE_CHECK_REQUIRED"
    blocked = make_session(asset_id="M03", channel="xiaohongshu", publish_at="2026-11-13 12:00")
    checked(blocked)
    assert save(blocked, "2026-11-13 12:00")["error"]["code"] == "ASSET_BLOCKED"
    pending = make_session(asset_id="M04", channel="wechat_channels", publish_at="2026-11-13 12:00")
    checked(pending)
    assert save(pending, "2026-11-13 12:00")["error"]["code"] == "VERIFICATION_REQUIRED"
    assert call(pending, "check_rules", asset_id="M04", channel="wechat_channels", deep_check=True)["data"]["verdict"] == "pass"
    assert save(pending, "2026-11-13 12:00")["ok"]
    assert [d["asset_id"] for d in store.drafts()] == ["M04"]


def test_changed_time_is_forced_to_pending_confirmation(make_session):
    s = checked(make_session(publish_at="2026-11-12 18:00"))
    result = save(s, "2026-11-12 19:00", requires_confirmation=False)["data"]
    assert result["draft"]["status"] == "pending_confirmation" and result["confirmation_forced"] is True


def test_fixed_date_and_occupied_slot_are_rejected(make_session, store):
    s = checked(make_session(publish_at="2026-11-12 18:00"))
    assert save(s, "2026-11-13 18:00", requires_confirmation=True)["error"]["code"] == "HARD_CONSTRAINT_DATE"
    assert save(s, "2026-11-12 18:00")["error"]["code"] == "SLOT_OCCUPIED"
    assert store.drafts() == []


def test_save_is_idempotent_and_one_draft_per_request(make_session, store):
    s = checked(make_session())
    first, second = save(s, "2026-11-13 18:00")["data"], save(s, "2026-11-13 18:00")["data"]
    assert first["created"] is True and second["created"] is False
    assert first["draft"]["draft_id"] == second["draft"]["draft_id"]
    other = save(s, "2026-11-13 19:00", requires_confirmation=True)["data"]  # 同一申请换个时段再存：仍是那一份
    assert other["created"] is False and other["draft"]["publish_at"] == "2026-11-13 18:00"
    assert len(store.drafts()) == 1


def test_duplicate_submission_across_processes(tmp_path):
    path = tmp_path / "drafts.json"
    results = []
    for _ in range(2):  # 两个独立进程各提交一次：共用落盘的草稿库
        s = SchedulingSession(DataStore(drafts_path=path), BASE_REQUEST)
        checked(s)
        results.append(save(s, "2026-11-13 18:00")["data"])
    assert [r["created"] for r in results] == [True, False]
    assert results[0]["draft"]["draft_id"] == results[1]["draft"]["draft_id"]
    assert len(json.loads(path.read_text(encoding="utf-8"))["drafts"]) == 1


def test_storage_faults(make_session, store):
    broken = checked(make_session(faults={"save_draft": "error"}))
    for _ in range(2):
        err = save(broken, "2026-11-13 18:00")["error"]
        assert err["code"] == "STORAGE_UNAVAILABLE" and err["retryable"] is True
    assert store.drafts() == []  # 写入前失败：什么都没写

    flaky = checked(make_session(faults={"save_draft": "error_once"}, request_id="REQ-TEST-002", publish_at="2026-11-13 19:00"))
    assert save(flaky, "2026-11-13 19:00")["ok"] is False
    assert save(flaky, "2026-11-13 19:00")["data"]["created"] is True


def test_timeout_after_commit_then_retry_returns_same_draft(make_session, store):
    s = checked(make_session(faults={"save_draft": "timeout_after_commit"}))
    assert save(s, "2026-11-13 18:00")["error"]["code"] == "TIMEOUT"
    assert len(store.drafts()) == 1  # 写入其实已生效
    retry = save(s, "2026-11-13 18:00")["data"]
    assert retry["created"] is False and len(store.drafts()) == 1
