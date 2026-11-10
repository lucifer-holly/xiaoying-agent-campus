"""用例级验收：同一套 expected 标准分别检查离线 Mock 流程和已录制的真实模型 Trace。

- Mock 流程：只证明工具、校验器、Trace、触顶逻辑能跑通，不证明模型决策效果；
- 真实录制：examples/*.trace.json 是 --llm real 的实际运行结果，断言它们满足每个验收点。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.mock_llm import PolicyMockLLM
from agent.prompts import PROMPT_VERSION
from expectations import check_expected
from main import load_case, run_case

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
CASES = sorted(EXAMPLES.glob("*.input.json"))
IDS = [p.name.split(".")[0] for p in CASES]


def recorded(case_id: str) -> tuple[dict, dict]:
    out_path, trace_path = EXAMPLES / f"{case_id}.output.json", EXAMPLES / f"{case_id}.trace.json"
    if not out_path.exists() or not trace_path.exists():
        pytest.skip(f"{case_id} 还没有用真实模型录制")
    return json.loads(out_path.read_text(encoding="utf-8")), json.loads(trace_path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("path", CASES, ids=IDS)
def test_mock_flow_meets_expected(path):
    case = load_case(path)
    output, trace = run_case(case, llm=PolicyMockLLM())
    assert check_expected(case, output, trace) == []


@pytest.mark.parametrize("path", CASES, ids=IDS)
def test_recorded_real_trace_meets_expected(path):
    case = load_case(path)
    output, trace = recorded(case["case"])
    for t in trace.get("runs") or [trace]:
        assert t["llm_mode"] == "real" and t["model"].startswith("qwen")
        assert t["prompt_version"] == PROMPT_VERSION, "提示词改过之后需要重新录制"
        assert all(s["decision_note"] for s in t["steps"] if s["tool"]), "每次工具调用都要有决策依据"
    assert check_expected(case, output, trace) == []


def test_recorded_paths_diverge_on_slot_availability():
    """01 与 02 的申请单只差日期：模型看到不同的时段结果后走了不同的路径。"""
    _, t1 = recorded("01-normal-free-slot")
    _, t2 = recorded("02-slot-conflict")

    def first_slot_status(trace):
        step = next(s for s in trace["steps"] if s["tool"] == "query_slots")
        return {x["time"]: x["status"] for x in step["observation"]["data"]["slots"]}["18:00"]

    def saved(trace):
        return next(s["args"] for s in trace["steps"] if s["tool"] == "save_draft" and s["ok"])

    assert first_slot_status(t1) == "free" and first_slot_status(t2) == "occupied"
    assert saved(t1)["publish_at"].endswith("18:00") and saved(t1)["requires_confirmation"] is False
    assert saved(t2)["publish_at"] == "2026-11-12 19:00" and saved(t2)["requires_confirmation"] is True
    tools2 = [s["tool"] for s in t2["steps"]]
    assert tools2.index("save_draft") > tools2.index("query_slots")  # 先看到占用，再决定改时段
