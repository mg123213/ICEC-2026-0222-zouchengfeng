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

v0.2.0 变更
-----------
初版把「地点」当成一个正则去套，结果从动词处开始匹配，抽出
`00前将以下材料交至行政楼` 这种脏值（评测地点命中率 50%）。
改为「先定位地点后缀词，再向前后双向扩展」的扫描式抽取，并把材料清单
改为「去括号 → 按逗号分句 → 剥动词前缀 → 按顿号/和拆分」的四步流水线。
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

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
    r"携带|带上|带好|自带|提交|上交|交至|交到|准备|备齐|提供|上传|附上|"
    r"材料|资料|证件|附件|复印件|原件|表格|申请表|证明"
)

# 具体材料名。没有命中这里面的词，不当作材料（避免把「截止到周五…」当材料）
_MATERIAL_ITEM_HINTS = re.compile(
    r"身份证|学生证|校园卡|学生卡|照片|申请表|报名表|证明|复印件|原件|"
    r"成绩单|简历|作品|材料|资料|表格|承诺书|推荐表|截图|清单|费用|押金|"
    r"签字笔|笔|U盘|电脑|作品集|体检表|回执"
)

# 数量：一式两份 / 2份 / 三张
_QTY_CN = re.compile(r"一式([一二三四五六七八九十两])份")
_QTY_RE = re.compile(r"(?<!\d)(\d{1,2}|[一二三四五六七八九十两])\s*(份|张|本|套|件|支|只|台|把|个|页|寸)")

# 动词前缀：「请符合条件的同学于……前将以下材料交至」这类开头要剥掉
_VERB_PREFIX = re.compile(
    r"^(?:请|需|须|务必|应|各位|各班|每人|大家)?[^，,。；：]{0,30}?"
    r"(?:携带|带上|带好|自带|提交|上交|交至|交到|准备|备齐|提供|上传|附上)"
)

# 明显是"动作"而不是"材料"的片段
_MATERIAL_BLACKLIST = re.compile(r"截止|时间|地点|方式|确认|填写|登录|过期|逾期|扫码|关注")

# 地点后缀，长的放前面，避免「办公室」被「室」抢先匹配
_LOC_SUFFIX_RE = re.compile(
    r"实训基地|实训楼|教学楼|宿舍楼|实验楼|综合楼|行政楼|图书馆|"
    r"会议室|报告厅|办公室|服务台|学生服务大厅|"
    r"楼|室|馆|厅|中心|校区|大厦|车间|机房|门口"
)

# 向前回溯时遇到这些字符就停，防止把动词、介词卷进地点名
_LOC_STOP = set("至在到于往前将的把向从和与及、，。；：！？（）()【】《》 　\t\n\r\"'“”‘’")

# 地点提示语：有这些词的句子优先
_LOCATION_HINT = re.compile(
    r"地点|地址|交至|提交至|报送至|送至|递交|前往|集合|"
    r"[到在]\s*[\u4e00-\u9fa5A-Za-z0-9]{0,8}(?:楼|室|馆|厅|中心|校区)"
)

# 提交语境：整篇没有这类动作时，说明它不是在叫人去哪儿交东西，
# 此时不应输出「提交地点」（例如「图书馆延长开放时间」里的图书馆）
_SUBMIT_ACTION = re.compile(
    r"交至|提交|上交|报送|送至|递交|前往|集合|领取|办理|"
    r"[到在]\s*[\u4e00-\u9fa5A-Za-z0-9]{0,8}(?:楼|室|馆|厅)"
)

# 太泛的地点名，有更好的候选时应跳过
_GENERIC_LOCATIONS = {"办公室", "教室", "会议室", "实训室", "机房", "报告厅", "中心", "门口"}

_CONTACT_RE = re.compile(
    r"(?:联系人|联系老师|咨询电话|联系电话|联系)\s*[:：]?\s*"
    r"([\u4e00-\u9fa5]{2,4}?)(?:老师|同学|主任|科长|辅导员)?(?=[，,。；;\s（(]|$)"
)
_PHONE_RE = re.compile(r"(?<!\d)(1[3-9]\d{9}|\d{3,4}-\d{7,8}|0\d{2,3}-\d{7,8})(?!\d)")

