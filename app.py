#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""校园事务小工具 —— 本地服务入口。

    python app.py                # 启动，自动打开浏览器
    python app.py --port 9000    # 指定端口
    python app.py --no-browser   # 不自动打开浏览器

只用 Python 标准库，不需要 pip install 任何东西。服务只监听 127.0.0.1，
通知原文、器材表格、反馈内容全部留在本机，不出网。
"""

from __future__ import annotations

import argparse
import json
import mimetypes
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

from core import __version__  # noqa: E402
from core import inventory, notice_parser, timeparse  # noqa: E402
from core.telemetry import CST, Telemetry, summarize_records  # noqa: E402

WEB_DIR = BASE_DIR / "web"
DATA_DIR = BASE_DIR / "data"
TASK_FILE = DATA_DIR / "tasks.json"
NOTE_DIR = DATA_DIR / "notes"
FEEDBACK_FILE = BASE_DIR / "feedback" / "responses.jsonl"

MAX_BODY = 512 * 1024      # 单次请求体上限，防止误粘贴超大文件把内存打满

_io_lock = threading.Lock()
_tel = Telemetry()


# --------------------------------------------------------------------- 存储
def _ensure_dirs() -> None:
    for path in (DATA_DIR, NOTE_DIR, FEEDBACK_FILE.parent):
        path.mkdir(parents=True, exist_ok=True)


def load_tasks() -> list:
    with _io_lock:
        if not TASK_FILE.exists():
            return []
        try:
            return json.loads(TASK_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            # 文件损坏时不要毁掉用户数据，改名备份后重新开始
            backup = TASK_FILE.with_suffix(".broken.json")
            try:
                TASK_FILE.replace(backup)
            except OSError:
                pass
            return []


def save_tasks(tasks: list) -> None:
    with _io_lock:
        tmp = TASK_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(TASK_FILE)


def next_task_id(tasks: list) -> str:
    stamp = datetime.now(CST).strftime("%Y%m%d")
    used = {t.get("id", "") for t in tasks}
    for index in range(1, 1000):
        candidate = f"t{stamp}-{index:03d}"
        if candidate not in used:
            return candidate
    return f"t{stamp}-{uuid.uuid4().hex[:4]}"


# --------------------------------------------------------------------- 业务
def handle_parse(payload: Dict[str, Any]) -> Dict[str, Any]:
    text = str(payload.get("text") or "")
    if len(text) > 20000:
        text = text[:20000]

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
    )

    if result.get("ok") and payload.get("save"):
        tasks = load_tasks()
        task = {
            "id": next_task_id(tasks),
            "title": result["title"],
            "deadline": (result.get("deadline") or {}).get("iso", ""),
            "deadline_conf": (result.get("deadline") or {}).get("confidence", 0),
            "urgency": result.get("urgency", "none"),
            "location": result.get("location", ""),
            "materials": result.get("materials", []),
            "tags": result.get("tags", []),
            "done": False,
            "created_at": datetime.now(CST).strftime("%Y-%m-%dT%H:%M"),
            "note_file": "",
        }
        # 原文单独落一个文件，tasks.json 保持轻量
        note_path = NOTE_DIR / f"{task['id']}.txt"
        note_path.write_text(text, encoding="utf-8")
        task["note_file"] = str(note_path.relative_to(BASE_DIR))
        tasks.append(task)
        save_tasks(tasks)
        result["task_id"] = task["id"]

    return result


def handle_inventory(payload: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    result = inventory.check_inventory(
        str(payload.get("lent") or ""),
        str(payload.get("returned") or ""),
    )
    elapsed = (time.perf_counter() - started) * 1000
    summary = result.get("summary") or {}
    _tel.event(
        "check_inventory",
        dur_ms=elapsed,
        ok=bool(result.get("ok")),
        error=None if result.get("ok") else result.get("error"),
        rows=summary.get("pairs", 0),
        diff_rows=summary.get("qty_outstanding", 0),
        matched=summary.get("qty_returned", 0),
        unmatched=summary.get("people_overdue", 0),
        source="web",
    )
    return result


def handle_stats() -> Dict[str, Any]:
    dates = _tel.available_dates()[-7:]
    days = []
    for date in dates:
        records = _tel.read_day(date)
        summary = summarize_records(records)
        days.append(summary)
    totals = {
        "events": sum(d["events"] for d in days),
        "errors": sum(d["errors"] for d in days),
        "days": len(days),
    }
    return {"days": days, "totals": totals, "log_dir": str(_tel.log_dir.relative_to(BASE_DIR))}


def handle_ics() -> str:
    """把未完成待办导出为日历文件，截止前 2 小时提醒。"""
    tasks = [t for t in load_tasks() if not t.get("done") and t.get("deadline")]
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


def handle_feedback(payload: Dict[str, Any]) -> Dict[str, Any]:
    score = payload.get("score")
    try:
        score = max(1, min(5, int(score)))
    except (TypeError, ValueError):
        score = 0
    record = {
        "ts": datetime.now(CST).strftime("%Y-%m-%dT%H:%M"),
        "role": str(payload.get("role") or "其他")[:20],
        "score": score,
        "useful": [str(x)[:12] for x in (payload.get("useful") or [])][:5],
        "comment": str(payload.get("comment") or "")[:300],
        "would_use": bool(payload.get("would_use")),
    }
    _ensure_dirs()
    with _io_lock:
        with open(FEEDBACK_FILE, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    _tel.event("submit_feedback", ok=True, score=score, role=record["role"], source="web")
    return {"ok": True, "saved": record["ts"], "count": count_feedback()}


def count_feedback() -> int:
    if not FEEDBACK_FILE.exists():
        return 0
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


# --------------------------------------------------------------------- HTTP
class Handler(BaseHTTPRequestHandler):
    server_version = "CampusRadar/" + __version__

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A003
        # 默认实现会往 stderr 打每一条请求；这里静音，改用 telemetry
        return

    # ----------------------------------------------------------- 响应工具
    def _send(self, code: int, body: bytes, content_type: str) -> None:
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, data: Any, code: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self._send(code, body, "application/json; charset=utf-8")

    def _read_json(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ValueError("body_too_large")
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("invalid_json")

    def _serve_file(self, path: Path) -> None:
        if not path.exists() or not path.is_file():
            self._json({"ok": False, "error": "not_found"}, 404)
            return
        ctype = mimetypes.guess_type(str(path))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype in ("application/javascript", "application/json"):
            ctype += "; charset=utf-8"
        self._send(200, path.read_bytes(), ctype)

    # ----------------------------------------------------------- GET
    def do_GET(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            if route in ("/", "/index.html"):
                self._serve_file(WEB_DIR / "index.html")
            elif route.startswith("/static/"):
                rel = unquote(route[len("/static/"):])
                target = (WEB_DIR / rel).resolve()
                if WEB_DIR.resolve() not in target.parents:
                    self._json({"ok": False, "error": "forbidden"}, 403)
                    return
                self._serve_file(target)
            elif route == "/api/health":
                self._json({"ok": True, "version": __version__, "time": datetime.now(CST).isoformat()})
            elif route == "/api/tasks":
                self._json({"ok": True, "tasks": load_tasks()})
            elif route == "/api/stats":
                self._json({"ok": True, **handle_stats()})
            elif route == "/api/export.ics":
                body = handle_ics().encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/calendar; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=campus-radar.ics")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                _tel.event("export_ics", ok=True, source="web")
            elif route == "/api/feedback/count":
                self._json({"ok": True, "count": count_feedback()})
            else:
                self._json({"ok": False, "error": "not_found"}, 404)
        except Exception as exc:  # noqa: BLE001 - 兜底，避免单个请求打断服务
            _tel.event("http_error", ok=False, error=f"{type(exc).__name__}: {exc}", route=route)
            self._json({"ok": False, "error": "server_error"}, 500)

    # ----------------------------------------------------------- POST
    def do_POST(self) -> None:  # noqa: N802
        route = urlparse(self.path).path
        try:
            payload = self._read_json()
        except ValueError as exc:
            _tel.event("bad_request", ok=False, error=str(exc), route=route)
            self._json({"ok": False, "error": str(exc)}, 400)
            return

        try:
            if route == "/api/parse":
                self._json(handle_parse(payload))
            elif route == "/api/inventory":
                self._json(handle_inventory(payload))
            elif route == "/api/feedback":
                self._json(handle_feedback(payload))
            elif route == "/api/tasks/complete":
                tasks = load_tasks()
                target = str(payload.get("id") or "")
                for task in tasks:
                    if task.get("id") == target:
                        task["done"] = bool(payload.get("done", True))
                        task["done_at"] = datetime.now(CST).strftime("%Y-%m-%dT%H:%M")
                        break
                save_tasks(tasks)
                _tel.event("complete_task", ok=True, task_id=target[:20], source="web")
                self._json({"ok": True, "tasks": tasks})
            elif route == "/api/tasks/delete":
                tasks = [t for t in load_tasks() if t.get("id") != str(payload.get("id") or "")]
                save_tasks(tasks)
                _tel.event("delete_task", ok=True, source="web")
                self._json({"ok": True, "tasks": tasks})
            elif route == "/api/export":
                rows = payload.get("rows") or []
                csv_text = inventory.rows_to_csv(rows)
                body = csv_text.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/csv; charset=utf-8")
                self.send_header("Content-Disposition", "attachment; filename=inventory-check.csv")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                _tel.event("export_inventory", ok=True, rows=len(rows), source="web")
            else:
                self._json({"ok": False, "error": "not_found"}, 404)
        except Exception as exc:  # noqa: BLE001
            _tel.event("api_error", ok=False, error=f"{type(exc).__name__}: {exc}", route=route)
            self._json({"ok": False, "error": "server_error", "detail": str(exc)[:120]}, 500)


# --------------------------------------------------------------------- 启动
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
    parser = argparse.ArgumentParser(description="校园通知雷达 · 本地服务")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    _ensure_dirs()
    port = pick_port(args.port)
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"

    _tel.event("app_start", ok=True, version=__version__, route="boot")
    print(f"校园通知雷达 v{__version__} 已启动：{url}")
    print("日志目录：process_logs/   按 Ctrl+C 停止")

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
