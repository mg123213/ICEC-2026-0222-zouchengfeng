#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""中文通知时间表达解析。

技工院校的通知文本时间写法很杂，实测高频形态：

    "请于11月20日17:00前将材料交至行政楼302"
    "报名截止时间为下周五下午5点"
    "材料须在三个工作日内提交"
    "11月18日—11月20日 每天 9:00-16:00"
    "即日起至十一月二十五日"

本模块只做一件事：从一段中文里找出「最可能是截止时刻」的那一个时间点，
并给出置信度与原文位置，便于上层做人工复核（不做静默猜测）。

设计取舍
--------
* 不引入第三方 NLP 依赖 —— 工具要在同学的个人电脑上零安装运行。
* 规则 + 打分，而不是单一正则 —— 通知里同时出现发布日期、活动日期、
  截止日期是常态，需要靠"截止"类锚点词来消歧。
* 宁可返回低置信度，也不返回一个看起来合理的错误日期。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional

# --------------------------------------------------------------------- 常量
CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}

_CN_NUM_CHARS = "零〇一二三四五六七八九十两"

# 全角 -> 半角（只处理数字与常见标点，避免动到中文本身）
_FULLWIDTH_MAP = {ord("０") + i: ord("0") + i for i in range(10)}
_FULLWIDTH_MAP.update({
    ord("："): ord(":"), ord("／"): ord("/"), ord("－"): ord("-"),
    ord("．"): ord("."), ord("　"): ord(" "), ord("～"): ord("~"),
})

# 强锚点：几乎只出现在"截止"语境
_STRONG_ANCHORS = re.compile(
    r"截止|截至|不晚于|务必于|请于|须于|需于|应于|最迟|逾期|"
    r"报名时间|提交时间|报送时间|受理时间|申报时间|办理时间"
)
# 弱锚点：出现频率高，只能轻微加权
_WEAK_ANCHORS = re.compile(r"之前|以前|前(?=[，,。；;、\s])|于\s*\d|内")

# 日期候选模式：(类型, 正则, 基础置信度)
_DATE_PATTERNS = (
    ("absolute", re.compile(r"(?P<y>\d{4})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号]?"), 0.96),
    ("month_day", re.compile(r"(?<![\d年])(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*[日号]"), 0.90),
    ("slash", re.compile(r"(?<![\d/])(?P<m>\d{1,2})\s*/\s*(?P<d>\d{1,2})(?![\d/])"), 0.70),
    ("relative_day", re.compile(r"(?P<rel>大后天|后天|明天|明日|今天|今日)"), 0.92),
    ("weekday", re.compile(r"(?P<wk>下下周|下周|本周|这周)?\s*(?:周|星期|礼拜)\s*(?P<wd>[一二三四五六日天])"), 0.72),
    ("duration", re.compile(r"(?P<n>\d{1,2})\s*(?:个)?\s*(?P<unit>工作日|天|日)\s*(?:内|以内|之内)"), 0.60),
)

# 时刻候选：支持 17:30 / 17点30分 / 17时30分 / 5点半 / 下午5点
_TIME_RE = re.compile(
    r"(?P<ampm>上午|下午|晚上|傍晚|中午|凌晨|早上|晚间)?\s*"
    r"(?P<h>\d{1,2})\s*"
    r"(?:"
    r":\s*(?P<mi1>\d{1,2})"
    r"|点\s*(?:(?P<mi2>\d{1,2})\s*分?|(?P<half>半))?"
    r"|时\s*(?:(?P<mi3>\d{1,2})\s*分?)?"
    r")"
)

_WEEKDAY_INDEX = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

# 只在后面紧跟时间单位时才做中文数字转换，避免误伤普通词语
_CN_DIGITIZE = re.compile(
    rf"([{_CN_NUM_CHARS}]{{1,3}})(?=\s*(?:年|月|日|号|时|点|分|天|周|星期|礼拜|份|张|本|套|件|支|台|把))"
)


# --------------------------------------------------------------------- 工具
def cn_to_int(text: str) -> int:
    """把「十一」「二十三」「十」这类中文数字转为整数，失败抛 ValueError。"""
    text = text.strip()
    if not text:
        raise ValueError("空字符串")
    if text.isdigit():
        return int(text)
    if text == "十":
        return 10
    if "十" in text:
        head, _, tail = text.partition("十")
        tens = CN_DIGITS[head] if head else 1
        ones = CN_DIGITS[tail] if tail else 0
        if len(tail) > 1:
            raise ValueError(f"无法解析的中文数字：{text}")
        return tens * 10 + ones
    if len(text) == 1 and text in CN_DIGITS:
        return CN_DIGITS[text]
    raise ValueError(f"无法解析的中文数字：{text}")


