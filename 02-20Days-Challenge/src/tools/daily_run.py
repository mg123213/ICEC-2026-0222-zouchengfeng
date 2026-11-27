#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每日自动运行任务。

由 Windows 计划任务 / 自动化调度器在每天固定时间调起，做四件事：

1. 扫描 data/inbox/ 里手动转存的通知文本，逐条解析并写入待办；
2. 跑一次自检（解析器黄金用例 + 器材核对冒烟），失败会记进日志；
3. 统计当天运行日志，生成 process_logs/reports/YYYY-MM-DD.md；
4. 把汇总追加到 process_logs/summary.csv。

设计成可无人值守：任何一步出错都记录后继续，退出码仅用于外部监控。

    python tools/daily_run.py            # 正常跑一次
    python tools/daily_run.py --rollup   # 只做汇总，不扫 inbox
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent          # .../02-20Days-Challenge/src
# 日志与迭代在 src 的上一层，源码与数据在 src 内，两个根分开算
BASE = SRC.parent if (SRC.parent / "process_logs").is_dir() else SRC

sys.path.insert(0, str(SRC))

from core import inventory, notice_parser  # noqa: E402
from core.telemetry import CST, Telemetry, summarize_records  # noqa: E402

INBOX = SRC / "data" / "inbox"
TASK_FILE = SRC / "data" / "tasks.json"
NOTE_DIR = SRC / "data" / "notes"
REPORT_DIR = BASE / "process_logs" / "reports"
SUMMARY_CSV = BASE / "process_logs" / "telemetry" / "summary.csv"

SUMMARY_FIELDS = [
    "date", "events", "calls", "errors", "error_rate",
    "avg_ms", "p95_ms", "max_ms", "sessions", "top_event",
]

_tel = Telemetry()


# --------------------------------------------------------------------- 待办
def load_tasks() -> list:
    if not TASK_FILE.exists():
        return []
    try:
        return json.loads(TASK_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []


def save_tasks(tasks: list) -> None:
    TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = TASK_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(TASK_FILE)


def next_id(tasks: list) -> str:
    stamp = datetime.now(CST).strftime("%Y%m%d")
    used = {t.get("id") for t in tasks}
    for i in range(1, 1000):
        candidate = f"t{stamp}-{i:03d}"
        if candidate not in used:
            return candidate
    return f"t{stamp}-999"


# --------------------------------------------------------------------- 主流程
def scan_inbox() -> list:
    """解析 inbox 里的新文本。返回本次新解析出的任务标题列表。"""
    INBOX.mkdir(parents=True, exist_ok=True)
    NOTE_DIR.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks()
    known_files = {t.get("source_file") for t in tasks}
    added = []

    for path in sorted(INBOX.glob("*.txt")):
        if str(path.relative_to(BASE)) in known_files:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if not text.strip():
            continue
        started = time.perf_counter()
        try:
            result = notice_parser.parse_notice(text)
            ok = bool(result.get("ok"))
            err = None if ok else str(result.get("error"))
        except Exception as exc:  # noqa: BLE001 - 单条失败不能中断整批
            _tel.event(
                "auto_parse", dur_ms=(time.perf_counter() - started) * 1000,
                ok=False, error=f"{type(exc).__name__}: {exc}",
                chars=len(text), source="auto", mode="inbox",
            )
            continue

        _tel.event(
            "auto_parse",
            dur_ms=(time.perf_counter() - started) * 1000,
            ok=ok, error=err,
            chars=len(text),
            items=len(result.get("materials") or []),
            deadline=bool(result.get("deadline")),
            deadline_conf=(result.get("deadline") or {}).get("confidence", 0),
            materials=len(result.get("materials") or []),
            located=bool(result.get("location")),
            source="auto",
            mode="inbox",
        )

        if not ok:
            continue

        task_id = next_id(tasks)
        note_path = NOTE_DIR / f"{task_id}.txt"
        note_path.write_text(text, encoding="utf-8")
        tasks.append({
            "id": task_id,
            "title": result["title"],
            "deadline": (result.get("deadline") or {}).get("iso", ""),
            "deadline_conf": (result.get("deadline") or {}).get("confidence", 0),
            "urgency": result.get("urgency", "none"),
            "location": result.get("location", ""),
            "materials": result.get("materials", []),
            "tags": result.get("tags", []),
            "done": False,
            "created_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M"),
            "note_file": str(note_path.relative_to(BASE)),
            "source_file": str(path.relative_to(BASE)),
        })
        added.append(result["title"])

    if added:
        save_tasks(tasks)
    return added


