"""运行记录（Trace）：每一步的工具、参数、返回摘要、后续动作和决策依据。

决策依据来自工具参数里的 decision_note（模型自己写的一句话），不记录模型内部思维过程。
observation 是模型在这一步实际看到的工具返回，便于复查“模型是根据什么做的下一步”。
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

CST = timezone(timedelta(hours=8))
END_LABELS = {
    "finish": "结束",
    "step_limit": "触顶终止（步数上限）",
    "tool_limit": "触顶终止（工具调用次数上限）",
    "llm_error": "模型调用失败，终止",
}


def _now() -> str:
    return datetime.now(CST).isoformat(timespec="seconds")


class Trace:
    def __init__(self, *, case_id: str | None, llm_mode: str, model: str, prompt_version: str, limits: dict, request: dict, fault_injection: dict):
        self.data = {
            "trace_format": "q1-trace/v1",
            "run_id": uuid.uuid4().hex[:12],
            "case_id": case_id,
            "llm_mode": llm_mode,
            "model": model,
            "prompt_version": prompt_version,
            "started_at": _now(),
            "finished_at": None,
            "limits": limits,
            "request": request,
            "fault_injection": fault_injection,
            "steps": [],
            "end_reason": None,
            "final": None,
            "llm_usage": {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0, "latency_ms": 0},
        }

    def record_llm(self, model: str, latency_ms: int, usage: dict | None) -> dict:
        totals = self.data["llm_usage"]
        totals["calls"] += 1
        totals["latency_ms"] += latency_ms
        if usage:
            totals["prompt_tokens"] += usage.get("prompt_tokens") or 0
            totals["completion_tokens"] += usage.get("completion_tokens") or 0
        if model and model != self.data["model"]:
            self.data["model_reported"] = model  # 接口回报的实际模型名
        return {"latency_ms": latency_ms, **(usage or {})}

    def add_step(self, *, step: int, tool: str | None, args: dict, decision_note: str | None, ok: bool,
                 result_summary: str, observation, llm: dict | None, assistant_text: str | None = None) -> dict:
        steps = self.data["steps"]
        if steps and steps[-1]["next_action"] is None:
            steps[-1]["next_action"] = tool or "（未调用工具）"
        entry = {
            "step": step,
            "tool": tool,
            "args": args,
            "decision_note": decision_note,
            "ok": ok,
            "result_summary": result_summary,
            "next_action": None,
            "observation": observation,
            "llm": llm,
        }
        if assistant_text:
            entry["assistant_text"] = assistant_text[:500]
        steps.append(entry)
        return entry

    def end(self, end_reason: str, output: dict) -> None:
        steps = self.data["steps"]
        if steps and steps[-1]["next_action"] is None:
            steps[-1]["next_action"] = END_LABELS[end_reason]
        self.data["end_reason"] = end_reason
        self.data["finished_at"] = _now()
        self.data["final"] = output

    def to_dict(self) -> dict:
        return self.data

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