# 这些不是人名，是部门
_CONTACT_BLACKLIST = {
    "教务科", "学生处", "团委", "办公室", "实训室", "财务处", "图书馆",
    "宿管", "后勤", "保卫处", "招生办", "教务处", "学工部", "校团委",
}

# 待办动作：祈使句里常见的动词
_ACTION_VERBS = (
    "报名", "提交", "上交", "填写", "填报", "参加", "领取", "确认", "缴纳", "缴费",
    "打印", "签字", "登录", "扫码", "加入", "携带", "准备", "核对", "归还", "签到",
)
_ACTION_RE = re.compile(r"(?:请|需|须|务必|应|及时)[^。；\n]{0,40}(?:" + "|".join(_ACTION_VERBS) + r")[^。；\n]{0,30}")

_SENT_SPLIT = re.compile(r"[。！？；\n]+")
_CLAUSE_SPLIT = re.compile(r"[，,]")
_ITEM_SPLIT = re.compile(r"(?:^|\s)(?:\d{1,2}[.、)）]|[①-⑩]|[（(]\d{1,2}[)）]|[·•\-–—])\s*|、|和|及|以及")
_BRACKET = re.compile(r"[（(][^）)]*[）)]")

_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6,
           "七": 7, "八": 8, "九": 9, "十": 10}


# --------------------------------------------------------------------- 工具
def split_sentences(text: str) -> List[str]:
    """按中文标点切句，保留非空片段。"""
    return [s.strip() for s in _SENT_SPLIT.split(text) if s and s.strip()]


def _normalize_space(text: str) -> str:
    return re.sub(r"[ \t\u3000]+", " ", text.replace("\r\n", "\n").replace("\r", "\n")).strip()


def guess_title(text: str) -> str:
    """优先取「关于……的通知」句式，否则取首行并截到第一个句末标点。"""
    match = re.search(r"(关于[^。\n]{4,50}?(?:通知|公告|公示|安排|须知))", text)
    if match:
        return match.group(1).strip()

    head = _normalize_space(text).split("\n")[0][:80]
    head = re.sub(r"^@\S+\s*", "", head)                       # 去掉 @全体成员
    head = re.sub(r"^[【\[][^】\]]{1,20}[】\]]\s*", "", head)   # 去掉【通知】类前缀
    head = re.split(r"[。！？；]", head)[0].strip()
    head = re.sub(r"^(?:通知|通知：|公告|提醒)\s*[:：]?\s*", "", head)
    return head[:50] or "未命名通知"


# --------------------------------------------------------------------- 材料
def _clean_material_name(item: str) -> str:
    """去掉数量、书名号、多余虚词，留下材料本体。"""
    name = _QTY_CN.sub("", item)
    name = _QTY_RE.sub("", name)
    name = name.replace("一式", "").replace("《", "").replace("》", "")
    name = re.sub(r"^(?:携带|带上|带好|自带|提交|上交|提供|准备|备齐|并)", "", name)
    name = name.strip(" 　，,。.：:；;、的及各")
    return name


