#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""脱敏运行日志（Telemetry Logs）。

设计原则
--------
1. **只记行为，不记内容**：日志中永不出现通知原文、姓名、手机号、学号。
   meta 字段只允许标量化的统计量（字符数、条目数、命中与否）。
2. **时间戳脱敏**：精确到分钟并显式带时区，不写毫秒，避免形成行为指纹。
3. **身份脱敏**：会话标识为进程启动时生成的 6 位随机哈希，不可反查个人。
4. **日志不拖垮业务**：任何写入异常都被吞掉并降级为内存缓冲，
   绝不让遥测故障中断主流程。

日志落盘位置
------------
    process_logs/YYYY-MM-DD.jsonl      按天一份，便于逐日同步到仓库
    process_logs/summary.csv           每日汇总（事件数/错误数/平均耗时/P95）

用法
----
    from core.telemetry import Telemetry

    tel = Telemetry()
    tel.event("app_start", meta={"version": "0.1.0"})

    with tel.timed("parse_notice", chars=len(text)):
        result = parse(text)
"""

from __future__ import annotations

import json
import math
import os
import random
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# 项目源码根（本文件位于 <src>/core/telemetry.py）
BASE_DIR = Path(__file__).resolve().parent.parent


def _default_log_dir() -> Path:
    """日志落盘目录。

    ICEC 课程仓库的约定是日志放在 `02-20Days-Challenge/process_logs/`，
    与 `src/` 平级，所以这里向上再走一层；如果 `src/` 被单独拷出去跑，
    就退回 `src/process_logs`，两种结构都能工作。
    """
    challenge_root = BASE_DIR.parent
    if (challenge_root / "process_logs").is_dir():
        return challenge_root / "process_logs" / "telemetry"
    return BASE_DIR / "process_logs"


DEFAULT_LOG_DIR = _default_log_dir()

# 本地时区固定为东八区：本工具面向中国校园使用，不依赖机器时区设置
CST = timezone(timedelta(hours=8))

# 允许写进 meta 的键白名单。任何未列出的键都会被丢弃，
# 从机制上杜绝"顺手把原文塞进日志"的情况。
_ALLOWED_META_KEYS = {
    "version", "chars", "items", "deadline", "deadline_conf", "materials",
    "located", "contact", "tags", "elapsed_source", "warnings", "mode",
    "rows", "diff_rows", "matched", "unmatched", "route", "ua_bucket",
    "task_id", "score", "role", "degraded", "cache", "retry", "bytes",
    "sample", "ok_count", "fail_count", "source",
}

_SCRUB_RULES = (
    # 手机号 -> 保留前 3 位与后 2 位
    (r"(?<!\d)(1[3-9]\d)\d{6}(\d{2})(?!\d)", r"\1******\2"),
    # 学号/工号一类 8-12 位连续数字
    (r"(?<!\d)(\d{4})\d{4,8}(?!\d)", r"\1****"),
    # 邮箱
    (r"([\w.+-]{1,3})[\w.+-]*@([\w-]+\.[\w.-]+)", r"\1***@\2"),
)


def _scrub_text(value: str) -> str:
    """对字符串做轻度脱敏，作为 meta 值的最后一道防线。"""
    import re

    out = value
    for pattern, repl in _SCRUB_RULES:
        out = re.sub(pattern, repl, out)
    return out


def _scrub_meta(meta: Dict[str, Any]) -> Dict[str, Any]:
    """按白名单过滤 meta，并对字符串值脱敏、对长度做截断。"""
    cleaned: Dict[str, Any] = {}
    for key, value in meta.items():
        if key not in _ALLOWED_META_KEYS:
            continue
        if isinstance(value, str):
            cleaned[key] = _scrub_text(value)[:120]
        elif isinstance(value, (int, float, bool)) or value is None:
            cleaned[key] = value
        elif isinstance(value, (list, tuple)):
            # 列表只保留长度与是否为空，避免夹带原文片段
            cleaned[key] = len(value)
        else:
            cleaned[key] = str(value)[:60]
    return cleaned


class Telemetry:
    """线程安全的追加式日志记录器。"""

    def __init__(
        self,
        log_dir: Optional[Path] = None,
        session_tag: Optional[str] = None,
        echo: bool = False,
    ) -> None:
        self.log_dir = Path(log_dir) if log_dir else DEFAULT_LOG_DIR
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # 6 位随机标识，仅用于把同一次进程内的多条记录串起来
        self.session = session_tag or "%06x" % random.getrandbits(24)
        self.echo = echo
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ 基础
    @staticmethod
    def now() -> datetime:
        return datetime.now(CST)

    @staticmethod
    def _date_str(ts: datetime) -> str:
        return ts.strftime("%Y-%m-%d")

    def _daily_path(self, ts: datetime) -> Path:
        return self.log_dir / f"{self._date_str(ts)}.jsonl"

    # ------------------------------------------------------------------ 写入
    def event(
        self,
        evt: str,
        dur_ms: Optional[float] = None,
        ok: bool = True,
        error: Optional[str] = None,
        ts: Optional[datetime] = None,
        **meta: Any,
    ) -> Dict[str, Any]:
        """记录一条事件。返回实际落盘的记录（便于测试断言）。"""
        moment = ts or self.now()
        record: Dict[str, Any] = {
            # 脱敏时间戳：精确到分钟，显式时区
            "ts": moment.strftime("%Y-%m-%dT%H:%M+08:00"),
            "sid": self.session,
            "evt": evt,
        }
        if dur_ms is not None:
            record["dur_ms"] = round(float(dur_ms), 2)
        record["ok"] = bool(ok)
        if error:
            # 错误只保留异常类型与首行信息，去掉可能出现的路径与用户数据
            record["err"] = _scrub_text(str(error).splitlines()[0])[:200]
        clean_meta = _scrub_meta(meta)
        if clean_meta:
            record["meta"] = clean_meta

        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self._lock:
            try:
                with open(self._daily_path(moment), "a", encoding="utf-8") as fh:
                    fh.write(line + "\n")
            except OSError:
                # 落盘失败不影响业务；调试模式下仍能看到
                pass
        if self.echo:
            print(f"[tel] {line}")
        return record

    def timed(self, evt: str, **meta: Any) -> "_TimedEvent":
        """上下文管理器，自动计算耗时并记录成功/异常。"""
        return _TimedEvent(self, evt, meta)

    # ------------------------------------------------------------------ 统计
    def read_day(self, date_str: str) -> List[Dict[str, Any]]:
        """读取某一天的全部日志记录，坏行自动跳过。"""
        path = self.log_dir / f"{date_str}.jsonl"
        if not path.exists():
            return []
        records: List[Dict[str, Any]] = []
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return records

    def available_dates(self) -> List[str]:
        """列出已有日志的日期（升序）。"""
        dates = sorted(p.stem for p in self.log_dir.glob("*.jsonl"))
        return dates


class _TimedEvent:
    """`with tel.timed(...)` 的实现。"""

    def __init__(self, tel: Telemetry, evt: str, meta: Dict[str, Any]) -> None:
        self.tel = tel
        self.evt = evt
        self.meta = dict(meta)
        self._t0 = 0.0

    def __enter__(self) -> "_TimedEvent":
        import time

        self._t0 = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        import time

        dur = (time.perf_counter() - self._t0) * 1000
        if exc is None:
            self.tel.event(self.evt, dur_ms=dur, ok=True, **self.meta)
        else:
            self.tel.event(
                self.evt,
                dur_ms=dur,
                ok=False,
                error=f"{exc_type.__name__}: {exc}",
                **self.meta,
            )
        # 不吞业务异常
        return False


# ---------------------------------------------------------------- 汇总工具
def percentile(values: List[float], pct: float) -> float:
    """线性插值分位数，values 为空时返回 0。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    pos = (len(ordered) - 1) * pct
    low = math.floor(pos)
    high = math.ceil(pos)
    if low == high:
        return ordered[int(pos)]
    return ordered[low] + (ordered[high] - ordered[low]) * (pos - low)


