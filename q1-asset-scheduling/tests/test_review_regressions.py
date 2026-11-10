"""独立复核发现的问题的回归测试：每条先复现问题（修复前失败），再验证修复。

对应 docs/03 第 6 节的复核记录。
"""
from __future__ import annotations

import threading

import pytest

import main as cli
from agent.llm import LLMError, QwenLLM
from agent.loop import run_agent
from agent.mock_llm import PolicyMockLLM, ScriptedMockLLM
from config import LLMSettings
from conftest import BASE_REQUEST, call
from domain.scheduling import SchedulingSession, summarize
from domain.store import DataStore
from domain.validator import build_output

N = {"decision_note": "脚本"}
CONFLICT = {**BASE_REQUEST, "request_id": "REQ-1112-001", "publish_at": "2026-11-12 18:00"}
PREP = [
    {"tool": "read_asset", "args": {"asset_id": "M01", **N}},
    {"tool": "check_rules", "args": {"asset_id": "M01", "channel": "douyin", **N}},
    {"tool": "query_slots", "args": {"channel": "douyin", "date": "2026-11-13", "time": "18:00", **N}},
]
SAVE = {"tool": "save_draft", "args": {"asset_id": "M01", "channel": "douyin", "publish_at": "2026-11-13 18:00", "requires_confirmation": False, **N}}


def finish(status, message="模型的说明", **extra):
    return {"tool": "finish", "args": {"status": status, "message": message, **N, **extra}}


def run(script, *, request=None, faults=None, store=None, llm=None, **limits):
    session = SchedulingSession(store or DataStore(), request or BASE_REQUEST, faults)
    return run_agent(session=session, llm=llm or ScriptedMockLLM(script), finalize=build_output, summarize=summarize, **limits).output


def checks(out):
    return {c["check"] for c in out["validator"]["corrections"]}


def save_on(store, request, publish_at, confirm=False):
    s = SchedulingSession(store, request)
    call(s, "check_rules", asset_id=request["asset_id"], channel=request["channel"])
    return call(s, "save_draft", asset_id=request["asset_id"], channel=request["channel"], publish_at=publish_at, requires_confirmation=confirm)


# ---- 复核 Important 1：最终说明和状态都要和草稿库对得上 ------------------------------
def test_message_claiming_a_save_that_never_happened_is_corrected():
    out = run(PREP + [finish("needs_confirmation", "已为您保存 19:00 的待确认草稿并占住时段")])
    assert out["status"] == "failed" and out["draft"] is None
    assert "message_contradicts_store" in checks(out) and "已为您保存" not in out["message"]


def test_message_claiming_publication_is_corrected():
    out = run(PREP + [SAVE, finish("completed", "已发布到抖音，内容已上线")])
    assert out["status"] == "completed" and "已发布" not in out["message"]
    assert "message_contradicts_store" in checks(out)


def test_storage_failure_forces_failed_whatever_the_model_says():
    out = run(PREP + [SAVE, finish("needs_input", "草稿已保存")], faults={"save_draft": "error"})
    assert out["status"] == "failed" and out["draft"] is None


def test_draft_written_in_this_run_overrides_a_blocked_claim():
    out = run(PREP + [SAVE, finish("blocked", "保存超时，未保存任何草稿")], faults={"save_draft": "timeout_after_commit"})
    assert out["status"] == "completed" and out["draft"]["created_in_this_run"] is True
    assert "未保存任何草稿" not in out["message"]


def test_every_output_carries_a_fact_based_summary():
    out = run(PREP + [SAVE, finish("completed")])
    assert out["facts_summary"].startswith("系统核对") and out["draft"]["draft_id"] in out["facts_summary"]


# ---- 复核 Important 2：幂等键按申请内容计算，而不是模型选的时段 ------------------------------
def test_resubmitted_form_with_new_id_returns_the_existing_draft(store):
    first = save_on(store, CONFLICT, "2026-11-12 19:00", confirm=True)["data"]
    again = save_on(store, {**CONFLICT, "request_id": "REQ-1112-001-B"}, "2026-11-12 21:00", confirm=True)
    assert again["ok"] and again["data"]["created"] is False
    assert again["data"]["draft"]["draft_id"] == first["draft"]["draft_id"]
    assert len(store.drafts()) == 1


def test_policy_mock_resubmission_does_not_create_a_second_pending_draft(store):
    for rid in ("REQ-1112-001", "REQ-1112-001-B"):
        run(None, request={**CONFLICT, "request_id": rid}, store=store, llm=PolicyMockLLM())
    assert len(store.drafts()) == 1


# ---- 复核 Important 3 / Minor 2：多进程、多线程共用草稿库 ---------------------------------
def test_two_store_instances_on_one_file_do_not_lose_or_double_book(tmp_path):
    path = tmp_path / "drafts.json"
    a, b = DataStore(drafts_path=path), DataStore(drafts_path=path)  # 模拟两个先后启动的进程
    req1 = {**BASE_REQUEST, "request_id": "REQ-P-1", "asset_id": "M06", "channel": "xiaohongshu", "publish_at": "2026-11-14 12:00", "constraints": {}}
    req2 = {**req1, "request_id": "REQ-P-2", "asset_id": "M03"}
    assert save_on(a, req1, "2026-11-14 12:00")["data"]["created"] is True
    second = save_on(b, {**req2, "asset_id": "M06"}, "2026-11-14 12:00")  # 同一内容、另一个进程
    assert second["data"]["created"] is False
    other = save_on(b, {**req1, "request_id": "REQ-P-3", "asset_id": "M05", "channel": "douyin", "publish_at": "2026-11-14 12:00"}, "2026-11-14 12:00")
    assert other["data"]["created"] is True  # 不同渠道的时段，互不影响
    assert len(DataStore(drafts_path=path).drafts()) == 2


