#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户反馈汇总导出。

把手填/网页提交的反馈（feedback/responses.jsonl）整理成一份 Markdown，
包含评分分布、身份分布、功能使用率、原始反馈列表。

    python tools/export_feedback.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
SOURCE = BASE / "feedback" / "responses.jsonl"
TARGET = BASE / "docs" / "用户反馈汇总.md"


def load() -> list:
    if not SOURCE.exists():
        return []
    rows = []
    with open(SOURCE, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return rows


def render(rows: list) -> str:
    if not rows:
        return (
            "# 用户反馈汇总\n\n"
            "暂无反馈数据。\n\n"
            "收集方式见 `docs/用户反馈收集说明.md`：打开程序 → 「使用反馈」标签页 → 填完提交，\n"
            "数据写入 `feedback/responses.jsonl`，再运行本脚本生成汇总。\n"
        )

    scores = [r.get("score", 0) for r in rows if r.get("score")]
    avg = round(sum(scores) / len(scores), 2) if scores else 0
    roles = Counter(r.get("role", "未填") for r in rows)
    useful = Counter()
    for row in rows:
        for item in row.get("useful") or []:
            useful[item] += 1

    lines = [
        "# 用户反馈汇总",
        "",
        f"> 样本数：{len(rows)} 人 ｜ 平均分：{avg} / 5 ｜ 生成时间：{datetime.now():%Y-%m-%d %H:%M}",
        "",
        "## 评分分布",
        "",
        "| 分数 | 人数 |",
        "| --- | --- |",
    ]
    score_counter = Counter(scores)
    for score in range(5, 0, -1):
        lines.append(f"| {score} 分 | {score_counter.get(score, 0)} |")

    lines += ["", "## 身份分布", "", "| 身份 | 人数 |", "| --- | --- |"]
    for role, count in roles.most_common():
        lines.append(f"| {role} | {count} |")

    if useful:
        lines += ["", "## 功能使用率", "", "| 功能 | 勾选人数 | 占比 |", "| --- | --- | --- |"]
        for item, count in useful.most_common():
            lines.append(f"| {item} | {count} | {round(count / len(rows) * 100)}% |")

    lines += ["", "## 逐条反馈", "", "| # | 时间 | 身份 | 评分 | 反馈内容 |", "| --- | --- | --- | --- | --- |"]
    for index, row in enumerate(rows, 1):
        comment = str(row.get("comment") or "（无文字）").replace("|", "\\|").replace("\n", " ")
        lines.append(
            f"| {index} | {row.get('ts', '')} | {row.get('role', '')} | "
            f"{row.get('score', '')} | {comment} |"
        )

    lines.append("")
    return "\n".join(lines) + "\n"


def main() -> None:
    rows = load()
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    TARGET.write_text(render(rows), encoding="utf-8")
    print(f"已汇总 {len(rows)} 条反馈 → {TARGET.relative_to(BASE)}")


if __name__ == "__main__":
    main()