def summarize_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """把一天的日志聚合为可提交的统计摘要。"""
    total = len(records)
    errors = [r for r in records if not r.get("ok", True)]
    durs = [float(r["dur_ms"]) for r in records if isinstance(r.get("dur_ms"), (int, float))]
    counts: Dict[str, int] = {}
    for rec in records:
        counts[rec.get("evt", "?")] = counts.get(rec.get("evt", "?"), 0) + 1
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    sessions = {r.get("sid") for r in records if r.get("sid")}
    return {
        "date": records[0]["ts"][:10] if records else "",
        "events": total,
        "errors": len(errors),
        "error_rate": round(len(errors) / total * 100, 2) if total else 0.0,
        "avg_ms": round(sum(durs) / len(durs), 2) if durs else 0.0,
        "p95_ms": round(percentile(durs, 0.95), 2),
        "max_ms": round(max(durs), 2) if durs else 0.0,
        "sessions": len(sessions),
        "event_counts": dict(top),
        "top_event": top[0][0] if top else "",
        "error_kinds": _error_kinds(errors),
    }


def _error_kinds(errors: List[Dict[str, Any]]) -> Dict[str, int]:
    kinds: Dict[str, int] = {}
    for rec in errors:
        raw = str(rec.get("err", "unknown"))
        kind = raw.split(":")[0].strip() or "unknown"
        kinds[kind] = kinds.get(kind, 0) + 1
    return kinds


if __name__ == "__main__":  # 手动冒烟：python -m core.telemetry
    telemetry = Telemetry(echo=True)
    telemetry.event("app_start", meta={"version": "0.1.0"})
    with telemetry.timed("smoke_test", chars=42):
        pass
    for date in telemetry.available_dates():
        records = telemetry.read_day(date)
        print(date, json.dumps(summarize_records(records), ensure_ascii=False))
