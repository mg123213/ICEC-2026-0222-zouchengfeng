#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校园事务小工具 —— 本地 / 云端服务入口。

    python app.py                # 启动，自动打开浏览器
    python app.py --port 9000    # 指定端口
    python app.py --no-browser   # 不自动打开浏览器

只用 Python 标准库，不需要 pip install 任何东西。

多用户模式（v0.6）
------------------
从"一个公共页面"改成"每人一个账号、只看自己的数据"：

* `/`        未登录返回登录页，已登录返回工作台
* `/admin`   仅管理员可进，看全局数据
* `/api/*`   业务接口一律要求登录，数据按 user_id 隔离

监听地址分两种模式：本机只绑 127.0.0.1；检测到 `PORT` 环境变量（发布到沙箱后
由平台注入）则绑 0.0.0.0，并把样式脚本内联进 HTML —— 因为平台网关要求每个
请求带 `sharecode`，而浏览器发起的 `<link>` / `<script>` 不会自动带。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import socket
import sys
import threading
import time
import uuid
import webbrowser
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.parse import unquote, urlparse

BASE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE_DIR))

from core import __version__, auth, inventory, notice_parser  # noqa: E402
from core.store import Store  # noqa: E402
from core.telemetry import CST, Telemetry, summarize_records  # noqa: E402

WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
NOTE_DIR = DATA_DIR / "notes"
DB_FILE = DATA_DIR / "app.db"
FEEDBACK_FILE = BASE_DIR / "feedback" / "responses.jsonl"

MAX_BODY = 512 * 1024
IN_CLOUD = (os.environ.get("PORT") or "").strip().isdigit()

_io_lock = threading.Lock()
_tel = Telemetry()
_store: Optional[Store] = None


def store() -> Store:
    global _store
    if _store is None:
        _store = Store(DB_FILE)
    return _store


# --------------------------------------------------------------------- 工具
def _ensure_dirs() -> None:
    for path in (DATA_DIR, NOTE_DIR, FEEDBACK_FILE.parent):
        path.mkdir(parents=True, exist_ok=True)


def user_tag(user: Dict[str, Any]) -> str:
    """学号在日志里只留 6 位哈希，不可反查。"""
    return hashlib.sha256(str(user.get("student_id", "")).encode()).hexdigest()[:6]


def next_task_id() -> str:
    stamp = datetime.now(CST).strftime("%Y%m%d")
    for index in range(1, 1000):
        candidate = f"t{stamp}-{index:03d}"
        if not store().task_exists(candidate):
            return candidate
    return f"t{stamp}-{uuid.uuid4().hex[:4]}"


# --------------------------------------------------------------------- 业务
def handle_parse(payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    text = str(payload.get("text") or "")[:20000]

    started = time.perf_counter()
    result = notice_parser.parse_notice(text)
    elapsed = (time.perf_counter() - started) * 1000

    deadline = result.get("deadline") or {}
    _tel.event(
        "parse_notice",
        dur_ms=elapsed,
        ok=bool(result.get("ok")),
        error=None if result.get("ok") else result.get("error"),
        chars=len(text),
        items=len(result.get("materials") or []),
        deadline=bool(deadline),
        deadline_conf=deadline.get("confidence", 0),
        materials=len(result.get("materials") or []),
        located=bool(result.get("location")),
        contact=bool(result.get("contacts")),
        tags=len(result.get("tags") or []),
        mode=payload.get("mode", "web"),
        source="web",
        uid=user_tag(user),
        role=user.get("role", "student"),
    )

    if result.get("ok") and payload.get("save"):
        task_id = next_task_id()
        note_path = NOTE_DIR / f"{task_id}.txt"
        note_path.write_text(text, encoding="utf-8")
        store().add_task({
            "id": task_id,
            "user_id": int(user["id"]),
            "title": result["title"],
            "deadline": (result.get("deadline") or {}).get("iso", ""),
            "deadline_conf": (result.get("deadline") or {}).get("confidence", 0),
            "urgency": result.get("urgency", "none"),
            "location": result.get("location", ""),
            "materials": result.get("materials", []),
            "tags": result.get("tags", []),
            "created_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M"),
            "note_file": f"data/notes/{task_id}.txt",
        })
        result["task_id"] = task_id

    return result


