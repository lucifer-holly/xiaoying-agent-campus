"""输出校验器：把模型 finish 的说法和“事实”（调用台账 + 草稿库）核对，修正或降级状态。

模型说什么都只是“声明”。草稿有没有、是什么状态，以草稿库为准：
1. 草稿库里有本申请的草稿 → 状态必须与草稿一致（已排期 = completed，待确认 = needs_confirmation）；
2. 草稿库里没有 → 不能是 completed；保存失败过 → 一律 failed；
3. 模型的说明里声称“已保存”（实际没有）或“已发布”（系统没有发布能力）→ 换成按事实生成的说明；
4. 结构化字段（草稿、缺失项、命中规则）只来自事实，不采信模型自报；
5. 每份输出都带 facts_summary：一句由代码按草稿库生成的核对结论。
所有修正写进 output.validator.corrections，并保留模型原话（model_claim）。
"""
from __future__ import annotations

import re

from .scheduling import MODEL_STATUSES, SchedulingSession

STATUS_LABELS = {
    "completed": "已保存排期草稿",
    "needs_input": "需要补充信息",
    "needs_confirmation": "等待申请人确认",
    "blocked": "规则风险，已阻断",
    "failed": "未完成（失败）",
    "incomplete_step_limit": "未完成（达到步数上限）",
}
DRAFT_LABELS = {"scheduled_draft": "已排期草稿", "pending_confirmation": "待确认草稿"}
CHANNEL_NAMES = {"douyin": "抖音", "wechat_channels": "视频号", "xiaohongshu": "小红书"}
NOTICE = "本 Agent 只保存排期草稿，没有发布能力；草稿需要人工在发布系统确认后才会发布。"

# 说明文字里的“已保存 / 已发布”声明（同一小句内，前面或中间没有否定词）
_CLAUSE = r"[^。；，,;！!？?\n]"
SAVE_CLAIM = re.compile(rf"已{_CLAUSE}{{0,20}}?(保存|存为|存好|创建|新建|生成|写入|占住|占位|排入|排好|排上)|(保存|创建|写入)成功")
PUBLISH_CLAIM = re.compile(rf"已{_CLAUSE}{{0,12}}?(发布|上线)|(发布|上线)成功")
NEGATIONS = set("未没不无非否别")


def _claims(pattern: re.Pattern, text: str) -> bool:
    for match in pattern.finditer(text or ""):
        before = text[max(0, match.start() - 2):match.start()]
        if not (NEGATIONS & set(match.group(0)) or NEGATIONS & set(before)):
            return True
    return False


def _derived_from_draft(draft: dict) -> str:
    return "needs_confirmation" if draft["status"] == "pending_confirmation" else "completed"