def normalize(text: str) -> str:
    """全角转半角，并把紧邻时间单位的中文数字替换为阿拉伯数字。"""
    out = text.translate(_FULLWIDTH_MAP)

    def _repl(match: "re.Match[str]") -> str:
        try:
            return str(cn_to_int(match.group(1)))
        except ValueError:
            return match.group(1)

    return _CN_DIGITIZE.sub(_repl, out)


@dataclass
class TimeCandidate:
    """一个被识别出来的时间点及其来源信息。"""

    dt: datetime
    start: int
    end: int
    raw: str
    confidence: float
    kind: str
    has_clock: bool
    date_end: int = 0              # 日期部分本身的结束位置（不含绑定的时刻）
    is_range_start: bool = False   # 「11月18日至11月22日」中的前者
    is_range_end: bool = False     # 区间终点，更像截止时间

    def to_dict(self) -> dict:
        return {
            "iso": self.dt.strftime("%Y-%m-%d %H:%M"),
            "raw": self.raw,
            "kind": self.kind,
            "confidence": round(self.confidence, 2),
            "has_clock": self.has_clock,
            "range_start": self.is_range_start,
        }


@dataclass
class Deadline:
    """解析出的截止时间。"""

    dt: datetime
    raw: str
    confidence: float
    kind: str
    has_clock: bool
    assumed: bool = False        # 是否由"仅日期"补全为 23:59
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "iso": self.dt.strftime("%Y-%m-%d %H:%M"),
            "date": self.dt.strftime("%Y-%m-%d"),
            "time": self.dt.strftime("%H:%M"),
            "raw": self.raw,
            "confidence": round(self.confidence, 2),
            "kind": self.kind,
            "has_clock": self.has_clock,
            "assumed_midnight": self.assumed,
            "note": self.note,
        }


# --------------------------------------------------------------------- 解析
def _safe_date(year: int, month: int, day: int) -> Optional[datetime]:
    try:
        return datetime(year, month, day)
    except ValueError:
        return None


def _resolve_clock(ampm: Optional[str], hour: int, minute: int) -> Optional[tuple]:
    """把「下午5点」「晚上8点」修正为 24 小时制。返回 (h, m) 或 None。"""
    # 「24:00」是通知里常见的当日结束写法，按 23:59 处理更符合用户直觉
    if hour == 24 and minute == 0:
        return 23, 59
    if hour > 23 or minute > 59:
        return None
    if ampm in ("下午", "傍晚", "晚间"):
        hour = hour + 12 if hour < 12 else hour
    elif ampm == "晚上":
        hour = hour + 12 if hour < 12 else hour
        if hour == 24:
            hour = 0
    elif ampm == "中午":
        if hour < 11:
            hour = hour + 12
    elif ampm in ("凌晨", "早上", "上午"):
        if hour == 12:
            hour = 0
    return hour, minute


def _find_clocks(text: str) -> List[tuple]:
    """扫描全部时刻候选，返回 [(start, end, (h, m), raw)]。"""
    clocks = []
    for match in _TIME_RE.finditer(text):
        raw_h = match.group("h")
        if raw_h is None:
            continue
        hour = int(raw_h)
        minute = 0
        for key in ("mi1", "mi2", "mi3"):
            if match.group(key):
                minute = int(match.group(key))
                break
        if match.group("half"):
            minute = 30
        resolved = _resolve_clock(match.group("ampm"), hour, minute)
        if resolved is None:
            continue
        clocks.append((match.start(), match.end(), resolved, match.group(0).strip()))
    return clocks


def _nearest_clock(clocks, start: int, end: int, window_after: int = 20, window_before: int = 10):
    """在日期候选后（优先）或前找最近的时刻。"""
    best = None
    for c_start, c_end, hm, raw in clocks:
        if 0 <= c_start - end <= window_after:
            if best is None or c_start < best[0]:
                best = (c_start, c_end, hm, raw, True)
        elif 0 <= start - c_end <= window_before:
            if best is None or not best[4]:
                best = (c_start, c_end, hm, raw, False)
    return best


