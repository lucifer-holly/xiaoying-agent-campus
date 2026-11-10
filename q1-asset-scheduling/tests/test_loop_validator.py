"""ReAct 循环与输出校验器：用脚本化 Mock 构造“说谎的模型”“乱调工具的模型”等情况。

这些测试证明的是代码边界：不管模型说什么，最终状态都以台账和草稿库为准。
"""
from __future__ import annotations

from agent.loop import run_agent
from agent.mock_llm import PolicyMockLLM, ScriptedMockLLM
from conftest import BASE_REQUEST
from domain.scheduling import SchedulingSession, summarize
from domain.store import DataStore
from domain.validator import build_output

N = {"decision_note": "脚本"}
PREP = [
    {"tool": "read_asset", "args": {"asset_id": "M01", **N}},
    {"tool": "check_rules", "args": {"asset_id": "M01", "channel": "douyin", **N}},
    {"tool": "query_slots", "args": {"channel": "douyin", "date": "2026-11-13", "time": "18:00", **N}},
]
SAVE = {"tool": "save_draft", "args": {"asset_id": "M01", "channel": "douyin", "publish_at": "2026-11-13 18:00", "requires_confirmation": False, **N}}


def finish(status, **extra):
    return {"tool": "finish", "args": {"status": status, "message": "模型的说明", **N, **extra}}


def run(script, *, request=None, faults=None, max_steps=8, llm=None):
    session = SchedulingSession(DataStore(), request or BASE_REQUEST, faults)
    llm = llm or ScriptedMockLLM(script)
    return run_agent(session=session, llm=llm, finalize=build_output, summarize=summarize, max_steps=max_steps)


def checks(output):
    return {c["check"] for c in output["validator"]["corrections"]}


def test_false_save_success_is_downgraded_to_failed():
    result = run(PREP + [SAVE, finish("completed", draft_id="D-FAKE0001", message="已保存成功")], faults={"save_draft": "error"})
    out = result.output
    assert out["status"] == "failed" and out["draft"] is None
    assert {"draft_id_from_store", "no_false_save_success"} <= checks(out)
    assert out["model_claim"]["status"] == "completed" and out["message"].startswith("【校验器已更正】")


def test_completed_claim_on_pending_draft_becomes_needs_confirmation():
    request = {**BASE_REQUEST, "publish_at": "2026-11-12 18:00"}
    save_19 = {"tool": "save_draft", "args": {**SAVE["args"], "publish_at": "2026-11-12 19:00"}}
    out = run(PREP[:2] + [save_19, finish("completed")], request=request).output
    assert out["status"] == "needs_confirmation" and out["draft"]["status"] == "pending_confirmation"
    assert "pending_draft_needs_confirmation" in checks(out)


def test_published_status_is_never_accepted():
    result = run(PREP + [SAVE, finish("published"), finish("completed")])
    rejected = [s for s in result.trace["steps"] if s["tool"] == "finish" and not s["ok"]]
    assert rejected and "published" in rejected[0]["result_summary"]
    assert result.output["status"] == "completed"


def test_save_state_comes_from_store_after_ambiguous_timeout():
    out = run(PREP + [SAVE, finish("failed", message="保存超时，未保存")], faults={"save_draft": "timeout_after_commit"}).output
    assert out["status"] == "completed" and out["draft"]["created_in_this_run"] is True
    assert "save_state_from_store" in checks(out)


def test_step_limit_returns_incomplete_status():
    result = run([PREP[0]] * 10, max_steps=3)
    out = result.output
    assert out["status"] == "incomplete_step_limit" and len(out["completed_steps"]) == 3
    assert result.trace["steps"][-1]["next_action"].startswith("触顶")


def test_unknown_tool_bad_json_and_text_replies_do_not_crash_the_loop():
    script = [
        {"content": "我先想想"},
        {"tool": "publish_now", "args": {"asset_id": "M01", **N}},
        {"tool": "query_slots", "args": '{"channel": "douyin"'},
        finish("needs_input", missing_fields=["publish_at"]),
    ]
    result = run(script)
    steps = result.trace["steps"]
    assert steps[0]["tool"] is None
    assert steps[1]["observation"]["error"]["code"] == "UNKNOWN_TOOL"
    assert steps[2]["observation"]["error"]["code"] == "INVALID_ARGUMENTS"
    assert result.output["status"] == "needs_input"


def test_llm_error_ends_with_failed_status():
    result = run([{"raise": "连接被重置"}])
    assert result.output["status"] == "failed" and "连接被重置" in result.output["error"]
    assert result.trace["end_reason"] == "llm_error"


def test_trace_links_each_step_to_the_next_action():
    request = {**BASE_REQUEST, "publish_at": "2026-11-12 18:00"}
    trace = run(None, request=request, llm=PolicyMockLLM()).trace
    tools = [s["tool"] for s in trace["steps"]]
    assert tools == ["read_asset", "check_rules", "query_slots", "query_slots", "save_draft", "finish"]
    assert [s["next_action"] for s in trace["steps"]] == tools[1:] + ["结束"]
    assert all(s["decision_note"] and s["result_summary"] for s in trace["steps"])
