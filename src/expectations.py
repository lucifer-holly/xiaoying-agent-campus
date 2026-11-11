"""把一次运行的输出 / Trace 与用例文件里的 expected 对照。

录制脚本用它给出提示，测试用它做断言（Mock 和真实录制共用同一套标准）。
expected 支持的键：
  status                 每次运行的最终状态
  draft                  null 表示最后不应有草稿
  draft_status           草稿状态（scheduled_draft / pending_confirmation）
  draft_publish_at       草稿发布时间
  tools_include          必须调用过的工具
  tools_exclude          不得调用的工具
  missing_fields_include 输出 missing_fields 必须包含的项
  risk_rule_ids_include  输出 risk_rule_ids 必须包含的项
  deep_check_called      是否调用过 check_rules(deep_check=true)
  drafts_for_request     （repeat 用例）草稿库里该申请的草稿数
  second_run_created     （repeat 用例）第二次提交是否新建了草稿
"""
from __future__ import annotations


def _runs(doc: dict) -> list[dict]:
    return doc.get("runs") or [doc]


def check_expected(case: dict, output: dict, trace: dict) -> list[str]:
    exp = case.get("expected") or {}
    outs, traces = _runs(output), _runs(trace)
    problems: list[str] = []
    for i, (out, tr) in enumerate(zip(outs, traces), 1):
        tag = f"run{i}"
        tools = [s["tool"] for s in tr["steps"] if s["tool"]]
        if exp.get("status") and out["status"] != exp["status"]:
            problems.append(f"{tag}: status={out['status']}，预期 {exp['status']}")
        for name in exp.get("tools_include", []):
            if name not in tools:
                problems.append(f"{tag}: 没有调用 {name}")
        for name in exp.get("tools_exclude", []):
            if name in tools:
                problems.append(f"{tag}: 不应调用 {name}")
        if exp.get("deep_check_called") and not any(s["tool"] == "check_rules" and s["args"].get("deep_check") for s in tr["steps"]):
            problems.append(f"{tag}: 没有 deep_check 补查")
        for field in exp.get("missing_fields_include", []):
            if field not in out.get("missing_fields", []):
                problems.append(f"{tag}: missing_fields 缺少 {field}")
        for rule_id in exp.get("risk_rule_ids_include", []):
            if rule_id not in out.get("risk_rule_ids", []):
                problems.append(f"{tag}: risk_rule_ids 缺少 {rule_id}")
        if out["status"] == "published" or (out.get("draft") or {}).get("status") not in (None, "scheduled_draft", "pending_confirmation"):
            problems.append(f"{tag}: 出现了不允许的状态")
    last = outs[-1]
    draft = last.get("draft") or {}
    if "draft" in exp and exp["draft"] is None and last.get("draft") is not None:
        problems.append("预期没有草稿，实际有草稿")
    if exp.get("draft_status") and draft.get("status") != exp["draft_status"]:
        problems.append(f"草稿状态 {draft.get('status')}，预期 {exp['draft_status']}")
    if exp.get("draft_publish_at") and draft.get("publish_at") != exp["draft_publish_at"]:
        problems.append(f"草稿时间 {draft.get('publish_at')}，预期 {exp['draft_publish_at']}")
    if "drafts_for_request" in exp:
        got = (output.get("store_check") or {}).get("drafts_for_request")
        if got != exp["drafts_for_request"]:
            problems.append(f"该申请的草稿数 {got}，预期 {exp['drafts_for_request']}")
    if "second_run_created" in exp and len(outs) > 1:
        got = (outs[1].get("draft") or {}).get("created_in_this_run")
        if got != exp["second_run_created"]:
            problems.append(f"第二次提交 created_in_this_run={got}，预期 {exp['second_run_created']}")
        ids = {(o.get("draft") or {}).get("draft_id") for o in outs}
        if len(ids) != 1:
            problems.append(f"多次提交得到的草稿编号不一致：{ids}")
    return problems