def facts_summary(facts: dict) -> str:
    draft = facts["draft"]
    if draft:
        where = f"{CHANNEL_NAMES.get(draft['channel'], draft['channel'])} {draft['publish_at']}"
        if draft["status"] == "pending_confirmation":
            text = (f"系统核对：草稿库中有本申请的待确认草稿 {draft['draft_id']}（{where}，申请时间 {draft['requested_publish_at']}），"
                    "申请人确认前不会进入排期")
        else:
            text = f"系统核对：草稿库中有本申请的排期草稿 {draft['draft_id']}（{where}）"
        text += "，本次新建" if facts["draft_created_this_run"] else "，此前已存在、本次没有新建"
        return text + "；没有发布任何内容。"
    text = "系统核对：草稿库中没有本申请的草稿，也没有发布任何内容。"
    if facts["save_errors"]:
        err = facts["save_errors"][-1]
        text += f"最后一次保存返回 {err['code']}：{err['message']}。"
    other = facts["conflicting_draft"]
    if other:
        text += f"申请单 {other['request_id']} 已有另一份内容不同的草稿 {other['draft_id']}（{other['publish_at']}）。"
    return text


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
    summary = facts_summary(facts)
    corrections: list[dict] = []
    warnings: list[str] = []
    finish_args = finish_args or {}

    def correct(check: str, old, new, reason: str) -> None:
        corrections.append({"check": check, "from": old, "to": new, "reason": reason})

    if end_reason == "finish":
        status = finish_args.get("status")
        message = finish_args.get("message") or ""
        if status not in MODEL_STATUSES:  # finish 的 Schema 已限制枚举，这里是第二道防线
            new = _derived_from_draft(draft) if draft else "failed"
            correct("status_enum", status, new, f"状态 {status!r} 不在允许范围内（没有发布能力，不存在 published 一类状态）")
            status = new

        # ---- 状态必须与草稿库一致 ----
        if draft is not None:
            derived = _derived_from_draft(draft)
            if status != derived:
                correct("status_matches_store", status, derived,
                        f"草稿库中有本申请的{DRAFT_LABELS[draft['status']]} {draft['draft_id']}，状态以草稿库为准")
                status = derived
        elif facts["save_failed"]:
            if status != "failed":
                correct("save_failure_is_failed", status, "failed", "保存草稿失败，草稿库中没有本申请的草稿")
            status = "failed"
        elif status == "completed":
            correct("no_false_save_success", "completed", "failed", "草稿库中没有本申请的草稿，不能报告为已完成")
            status = "failed"

        # ---- 草稿编号与说明文字 ----
        claimed_id = finish_args.get("draft_id")
        if claimed_id and (draft is None or claimed_id != draft["draft_id"]):
            correct("draft_id_from_store", claimed_id, draft and draft["draft_id"], "模型给出的草稿编号与草稿库不一致，以草稿库为准")
        if _claims(PUBLISH_CLAIM, message):
            correct("message_contradicts_store", "声称已发布", "未发布", "说明里声称已经发布，但系统没有发布能力，草稿不会被发布")
        if draft is None and _claims(SAVE_CLAIM, message):
            correct("message_contradicts_store", "声称已保存", "没有草稿", "说明里声称已保存草稿，但草稿库中没有本申请的草稿")
            if status in ("completed", "needs_confirmation"):
                correct("no_false_save_success", status, "failed", "声称已保存的草稿并不存在，按失败处理")
                status = "failed"
        if status == "blocked" and not facts["block_findings"]:
            warnings.append("模型判定为阻断，但规则检查没有 block 级命中，建议人工复核")
        if status == "needs_input" and not facts["missing_fields"]:
            warnings.append("模型判定需要补充信息，但工具结果里没有缺失项，建议人工复核")
        if corrections:
            message = "【校验器已更正】" + "；".join(c["reason"] for c in corrections) + "。" + summary
    elif end_reason in ("step_limit", "tool_limit"):
        status = "incomplete_step_limit"
        limit = run.get("max_steps") if end_reason == "step_limit" else run.get("max_tool_calls")
        unit = "步数" if end_reason == "step_limit" else "工具调用次数"
        message = f"达到{unit}上限（{limit}），任务未完成；已完成的步骤见 completed_steps。" + summary
    else:  # llm_error
        status = "failed"
        message = f"模型调用失败，处理中断：{error}。" + summary

    rule = facts["rule"]
    output = {
        "request_id": req["request_id"],
        "status": status,
        "status_label": STATUS_LABELS[status],
        "message": message,
        "facts_summary": summary,
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
        "missing_fields": facts["missing_fields"],
        "risk_rule_ids": sorted({f["rule_id"] for f in facts["block_findings"]}),
        "confirmation_question": finish_args.get("confirmation_question"),
        "notice": NOTICE,
        "validator": {"corrections": corrections, "warnings": warnings},
    }
    if facts["conflicting_draft"]:
        output["conflicting_draft"] = _draft_view(facts["conflicting_draft"], False)
    if corrections:
        output["model_claim"] = {k: finish_args.get(k) for k in ("status", "draft_id", "message", "risk_rule_ids", "missing_fields")}
    if status == "incomplete_step_limit":
        output["completed_steps"] = [{"tool": e.name, "ok": e.ok, "args": e.args} for e in session.ledger]
    if error:
        output["error"] = error
    output["run"] = run
    return output
