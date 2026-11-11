"""把 examples/ 里的真实录制打包成回放页的数据文件 demo/data/replay.js。

    python scripts/build_demo.py

回放页（demo/index.html）直接读这个文件，所以本地双击打开、GitHub Pages、演示服务三种方式都能用。
数据原样来自 examples/*.output.json / *.trace.json，不做任何修改。
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"
OUT = ROOT / "demo" / "data" / "replay.js"
# 迭代记录在回放页上的说明（这些结论来自 docs/03 第 5 节的分析，不是脚本推断出来的）
ITERATION_NOTES = {
    "02-slot-conflict.q1-v1": "提示词迭代前：时段冲突时找到 19:00 却没有先保存待确认草稿",
}


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    cases = []
    for path in sorted(EXAMPLES.glob("*.input.json")):
        case_id = path.name.split(".")[0]
        out_path, trace_path = EXAMPLES / f"{case_id}.output.json", EXAMPLES / f"{case_id}.trace.json"
        if not (out_path.exists() and trace_path.exists()):
            print(f"跳过 {case_id}：还没有录制结果", file=sys.stderr)
            continue
        spec = load(path)
        cases.append({
            "case": case_id,
            "title": spec.get("title"),
            "covers": spec.get("covers", []),
            "request": spec["request"],
            "fault_injection": spec.get("fault_injection") or {},
            "options": spec.get("options") or {},
            "expected": spec.get("expected") or {},
            "output": load(out_path),
            "trace": load(trace_path),
        })
    iterations = []
    for trace_path in sorted((EXAMPLES / "prompt-iterations").glob("*.trace.json")):
        out_path = trace_path.with_name(trace_path.name.replace(".trace.json", ".output.json"))
        trace = load(trace_path)
        iterations.append({
            "case": trace_path.name.replace(".trace.json", ""),
            "title": ITERATION_NOTES.get(trace_path.name.replace(".trace.json", ""),
                                         f"{trace['case_id']}：提示词迭代前的原始记录"),
            "request": trace["request"],
            "fault_injection": trace.get("fault_injection") or {},
            "output": load(out_path) if out_path.exists() else trace["final"],
            "trace": trace,
        })
    if not cases:
        print("没有可打包的录制结果，先运行 scripts/record_examples.py --llm real", file=sys.stderr)
        return 1
    first = cases[0]["trace"].get("runs", [cases[0]["trace"]])[0]
    stability = None
    if (EXAMPLES / "stability-report.json").exists():
        report = load(EXAMPLES / "stability-report.json")
        stability = {**report["total"], "runs_per_case": report["runs_per_case"]}
    tests_passed = None
    if (EXAMPLES / "test-results.txt").exists():
        found = re.search(r"(\d+) passed", (EXAMPLES / "test-results.txt").read_text(encoding="utf-8"))
        tests_passed = int(found.group(1)) if found else None
    payload = {
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "model": first["model"],
        "prompt_version": first["prompt_version"],
        "stability": stability,
        "tests_passed": tests_passed,
        "cases": cases,
        "iterations": iterations,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text("// 由 scripts/build_demo.py 生成，请勿手工修改\nwindow.Q1_REPLAY = " + body + ";\n", encoding="utf-8")
    print(f"已写入 {OUT.relative_to(ROOT)}：{len(cases)} 个用例，{len(iterations)} 条迭代记录，{OUT.stat().st_size // 1024} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
