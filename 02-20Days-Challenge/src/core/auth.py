#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账号、密码与会话。

安全上的几个决定
----------------
1. **密码不落明文**。存 PBKDF2-HMAC-SHA256（12 万次迭代）+ 每用户独立随机盐。
   即使数据库文件被拿走，也拿不到原始密码。
2. **登录失败不区分原因**。学号不存在和密码错误都返回同一句"学号或密码不正确"，
   否则等于给攻击者一个枚举学号的接口。
3. **简单限流**。同一学号连续失败 5 次锁 5 分钟，内存计数，重启即失效——
   作业场景够用，不引入 redis 这类额外依赖。
4. **会话用随机 token**，存 HTTP-only Cookie，服务端留过期时间，30 天。

管理员
------
`ADMIN_STUDENT_IDS` 里的学号注册后即为 admin，能看全局数据；
其余一律 student，只能看自己的。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import threading
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple

from .store import Store

# 管理员学号白名单：注册时命中即为管理员
ADMIN_STUDENT_IDS = {"2024400222"}

SESSION_DAYS = 30
PBKDF2_ROUNDS = 120_000
SALT_BYTES = 16

_STUDENT_ID_RE = re.compile(r"^\d{8,12}$")
_HAS_LETTER = re.compile(r"[A-Za-z]")
_HAS_DIGIT = re.compile(r"\d")

_MAX_FAILS = 5
_LOCK_MINUTES = 5
_fail_counter: Dict[str, Tuple[int, datetime]] = {}
_fail_lock = threading.Lock()


# --------------------------------------------------------------------- 密码
def hash_password(password: str, salt: Optional[str] = None) -> Tuple[str, str]:
    """返回 (hash_hex, salt_hex)。"""
    salt_hex = salt or os.urandom(SALT_BYTES).hex()
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ROUNDS
    )
    return digest.hex(), salt_hex


def verify_password(password: str, expected_hash: str, salt_hex: str) -> bool:
    """常量时间比较，避免时序侧信道。"""
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), PBKDF2_ROUNDS
    )
    return hmac.compare_digest(digest.hex(), expected_hash)


# --------------------------------------------------------------------- 校验
def validate_student_id(student_id: str) -> Optional[str]:
    """返回错误码，None 表示通过。"""
    if not _STUDENT_ID_RE.match(student_id or ""):
        return "invalid_student_id"
    return None


def validate_password(password: str) -> Optional[str]:
    if not password or len(password) < 6:
        return "weak_password"
    if len(password) > 64:
        return "weak_password"
    if not _HAS_LETTER.search(password) or not _HAS_DIGIT.search(password):
        return "weak_password"
    return None


def _check_rate(student_id: str) -> bool:
    """是否处于锁定状态。"""
    with _fail_lock:
        entry = _fail_counter.get(student_id)
        if not entry:
            return False
        count, last = entry
        if count < _MAX_FAILS:
            return False
        if datetime.now() - last > timedelta(minutes=_LOCK_MINUTES):
            _fail_counter.pop(student_id, None)
            return False
        return True


def _record_fail(student_id: str) -> None:
    with _fail_lock:
        count, _ = _fail_counter.get(student_id, (0, datetime.now()))
        _fail_counter[student_id] = (count + 1, datetime.now())


def _clear_fail(student_id: str) -> None:
    with _fail_lock:
        _fail_counter.pop(student_id, None)


# --------------------------------------------------------------------- 注册
def register(store: Store, student_id: str, password: str) -> Dict[str, Any]:
    student_id = (student_id or "").strip()
    err = validate_student_id(student_id) or validate_password(password)
    if err:
        return {"ok": False, "error": err}

    if store.get_user_by_student_id(student_id):
        return {"ok": False, "error": "student_exists"}

    role = "admin" if student_id in ADMIN_STUDENT_IDS else "student"
    pwd_hash, salt = hash_password(password)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    user_id = store.create_user(student_id, pwd_hash, salt, role, now)
    return {
        "ok": True,
        "user_id": user_id,
        "student_id": student_id,
        "role": role,
    }


# --------------------------------------------------------------------- 登录
def login(store: Store, student_id: str, password: str) -> Dict[str, Any]:
    student_id = (student_id or "").strip()
    if not student_id or not password:
        return {"ok": False, "error": "invalid_credentials"}

    if _check_rate(student_id):
        return {"ok": False, "error": "too_many_attempts"}

    user = store.get_user_by_student_id(student_id)
    # 学号不存在也走一次哈希，避免通过响应时间判断账号是否存在
    if not user:
        hash_password(password, "00" * SALT_BYTES)
        _record_fail(student_id)
        return {"ok": False, "error": "invalid_credentials"}

    if not verify_password(password, user["password_hash"], user["salt"]):
        _record_fail(student_id)
        return {"ok": False, "error": "invalid_credentials"}

    _clear_fail(student_id)
    token = secrets.token_urlsafe(32)
    now_dt = datetime.now()
    store.create_session(
        token,
        int(user["id"]),
        now_dt.strftime("%Y-%m-%dT%H:%M"),
        (now_dt + timedelta(days=SESSION_DAYS)).strftime("%Y-%m-%dT%H:%M"),
    )
    store.touch_login(int(user["id"]), now_dt.strftime("%Y-%m-%dT%H:%M"))
    store.purge_expired_sessions(now_dt.strftime("%Y-%m-%dT%H:%M"))

    return {
        "ok": True,
        "token": token,
        "student_id": user["student_id"],
        "role": user["role"],
    }


# --------------------------------------------------------------------- 会话
def resolve_session(store: Store, token: Optional[str]) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    now = datetime.now().strftime("%Y-%m-%dT%H:%M")
    return store.get_session_user(token, now)


def logout(store: Store, token: Optional[str]) -> None:
    if token:
        store.delete_session(token)
