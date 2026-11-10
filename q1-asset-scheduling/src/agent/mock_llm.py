"""离线 Mock：没有 Key 也能跑通整条流程（工具、校验器、Trace、触顶逻辑）。

注意：Mock 只验证流程，不证明模型决策效果。
- PolicyMockLLM：一套写死的参考策略，读上一步的工具结果决定下一步，供 `--llm mock` 使用；
- ScriptedMockLLM：按脚本逐条返回，供单元测试构造“说谎的模型”“乱调工具的模型”等边界情况。
“模型会根据工具结果调整动作”只能由 examples/ 里真实模型的 Trace 证明。
"""
from __future__ import annotations

import json
import re

from .llm import LLMError, LLMReply, ToolCall

_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.S)


class ScriptedMockLLM:
    mode = "mock"
    model = "scripted-mock"

    def __init__(self, script: list[dict]):
        """script 每项：{"tool": 名称, "args": {...}} / {"tools": [多个工具调用]} / {"content": "只回文字"} / {"raise": "模拟模型调用失败"}。"""
        self._script = list(script)
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        self.calls += 1
        if not self._script:
            return LLMReply(content="（脚本已用完）", model=self.model)
        item = self._script.pop(0)
        if "raise" in item:
            raise LLMError(item["raise"])
        calls = item.get("tools") or ([item] if "tool" in item else [])
        if not calls:
            return LLMReply(content=item.get("content", ""), model=self.model)
        tool_calls = []
        for i, c in enumerate(calls):
            args = c.get("args", {})
            raw = args if isinstance(args, str) else json.dumps(args, ensure_ascii=False)
            tool_calls.append(ToolCall(id=f"mock_{self.calls}_{i}", name=c["tool"], arguments=raw))
        return LLMReply(content=item.get("content", ""), tool_calls=tool_calls, model=self.model)


class _Obs:
    """一次工具调用及其结果，从对话历史里还原出来。"""

    def __init__(self, name: str, args: dict, result: dict):
        self.name, self.args, self.result = name, args, result
        self.ok = bool(result.get("ok"))
        self.data = result.get("data") or {}
        self.error = result.get("error") or {}