def find_candidates(text: str, now: Optional[datetime] = None) -> List[TimeCandidate]:
    """列出文本中所有可解释为日期的候选（不做打分）。"""
    now = now or datetime.now()
    norm = normalize(text)
    clocks = _find_clocks(norm)
    used_clock_spans = set()
    results: List[TimeCandidate] = []

    for kind, pattern, base_conf in _DATE_PATTERNS:
        for match in pattern.finditer(norm):
            # 已被更高优先级的模式覆盖的区间跳过（如 "2026年11月20日" 里的 "11月20日"）
            if any(r.start <= match.start() and match.end() <= r.end for r in results):
                continue

            base: Optional[datetime] = None
            has_clock = False
            conf = base_conf

            if kind in ("absolute", "month_day", "slash"):
                year = int(match.group("y")) if kind == "absolute" else now.year
                month = int(match.group("m"))
                day = int(match.group("d"))
                if kind != "absolute" and month < now.month - 6:
                    # 跨年通知：12 月里写"1月5日"指的是明年
                    year += 1
                base = _safe_date(year, month, day)
            elif kind == "relative_day":
                offset = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3}
                base = (now + timedelta(days=offset[match.group("rel")])).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
            elif kind == "weekday":
                prefix = match.group("wk") or ""
                target = _WEEKDAY_INDEX[match.group("wd")]
                monday = (now - timedelta(days=now.weekday())).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                base = monday + timedelta(days=target)
                if prefix == "下周":
                    base += timedelta(days=7)
                elif prefix == "下下周":
                    base += timedelta(days=14)
                elif not prefix and base.date() < now.date():
                    base += timedelta(days=7)      # "周五" 已过 -> 指下周五
                elif prefix == "本周" and base.date() < now.date():
                    conf -= 0.20                   # 本周已过，多半不是截止日
            elif kind == "duration":
                days = int(match.group("n"))
                base = (now + timedelta(days=days)).replace(
                    hour=0, minute=0, second=0, microsecond=0
                )
                if match.group("unit") == "工作日":
                    # 粗算：自然日里扣掉周末，标注低置信
                    extra = sum(
                        1 for i in range(1, days + 1)
                        if (now + timedelta(days=i)).weekday() >= 5
                    )
                    base += timedelta(days=extra)

            if base is None:
                continue

            clock = _nearest_clock(clocks, match.start(), match.end())
            if clock and clock[:2] not in used_clock_spans:
                c_start, c_end, (hour, minute), raw_clock, after = clock
                base = base.replace(hour=hour, minute=minute)
                has_clock = True
                used_clock_spans.add((c_start, c_end))
                span_end = c_end if after else match.end()
                raw = norm[match.start():span_end].strip()
                conf += 0.04
            else:
                base = base.replace(hour=23, minute=59)
                span_end = match.end()
                raw = match.group(0).strip()

            results.append(TimeCandidate(
                dt=base, start=match.start(), end=span_end,
                raw=raw, confidence=min(conf, 0.99), kind=kind, has_clock=has_clock,
                date_end=match.end(),
            ))

    results.sort(key=lambda c: c.start)
    _link_ranges(norm, results)
    return results


# 「11月18日9:00至11月22日24:00」这类区间的连接符
_RANGE_CONNECTOR = re.compile(r"^\s*(?:至|到|持续到|截止到|—|－|-|~|～|–)+\s*$")


def _link_ranges(text: str, candidates: List[TimeCandidate]) -> None:
    """把 「A 至 B」 标记为区间，避免把开始时间当成截止时间。

    v0.1.0 在「选课时间为11月18日9:00至11月22日24:00」上取到了 11-18 09:00，
    这是最容易被用户直接照做、从而错过截止的一类错误，必须专门处理。
    """
    for prev, nxt in zip(candidates, candidates[1:]):
        if prev.end > nxt.start:
            continue
        if _RANGE_CONNECTOR.match(text[prev.end:nxt.start]):
            prev.is_range_start = True
            nxt.is_range_end = True


# 起始语：「自 11 月 20 日起」是事件的开始，不是截止
_START_BEFORE = re.compile(r"(?:自|从)\s*$")
_START_AFTER = re.compile(r"^\s*(?:起|开始|起算)")
_END_AFTER = re.compile(r"^\s*(?:止|截止)")

# 事件安排语：「补考定于11月28日进行」是考试时间，不是要交东西的截止
_EVENT_BEFORE = re.compile(r"(?:定于|将于|安排在|计划于|拟于)\s*$")
_EVENT_AFTER = re.compile(r"^\s*(?:举行|进行|开始|开幕|开展|举办|召开|当天)")


def _anchor_spans(text: str):
    """返回强锚点与弱锚点出现的位置集合。"""
    strong = [m.start() for m in _STRONG_ANCHORS.finditer(text)]
    weak = [m.start() for m in _WEAK_ANCHORS.finditer(text)]
    return strong, weak


def _score(cand: TimeCandidate, text: str, strong, weak, now: datetime) -> float:
    score = cand.confidence

    if strong:
        dist = min(abs(cand.start - p) for p in strong)
        if dist <= 15:
            score += 0.30
        elif dist <= 45:
            score += 0.14
    if weak:
        dist = min(abs(cand.start - p) for p in weak)
        if dist <= 10:
            score += 0.10

    # 区间的结束端更像截止时间，开始端几乎不是
    if cand.is_range_end:
        score += 0.15
    elif cand.is_range_start:
        score -= 0.50

    # 上下文语义：「自……起」是起始，「……止」是结束，「定于……举行」是活动时间
    before = text[max(0, cand.start - 8):cand.start]
    anchor = cand.date_end or cand.end
    after = text[anchor:anchor + 8]
    if _START_BEFORE.search(before) or _START_AFTER.search(after):
        score -= 0.45
    if _END_AFTER.search(after):
        score += 0.20
    if _EVENT_BEFORE.search(before) or _EVENT_AFTER.search(after):
        score -= 0.50

    # 时间必须落在未来（或就在今天）；已经过去的多半是发布日期
    delta_hours = (cand.dt - now).total_seconds() / 3600
    if delta_hours >= 0:
        score += 0.12
    elif delta_hours > -24:
        score -= 0.15
    else:
        score -= 0.70
    return score