def handle_inventory(payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    result = inventory.check_inventory(
        str(payload.get("lent") or ""),
        str(payload.get("returned") or ""),
    )
    summary = result.get("summary") or {}
    _tel.event(
        "check_inventory",
        dur_ms=(time.perf_counter() - started) * 1000,
        ok=bool(result.get("ok")),
        error=None if result.get("ok") else result.get("error"),
        rows=summary.get("pairs", 0),
        diff_rows=summary.get("qty_outstanding", 0),
        matched=summary.get("qty_returned", 0),
        unmatched=summary.get("people_overdue", 0),
        source="web",
        uid=user_tag(user),
    )
    return result


def handle_ics(user: Dict[str, Any]) -> str:
    """把当前用户未完成的待办导出为日历，截止前 2 小时提醒。"""
    tasks = [t for t in store().list_tasks(int(user["id"])) if not t.get("done") and t.get("deadline")]
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Campus Notice Radar//CN",
        "CALSCALE:GREGORIAN",
    ]
    for task in tasks:
        try:
            due = datetime.strptime(task["deadline"], "%Y-%m-%d %H:%M")
        except (ValueError, KeyError):
            continue
        stamp = datetime.now(CST).strftime("%Y%m%dT%H%M%S")
        lines += [
            "BEGIN:VEVENT",
            f"UID:{task['id']}@campus-radar",
            f"DTSTAMP:{stamp}Z",
            f"DTSTART:{due.strftime('%Y%m%dT%H%M%S')}",
            f"DTEND:{(due + timedelta(minutes=30)).strftime('%Y%m%dT%H%M%S')}",
            f"SUMMARY:{_ics_escape(task['title'])}",
            f"DESCRIPTION:{_ics_escape(task.get('location', '') or '见通知原文')}",
            "BEGIN:VALARM",
            "TRIGGER:-PT2H",
            "ACTION:DISPLAY",
            f"DESCRIPTION:{_ics_escape(task['title'])}",
            "END:VALARM",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)


def _ics_escape(text: str) -> str:
    return (text or "").replace("\\", "\\\\").replace(",", "\\,").replace(";", "\\;").replace("\n", "\\n")


def handle_feedback(payload: Dict[str, Any], user: Dict[str, Any]) -> Dict[str, Any]:
    score = payload.get("score")
    try:
        score = max(1, min(5, int(score)))
    except (TypeError, ValueError):
        score = 0
    record = {
        "user_id": int(user["id"]),
        "role": str(payload.get("role") or "其他")[:20],
        "score": score,
        "useful": [str(x)[:12] for x in (payload.get("useful") or [])][:5],
        "comment": str(payload.get("comment") or "")[:300],
        "would_use": bool(payload.get("would_use")),
        "created_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M"),
    }
    serialized = json.dumps(record, ensure_ascii=False)

    persisted = True
    try:
        store().add_feedback(record)
        # 同时留一份 JSONL，便于导出报告；这一步失败不影响主流程
        with _io_lock, open(FEEDBACK_FILE, "a", encoding="utf-8") as fh:
            fh.write(serialized + "\n")
    except Exception:  # noqa: BLE001
        persisted = False

    _tel.event(
        "submit_feedback", ok=True, score=score, role=record["role"],
        source="web", uid=user_tag(user), degraded=not persisted,
    )
    return {
        "ok": True,
        "persisted": persisted,
        "saved": record["created_at"],
        "count": store().count_feedback() if persisted else 0,
        "line": serialized,
    }


def handle_my_stats(user: Dict[str, Any]) -> Dict[str, Any]:
    tasks = store().list_tasks(int(user["id"]))
    open_tasks = [t for t in tasks if not t.get("done")]
    dated = sorted([t for t in open_tasks if t.get("deadline")], key=lambda t: t["deadline"])
    return {
        "ok": True,
        "tasks": len(tasks),
        "open_tasks": len(open_tasks),
        "my_feedback": len(store().list_feedback(int(user["id"]))),
        "nearest_deadline": dated[0]["deadline"] if dated else "",
        "student_id": user["student_id"],
        "role": user["role"],
    }


def handle_admin_overview() -> Dict[str, Any]:
    data = store().overview()
    days = [summarize_records(_tel.read_day(d)) for d in _tel.available_dates()[-7:]]
    data["telemetry"] = {
        "days": len(days),
        "events": sum(d["events"] for d in days),
        "errors": sum(d["errors"] for d in days),
        "daily": days,
    }
    return {"ok": True, **data}