def _extract_materials(text: str) -> Tuple[List[Dict[str, object]], List[str]]:
    """抽取材料清单，返回 (材料列表, 命中的证据句)。"""
    materials: List[Dict[str, object]] = []
    evidence: List[str] = []
    seen = set()

    for sentence in split_sentences(text):
        # 句子里既没有提交类动词，也没有具体材料名，直接跳过
        if not _MATERIAL_HINTS.search(sentence) and not _MATERIAL_ITEM_HINTS.search(sentence):
            continue
        if "截止" not in sentence and _MATERIAL_ITEM_HINTS.search(sentence):
            pass

        stripped = _BRACKET.sub("", sentence)      # 去掉补充说明的括号内容
        hit_this_sentence = False

        for clause in _CLAUSE_SPLIT.split(stripped):
            clause = clause.strip(" 　")
            if not clause or not re.search(r"[\u4e00-\u9fa5]", clause):
                continue

            # 剥掉「请……携带」这类动词前缀
            body = _VERB_PREFIX.sub("", clause).strip(" 　")
            if not body:
                continue

            for chunk in _ITEM_SPLIT.split(body):
                if not chunk:
                    continue
                item = chunk.strip(" 　，,。.：:；;、")
                if not (2 <= len(item) <= 22):
                    continue
                if not _MATERIAL_ITEM_HINTS.search(item):
                    continue
                if _MATERIAL_BLACKLIST.search(item):
                    continue

                qty, unit = None, None
                cn_qty = _QTY_CN.search(item)
                if cn_qty:
                    qty, unit = _CN_NUM.get(cn_qty.group(1)), "份"
                else:
                    qty_match = _QTY_RE.search(item)
                    if qty_match:
                        raw_qty = qty_match.group(1)
                        qty = int(raw_qty) if raw_qty.isdigit() else _CN_NUM.get(raw_qty)
                        unit = qty_match.group(2)

                name = _clean_material_name(item)
                if len(name) < 2 or name in seen or name.isdigit():
                    continue
                seen.add(name)
                materials.append({"name": name[:24], "qty": qty, "unit": unit})
                hit_this_sentence = True
                if len(materials) >= 12:
                    break

            if hit_this_sentence and sentence[:80] not in evidence:
                evidence.append(sentence[:80])
            if len(materials) >= 12:
                break

        if len(materials) >= 12:
            break

    return materials, evidence[:4]


# --------------------------------------------------------------------- 地点
def _location_candidates(text: str) -> List[Tuple[str, int, int]]:
    """定位所有地点后缀，向前后扩展成完整地点名。

    这样得到的是「行政楼302室」而不是「00前将以下材料交至行政楼」——
    关键在向前回溯时遇到「至/在/到/前/将」这类虚词就立即停止。
    """
    found: List[Tuple[str, int, int]] = []
    for match in _LOC_SUFFIX_RE.finditer(text):
        # 向前收集中文/字母，最多 6 字
        left_chars: List[str] = []
        cursor = match.start()
        while cursor > 0 and len(left_chars) < 6:
            ch = text[cursor - 1]
            if ch in _LOC_STOP or not re.match(r"[\u4e00-\u9fa5A-Za-z]", ch):
                break
            left_chars.append(ch)
            cursor -= 1
        head = "".join(reversed(left_chars))

        # 向后接房间号，如 302室 / B305 / 508
        tail = ""
        room = re.match(r"[A-Za-z]?\d{1,4}(?:室|号|房|教室)?", text[match.end():])
        if room:
            tail = room.group(0)

        name = (head + match.group(0) + tail).strip()
        if len(name) >= 3:
            found.append((name, cursor, match.end() + len(tail)))
    return found


def _extract_location(text: str) -> Optional[str]:
    """抽取提交/集合地点。优先取带「交至/在……集合」提示语的那一句。"""
    if not _SUBMIT_ACTION.search(text):
        return None

    hinted: List[str] = []
    plain: List[str] = []

    for sentence in split_sentences(text):
        candidates = [name for name, _, _ in _location_candidates(sentence)]
        if not candidates:
            continue
        target = hinted if _LOCATION_HINT.search(sentence) else plain
        for name in candidates:
            if name not in target:
                target.append(name)

    for pool in (hinted, plain):
        for name in pool:
            if name in _GENERIC_LOCATIONS:
                continue
            return name[:24]

    # 全是泛称时退回第一个
    for pool in (hinted, plain):
        if pool:
            return pool[0][:24]
    return None


# --------------------------------------------------------------------- 其他
def _extract_contacts(text: str) -> List[Dict[str, str]]:
    contacts: List[Dict[str, str]] = []
    for phone in _PHONE_RE.findall(text):
        contacts.append({"name": "", "phone": phone})
    for match in _CONTACT_RE.finditer(text):
        name = match.group(1)
        if name in _CONTACT_BLACKLIST or name in ("时间", "地点", "材料", "要求", "事项", "方式"):
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
