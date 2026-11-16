#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""核心逻辑单元测试。

    python -m unittest discover -s tests -v
    python tests/test_core.py
"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.inventory import check_inventory, parse_table  # noqa: E402
from core.notice_parser import parse_notice  # noqa: E402
from core.telemetry import Telemetry, _scrub_meta, summarize_records  # noqa: E402
from core.timeparse import cn_to_int, extract_deadline, humanize, normalize  # noqa: E402

NOW = datetime(2026, 11, 17, 0, 40)          # 周二凌晨，作为统一时间基准


class TestChineseNumber(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(cn_to_int("三"), 3)
        self.assertEqual(cn_to_int("十"), 10)
        self.assertEqual(cn_to_int("十一"), 11)
        self.assertEqual(cn_to_int("二十"), 20)
        self.assertEqual(cn_to_int("三十一"), 31)

    def test_normalize_keeps_other_words(self):
        # 只转换紧邻时间单位的中文数字，普通词语不能被改
        self.assertEqual(normalize("十一月二十日"), "11月20日")
        self.assertIn("第一", normalize("第一名"))
        self.assertIn("万一", normalize("万一下雨"))


class TestDeadlineExtraction(unittest.TestCase):
    def test_month_day_with_clock(self):
        got = extract_deadline("请于11月21日17:00前将材料交至行政楼302室。", now=NOW)
        self.assertIsNotNone(got)
        self.assertEqual(got.dt.strftime("%Y-%m-%d %H:%M"), "2026-11-21 17:00")
        self.assertTrue(got.has_clock)

    def test_full_date_with_weekday_annotation(self):
        got = extract_deadline("请于2026年11月25日（周三）18:00前完成报名。", now=NOW)
        self.assertEqual(got.dt.strftime("%Y-%m-%d %H:%M"), "2026-11-25 18:00")

    def test_weekday_afternoon(self):
        got = extract_deadline("截止到周五中午12点前在表格里确认尺码。", now=NOW)
        self.assertEqual(got.dt.strftime("%Y-%m-%d %H:%M"), "2026-11-20 12:00")

    def test_pm_conversion(self):
        got = extract_deadline("本周五下午4点半在实训楼B305集合。", now=NOW)
        self.assertEqual(got.dt.strftime("%H:%M"), "16:30")

    def test_range_takes_end(self):
        """「A 至 B」是一个区间，截止应取结束时间，不能取开始时间。"""
        got = extract_deadline("选课时间为11月18日9:00至11月22日24:00。", now=NOW)
        self.assertEqual(got.dt.strftime("%Y-%m-%d %H:%M"), "2026-11-22 23:59")

    def test_start_phrase_is_not_deadline(self):
        """「自 X 日起」是起始语，不是截止，不应被当成截止时间。"""
        got = extract_deadline("图书馆自11月20日起将闭馆时间由21:00延长至22:30。", now=NOW)
        self.assertIsNone(got)

    def test_empty_returns_none(self):
        self.assertIsNone(extract_deadline("", now=NOW))
        self.assertIsNone(extract_deadline("请同学们注意安全。", now=NOW))


class TestNoticeParser(unittest.TestCase):
    def test_materials_split_and_qty(self):
        text = (
            "请于11月21日17:00前将以下材料交至行政楼302室：\n"
            "1.《学生困难补助申请表》一式两份\n"
            "2.身份证复印件1份\n"
        )
        result = parse_notice(text, now=NOW)
        names = [m["name"] for m in result["materials"]]
        self.assertTrue(any("申请表" in n for n in names))
        self.assertTrue(any("身份证复印件" in n for n in names))
        qty = {m["name"]: m["qty"] for m in result["materials"]}
        self.assertEqual(qty.get("身份证复印件"), 1)

    def test_location_with_room_number(self):
        result = parse_notice("请于11月21日17:00前交至行政楼302室学生服务大厅。", now=NOW)
        self.assertIn("行政楼", result["location"])
        self.assertNotIn("前将以下", result["location"])

    def test_empty_input(self):
        result = parse_notice("", now=NOW)
        self.assertFalse(result["ok"])


class TestInventory(unittest.TestCase):
    LENT = (
        "编号,器材,借用人,数量,借出日期,应还日期\n"
        "MJ-01,游标卡尺,张三,2,2026-11-10,2026-11-15\n"
        "MJ-02,千分尺,李四,1,2026-11-12,2026-11-20\n"
    )
    RETURNED = (
        "编号,器材,归还人,数量,归还日期\n"
        "MJ-01,游标卡尺,张三,1,2026-11-14\n"
        "MJ-09,游标卡尺,王五,1,2026-11-16\n"
    )

    def test_partial_return_is_not_settled(self):
        result = check_inventory(self.LENT, self.RETURNED, today=datetime(2026, 11, 17).date())
        row = next(r for r in result["rows"] if r["code"] == "MJ-01")
        self.assertEqual(row["returned"], 1)
        self.assertEqual(row["outstanding"], 1)
        self.assertEqual(row["status"], "部分归还")

    def test_overdue_days(self):
        result = check_inventory(self.LENT, self.RETURNED, today=datetime(2026, 11, 17).date())
        row = next(r for r in result["rows"] if r["code"] == "MJ-01")
        self.assertEqual(row["overdue_days"], 2)

    def test_returned_without_lent_is_anomaly(self):
        result = check_inventory(self.LENT, self.RETURNED, today=datetime(2026, 11, 17).date())
        self.assertTrue(any("MJ-09" in a for a in result["anomalies"]))

    def test_missing_person_column(self):
        records, warnings = parse_table("编号,器材\nA,卡尺", "lent")
        self.assertEqual(records, [])
        self.assertTrue(warnings)


class TestTelemetry(unittest.TestCase):
    def test_scrub_meta_drops_unknown_keys(self):
        """未在白名单里的键必须被丢弃，防止顺手把原文写进日志。"""
        cleaned = _scrub_meta({"chars": 10, "raw_text": "张三 13800138000 的申请材料"})
        self.assertIn("chars", cleaned)
        self.assertNotIn("raw_text", cleaned)

    def test_scrub_phone(self):
        cleaned = _scrub_meta({"role": "13800138000"})
        self.assertNotIn("13800138000", cleaned["role"])

    def test_event_written_and_summarized(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            tel = Telemetry(log_dir=Path(tmp), session_tag="test01")
            tel.event("unit_test", dur_ms=1.5, ok=True, chars=10)
            tel.event("unit_test", dur_ms=2.5, ok=False, error="ValueError: boom")
            records = tel.read_day(datetime.now().strftime("%Y-%m-%d"))
            self.assertEqual(len(records), 2)
            summary = summarize_records(records)
            self.assertEqual(summary["events"], 2)
            self.assertEqual(summary["errors"], 1)
            self.assertAlmostEqual(summary["avg_ms"], 2.0, places=2)
            # 时间戳精确到分钟且带时区
            self.assertRegex(records[0]["ts"], r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}\+08:00$")


class TestHumanize(unittest.TestCase):
    def test_remaining(self):
        self.assertIn("还剩", humanize(datetime(2026, 11, 19, 12, 0), NOW))
        self.assertIn("逾期", humanize(datetime(2026, 11, 15, 12, 0), NOW))


if __name__ == "__main__":
    unittest.main(verbosity=2)
