"""命令行入口。

    python src/main.py --input examples/01-normal-free-slot.input.json --llm mock
    python src/main.py --input examples/02-slot-conflict.input.json --llm real

结构化结果（JSON）打印到标准输出，或用 --output 写文件；Trace 写到 --trace-out（默认 runs/ 目录）。
标准错误里会打印逐步摘要，方便直接在终端看 Agent 做了什么。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from agent.llm import LLMUnavailable, QwenLLM  # noqa: E402
from agent.loop import DEFAULT_MAX_STEPS, DEFAULT_MAX_TOOL_CALLS, run_agent  # noqa: E402
from agent.mock_llm import PolicyMockLLM  # noqa: E402
from config import PROJECT_ROOT, llm_settings  # noqa: E402
from domain.scheduling import SchedulingSession, summarize  # noqa: E402
from domain.store import DataStore  # noqa: E402
from domain.validator import build_output  # noqa: E402

MOCK_NOTICE = "[mock] 离线参考策略：只验证流程（工具、校验器、Trace、触顶），不证明模型决策效果。"


def make_llm(mode: str):
    if mode == "mock":
        return PolicyMockLLM()
    return QwenLLM(llm_settings())


def load_case(path: Path) -> dict:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if "request" not in data:  # 也接受只有申请单本身的文件
        data = {"request": data}
    data.setdefault("case", Path(path).name.split(".")[0])
    return data


def run_case(case: dict, *, llm, max_steps: int | None = None, max_tool_calls: int | None = None,
             store: DataStore | None = None, repeat: int | None = None) -> tuple[dict, dict]:
    """跑一个用例。repeat>1 时用同一个草稿库连续提交多次（用来验证防重复）。"""
    options = case.get("options") or {}

    def pick(cli_value, key, default):
        value = cli_value if cli_value is not None else options.get(key, default)
        if not isinstance(value, int) or value < 1:
            raise ValueError(f"{key} 必须是正整数，收到 {value!r}")
        return value

    max_steps = pick(max_steps, "max_steps", DEFAULT_MAX_STEPS)
    max_tool_calls = pick(max_tool_calls, "max_tool_calls", DEFAULT_MAX_TOOL_CALLS)
    repeat = pick(repeat, "repeat", 1)
    store = store or DataStore()
    outputs, traces = [], []
    for _ in range(repeat):
        session = SchedulingSession(store, case["request"], case.get("fault_injection"))
        result = run_agent(session=session, llm=llm, finalize=build_output, summarize=summarize,
                           max_steps=max_steps, max_tool_calls=max_tool_calls, case_id=case["case"])
        outputs.append(result.output)
        traces.append(result.trace)
    if repeat == 1:
        return outputs[0], traces[0]
    request_id = outputs[0]["request_id"]
    mine = [d for d in store.drafts() if d["request_id"] == request_id]
    combined = {
        "case_id": case["case"],
        "repeat": repeat,
        "runs": outputs,
        "store_check": {
            "request_id": request_id,
            "drafts_for_request": len(mine),
            "draft_ids": [d["draft_id"] for d in mine],
            "total_drafts_in_store": len(store.drafts()),
        },
    }
    return combined, {"case_id": case["case"], "repeat": repeat, "runs": traces}


def print_steps(trace: dict, stream=sys.stderr) -> None:
    runs = trace["runs"] if "runs" in trace else [trace]
    for i, t in enumerate(runs, 1):
        if len(runs) > 1:
            print(f"--- 第 {i} 次提交 ---", file=stream)
        print(f"[{t['llm_mode']}] model={t['model']} prompt={t['prompt_version']}", file=stream)
        for s in t["steps"]:
            args = ", ".join(f"{k}={v}" for k, v in s["args"].items() if k != "message")
            print(f"  #{s['step']} {s['tool'] or '(无工具)'}({args})", file=stream)
            print(f"      结果：{s['result_summary']}", file=stream)
            if s.get("decision_note"):
                print(f"      依据：{s['decision_note']}", file=stream)
        final = t["final"]
        print(f"  => status={final['status']}（{final['status_label']}）", file=stream)
        for c in final["validator"]["corrections"]:
            print(f"     校验器更正：{c['from']} -> {c['to']}：{c['reason']}", file=stream)


def positive_int(text: str) -> int:
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError("必须是正整数")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="素材审核与发布排期 Agent（Q1）")
    parser.add_argument("--input", required=True, help="用例文件（examples/*.input.json）")
    parser.add_argument("--llm", choices=["mock", "real"], default="mock", help="mock=离线参考策略；real=真实模型（需要 LLM_API_KEY）")
    parser.add_argument("--max-steps", type=positive_int, help=f"步数上限（默认 {DEFAULT_MAX_STEPS}，用例 options 可覆盖）")
    parser.add_argument("--max-tool-calls", type=positive_int, help=f"工具调用次数上限（默认 {DEFAULT_MAX_TOOL_CALLS}）")
    parser.add_argument("--trace-out", help="Trace 输出路径（默认 runs/<用例>.<llm>.trace.json）")
    parser.add_argument("--output", help="结果 JSON 输出路径（默认打印到标准输出）")
    parser.add_argument("--store", help="草稿库 JSON 文件；不传则只在内存里（每次运行互不影响）")
    parser.add_argument("--repeat", type=positive_int, help="同一申请连续提交的次数（共用草稿库，用于验证防重复）")
    parser.add_argument("--quiet", action="store_true", help="不在标准错误打印逐步摘要")
    args = parser.parse_args(argv)

    case = load_case(Path(args.input))
    try:
        llm = make_llm(args.llm)
    except LLMUnavailable as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 3
    if args.llm == "mock" and not args.quiet:
        print(MOCK_NOTICE, file=sys.stderr)
    store = DataStore(drafts_path=Path(args.store) if args.store else None)
    try:
        output, trace = run_case(case, llm=llm, max_steps=args.max_steps, max_tool_calls=args.max_tool_calls,
                                 store=store, repeat=args.repeat)
    except ValueError as exc:  # 例如 fault_injection 配置写错
        print(f"错误：{exc}", file=sys.stderr)
        return 2

    trace_path = Path(args.trace_out) if args.trace_out else PROJECT_ROOT / "runs" / f"{case['case']}.{args.llm}.trace.json"
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    trace_path.write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    text = json.dumps(output, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    if not args.quiet:
        print_steps(trace)
        print(f"Trace 已写入 {trace_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
