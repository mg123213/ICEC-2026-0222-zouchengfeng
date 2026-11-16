#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通知结构化提取。

输入：一段从班级群 / 公众号 / 官网粘过来的通知正文。
输出：标题、截止时间、提交地点、材料清单、联系人、待办动作、分类标签。

四条原则
--------
1. **可复核**：每一项都附带 evidence（命中的原句），界面上跟原文对照高亮，
   识别错了用户一眼能看出来，而不是盲信一个黑盒结果。
2. **宁缺勿错**：抽不到就返回空 + 一条 warning，绝不编造。
3. **纯本地**：不调用任何外部接口，通知原文不出本机。
4. **可度量**：返回 quality 自评分数，作为运行日志的指标，驱动后续迭代。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from . import timeparse

# --------------------------------------------------------------------- 词表
_TAG_RULES = {
    "竞赛": ("竞赛", "技能大赛", "选拔", "世赛", "国赛", "省赛", "市赛", "比武", "技能节"),
    "教务": ("选课", "重修", "补修", "补考", "学分", "课程", "成绩", "统考", "教务", "考试"),
    "资助": ("补助", "奖学金", "助学金", "困难", "资助", "认定", "减免"),
    "实训": ("实训", "器材", "设备", "耗材", "机房", "车间", "工位", "工具", "借用"),
    "活动": ("文体", "艺术节", "运动会", "晚会", "讲座", "社团", "志愿", "比赛", "报名参加"),
    "就业": ("实习", "就业", "招聘", "双选", "顶岗", "企业", "面试", "简历"),
    "学籍": ("学籍", "注册", "报到", "请假", "证明", "档案", "毕业", "退课"),
    "生活": ("宿舍", "校园卡", "体检", "医保", "快递", "食堂", "门禁"),
}

_MATERIAL_HINTS = re.compile(
    r"携带|提交|上交|交至|交到|准备|备齐|自带|附上|提供|"
    r"材料|资料|证件|附件|复印件|原件|表格|申请表|证明"
)
_MATERIAL_ITEM_HINTS = re.compile(
    r"身份证|学生证|校园卡|学生卡|照片|申请表|报名表|证明|复印件|原件|"
    r"成绩单|简历|作品|材料|资料|表格|承诺书|推荐表|截图|清单|费用|押金|U盘|电脑"
)

# 数量表达：2份 / 三张 / 1套
_QTY_RE = re.compile(r"(?<!\d)(\d{1,2}|[一二三四五六七八九十两])\s*(份|张|本|套|件|支|只|台|把|个|页|寸)")

_LOCATION_RE = re.compile(
    r"(?<![\u4e00-\u9fa5])"
    r"([\u4e00-\u9fa5A-Za-z0-9()（）\-]{1,12}?"
    r"(?:楼|室|馆|厅|中心|校区|大厦|车间|机房|会议室|报告厅|实训基地|办公室|服务台|门口))"
)
_LOCATION_HINT = re.compile(r"地点|地址|交至|提交至|前往|到\s*[\u4e00-\u9fa5]{0,6}(?:楼|室|馆|厅)|在\s*[\u4e00-\u9fa5]{0,8}(?:楼|室|馆|厅)集合")

_CONTACT_RE = re.compile(
    r"(?:联系人|联系老师|咨询电话|联系电话|联系)\s*[:：]?\s*"
    r"([\u4e00-\u9fa5]{2,4}?)(?:老师|同学|主任|科长|辅导员)?(?=[，,。；;\s（(]|$)"
)
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9}|\d{3,4}-\d{7,8}|0\d{2,3}-\d{7,8})(?!\d)")

# 待办动作：祈使句里常见的动词
_ACTION_VERBS = (
    "报名", "提交", "上交", "填写", "填报", "参加", "领取", "确认", "缴纳", "缴费",
    "打印", "签字", "登录", "扫码", "加入", "携带", "准备", "核对", "归还", "签到",
)
_ACTION_RE = re.compile(r"(?:请|需|须|务必|应|及时)[^。；\n]{0,40}(?:" + "|".join(_ACTION_VERBS) + r")[^。；\n]{0,30}")

_SENT_SPLIT = re.compile(r"[。！？；\n]+")
_ITEM_SPLIT = re.compile(r"(?:^|[\s　])(?:\d{1,2}[.、)）]|[①-⑩]|[（(]\d{1,2}[)）]|[·•\-–—])\s*|、|；")

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
           "七": 7, "八": 8, "九": 9, "十": 10}


# --------------------------------------------------------------------- 工具
def split_sentences(text: str) -> List[str]:
    """按中文标点切句，保留非空片段。"""
    return [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]