def test_concurrent_threads_cannot_double_book_a_slot(store):
    barrier, results = threading.Barrier(6), []

    def worker(i):
        s = SchedulingSession(store, {**BASE_REQUEST, "request_id": f"REQ-T-{i}", "asset_id": ["M01", "M05"][i % 2], "publish_at": "2026-11-13 19:00", "constraints": {}})
        call(s, "check_rules", asset_id=s.request["asset_id"], channel="douyin")
        barrier.wait()
        results.append(call(s, "save_draft", asset_id=s.request["asset_id"], channel="douyin", publish_at="2026-11-13 19:00", requires_confirmation=False))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    slot = [d for d in store.drafts() if d["publish_at"] == "2026-11-13 19:00"]
    assert len(slot) == 1


# ---- 复核 Important 4：写盘失败不能留下“幽灵草稿” ----------------------------------------
def test_failed_disk_write_leaves_no_phantom_draft(tmp_path, monkeypatch):
    store = DataStore(drafts_path=tmp_path / "drafts.json")

    def boom(*_args, **_kwargs):
        raise PermissionError("只读文件系统")

    monkeypatch.setattr("domain.store.os.replace", boom)
    s = SchedulingSession(store, BASE_REQUEST)
    call(s, "check_rules", asset_id="M01", channel="douyin")
    for _ in range(2):
        err = call(s, "save_draft", asset_id="M01", channel="douyin", publish_at="2026-11-13 18:00", requires_confirmation=False)["error"]
        assert err["code"] == "STORAGE_UNAVAILABLE"
    assert store.drafts() == []
    assert build_output(session=s, finish_args={"status": "failed", "message": "x"}, end_reason="finish", run={})["draft"] is None


# ---- 复核 Important 5：草稿按申请内容匹配，不只看申请单号 ------------------------------------
def test_resubmitting_conflict_case_reports_pending_draft_not_failure(store):
    outs = [run(None, request=CONFLICT, store=store, llm=PolicyMockLLM()) for _ in range(2)]
    assert [o["status"] for o in outs] == ["needs_confirmation", "needs_confirmation"]
    assert outs[1]["draft"]["created_in_this_run"] is False


def test_edited_request_with_same_id_is_not_reported_as_completed(store):
    save_on(store, {**BASE_REQUEST, "request_id": "REQ-E-1"}, "2026-11-13 18:00")
    edited = {**BASE_REQUEST, "request_id": "REQ-E-1", "publish_at": "2026-11-14 09:00", "constraints": {}}
    script = [PREP[0], PREP[1], {"tool": "save_draft", "args": {**SAVE["args"], "publish_at": "2026-11-14 09:00"}}, finish("completed")]
    out = run(script, request=edited, store=store)
    assert out["status"] == "failed" and out["draft"] is None
    assert out["conflicting_draft"]["publish_at"] == "2026-11-13 18:00"


# ---- 复核 Minor --------------------------------------------------------------------------
def test_llm_error_after_save_reports_the_store_state():
    out = run(PREP + [SAVE, {"raise": "连接被重置"}])
    assert out["status"] == "failed" and out["draft"]["draft_id"] in out["facts_summary"]
    assert "保存接口返回了错误" not in out["message"]


def test_malformed_model_response_becomes_llm_error():
    llm = QwenLLM(LLMSettings(base_url="http://127.0.0.1:9", api_key="test", model="qwen-test", timeout_s=1, temperature=0, enable_thinking=False))

    class Empty:
        choices: list = []
        usage = None
        model = "qwen-test"

    llm._client = type("C", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"create": staticmethod(lambda **_: Empty())})()})()})()
    with pytest.raises(LLMError):
        llm.chat([], [])
    assert run(None, llm=llm)["status"] == "failed"


def test_structured_fields_only_contain_facts():
    out = run(PREP[:2] + [finish("blocked", risk_rule_ids=["R02"], missing_fields=["cover_url"])])
    assert out["risk_rule_ids"] == [] and out["missing_fields"] == []
    assert out["validator"]["warnings"]


def test_tool_call_limit_returns_incomplete():
    two_at_once = {"tools": [PREP[0], PREP[1]]}
    out = run([two_at_once, two_at_once, two_at_once], max_tool_calls=3)
    assert out["status"] == "incomplete_step_limit" and out["run"]["end_reason"] == "tool_limit"


def test_guards_for_mismatch_incomplete_asset_and_held_slot(make_session, store):
    s = make_session()
    call(s, "check_rules", asset_id="M01", channel="douyin")
    assert call(s, "save_draft", asset_id="M05", channel="douyin", publish_at="2026-11-13 18:00", requires_confirmation=False)["error"]["code"] == "REQUEST_MISMATCH"
    m02 = make_session(asset_id="M02", request_id="REQ-T-M02")
    call(m02, "check_rules", asset_id="M02", channel="douyin")
    assert call(m02, "save_draft", asset_id="M02", channel="douyin", publish_at="2026-11-13 18:00", requires_confirmation=False)["error"]["code"] == "ASSET_INCOMPLETE"
    assert save_on(store, BASE_REQUEST, "2026-11-13 18:00")["ok"]
    rival = save_on(store, {**BASE_REQUEST, "request_id": "REQ-T-9", "asset_id": "M05", "constraints": {}}, "2026-11-13 18:00")
    assert rival["error"]["code"] == "SLOT_OCCUPIED"  # 草稿同样占住时段


def test_zero_limits_are_rejected(tmp_path):
    with pytest.raises(SystemExit) as info:
        cli.main(["--input", "examples/01-normal-free-slot.input.json", "--max-steps", "0"])
    assert info.value.code == 2
