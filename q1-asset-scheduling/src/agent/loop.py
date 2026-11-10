"""ReAct 循环：调用模型 → 解析工具调用 → 执行工具 → 把观察写回对话 → 直到 finish 或触顶。

循环本身没有任何业务分支：下一步做什么完全由模型根据上一步的观察决定。
循环只守三条边界：步数 / 工具调用次数上限；参数不合法时把错误交还模型；
finish 之后交给校验器（finalize）和事实核对，再决定最终状态。
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Callable

from .llm import LLMError
from .prompts import NUDGE, PROMPT_VERSION, SYSTEM_PROMPT, render_request
from .trace import Trace

DEFAULT_MAX_STEPS = 8
DEFAULT_MAX_TOOL_CALLS = 10


@dataclass
class AgentResult:
    output: dict
    trace: dict


def run_agent(*, session, llm, finalize: Callable[..., dict], summarize: Callable[[str, dict, dict], str],
              max_steps: int = DEFAULT_MAX_STEPS, max_tool_calls: int = DEFAULT_MAX_TOOL_CALLS,
              case_id: str | None = None) -> AgentResult:
    registry = session.registry
    limits = {"max_steps": max_steps, "max_tool_calls": max_tool_calls}
    trace = Trace(case_id=case_id, llm_mode=llm.mode, model=llm.model, prompt_version=PROMPT_VERSION,
                  limits=limits, request=session.request, fault_injection=session.fault_injection)
    messages: list[dict] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": render_request(session.request)},
    ]
    tools = registry.schemas()
    end_reason, finish_args, error, finish_step = "step_limit", None, None, None
    step = tool_calls_used = 0

    while step < max_steps:
        step += 1
        try:
            reply = llm.chat(messages, tools)
        except LLMError as exc:
            end_reason, error = "llm_error", str(exc)
            break
        llm_meta = trace.record_llm(reply.model, reply.latency_ms, reply.usage)

        if not reply.tool_calls:  # 模型只回了文字：提醒一次，算作一步
            messages.append({"role": "assistant", "content": reply.content or ""})
            messages.append({"role": "user", "content": NUDGE})
            trace.add_step(step=step, tool=None, args={}, decision_note=None, ok=False,
                           result_summary="模型没有调用工具，已提示它继续或调用 finish",
                           observation=None, llm=llm_meta, assistant_text=reply.content)
            continue

        messages.append(reply.to_message())
        done = False
        for call in reply.tool_calls:
            if tool_calls_used >= max_tool_calls:
                end_reason, done = "tool_limit", True
                break
            tool_calls_used += 1
            if call.name == "finish":
                args, note, errors = registry.parse("finish", call.arguments)
                if errors:  # finish 参数不合法：把错误交还模型，让它重新提交
                    result = {"ok": False, "error": {"code": "INVALID_ARGUMENTS", "message": "；".join(errors), "retryable": True}}
                    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, ensure_ascii=False)})
                    trace.add_step(step=step, tool="finish", args=args, decision_note=note, ok=False,
                                   result_summary="finish 参数不合法：" + "；".join(errors),
                                   observation=result, llm=llm_meta, assistant_text=reply.content)
                    continue
                end_reason, finish_args, done = "finish", args, True
                finish_step = (step, note, llm_meta, reply.content)
                break
            execution = registry.execute(call.name, call.arguments)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(execution.result, ensure_ascii=False)})
            trace.add_step(step=step, tool=call.name, args=execution.args, decision_note=execution.decision_note,
                           ok=execution.ok, result_summary=summarize(call.name, execution.args, execution.result),
                           observation=execution.result, llm=llm_meta, assistant_text=reply.content)
        if done:
            break

    run = {"llm_mode": llm.mode, "model": llm.model, "prompt_version": PROMPT_VERSION,
           "steps_used": step, "tool_calls_used": tool_calls_used, **limits, "end_reason": end_reason}
    output = finalize(session=session, finish_args=finish_args, end_reason=end_reason, run=run, error=error)

    if finish_step:
        s, note, llm_meta, text = finish_step
        corrections = output["validator"]["corrections"]
        summary = f"模型提交 status={finish_args.get('status')}；校验后 status={output['status']}"
        summary += f"（更正 {len(corrections)} 处）" if corrections else "（无更正）"
        trace.add_step(step=s, tool="finish", args=finish_args, decision_note=note, ok=True, result_summary=summary,
                       observation={"validated_status": output["status"], "corrections": corrections},
                       llm=llm_meta, assistant_text=text)
    elif error:
        trace.add_step(step=step, tool=None, args={}, decision_note=None, ok=False,
                       result_summary=f"模型调用失败：{error}", observation=None, llm=None)
    trace.end(end_reason, output)
    return AgentResult(output=output, trace=trace.to_dict())
