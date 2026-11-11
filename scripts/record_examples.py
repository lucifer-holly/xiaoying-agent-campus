"""批量运行 examples/*.input.json 并落盘 *.output.json / *.trace.json。

    python scripts/record_examples.py --llm real              # 用真实模型录制全部用例（覆盖 examples/）
    python scripts/record_examples.py --llm real --cases 02,07 # 只录指定用例
    python scripts/record_examples.py --llm mock --out runs/mock-examples   # 离线跑一遍，不覆盖正式录制结果

录制结果以真实运行为准，不手工修改；未走出预期路径时调整提示词重录，并在 docs/03 记录迭代过程。
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from expectations import check_expected  # noqa: E402
from main import load_case, make_llm, run_case  # noqa: E402

EXAMPLES = ROOT / "examples"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--llm", choices=["mock", "real"], required=True)
    parser.add_argument("--cases", help="逗号分隔的用例编号前缀，例如 01,02")
    parser.add_argument("--out", help="输出目录（默认 examples/，即覆盖正式录制结果）")
    args = parser.parse_args()

    out_dir = Path(args.out) if args.out else EXAMPLES
    out_dir.mkdir(parents=True, exist_ok=True)
    wanted = [c.strip() for c in args.cases.split(",")] if args.cases else None
    llm = make_llm(args.llm)
    failures = 0
    for path in sorted(EXAMPLES.glob("*.input.json")):
        case = load_case(path)
        if wanted and not any(case["case"].startswith(w) for w in wanted):
            continue
        started = time.monotonic()
        output, trace = run_case(case, llm=llm)
        elapsed = time.monotonic() - started
        (out_dir / f"{case['case']}.output.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (out_dir / f"{case['case']}.trace.json").write_text(json.dumps(trace, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        runs = trace.get("runs") or [trace]
        tools = " | ".join(" → ".join(s["tool"] or "(无工具)" for s in t["steps"]) for t in runs)
        statuses = ",".join(r["status"] for r in (output.get("runs") or [output]))
        problems = check_expected(case, output, trace)
        failures += bool(problems)
        mark = "OK " if not problems else "DIFF"
        print(f"[{mark}] {case['case']:<28} {statuses:<24} {elapsed:5.1f}s  {tools}")
        for p in problems:
            print(f"       ! {p}")
    print(f"\n{'全部符合预期' if not failures else f'{failures} 个用例与预期不符（如实保留，见上）'}；输出目录：{out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