def _negative_flags(cand: TimeCandidate, text: str) -> List[str]:
    """判断一个候选是否带「这不是截止时间」的语义信号。

    三类：起始语（自……起）、活动安排语（定于……举行）、区间起点（A 至 B 的 A）。
    这些位置上的时间几乎都不是学生需要卡的那个截止时刻。
    """
    before = text[max(0, cand.start - 8):cand.start]
    anchor = cand.date_end or cand.end
    after = text[anchor:anchor + 8]
    flags: List[str] = []
    if _START_BEFORE.search(before) or _START_AFTER.search(after):
        flags.append("start_phrase")
    if _EVENT_BEFORE.search(before) or _EVENT_AFTER.search(after):
        flags.append("event_phrase")
    if cand.is_range_start:
        flags.append("range_start")
    return flags


def extract_deadline(
    text: str,
    now: Optional[datetime] = None,
    min_score: float = 0.55,
) -> Optional[Deadline]:
    """抽取最可能的截止时间；找不到可靠结果时返回 None。"""
    if not text or not text.strip():
        return None
    now = now or datetime.now()
    norm = normalize(text)
    candidates = find_candidates(norm, now=now)
    if not candidates:
        return None

    strong, weak = _anchor_spans(norm)

    def _near_strong(cand: TimeCandidate) -> bool:
        """附近 15 字内有没有「截止/不晚于/请于」这类强锚点。

        有锚点时才允许推翻负向信号 —— 例如「报名截止定于11月20日」，
        虽然带「定于」，但明确写了截止，应以它为准。
        """
        return any(abs(cand.start - pos) <= 15 for pos in strong)

    usable = [c for c in candidates if not _negative_flags(c, norm) or _near_strong(c)]
    if not usable:
        # 全文的时间都是活动安排或起始时间，说明这条通知没写提交截止，
        # 宁可返回 None 让用户自己看一眼，也不给一个会被照做的错误日期
        return None

    scored = [(c, _score(c, norm, strong, weak, now)) for c in usable]
    best, best_score = max(scored, key=lambda item: item[1])

    if best_score < min_score:
        return None

    assumed = not best.has_clock
    note = ""
    if assumed:
        note = "仅识别到日期，未写具体时刻，按当日 23:59 处理"
    if best.kind == "duration":
        note = (note + "；" if note else "") + "由相对时长推算，建议人工复核"
    if best.kind == "weekday":
        note = (note + "；" if note else "") + "由星期推算，建议人工复核"

    return Deadline(
        dt=best.dt,
        raw=best.raw,
        confidence=min(best.confidence + (0.0 if best.has_clock else -0.10), 0.99),
        kind=best.kind,
        has_clock=best.has_clock,
        assumed=assumed,
        note=note,
    )


def find_all_times(text: str, now: Optional[datetime] = None) -> List[dict]:
    """列出全部时间候选，供界面展示「我在文中看到了哪些时间」。"""
    now = now or datetime.now()
    return [c.to_dict() for c in find_candidates(normalize(text), now=now)]


# --------------------------------------------------------------------- 展示
def humanize(dt: datetime, now: Optional[datetime] = None) -> str:
    """把截止时间渲染成「还剩 2 天 3 小时」这类相对描述。"""
    now = now or datetime.now()
    seconds = (dt - now).total_seconds()
    if seconds < 0:
        hours = int(-seconds // 3600)
        if hours < 24:
            return f"已逾期 {max(hours, 1)} 小时"
        return f"已逾期 {-seconds // 86400:.0f} 天"
    if seconds < 3600:
        return f"还剩 {int(seconds // 60)} 分钟"
    if seconds < 86400:
        return f"还剩 {int(seconds // 3600)} 小时"
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    return f"还剩 {days} 天 {hours} 小时" if hours else f"还剩 {days} 天"


def urgency(dt: datetime, now: Optional[datetime] = None) -> str:
    """紧急度分档，供前端上色：overdue / today / soon / normal。"""
    now = now or datetime.now()
    hours = (dt - now).total_seconds() / 3600
    if hours < 0:
        return "overdue"
    if hours <= 24:
        return "today"
    if hours <= 72:
        return "soon"
    return "normal"