def _replay(messages: list[dict]) -> tuple[dict, list[_Obs]]:
    request: dict = {}
    pending: dict[str, tuple[str, dict]] = {}
    history: list[_Obs] = []
    for m in messages:
        if m["role"] == "user" and not request:
            found = _JSON_BLOCK.search(m.get("content") or "")
            request = json.loads(found.group(1)) if found else {}
        elif m["role"] == "assistant":
            for c in m.get("tool_calls") or []:
                pending[c["id"]] = (c["function"]["name"], json.loads(c["function"]["arguments"] or "{}"))
        elif m["role"] == "tool":
            name, args = pending.pop(m["tool_call_id"], ("?", {}))
            history.append(_Obs(name, args, json.loads(m["content"])))
    return request, history


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def decide(request: dict, history: list[_Obs]) -> tuple[str, dict]:
    """参考策略：固定规则，等价于“写死的分支版 Agent”，只用于离线跑通流程。"""
    asset_id, channel, publish_at = request.get("asset_id"), request.get("channel"), request.get("publish_at")

    def last(name: str) -> _Obs | None:
        return next((o for o in reversed(history) if o.name == name), None)

    def count(name: str) -> int:
        return sum(1 for o in history if o.name == name)

    def note(text: str) -> str:
        return f"[mock 参考策略] {text}"

    def finish(status: str, message: str, why: str, **extra) -> tuple[str, dict]:
        return "finish", {"status": status, "message": message, "decision_note": note(why), **extra}

    missing_req = [k for k in ("asset_id", "channel", "publish_at") if not request.get(k)]
    if missing_req:
        return finish("needs_input", "申请单缺少：" + "、".join(missing_req), "申请单不完整", missing_fields=missing_req)

    ra = last("read_asset")
    if ra is None:
        return "read_asset", {"asset_id": asset_id, "decision_note": note("先读取素材信息")}
    if not ra.ok:
        if ra.error.get("retryable") and count("read_asset") < 2:
            return "read_asset", {"asset_id": asset_id, "decision_note": note("可重试错误，重试一次")}
        if ra.error.get("code") == "ASSET_NOT_FOUND":
            return finish("needs_input", f"素材库中没有 {asset_id}，请确认素材 ID。", "素材不存在", missing_fields=["asset_id"])
        return finish("failed", f"读取素材失败：{ra.error.get('message')}", "读取素材失败")
    if ra.data.get("missing_fields"):
        labels = "、".join(ra.data.get("missing_labels") or ra.data["missing_fields"])
        return finish("needs_input", f"素材缺少必填信息：{labels}，请补齐后重新提交。", "必填信息缺失",
                      missing_fields=ra.data["missing_fields"])

    cr = last("check_rules")
    if cr is None:
        return "check_rules", {"asset_id": asset_id, "channel": channel, "decision_note": note("素材信息齐全，做规则检查")}
    if not cr.ok:
        if cr.error.get("retryable") and count("check_rules") < 2:
            return "check_rules", {**{k: v for k, v in cr.args.items()}, "decision_note": note("规则服务可重试，重试一次")}
        return finish("failed", f"规则检查失败：{cr.error.get('message')}", "规则检查失败")
    verdict = cr.data["verdict"]
    if verdict == "incomplete":
        return finish("needs_input", "素材缺少必填信息，请补齐后重新提交。", "规则检查提示信息缺失",
                      missing_fields=[f for x in cr.data["findings"] for f in x.get("fields", [])])
    if verdict == "block":
        ids = sorted({f["rule_id"] for f in cr.data["findings"] if f["level"] == "block"})
        return finish("blocked", "规则检查存在阻断项：" + "；".join(f["message"] for f in cr.data["findings"] if f["level"] == "block"),
                      "存在 block 级规则命中", risk_rule_ids=ids)
    if verdict == "needs_verification":
        return "check_rules", {"asset_id": asset_id, "channel": channel, "deep_check": True, "decision_note": note("存在待补查项，补查版权库")}

    date, time = publish_at.split(" ")
    queries = [o for o in history if o.name == "query_slots"]
    if not queries:
        return "query_slots", {"channel": channel, "date": date, "time": time, "decision_note": note("规则通过，查申请时段")}
    lq = queries[-1]
    if not lq.ok:
        if lq.error.get("retryable") and len(queries) < 3:
            return "query_slots", {**lq.args, "decision_note": note("日历服务可重试，重试一次")}
        return finish("failed", f"查询时段失败：{lq.error.get('message')}", "查询时段失败")

    target = None
    for o in queries:
        if o.ok:
            for s in o.data["slots"]:
                if s["time"] == time:
                    target = s
    sd = last("save_draft")
    if sd is None:
        occupant = (target or {}).get("occupied_by") or {}
        mine = occupant.get("type") == "draft" and occupant.get("asset_id") == asset_id
        if target and (target["status"] == "free" or mine):
            return "save_draft", {"asset_id": asset_id, "channel": channel, "publish_at": publish_at,
                                  "requires_confirmation": False, "decision_note": note("申请时段可用（或是同一素材的已有草稿），按申请时间保存")}
        day = next((o for o in reversed(queries) if o.ok and "free_slots" in o.data), None)
        if day is None:
            return "query_slots", {"channel": channel, "date": date, "decision_note": note("申请时段被占用，查当天其他时段")}
        free = day.data["free_slots"]
        if not free:
            return finish("needs_confirmation", f"{date} 当天没有空闲时段，日期是否可以调整？", "当天无空闲时段且不能擅自改日期",
                          confirmation_question="当天时段已排满，能否改到其他日期？")
        best = min(free, key=lambda t: (abs(_minutes(t) - _minutes(time)), -_minutes(t)))
        return "save_draft", {"asset_id": asset_id, "channel": channel, "publish_at": f"{date} {best}", "requires_confirmation": True,
                              "change_reason": f"{time} 已被占用，改为当天最近的空闲时段 {best}", "decision_note": note("选最近的空闲时段并标记待确认")}
    if sd.ok:
        d = sd.data["draft"]
        dup = "" if sd.data["created"] else "（重复提交，返回已有草稿，未新建）"
        if d["status"] == "pending_confirmation":
            return finish("needs_confirmation", f"申请时段不可用，已保存待确认草稿 {d['draft_id']}（{d['publish_at']}）{dup}，请确认。",
                          "草稿为待确认状态", draft_id=d["draft_id"], publish_at=d["publish_at"],
                          confirmation_question=f"是否同意改到 {d['publish_at']}？")
        return finish("completed", f"已保存排期草稿 {d['draft_id']}（{d['publish_at']}）{dup}。", "草稿保存成功",
                      draft_id=d["draft_id"], publish_at=d["publish_at"])
    if sd.error.get("retryable") and count("save_draft") < 2 and sd.error.get("code") != "SLOT_OCCUPIED":
        return "save_draft", {**sd.args, "decision_note": note("保存失败但可重试，重试一次")}
    return finish("failed", f"草稿未保存：{sd.error.get('code')} {sd.error.get('message')}", "保存失败，如实报告")


class PolicyMockLLM:
    mode = "mock"
    model = "policy-mock"

    def __init__(self):
        self.calls = 0

    def chat(self, messages: list[dict], tools: list[dict]) -> LLMReply:
        self.calls += 1
        request, history = _replay(messages)
        name, args = decide(request, history)
        return LLMReply(content="", tool_calls=[ToolCall(id=f"mock_{self.calls}", name=name, arguments=json.dumps(args, ensure_ascii=False))], model=self.model)
