#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""实训器材借还核对。

真实场景：实训室是纸质/Excel 两张表 —— 借出登记表和归还登记表。
班委在收器材时靠肉眼对两列名字，容易出现三种漏账：

1. 借了两件、只还了一件（数量差），人却算"已还"；
2. 同一件器材被前后两人借走，归还记到了前一人头上；
3. 已经超期但没人发现，直到老师查台账。

本模块把两张表读进来，按「编号 + 借用人」对齐，输出差异清单和可直接
发到班级群的催还话术。表格文件不入库，只在本机内存里算。
"""

from __future__ import annotations

import csv
import io
import re
from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

# 表头别名 -> 标准字段名
_HEADER_ALIASES: Dict[str, Tuple[str, ...]] = {
    "code": ("编号", "器材编号", "资产编号", "序号", "id", "no", "code", "编码"),
    "item": ("器材名称", "器材", "名称", "设备", "品名", "物品", "item", "name"),
    "person": ("借用人", "借出人", "归还人", "还件人", "借用人姓名", "姓名", "学生", "borrower", "person", "谁"),
    "qty": ("数量", "件数", "数目", "qty", "count"),
    "lent_at": ("借出日期", "借出时间", "借用日期", "借出", "date", "lent"),
    "due_at": ("应还日期", "应归还日期", "归还期限", "预计归还", "应还", "due", "deadline"),
    "returned_at": ("归还日期", "归还时间", "归还", "实际归还", "returned"),
}

_DATE_FORMATS = ("%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d", "%Y年%m月%d日", "%m-%d", "%m/%d", "%m月%d日")


# --------------------------------------------------------------------- 解析
def _split_rows(text: str) -> List[List[str]]:
    """按逗号/制表符切表，兼容 Excel 直接复制粘贴的制表符格式。"""
    text = text.replace("\ufeff", "").strip()
    if not text:
        return []
    first_line = text.splitlines()[0]
    delimiter = "\t" if first_line.count("\t") >= first_line.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    return [[cell.strip() for cell in row] for row in reader if any(cell.strip() for cell in row)]


def _map_headers(header_row: List[str]) -> Dict[str, int]:
    """把表头映射到标准字段；识别不到就返回尽量少的映射。"""
    mapping: Dict[str, int] = {}
    normalized = [re.sub(r"[\s　]", "", h).lower() for h in header_row]
    for field, aliases in _HEADER_ALIASES.items():
        for index, cell in enumerate(normalized):
            if not cell:
                continue
            if cell in aliases or any(cell == a.lower() for a in aliases):
                mapping.setdefault(field, index)
                break
    return mapping


def _looks_like_header(row: List[str]) -> bool:
    joined = "".join(row)
    if not joined:
        return False
    hits = sum(1 for aliases in _HEADER_ALIASES.values()
               for alias in aliases if alias in joined)
    return hits >= 2


def _parse_date(text: str, today: Optional[date] = None) -> Optional[date]:
    """解析常见日期写法；只有月日时按今年补全。"""
    text = (text or "").strip()
    if not text:
        return None
    today = today or date.today()
    text = text.split(" ")[0].split("T")[0]
    for fmt in _DATE_FORMATS:
        try:
            parsed = datetime.strptime(text, fmt)
        except ValueError:
            continue
        if "%Y" not in fmt:
            return parsed.date().replace(year=today.year)
        return parsed.date()
    # 纯数字 Excel 序列号（如 45678）
    if text.isdigit() and 20000 < int(text) < 60000:
        try:
            return date.fromordinal(date(1899, 12, 30).toordinal() + int(text))
        except (ValueError, OverflowError):
            return None
    return None


def _to_int(text: str, default: int = 1) -> int:
    match = re.search(r"\d+", str(text))
    return int(match.group()) if match else default


def parse_table(text: str, kind: str = "lent") -> Tuple[List[Dict[str, object]], List[str]]:
    """解析一张登记表，返回 (记录列表, 警告列表)。"""
    rows = _split_rows(text)
    warnings: List[str] = []
    if not rows:
        return [], ["表格内容为空"]

    if _looks_like_header(rows[0]):
        mapping = _map_headers(rows[0])
        body = rows[1:]
    else:
        # 无表头：按「编号, 器材, 借用人, 数量, 日期...」的常见列序猜测
        mapping = {"code": 0, "item": 1, "person": 2, "qty": 3, "lent_at": 4, "due_at": 5}
        body = rows
        warnings.append("未识别到表头，已按「编号/器材/借用人/数量/日期」列序解析，请核对")

    required = ("person",)
    if not all(f in mapping for f in required):
        return [], ["表里找不到「借用人」列，无法核对"]

    records: List[Dict[str, object]] = []
    for raw_row in body:
        def cell(field: str, fallback: str = "") -> str:
            index = mapping.get(field)
            if index is None or index >= len(raw_row):
                return fallback
            return raw_row[index]

        person = cell("person").strip()
        if not person or person in ("合计", "小计", "总计"):
            continue
        records.append({
            "code": cell("code").strip() or "-",
            "item": cell("item").strip() or "未命名器材",
            "person": person,
            "qty": max(_to_int(cell("qty"), 1), 1),
            "lent_at": _parse_date(cell("lent_at")),
            "due_at": _parse_date(cell("due_at")),
            "returned_at": _parse_date(cell("returned_at")) if kind == "returned" else None,
            "kind": kind,
        })

    if not records:
        warnings.append("表中没有可用的数据行")
    return records, warnings


# --------------------------------------------------------------------- 核对
def check_inventory(
    lent_text: str,
    returned_text: str,
    today: Optional[date] = None,
) -> Dict[str, object]:
    """核对借出与归还，输出差异清单、催还清单和统计。"""
    today = today or date.today()
    lent, warn_lent = parse_table(lent_text, "lent")
    returned, warn_returned = parse_table(returned_text, "returned")

    if not lent:
        return {
            "ok": False,
            "error": "no_lent_records",
            "warnings": warn_lent + warn_returned,
            "message": "借出表没有读到有效记录，请检查表头是否包含「借用人」",
        }

    # 归还额按 (编号, 借用人) 累计
    returned_qty: Dict[Tuple[str, str], int] = {}
    returned_dates: Dict[Tuple[str, str], date] = {}
    for rec in returned:
        key = (str(rec["code"]), str(rec["person"]))
        returned_qty[key] = returned_qty.get(key, 0) + int(rec["qty"])  # type: ignore[arg-type]
        when = rec.get("returned_at") or rec.get("lent_at")
        if isinstance(when, date):
            returned_dates[key] = when

    # 借出额同理（同一人可能分两次借同一编号）
    lent_group: Dict[Tuple[str, str], Dict[str, object]] = {}
    for rec in lent:
        key = (str(rec["code"]), str(rec["person"]))
        if key in lent_group:
            lent_group[key]["qty"] = int(lent_group[key]["qty"]) + int(rec["qty"])  # type: ignore[arg-type]
            # 取最早的应还日期，宁可早提醒
            if rec["due_at"] and (not lent_group[key]["due_at"] or rec["due_at"] < lent_group[key]["due_at"]):  # type: ignore[operator]
                lent_group[key]["due_at"] = rec["due_at"]
        else:
            lent_group[key] = dict(rec)

    rows: List[Dict[str, object]] = []
    anomalies: List[str] = []
    by_person: Dict[str, List[Dict[str, object]]] = {}

    for key, rec in lent_group.items():
        borrowed = int(rec["qty"])  # type: ignore[arg-type]
        done = returned_qty.get(key, 0)
        outstanding = max(borrowed - done, 0)
        due = rec.get("due_at")
        overdue_days = 0
        if outstanding and isinstance(due, date) and due < today:
            overdue_days = (today - due).days

        if done > borrowed:
            anomalies.append(
                f"{rec['person']} 的「{rec['item']}」归还 {done} 件，多于借出 {borrowed} 件"
            )

        status = "已还清"
        if borrowed == 0:
            status = "无借出"
        elif outstanding == 0:
            status = "已还清"
        elif done > 0:
            status = "部分归还"
        elif overdue_days > 0:
            status = "超期未还"
        else:
            status = "未归还"

        row = {
            "code": rec["code"],
            "item": rec["item"],
            "person": rec["person"],
            "borrowed": borrowed,
            "returned": done,
            "outstanding": outstanding,
            "due_at": due.strftime("%Y-%m-%d") if isinstance(due, date) else "",
            "overdue_days": overdue_days,
            "status": status,
        }
        rows.append(row)
        if outstanding > 0:
            by_person.setdefault(str(rec["person"]), []).append(row)

    # 归还表里出现、借出表里没有的记录
    for key in returned_qty:
        if key not in lent_group:
            anomalies.append(f"归还表里的 {key[1]}「{key[0]}」在借出表中找不到对应记录")

    rows.sort(key=lambda r: (-int(r["outstanding"]), -int(r["overdue_days"]), str(r["person"])))

    total_lent = sum(int(r["borrowed"]) for r in rows)
    total_returned = sum(int(r["returned"]) for r in rows)
    total_outstanding = sum(int(r["outstanding"]) for r in rows)
    overdue_people = sorted({str(r["person"]) for r in rows if int(r["overdue_days"]) > 0})
    open_people = sorted(by_person.keys())

    return {
        "ok": True,
        "summary": {
            "lent_records": len(lent),
            "returned_records": len(returned),
            "pairs": len(rows),
            "qty_lent": total_lent,
            "qty_returned": total_returned,
            "qty_outstanding": total_outstanding,
            "people_open": len(open_people),
            "people_overdue": len(overdue_people),
            "anomalies": len(anomalies),
        },
        "rows": rows,
        "by_person": {name: items for name, items in sorted(by_person.items())},
        "anomalies": anomalies,
        "overdue_people": overdue_people,
        "warnings": warn_lent + warn_returned,
        "message": build_reminder(by_person, today),
    }


def build_reminder(by_person: Dict[str, List[Dict[str, object]]], today: Optional[date] = None) -> str:
    """生成可直接粘贴到班级群的催还话术。"""
    if not by_person:
        return "核对完毕：所有器材均已归还，无未结清记录。"

    today = today or date.today()
    lines = [f"【器材归还提醒】{today.strftime('%m月%d日')}", ""]
    for name, items in sorted(by_person.items()):
        parts = []
        for item in items:
            detail = f"{item['item']}×{item['outstanding']}"
            if int(item["overdue_days"]) > 0:
                detail += f"（超期 {item['overdue_days']} 天）"
            parts.append(detail)
        lines.append(f"· {name}：{'、'.join(parts)}")
    lines.append("")
    lines.append("请以上同学今天内到实训室办理归还，归还时当面清点数量。")
    return "\n".join(lines)


def rows_to_csv(rows: List[Dict[str, object]]) -> str:
    """把核对结果导出为 CSV（带 BOM，Excel 直接打开不乱码）。"""
    if not rows:
        return "\ufeff无数据\n"
    buffer = io.StringIO()
    fields = ["code", "item", "person", "borrowed", "returned", "outstanding",
              "due_at", "overdue_days", "status"]
    titles = ["编号", "器材", "借用人", "借出", "已还", "未还", "应还日期", "超期天数", "状态"]
    writer = csv.writer(buffer)
    writer.writerow(titles)
    for row in rows:
        writer.writerow([row.get(f, "") for f in fields])
    return "\ufeff" + buffer.getvalue()
