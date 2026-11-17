#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""账号、会话与数据隔离的单元测试。

    python tests/test_auth.py
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import auth  # noqa: E402
from core.store import Store  # noqa: E402


class AuthTestBase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self._tmp.name) / "test.db")

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TestRegister(AuthTestBase):
    def test_ok(self):
        result = auth.register(self.store, "2024400001", "abc12345")
        self.assertTrue(result["ok"])
        self.assertEqual(result["role"], "student")

    def test_admin_whitelist(self):
        """管理员学号注册后即为 admin。"""
        result = auth.register(self.store, "2024400222", "13579adS")
        self.assertTrue(result["ok"])
        self.assertEqual(result["role"], "admin")

    def test_duplicate(self):
        auth.register(self.store, "2024400002", "abc12345")
        again = auth.register(self.store, "2024400002", "abc12345")
        self.assertFalse(again["ok"])
        self.assertEqual(again["error"], "student_exists")

    def test_bad_student_id(self):
        for sid in ("", "123", "abcdefgh", "20244002221234"):
            self.assertEqual(auth.register(self.store, sid, "abc12345")["error"],
                             "invalid_student_id", msg=sid)

    def test_weak_password(self):
        for pwd in ("123", "123456", "abcdef", "13579adS"[:5]):
            self.assertEqual(auth.register(self.store, "2024400003", pwd)["error"],
                             "weak_password", msg=pwd)

    def test_password_not_stored_plain(self):
        """数据库里不能出现明文密码。"""
        auth.register(self.store, "2024400004", "secret123")
        user = self.store.get_user_by_student_id("2024400004")
        self.assertNotIn("secret123", str(user))
        self.assertEqual(len(user["password_hash"]), 64)


class TestLogin(AuthTestBase):
    def setUp(self) -> None:
        super().setUp()
        auth.register(self.store, "2024400005", "abc12345")

    def test_login_ok(self):
        result = auth.login(self.store, "2024400005", "abc12345")
        self.assertTrue(result["ok"])
        self.assertTrue(result["token"])
        self.assertEqual(result["role"], "student")

    def test_wrong_password(self):
        result = auth.login(self.store, "2024400005", "abc12346")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "invalid_credentials")

    def test_unknown_user_same_error(self):
        """学号不存在与密码错误返回同一个错误，避免枚举学号。"""
        a = auth.login(self.store, "2024409999", "abc12345")
        b = auth.login(self.store, "2024400005", "wrong123")
        self.assertEqual(a["error"], b["error"])

    def test_session_resolves(self):
        token = auth.login(self.store, "2024400005", "abc12345")["token"]
        user = auth.resolve_session(self.store, token)
        self.assertIsNotNone(user)
        self.assertEqual(user["student_id"], "2024400005")

    def test_logout_invalidates(self):
        token = auth.login(self.store, "2024400005", "abc12345")["token"]
        auth.logout(self.store, token)
        self.assertIsNone(auth.resolve_session(self.store, token))

    def test_rate_limit(self):
        for _ in range(auth._MAX_FAILS):
            auth.login(self.store, "2024400005", "bad12345")
        locked = auth.login(self.store, "2024400005", "abc12345")
        self.assertEqual(locked["error"], "too_many_attempts")
        auth._clear_fail("2024400005")


class TestIsolation(AuthTestBase):
    def test_tasks_are_per_user(self):
        """A 的待办不能出现在 B 的列表里。"""
        auth.register(self.store, "2024400010", "abc12345")
        auth.register(self.store, "2024400011", "abc12345")
        a = self.store.get_user_by_student_id("2024400010")
        b = self.store.get_user_by_student_id("2024400011")

        self.store.add_task({"id": "t1", "user_id": a["id"], "title": "A 的报销",
                             "materials": [], "tags": []})
        self.store.add_task({"id": "t2", "user_id": b["id"], "title": "B 的材料",
                             "materials": [], "tags": []})

        self.assertEqual([t["title"] for t in self.store.list_tasks(a["id"])], ["A 的报销"])
        self.assertEqual([t["title"] for t in self.store.list_tasks(b["id"])], ["B 的材料"])
        self.assertEqual(len(self.store.list_tasks(None)), 2)  # 管理员视角看全部

    def test_cannot_touch_others_task(self):
        """跨用户改状态或删除必须失败。"""
        auth.register(self.store, "2024400012", "abc12345")
        auth.register(self.store, "2024400013", "abc12345")
        a = self.store.get_user_by_student_id("2024400012")
        b = self.store.get_user_by_student_id("2024400013")
        self.store.add_task({"id": "t3", "user_id": a["id"], "title": "A 的任务",
                             "materials": [], "tags": []})

        self.assertFalse(self.store.set_task_done("t3", b["id"], True, "now"))
        self.assertFalse(self.store.delete_task("t3", b["id"]))
        self.assertTrue(self.store.set_task_done("t3", a["id"], True, "now"))

    def test_feedback_isolated(self):
        auth.register(self.store, "2024400014", "abc12345")
        auth.register(self.store, "2024400015", "abc12345")
        a = self.store.get_user_by_student_id("2024400014")
        b = self.store.get_user_by_student_id("2024400015")
        self.store.add_feedback({"user_id": a["id"], "role": "学生", "score": 5,
                                 "useful": [], "comment": "好", "would_use": True,
                                 "created_at": "2026-11-17T10:00"})
        self.assertEqual(len(self.store.list_feedback(a["id"])), 1)
        self.assertEqual(len(self.store.list_feedback(b["id"])), 0)
        self.assertEqual(len(self.store.list_feedback(None)), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
