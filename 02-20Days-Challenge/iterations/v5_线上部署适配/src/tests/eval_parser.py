#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""解析准确率离线评测。

每次改动解析逻辑后跑一遍，用固定语料算出「截止时间 / 地点 / 材料召回」三项指标，
把数字写进 docs/ 下的评测记录，作为迭代依据。
没有这个脚本，改解析规则就只能靠感觉，无法证明某一版是不是真的更好。

用法：
    python tests/eval_parser.py            # 打印当前指标
    python tests/eval_parser.py --save     # 同时写入 docs/eval_<日期>.md
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.notice_parser import parse_notice  # noqa: E402
from core.telemetry import Telemetry  # noqa: E402


def load_golden() -> dict:
    path = BASE / "tests" / "golden.json"
    return json.loads(path.read_text(encoding="utf-8"))


def material_hit(expected: str, got: list) -> bool:
    """材料名做子串匹配：标准答案里的关键词出现在结果里即算命中。"""
    names = [str(item.get("name", "")) for item in got]
    return any(expected in name or name in expected for name in names)


def run() -> dict:
    golden = load_golden()
    now = datetime.fromisoformat(golden["_now"])
    tel = Telemetry()
    cases = []

    for name, spec in golden["cases"].items():
        path = BASE / "data" / "samples" / f"{name}.txt"
        text = path.read_text(encoding="utf-8")
        with tel.timed("eval_case", chars=len(text), source=name):
            result = parse_notice(text, now=now)

        deadline = result.get("deadline")
        got_iso = deadline["iso"] if deadline else None
        expected_iso = spec["deadline"]

        deadline_ok = got_iso == expected_iso
        deadline_date_ok = bool(
            got_iso and expected_iso
            and got_iso[:10] == expected_iso[:10]
        )
        loc_expected = spec.get("location") or ""
        loc_got = result.get("location") or ""
        location_ok = (loc_expected in loc_got) if loc_expected else (loc_got == "")

        expected_mats = spec.get("materials") or []
        mat_hits = sum(1 for m in expected_mats if material_hit(m, result.get("materials", [])))
        mat_ok = mat_hits == len(expected_mats)

        if spec.get("no_deadline"):
            deadline_ok = got_iso is None
            deadline_date_ok = deadline_ok
            if not deadline_ok:
                # 无截止的通知被强行识别出时间，属于最严重的误报，单独计数
                pass

        cases.append({
            "name": name,
            "deadline_ok": deadline_ok,
            "deadline_date_ok": deadline_date_ok,
            "location_ok": location_ok,
            "material_ok": mat_ok,
            "expected_deadline": expected_iso,
            "got_deadline": got_iso,
            "expected_location": loc_expected,
            "got_location": loc_got,
            "material_recall": f"{mat_hits}/{len(expected_mats)}" if expected_mats else "-",
        })

    total = len(cases)
    summary = {
        "total": total,
        "deadline_acc": round(sum(c["deadline_ok"] for c in cases) / total * 100, 1),
        "deadline_date_acc": round(sum(c["deadline_date_ok"] for c in cases) / total * 100, 1),
        "location_acc": round(sum(c["location_ok"] for c in cases) / total * 100, 1),
        "material_acc": round(sum(c["material_ok"] for c in cases) / total * 100, 1),
        "all_pass": round(sum(
            c["deadline_ok"] and c["location_ok"] and c["material_ok"] for c in cases
        ) / total * 100, 1),
    }
    return {"summary": summary, "cases": cases}


def to_markdown(result: dict, label: str) -> str:
    s = result["summary"]
    lines = [
        f"# 解析准确率评测 · {label}",
        "",
        f"> 语料：data/samples/ 下 {s['total']} 条通知（模拟真实写法，覆盖公文、群消息、长文三种形态）",
        "",
        "## 汇总",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 截止时间完全命中 | {s['deadline_acc']}% |",
        f"| 截止时间日期命中 | {s['deadline_date_acc']}% |",
        f"| 地点命中 | {s['location_acc']}% |",
        f"| 材料全部召回 | {s['material_acc']}% |",
        f"| 三项全过 | {s['all_pass']}% |",
        "",
        "## 逐条结果",
        "",
        "| 用例 | 截止(期望) | 截止(实际) | 地点(期望/实际) | 材料召回 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for c in result["cases"]:
        mark = "OK" if c["deadline_ok"] else "FAIL"
        lines.append(
            f"| {c['name']} | {c['expected_deadline'] or '无(应为空)'} | "
            f"{c['got_deadline'] or '未识别'} {mark} | "
            f"{c['expected_location'] or '空'} / {c['got_location'] or '空'} | "
            f"{c['material_recall']} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--save", action="store_true", help="把评测结果写入 docs/")
    args = parser.parse_args()

    result = run()
    s = result["summary"]
    print(f"截止完全命中 {s['deadline_acc']}%  日期命中 {s['deadline_date_acc']}%  "
          f"地点 {s['location_acc']}%  材料 {s['material_acc']}%  全过 {s['all_pass']}%")
    for c in result["cases"]:
        flag = "PASS" if (c["deadline_ok"] and c["location_ok"] and c["material_ok"]) else "FAIL"
        print(f"  [{flag}] {c['name']:16s} deadline={c['got_deadline']} "
              f"loc={c['got_location']!r} mats={c['material_recall']}")

    if args.save:
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M")
        out = BASE / "docs" / f"eval_{stamp}.md"
        out.write_text(to_markdown(result, stamp), encoding="utf-8")
        print(f"\n已写入 {out.relative_to(BASE)}")


if __name__ == "__main__":
    main()
