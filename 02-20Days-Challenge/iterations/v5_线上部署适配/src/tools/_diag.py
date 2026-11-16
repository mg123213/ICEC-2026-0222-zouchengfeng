#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开发期诊断脚本：把 samples 里的通知批量过一遍解析器，打印关键字段。

用法：python tools/_diag.py
不参与正式运行日志统计（自身也会写一条 dev_diagnose 事件）。
"""

import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BASE))

from core.notice_parser import parse_notice  # noqa: E402
from core.telemetry import Telemetry  # noqa: E402


def main() -> None:
    tel = Telemetry()
    samples = sorted((BASE / "data" / "samples").glob("*.txt"))
    for path in samples:
        text = path.read_text(encoding="utf-8")
        with tel.timed("dev_diagnose", chars=len(text), source=path.stem):
            result = parse_notice(text)
        deadline = result.get("deadline") or {}
        print("=" * 70)
        print(f"[{path.stem}]")
        print(f"  标题    : {result.get('title')}")
        print(f"  截止    : {deadline.get('iso', '未识别')}  conf={deadline.get('confidence')} kind={deadline.get('kind')} raw={deadline.get('raw')!r}")
        print(f"  地点    : {result.get('location')}")
        mats = [
            f"{m['name']}x{m['qty']}" if m.get("qty") else str(m["name"])
            for m in result.get("materials", [])
        ]
        print(f"  材料    : {mats}")
        print(f"  联系人  : {result.get('contacts')}")
        print(f"  标签    : {result.get('tags')}")
        print(f"  quality : {result.get('quality')}")
        print(f"  warn    : {result.get('warnings')}")
        cands = result.get("candidates", [])
        if cands:
            print("  候选    : " + " | ".join(f"{c['iso']}({c['kind']},{c['confidence']})" for c in cands))


if __name__ == "__main__":
    main()
