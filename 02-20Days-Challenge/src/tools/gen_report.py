#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""多日运行汇总报告。

把 process_logs/ 下的逐日日志汇总成一份可以直接写进作业的 Markdown：
覆盖天数、每日指标、事件分布、错误清单、趋势对比。

    python tools/gen_report.py            # 输出到 docs/运行日志汇总.md
    python tools/gen_report.py --stdout   # 只打印
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.telemetry import Telemetry, percentile, summarize_records  # noqa: E402


def collect() -> tuple[list, Counter, list]:
    tel = Telemetry()
    dates = tel.available_dates()
    rows, events, errors = [], Counter(), []

    for date in dates:
        records = tel.read_day(date)
        summary = summarize_records(records)
        rows.append(summary)
        events.update(summary["event_counts"])
        for rec in records:
            if not rec.get("ok", True):
                errors.append(rec)

    return rows, events, errors


def render(rows: list, events: Counter, errors: list) -> str:
    if not rows:
        return "# 运行日志汇总\n\n暂无日志。\n"

    total_events = sum(r["events"] for r in rows)
    total_errors = sum(r["errors"] for r in rows)
    avg = round(sum(r["avg_ms"] * r["events"] for r in rows) / total_events, 2) if total_events else 0

    lines = [
        "# 程序自动化运行日志汇总",
        "",
        f"> 统计区间：{rows[0]['date']} — {rows[-1]['date']}，连续 {len(rows)} 天",
        f"> 本报告由 `tools/gen_report.py` 于 {datetime.now():%Y-%m-%d %H:%M} 自动生成，"
        "数据源为 `process_logs/*.jsonl`",
        "",
        "## 总体指标",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 覆盖天数 | {len(rows)} 天 |",
        f"| 事件总数 | {total_events} |",
        f"| 错误总数 | {total_errors}（{round(total_errors / total_events * 100, 2)}%） |",
        f"| 加权平均耗时 | {avg} ms |",
        "",
        "## 每日明细",
        "",
        "| 日期 | 事件数 | 错误 | 错误率 | 平均耗时 | P95 | 会话数 | 最高频事件 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for r in rows:
        lines.append(
            f"| {r['date']} | {r['events']} | {r['errors']} | {r['error_rate']}% | "
            f"{r['avg_ms']} ms | {r['p95_ms']} ms | {r['sessions']} | {r['top_event']} |"
        )

    lines += ["", "## 事件类型分布", "", "| 事件 | 次数 | 占比 |", "| --- | --- | --- |"]
    for evt, count in events.most_common():
        lines.append(f"| {evt} | {count} | {round(count / total_events * 100, 1)}% |")

    lines += ["", "## 错误记录", ""]
    if errors:
        lines += ["| 时间 | 事件 | 类型 | 信息 |", "| --- | --- | --- | --- |"]
        for rec in errors[:40]:
            raw = str(rec.get("err", ""))
            kind = raw.split(":")[0].strip() or "unknown"
            lines.append(
                f"| {rec.get('ts', '')} | {rec.get('evt', '')} | {kind} | {raw[:80]} |"
            )
        if len(errors) > 40:
            lines.append(f"| … | | | 其余 {len(errors) - 40} 条见原始 jsonl |")
    else:
        lines.append("区间内无错误记录。")

    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stdout", action="store_true")
    args = parser.parse_args()

    rows, events, errors = collect()
    report = render(rows, events, errors)

    if args.stdout:
        print(report)
        return

    out = BASE / "docs" / "运行日志汇总.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report, encoding="utf-8")
    print(f"已生成 {out.relative_to(BASE)}（{len(rows)} 天）")


if __name__ == "__main__":
    main()
