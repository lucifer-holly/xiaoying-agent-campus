"""输出校验器：把模型 finish 的说法和“事实”（调用台账 + 草稿库）核对，修正或降级状态。

模型说什么都只是“声明”；草稿有没有、是什么状态，以草稿库为准。
所有修正都写进 output.validator.corrections，并保留模型原话（model_claim），便于在 Trace 里复查。
"""
from __future__ import annotations

from .scheduling import MODEL_STATUSES, SchedulingSession

STATUS_LABELS = {
    "completed": "已保存排期草稿",
    "needs_input": "需要补充信息",
    "needs_confirmation": "等待申请人确认",
    "blocked": "规则风险，已阻断",
    "failed": "未完成（失败）",
    "incomplete_step_limit": "未完成（达到步数上限）",
}
NOTICE = "本 Agent 只保存排期草稿，没有发布能力；草稿需要人工在发布系统确认后才会发布。"


def _derive_status(facts: dict) -> str:
    draft = facts["draft"]
    if draft:
        return "needs_confirmation" if draft["status"] == "pending_confirmation" else "completed"
    if facts["storage_failure"]:
        return "failed"
    if facts["block_findings"]:
        return "blocked"
    if facts["missing_fields"]:
        return "needs_input"
    return "failed"


def _draft_view(draft: dict | None, created: bool) -> dict | None:
    if not draft:
        return None
    keep = ("draft_id", "status", "asset_id", "asset_version", "channel", "publish_at", "requested_publish_at", "change_reason", "warnings", "created_at")
    view = {k: draft.get(k) for k in keep}
    view["created_in_this_run"] = created
    return view


def build_output(*, session: SchedulingSession, finish_args: dict | None, end_reason: str, run: dict, error: str | None = None) -> dict:
    facts = session.facts()
    req = session.request
    draft = facts["draft"]
    corrections: list[dict] = []
    warnings: list[str] = []
    finish_args = finish_args or {}

    def correct(check: str, old, new, reason: str) -> None:
        corrections.append({"check": check, "from": old, "to": new, "reason": reason})

    # ---- 1. 初始状态 ------------------------------------------------------
    if end_reason == "finish":
        status = finish_args.get("status")
        message = finish_args.get("message") or ""
        if status not in MODEL_STATUSES:
            new = _derive_status(facts)
            correct("status_enum", status, new, f"状态 {status!r} 不在允许范围内（没有发布能力，不存在 published 一类状态）")
            status = new
    elif end_reason in ("step_limit", "tool_limit"):
        status = "incomplete_step_limit"
        limit = run["max_steps"] if end_reason == "step_limit" else run["max_tool_calls"]
        unit = "步数" if end_reason == "step_limit" else "工具调用次数"
        message = f"达到{unit}上限（{limit}），任务未完成；已完成的步骤见 completed_steps。"
    else:  # llm_error
        status = "failed"
        message = f"模型调用失败，任务中止：{error}"

    # ---- 2. 草稿编号只能来自草稿库 ------------------------------------------
    claimed_id = finish_args.get("draft_id")
    if claimed_id and (draft is None or claimed_id != draft["draft_id"]):
        correct("draft_id_from_store", claimed_id, draft and draft["draft_id"], "模型给出的草稿编号与草稿库不一致，以草稿库为准")

    # ---- 3. 状态必须与草稿库一致 --------------------------------------------
    if status == "completed":
        if draft is None:
            correct("no_false_save_success", "completed", "failed", "草稿库里没有本申请的草稿，不能报告为已完成")
            status = "failed"
        elif draft["status"] == "pending_confirmation":
            correct("pending_draft_needs_confirmation", "completed", "needs_confirmation", "草稿处于待确认状态，需要申请人确认后才算完成")
            status = "needs_confirmation"
    if status == "needs_confirmation" and draft is None and facts["storage_failure"]:
        correct("no_false_save_success", "needs_confirmation", "failed", "保存草稿失败，草稿库里没有本申请的草稿")
        status = "failed"
    if status == "failed" and draft is not None and facts["draft_created_this_run"]:
        new = _derive_status(facts)
        correct("save_state_from_store", "failed", new, f"保存接口返回了错误，但草稿库中已存在本申请的草稿 {draft['draft_id']}，以草稿库为准")
        status = new
    if status == "blocked" and not facts["block_findings"]:
        warnings.append("模型判定为阻断，但规则检查没有 block 级命中，建议人工复核")
    if status == "needs_input" and not facts["missing_fields"] and not finish_args.get("missing_fields"):
        warnings.append("模型判定需要补充信息，但没有给出缺失项")

    if corrections and any(c["check"] != "draft_id_from_store" for c in corrections):
        message = "【校验器已更正】" + "；".join(c["reason"] for c in corrections) + "。"
        if status == "failed" and facts["save_errors"]:
            err = facts["save_errors"][-1]
            message += f"最后一次保存返回 {err['code']}：{err['message']}"

    # ---- 4. 组装输出 --------------------------------------------------------
    rule = facts["rule"]
    missing = facts["missing_fields"] or list(finish_args.get("missing_fields") or [])
    output = {
        "request_id": req["request_id"],
        "status": status,
        "status_label": STATUS_LABELS[status],
        "message": message,
        "draft": _draft_view(draft, facts["draft_created_this_run"]),
        "schedule": {
            "requested_publish_at": req.get("publish_at"),
            "draft_publish_at": draft["publish_at"] if draft else None,
            "changed": bool(draft and draft["publish_at"] != req.get("publish_at")),
        },
        "review": None if rule is None else {
            "verdict": rule["verdict"],
            "deep_check": rule["deep_check"],
            "findings": rule["findings"],
            "resolved": rule["resolved"],
        },
        "missing_fields": missing,
        "risk_rule_ids": sorted({f["rule_id"] for f in facts["block_findings"]} | set(finish_args.get("risk_rule_ids") or [])),
        "confirmation_question": finish_args.get("confirmation_question"),
        "notice": NOTICE,
        "validator": {"corrections": corrections, "warnings": warnings},
    }
    if corrections:
        output["model_claim"] = {k: finish_args.get(k) for k in ("status", "draft_id", "message")}
    if status == "incomplete_step_limit":
        output["completed_steps"] = [
            {"tool": e.name, "ok": e.ok, "args": e.args} for e in session.ledger
        ]
    if error:
        output["error"] = error
    output["run"] = run
    return output