def _normalize_space(text: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def guess_title(text: str) -> str:
    """优先取「关于……的通知」句式，否则取首行。"""
    head = _normalize_space(text).split("\n")[0][:80]
    match = re.search(r"(关于[^。\n]{4,50}?(?:通知|公告|公示|安排|须知))", text)
    if match:
        return match.group(1).strip()
    cleaned = re.sub(r"^[【\[（(][^】\]）)]{1,20}[】\]）)]\s*", "", head)
    return cleaned.strip()[:50] or "未命名通知"


def _extract_materials(text: str) -> (List[Dict[str, object]], List[str]):
    """抽取材料清单，返回 (材料列表, 命中的证据句)。"""
    materials: List[Dict[str, object]] = []
    evidence: List[str] = []
    seen = set()

    for sentence in split_sentences(text):
        if not _MATERIAL_HINTS.search(sentence):
            continue
        evidence.append(sentence[:80])
        # 句内再按序号拆成条目
        for chunk in _ITEM_SPLIT.split(sentence):
            if not chunk:
                continue
            item = chunk.strip(" 　，,。.：:；;")
            if not (2 <= len(item) <= 30):
                continue
            if not _MATERIAL_ITEM_HINTS.search(item):
                continue
            qty = None
            unit = None
            qty_match = _QTY_RE.search(item)
            if qty_match:
                raw_qty = qty_match.group(1)
                qty = int(raw_qty) if raw_qty.isdigit() else _CN_NUM.get(raw_qty)
                unit = qty_match.group(2)
            name = _QTY_RE.sub("", item).strip(" 　的")
            if not name or name in seen:
                continue
            seen.add(name)
            materials.append({"name": name[:24], "qty": qty, "unit": unit})
            if len(materials) >= 12:
                break
        if len(materials) >= 12:
            break

    return materials, evidence[:4]


def _extract_location(text: str) -> Optional[str]:
    """抽取提交/集合地点；优先取有「地点/交至」提示语的句子里的。"""
    for sentence in split_sentences(text):
        if not _LOCATION_HINT.search(sentence):
            continue
        for match in _LOCATION_RE.finditer(sentence):
            candidate = match.group(1).strip()
            if len(candidate) >= 3 and not candidate.startswith(("本次", "以上", "相关")):
                return candidate[:24]

    # 退一步：全文里任何一个像地点后缀的说法
    for match in _LOCATION_RE.finditer(text):
        candidate = match.group(1).strip()
        if 3 <= len(candidate) <= 16:
            return candidate
    return None


def _extract_contacts(text: str) -> List[Dict[str, str]]:
    contacts: List[Dict[str, str]] = []
    for phone in _PHONE_RE.findall(text):
        contacts.append({"name": "", "phone": phone})
    for match in _CONTACT_RE.finditer(text):
        name = match.group(1)
        if name in ("时间", "地点", "材料", "要求", "事项", "方式"):
            continue
        if any(c["name"] == name for c in contacts):
            continue
        contacts.append({"name": name, "phone": ""})
    return contacts[:3]


def _extract_actions(text: str) -> List[str]:
    actions: List[str] = []
    seen = set()
    for match in _ACTION_RE.finditer(text):
        item = match.group(0).strip(" 　，,。")
        if len(item) < 6 or item in seen:
            continue
        seen.add(item)
        actions.append(item[:48])
    return actions[:6]


def _extract_tags(text: str) -> List[str]:
    tags = [tag for tag, words in _TAG_RULES.items() if any(w in text for w in words)]
    return tags[:3]


# --------------------------------------------------------------------- 主函数
def parse_notice(text: str, now=None) -> Dict[str, object]:
    """把一段通知文本解析成结构化结果。"""
    now = now or timeparse.datetime.now()
    raw = _normalize_space(text or "")
    if not raw:
        return {
            "ok": False,
            "error": "empty_input",
            "warnings": ["没有拿到通知正文，请先粘贴内容"],
        }

    title = guess_title(raw)
    deadline = timeparse.extract_deadline(raw, now=now)
    materials, material_evidence = _extract_materials(raw)
    location = _extract_location(raw)
    contacts = _extract_contacts(raw)
    actions = _extract_actions(raw)
    tags = _extract_tags(raw)

    warnings: List[str] = []
    if deadline is None:
        warnings.append("未识别到明确的截止时间，建议手动补充")
    elif deadline.confidence < 0.75:
        warnings.append("截止时间置信度偏低，请对照原文核对")
    if not materials:
        warnings.append("未识别到材料清单")
    if not location:
        warnings.append("未识别到提交地点")

    # 质量自评：用于运行日志里的 quality 指标
    quality = 0.0
    quality += 0.5 if deadline else 0.0
    quality += 0.25 if materials else 0.0
    quality += 0.15 if location else 0.0
    quality += 0.10 if actions else 0.0

    return {
        "ok": True,
        "title": title,
        "deadline": deadline.to_dict() if deadline else None,
        "deadline_human": timeparse.humanize(deadline.dt, now) if deadline else "",
        "urgency": timeparse.urgency(deadline.dt, now) if deadline else "none",
        "materials": materials,
        "location": location or "",
        "contacts": contacts,
        "actions": actions,
        "tags": tags,
        "warnings": warnings,
        "quality": round(quality, 2),
        "evidence": {
            "deadline": _deadline_evidence(raw, deadline),
            "materials": material_evidence,
        },
        "candidates": timeparse.find_all_times(raw, now=now),
        "stats": {"chars": len(raw), "sentences": len(split_sentences(raw))},
    }


def _deadline_evidence(text: str, deadline) -> str:
    """找出包含截止原文的那一句，便于界面并排核对。"""
    if deadline is None:
        return ""
    for sentence in split_sentences(text):
        if deadline.raw and deadline.raw[:6] in sentence:
            return sentence[:90]
    return deadline.raw