def self_check() -> dict:
    """轻量自检：解析器能否在样例上抽到截止时间，器材核对能否算出差异。"""
    started = time.perf_counter()
    checks = {}

    samples = sorted((SRC / "data" / "samples").glob("*.txt"))
    hit = 0
    probe = samples[:4]
    # 自检必须与真实日期解耦：样例里的截止时间是固定的 11-21~11-25，
    # 过了这些日期后解析器会正确判定「已过期」并返回 None，
    # 若仍用 datetime.now()，自检会从某天起恒失败（11-26 起出现过）。
    # 这里固定一个样例设计时的参考时刻，测的是「解析能力」而不是「日期是否还没过」。
    ref_now = datetime(2026, 11, 17, 9, 0)
    for path in probe:
        try:
            result = notice_parser.parse_notice(path.read_text(encoding="utf-8"), now=ref_now)
            hit += 1 if result.get("deadline") else 0
        except Exception:  # noqa: BLE001
            pass
    # 前 4 条样例都带明确截止时间，允许 1 条失手
    checks["parser"] = hit >= max(1, len(probe) - 1)

    try:
        demo = inventory.check_inventory(
            "编号,器材,借用人,数量,借出日期,应还日期\nS-01,卡尺,张三,2,2026-11-10,2026-11-15",
            "编号,器材,归还人,数量,归还日期\nS-01,卡尺,张三,1,2026-11-14",
            today=date(2026, 11, 17),
        )
        checks["inventory"] = demo.get("summary", {}).get("qty_outstanding") == 1
    except Exception:  # noqa: BLE001
        checks["inventory"] = False

    passed = all(checks.values())
    _tel.event(
        "self_check",
        dur_ms=(time.perf_counter() - started) * 1000,
        ok=passed,
        error=None if passed else "self_check_failed",
        sample=sum(checks.values()),
    )
    return {"passed": passed, "detail": checks}


def rollup(extra_notes: list | None = None) -> dict:
    """生成当天日报并追加汇总行。"""
    today = datetime.now(CST).strftime("%Y-%m-%d")
    records = _tel.read_day(today)
    summary = summarize_records(records)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    SUMMARY_CSV.parent.mkdir(parents=True, exist_ok=True)

    # 汇总 CSV：首行写表头，之后按日期去重更新
    rows = []
    if SUMMARY_CSV.exists():
        with open(SUMMARY_CSV, "r", encoding="utf-8-sig", newline="") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("date") != today]

    rows.append({
        "date": today,
        "events": summary["events"],
        "calls": summary["events"] - summary["event_counts"].get("app_start", 0),
        "errors": summary["errors"],
        "error_rate": summary["error_rate"],
        "avg_ms": summary["avg_ms"],
        "p95_ms": summary["p95_ms"],
        "max_ms": summary["max_ms"],
        "sessions": summary["sessions"],
        "top_event": summary["top_event"],
    })
    rows.sort(key=lambda r: r["date"])

    with open(SUMMARY_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SUMMARY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    report = _render_report(summary, extra_notes or [])
    (REPORT_DIR / f"{today}.md").write_text(report, encoding="utf-8")
    return summary


def _render_report(summary: dict, notes: list) -> str:
    lines = [
        f"# 运行日报 {summary['date']}",
        "",
        "| 指标 | 数值 |",
        "| --- | --- |",
        f"| 事件总数 | {summary['events']} |",
        f"| 错误数 | {summary['errors']}（{summary['error_rate']}%） |",
        f"| 平均耗时 | {summary['avg_ms']} ms |",
        f"| P95 耗时 | {summary['p95_ms']} ms |",
        f"| 最大耗时 | {summary['max_ms']} ms |",
        f"| 会话数 | {summary['sessions']} |",
        "",
        "## 事件分布",
        "",
        "| 事件 | 次数 |",
        "| --- | --- |",
    ]
    for evt, count in sorted(summary["event_counts"].items(), key=lambda kv: -kv[1]):
        lines.append(f"| {evt} | {count} |")

    if summary["error_kinds"]:
        lines += ["", "## 错误类型", "", "| 类型 | 次数 |", "| --- | --- |"]
        for kind, count in summary["error_kinds"].items():
            lines.append(f"| {kind} | {count} |")

    if notes:
        lines += ["", "## 本次新增待办", ""]
        lines += [f"- {n}" for n in notes]

    tasks = load_tasks()
    pending = [t for t in tasks if not t.get("done")]
    if pending:
        lines += ["", f"## 未完成待办（{len(pending)}）", ""]
        for task in sorted(pending, key=lambda t: t.get("deadline") or "9999")[:8]:
            due = task.get("deadline") or "无截止"
            lines.append(f"- {task['title']}（{due}）")

    lines.append("")
    lines.append(f"_由 tools/daily_run.py 于 {datetime.now(CST).strftime('%Y-%m-%d %H:%M')} 自动生成_")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rollup", action="store_true", help="只做汇总，不扫 inbox")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    t0 = time.perf_counter()
    _tel.event("daily_run_start", ok=True, mode="rollup" if args.rollup else "full", source="auto")

    added: list = []
    check = {"passed": True, "detail": {}}
    if not args.rollup:
        added = scan_inbox()
        check = self_check()

    # 先写收尾日志再汇总：v0.1 把顺序反了，导致日报里永远少一条 daily_run_end
    _tel.event(
        "daily_run_end",
        dur_ms=(time.perf_counter() - t0) * 1000,
        ok=check["passed"],
        mode="rollup" if args.rollup else "full",
        items=len(added),
        source="auto",
    )
    summary = rollup(added)

    if not args.quiet:
        print(f"[{datetime.now(CST):%Y-%m-%d %H:%M}] 新增待办 {len(added)} 条，"
              f"自检 {'通过' if check['passed'] else '失败'}，"
              f"今日事件 {summary['events']}，错误 {summary['errors']}")
        print(f"日报：process_logs/reports/{summary['date']}.md")

    return 0 if check["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
