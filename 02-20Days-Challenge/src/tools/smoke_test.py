#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端到端冒烟测试：注册 → 登录 → 数据隔离 → 管理员权限。

服务需先启动。默认打本机 8765：

    python tools/smoke_test.py
    python tools/smoke_test.py --base https://xxx.app.workbuddy.host --sharecode ABC
"""

from __future__ import annotations

import argparse
import http.cookiejar
import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any, Dict, Optional

PASS, FAIL = "PASS", "FAIL"
results = []


def check(name: str, condition: bool, detail: str = "") -> None:
    results.append((PASS if condition else FAIL, name, detail))
    print(f"[{PASS if condition else FAIL}] {name}" + (f"  — {detail}" if detail else ""))


class Client:
    def __init__(self, base: str, sharecode: str = "") -> None:
        self.base = base.rstrip("/")
        self.sharecode = sharecode
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def url(self, path: str) -> str:
        if not self.sharecode:
            return self.base + path
        sep = "&" if "?" in path else "?"
        return f"{self.base}{path}{sep}sharecode={self.sharecode}"

    def request(self, path: str, method: str = "GET",
                payload: Optional[Dict[str, Any]] = None):
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(
            self.url(path), data=data, method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with self.opener.open(req, timeout=20) as resp:
                body = resp.read().decode("utf-8", "replace")
                try:
                    return resp.status, json.loads(body)
                except json.JSONDecodeError:
                    return resp.status, body
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                return exc.code, json.loads(body)
            except json.JSONDecodeError:
                return exc.code, body


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8765")
    parser.add_argument("--sharecode", default="")
    parser.add_argument("--admin", default="2024400222")
    # 默认不写死管理员密码：用环境变量传入，避免公开仓库泄漏线上账号
    parser.add_argument("--admin-pwd", default=os.environ.get("ICEC_ADMIN_PWD", ""))
    parser.add_argument("--student", default="2024400001")
    parser.add_argument("--student-pwd", default="test1234")
    args = parser.parse_args()

    admin = Client(args.base, args.sharecode)
    student = Client(args.base, args.sharecode)

    # ---------- 未登录 ----------
    status, data = admin.request("/api/tasks")
    check("未登录访问待办被拒", status == 401, f"status={status}")

    status, body = admin.request("/")
    check("首页返回登录页", status == 200 and "登录" in str(body)[:2000], f"status={status}")

    # ---------- 注册 ----------
    status, data = admin.request("/api/register", "POST",
                                 {"student_id": args.admin, "password": args.admin_pwd})
    check("注册管理员账号", status == 200 and data.get("ok"),
          data.get("error", "已完成") if isinstance(data, dict) else str(data))

    status, data = student.request("/api/register", "POST",
                                   {"student_id": args.student, "password": args.student_pwd})
    check("注册学生账号", status == 200 and data.get("ok"),
          data.get("error", "已完成") if isinstance(data, dict) else str(data))

    # ---------- 登录 ----------
    status, data = admin.request("/api/login", "POST",
                                 {"student_id": args.admin, "password": args.admin_pwd})
    check("管理员登录", status == 200 and data.get("ok") and data.get("role") == "admin",
          f"role={data.get('role') if isinstance(data, dict) else '?'}")

    status, data = student.request("/api/login", "POST",
                                   {"student_id": args.student, "password": args.student_pwd})
    check("学生登录", status == 200 and data.get("ok") and data.get("role") == "student",
          f"role={data.get('role') if isinstance(data, dict) else '?'}")

    status, data = admin.request("/api/me")
    check("会话保持", status == 200 and data.get("student_id") == args.admin)

    # ---------- 数据隔离 ----------
    status, data = student.request("/api/parse", "POST",
                                   {"text": "请于11月21日17:00前将材料交至行政楼302室。", "save": True})
    check("学生保存待办", status == 200 and data.get("ok") and data.get("task_id"),
          str(data.get("task_id")) if isinstance(data, dict) else "")

    status, data = student.request("/api/tasks")
    student_tasks = data.get("tasks", []) if isinstance(data, dict) else []
    check("学生看到自己的待办", len(student_tasks) == 1, f"{len(student_tasks)} 条")

    status, data = admin.request("/api/tasks")
    admin_tasks = data.get("tasks", []) if isinstance(data, dict) else []
    check("管理员私有待办不见学生数据", len(admin_tasks) == 0, f"{len(admin_tasks)} 条")

    # ---------- 管理员接口 ----------
    status, data = student.request("/api/admin/overview")
    check("学生访问管理接口被拒", status == 403, f"status={status}")

    status, data = admin.request("/api/admin/overview")
    check("管理员可看全局概览", status == 200 and data.get("ok"),
          f"users={data.get('users') if isinstance(data, dict) else '?'}")

    status, data = admin.request("/api/admin/users")
    users = data.get("users", []) if isinstance(data, dict) else []
    check("管理员可看用户列表", status == 200 and len(users) >= 2, f"{len(users)} 人")

    status, data = admin.request("/api/admin/tasks")
    all_tasks = data.get("tasks", []) if isinstance(data, dict) else []
    check("管理员可看全部待办", status == 200 and len(all_tasks) >= 1, f"{len(all_tasks)} 条")

    # ---------- 页面 ----------
    status, body = admin.request("/admin")
    check("管理员可打开后台页面", status == 200 and "管理后台" in str(body)[:3000], f"status={status}")

    status, body = student.request("/admin")
    check("学生打开后台被拒", status == 403, f"status={status}")

    # ---------- 退出 ----------
    status, _ = student.request("/api/logout", "POST", {})
    status, data = student.request("/api/tasks")
    check("退出后会话失效", status == 401, f"status={status}")

    failed = sum(1 for r in results if r[0] == FAIL)
    print(f"\n{len(results) - failed}/{len(results)} 通过")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
