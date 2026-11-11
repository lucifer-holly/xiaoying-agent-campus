"""用真实模型把每个用例重复跑 N 次，统计满足 expected 的比例和实际走过的路径。

    python scripts/eval_stability.py --runs 3

结果写到 examples/stability-report.json，不覆盖正式录制的 *.output.json / *.trace.json。
它回答的是“同一输入下模型的决策稳不稳定”，不是新的验收用例。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from agent.prompts import PROMPT_VERSION  # noqa: E402
from expectations import check_expected  # noqa: E402
from main import load_case, make_llm, run_case  # noqa: E402

EXAMPLES = ROOT / "examples"


def path_of(trace: dict) -> str:
    runs = trace.get("runs") or [trace]
    return " | ".join(" → ".join(s["tool"] or "(无工具)" for s in t["steps"]) for t in runs)


def usage_of(trace: dict) -> tuple[int, int]:
    runs = trace.get("runs") or [trace]
    return (sum(t["llm_usage"]["prompt_tokens"] + t["llm_usage"]["completion_tokens"] for t in runs),
            sum(t["llm_usage"]["latency_ms"] for t in runs))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--cases", help="逗号分隔的用例编号前缀")
    parser.add_argument("--out", default=str(EXAMPLES / "stability-report.json"))
    args = parser.parse_args()

    llm = make_llm("real")
    wanted = [c.strip() for c in args.cases.split(",")] if args.cases else None
    cases_report = []
    for path in sorted(EXAMPLES.glob("*.input.json")):
        case = load_case(path)
        if wanted and not any(case["case"].startswith(w) for w in wanted):
            continue
        paths, problems, tokens, latency, passed = Counter(), [], 0, 0, 0
        for i in range(args.runs):
            output, trace = run_case(case, llm=llm)
            found = check_expected(case, output, trace)
            passed += not found
            paths[path_of(trace)] += 1
            problems += [f"run{i + 1}: {p}" for p in found]
            t, ms = usage_of(trace)
            tokens += t
            latency += ms
        cases_report.append({
            "case": case["case"],
            "passed": passed,
            "runs": args.runs,
            "paths": dict(paths),
            "problems": problems,
            "avg_tokens": round(tokens / args.runs),
            "avg_llm_latency_s": round(latency / args.runs / 1000, 1),
        })
        print(f"{case['case']:<30} {passed}/{args.runs}  路径 {len(paths)} 种", flush=True)

    total_runs = sum(c["runs"] for c in cases_report)
    total_passed = sum(c["passed"] for c in cases_report)
    report = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "model": llm.model,
        "prompt_version": PROMPT_VERSION,
        "runs_per_case": args.runs,
        "total": {"passed": total_passed, "runs": total_runs},
        "cases": cases_report,
    }
    Path(args.out).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"\n合计 {total_passed}/{total_runs} 次满足预期；报告：{args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