# --------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "CampusRadar/" + __version__

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        return

    # ---------------------------------------------------------- 响应工具
    def _send(self, code: int, body: bytes, content_type: str, extra: Optional[dict] = None) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, code: int = 200, extra: Optional[dict] = None) -> None:
        self._send(code, json.dumps(data, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8", extra)

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("body_too_large")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("invalid_json")

    # ---------------------------------------------------------- 会话
    def _cookies(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for part in (self.headers.get("Cookie") or "").split(";"):
            if "=" in part:
                key, value = part.split("=", 1)
                out[key.strip()] = value.strip()
        return out

    def _current_user(self) -> Optional[Dict[str, Any]]:
        token = self._cookies().get("sid") or ""
        return auth.resolve_session(store(), token) if token else None

    def _cookie_header(self, token: str) -> str:
        attrs = "sid=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"
        if token:
            attrs = f"sid={token}; Path=/; HttpOnly; SameSite=Lax; Max-Age={auth.SESSION_DAYS * 86400}"
            if IN_CLOUD:
                attrs += "; Secure"
        return attrs

    def _require_user(self) -> Optional[Dict[str, Any]]:
        user = self._current_user()
        if not user:
            self._json({"ok": False, "error": "unauthorized", "message": "请先登录"}, 401)
            return None
        return user

    def _require_admin(self) -> Optional[Dict[str, Any]]:
        user = self._require_user()
        if not user:
            return None
        if user.get("role") != "admin":
            self._json({"ok": False, "error": "forbidden", "message": "需要管理员权限"}, 403)
            return None
        return user

    # ---------------------------------------------------------- 页面
    def _serve_asset(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._json({"ok": False, "error": "not_found"}, 404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    def _serve_page(self, page: str, js_name: str) -> None:
        """返回页面。云端模式把 CSS/JS 内联，避免静态资源被网关拦成 403。"""
        html = (WEB_DIR / page).read_text(encoding="utf-8")
        if IN_CLOUD:
            css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
            js = (WEB_DIR / js_name).read_text(encoding="utf-8")
            html = html.replace(
                '<link rel="stylesheet" href="/static/style.css">', f"<style>\n{css}\n</style>"
            )
            html = html.replace(
                f'<script src="/static/{js_name}"></script>', f"<script>\n{js}\n</script>"
            )
        self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")

    # ---------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            if route in ("/", "/index.html"):
                user = self._current_user()
                if user:
                    self._serve_page("index.html", "app.js")
                else:
                    self._serve_page("login.html", "login.js")
            elif route == "/admin":
                user = self._current_user()
                if not user:
                    self._json({"ok": False, "error": "unauthorized"}, 401)
                elif user.get("role") != "admin":
                    self._send(403, "需要管理员权限".encode("utf-8"), "text/plain; charset=utf-8")
                else:
                    self._serve_page("admin.html", "admin.js")
            elif route.startswith("/static/"):
                rel = unquote(route[len("/static/"):])
                target = (WEB_DIR / rel).resolve()
                if WEB_DIR.resolve() not in target.parents:
                    self._json({"ok": False, "error": "forbidden"}, 403)
                    return
                self._serve_asset(target)
            elif route == "/api/health":
                self._json({"ok": True, "version": __version__, "time": datetime.now(CST).isoformat()})
            elif route == "/api/me":
                user = self._require_user()
                if user:
                    self._json({"ok": True, "student_id": user["student_id"],
                                "role": user["role"], "uid": user_tag(user)})
            elif route == "/api/tasks":
                user = self._require_user()
                if user:
                    self._json({"ok": True, "tasks": store().list_tasks(int(user["id"]))})
            elif route == "/api/stats":
                user = self._require_user()
                if user:
                    self._json(handle_my_stats(user))
            elif route == "/api/export.ics":
                user = self._require_user()
                if user:
                    body = handle_ics(user).encode("utf-8")
                    self._send(200, body, "text/calendar; charset=utf-8",
                               {"Content-Disposition": "attachment; filename=campus-radar.ics"})
                    _tel.event("export_ics", ok=True, source="web", uid=user_tag(user))
            elif route == "/api/admin/overview":
                if self._require_admin():
                    self._json(handle_admin_overview())
            elif route == "/api/admin/users":
                if self._require_admin():
                    self._json({"ok": True, "users": store().list_users()})
            elif route == "/api/admin/tasks":
                if self._require_admin():
                    users = {u["id"]: u["student_id"] for u in store().list_users()}
                    tasks = store().list_tasks(None)
                    for task in tasks:
                        task["student_id"] = users.get(task["user_id"], "?")
                    self._json({"ok": True, "tasks": tasks})
            elif route == "/api/admin/feedback":
                if self._require_admin():
                    self._json({"ok": True, "feedback": store().list_feedback(None)})
            else:
                self._json({"ok": False, "error": "not_found"}, 404)
        except Exception as exc:  # noqa: BLE001
            _tel.event("http_error", ok=False, error=f"{type(exc).__name__}: {exc}", route=route)
            self._json({"ok": False, "error": "server_error"}, 500)

    # ---------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            payload = self._read_json()
        except ValueError as exc:
            self._json({"ok": False, "error": str(exc)}, 400)
            return

        try:
            # ---------------- 公开接口 ----------------
            if route == "/api/register":
                sid = str(payload.get("student_id") or "")
                result = auth.register(store(), sid, str(payload.get("password") or ""))
                _tel.event("register", ok=result["ok"], error=result.get("error"),
                           uid=hashlib.sha256(sid.encode()).hexdigest()[:6])
                self._json(result, 200 if result["ok"] else 400)
                return

            if route == "/api/login":
                sid = str(payload.get("student_id") or "")
                result = auth.login(store(), sid, str(payload.get("password") or ""))
                _tel.event("login", ok=result["ok"], error=result.get("error"),
                           uid=hashlib.sha256(sid.encode()).hexdigest()[:6],
                           role=result.get("role", ""))
                if result["ok"]:
                    self._json({"ok": True, "role": result["role"]},
                               extra={"Set-Cookie": self._cookie_header(result["token"])})
                else:
                    self._json(result, 401)
                return

            if route == "/api/logout":
                auth.logout(store(), self._cookies().get("sid"))
                self._json({"ok": True}, extra={"Set-Cookie": self._cookie_header("")})
                return

            # ---------------- 需要登录 ----------------
            if route == "/api/parse":
                user = self._require_user()
                if user:
                    self._json(handle_parse(payload, user))
            elif route == "/api/inventory":
                user = self._require_user()
                if user:
                    self._json(handle_inventory(payload, user))
            elif route == "/api/feedback":
                user = self._require_user()
                if user:
                    self._json(handle_feedback(payload, user))
            elif route == "/api/tasks/complete":
                user = self._require_user()
                if user:
                    ok = store().set_task_done(
                        str(payload.get("id") or ""), int(user["id"]),
                        bool(payload.get("done", True)),
                        datetime.now(CST).strftime("%Y-%m-%dT%H:%M"))
                    _tel.event("complete_task", ok=ok, source="web", uid=user_tag(user))
                    self._json({"ok": ok, "tasks": store().list_tasks(int(user["id"]))})
            elif route == "/api/tasks/delete":
                user = self._require_user()
                if user:
                    ok = store().delete_task(str(payload.get("id") or ""), int(user["id"]))
                    _tel.event("delete_task", ok=ok, source="web", uid=user_tag(user))
                    self._json({"ok": ok, "tasks": store().list_tasks(int(user["id"]))})
            elif route == "/api/export":
                user = self._require_user()
                if user:
                    rows = payload.get("rows") or []
                    body = inventory.rows_to_csv(rows).encode("utf-8")
                    self._send(200, body, "text/csv; charset=utf-8",
                               {"Content-Disposition": "attachment; filename=inventory-check.csv"})
                    _tel.event("export_inventory", ok=True, rows=len(rows),
                               source="web", uid=user_tag(user))
            else:
                self._json({"ok": False, "error": "not_found"}, 404)
        except Exception as exc:  # noqa: BLE001
            _tel.event("api_error", ok=False, error=f"{type(exc).__name__}: {exc}", route=route)
            self._json({"ok": False, "error": "server_error", "detail": str(exc)[:120]}, 500)


# --------------------------------------------------------------------- 启动
def resolve_bind() -> tuple:
    env_port = (os.environ.get("PORT") or "").strip()
    if env_port.isdigit():
        return "0.0.0.0", int(env_port), True
    return "127.0.0.1", 8765, False


def pick_port(preferred: int, host: str = "127.0.0.1") -> int:
    for port in [preferred] + list(range(preferred + 1, preferred + 20)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError("找不到可用端口，请用 --port 指定")


def main() -> None:
    host, default_port, in_cloud = resolve_bind()

    parser = argparse.ArgumentParser(description="校园通知雷达 · 本地服务")
    parser.add_argument("--port", type=int, default=default_port)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    _ensure_dirs()
    store()  # 建表

    port = args.port if in_cloud else pick_port(args.port, host)
    httpd = ThreadingHTTPServer((host, port), Handler)

    _tel.event("app_start", ok=True, version=__version__,
               route="cloud" if in_cloud else "boot")

    if in_cloud:
        print(f"校园通知雷达 v{__version__} 已启动，监听 0.0.0.0:{port}")
    else:
        url = f"http://127.0.0.1:{port}/"
        print(f"校园通知雷达 v{__version__} 已启动：{url}")
        print(f"数据库：{DB_FILE}")
        if not args.no_browser:
            threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
    finally:
        _tel.event("app_stop", ok=True, route="shutdown")
        httpd.server_close()


if __name__ == "__main__":
    main()
