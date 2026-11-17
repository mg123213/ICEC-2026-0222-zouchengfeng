#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""数据存储层（SQLite）。

为什么从 JSON 换成 SQLite
------------------------
v0.5 之前待办和反馈都是 JSON/JSONL 文件，单用户够用。但加上登录之后变成多用户：
待办要按人隔离、管理员要跨用户统计、还要存会话。文件方案要么每次全量读写，
要么自己写锁，很容易出现"两个人同时保存，一个人的记录被覆盖"。

SQLite 是 Python 标准库自带的，仍然是零第三方依赖，但给了事务和并发控制。

表
--
users      账号（学号唯一，密码只存 PBKDF2 哈希 + 盐）
sessions   登录会话（token 主键，带过期时间）
tasks      待办（归属 user_id，素材存 JSON 字符串）
feedback   使用反馈（归属 user_id）
"""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id    TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'student',
    created_at    TEXT NOT NULL,
    last_login    TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    INTEGER NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS tasks (
    id           TEXT PRIMARY KEY,
    user_id      INTEGER NOT NULL,
    title        TEXT NOT NULL,
    deadline     TEXT,
    deadline_conf REAL DEFAULT 0,
    urgency      TEXT,
    location     TEXT,
    materials    TEXT,
    tags         TEXT,
    done         INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT,
    done_at      TEXT,
    note_file    TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS feedback (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id    INTEGER NOT NULL,
    role       TEXT,
    score      INTEGER DEFAULT 0,
    useful     TEXT,
    comment    TEXT,
    would_use  INTEGER DEFAULT 0,
    created_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_tasks_user ON tasks(user_id);
CREATE INDEX IF NOT EXISTS idx_feedback_user ON feedback(user_id);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token);
"""


class Store:
    """SQLite 的薄封装。每次操作开一个短连接，避免跨线程共享连接对象。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.executescript(_SCHEMA)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ------------------------------------------------------------------ 用户
    def create_user(self, student_id: str, password_hash: str, salt: str,
                    role: str, created_at: str) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (student_id, password_hash, salt, role, created_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (student_id, password_hash, salt, role, created_at),
            )
            return int(cur.lastrowid or 0)

    def get_user_by_student_id(self, student_id: str) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE student_id = ?", (student_id,)
            ).fetchone()
        return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[Dict[str, Any]]:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None

    def touch_login(self, user_id: int, when: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("UPDATE users SET last_login = ? WHERE id = ?", (when, user_id))

    def list_users(self) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT u.id, u.student_id, u.role, u.created_at, u.last_login,"
                "  (SELECT COUNT(*) FROM tasks t WHERE t.user_id = u.id) AS task_count,"
                "  (SELECT COUNT(*) FROM tasks t WHERE t.user_id = u.id AND t.done = 0) AS open_count,"
                "  (SELECT COUNT(*) FROM feedback f WHERE f.user_id = u.id) AS feedback_count"
                " FROM users u ORDER BY u.created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------ 会话
    def create_session(self, token: str, user_id: int, created_at: str, expires_at: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
                (token, user_id, created_at, expires_at),
            )

    def get_session_user(self, token: str, now: str) -> Optional[Dict[str, Any]]:
        """token 有效则返回所属用户，过期或不存在返回 None。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
                " WHERE s.token = ? AND s.expires_at > ?",
                (token, now),
            ).fetchone()
        return dict(row) if row else None

    def delete_session(self, token: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE token = ?", (token,))

    def purge_expired_sessions(self, now: str) -> None:
        with self._lock, self._conn() as conn:
            conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))

    # ------------------------------------------------------------------ 待办
    def add_task(self, task: Dict[str, Any]) -> None:
        with self._lock, self._conn() as conn:
            conn.execute(
                "INSERT INTO tasks (id, user_id, title, deadline, deadline_conf, urgency,"
                " location, materials, tags, done, created_at, note_file)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    task["id"], task["user_id"], task["title"], task.get("deadline", ""),
                    task.get("deadline_conf", 0), task.get("urgency", ""),
                    task.get("location", ""),
                    json.dumps(task.get("materials", []), ensure_ascii=False),
                    json.dumps(task.get("tags", []), ensure_ascii=False),
                    0, task.get("created_at", ""), task.get("note_file", ""),
                ),
            )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> Dict[str, Any]:
        item = dict(row)
        item["materials"] = json.loads(item.get("materials") or "[]")
        item["tags"] = json.loads(item.get("tags") or "[]")
        item["done"] = bool(item.get("done"))
        return item

    def list_tasks(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if user_id is None:
                rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC").fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM tasks WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
                ).fetchall()
        return [self._row_to_task(r) for r in rows]

    def task_exists(self, task_id: str) -> bool:
        with self._conn() as conn:
            return conn.execute("SELECT 1 FROM tasks WHERE id = ?", (task_id,)).fetchone() is not None

    def set_task_done(self, task_id: str, user_id: int, done: bool, when: str) -> bool:
        """只允许操作自己的待办，返回是否命中。"""
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "UPDATE tasks SET done = ?, done_at = ? WHERE id = ? AND user_id = ?",
                (1 if done else 0, when, task_id, user_id),
            )
            return cur.rowcount > 0

    def delete_task(self, task_id: str, user_id: int) -> bool:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "DELETE FROM tasks WHERE id = ? AND user_id = ?", (task_id, user_id)
            )
            return cur.rowcount > 0

    def count_open_tasks(self, user_id: Optional[int] = None) -> int:
        with self._conn() as conn:
            if user_id is None:
                row = conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE done = 0").fetchone()
            else:
                row = conn.execute(
                    "SELECT COUNT(*) AS c FROM tasks WHERE done = 0 AND user_id = ?", (user_id,)
                ).fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------ 反馈
    def add_feedback(self, item: Dict[str, Any]) -> int:
        with self._lock, self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO feedback (user_id, role, score, useful, comment, would_use, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    item["user_id"], item.get("role", ""), item.get("score", 0),
                    json.dumps(item.get("useful", []), ensure_ascii=False),
                    item.get("comment", ""), 1 if item.get("would_use") else 0,
                    item.get("created_at", ""),
                ),
            )
            return int(cur.lastrowid or 0)

    def list_feedback(self, user_id: Optional[int] = None) -> List[Dict[str, Any]]:
        with self._conn() as conn:
            if user_id is None:
                rows = conn.execute(
                    "SELECT f.*, u.student_id FROM feedback f JOIN users u ON u.id = f.user_id"
                    " ORDER BY f.created_at DESC"
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT f.*, u.student_id FROM feedback f JOIN users u ON u.id = f.user_id"
                    " WHERE f.user_id = ? ORDER BY f.created_at DESC", (user_id,)
                ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["useful"] = json.loads(item.get("useful") or "[]")
            item["would_use"] = bool(item.get("would_use"))
            out.append(item)
        return out

    def count_feedback(self) -> int:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) AS c FROM feedback").fetchone()
        return int(row["c"]) if row else 0

    # ------------------------------------------------------------------ 统计
    def overview(self) -> Dict[str, Any]:
        """管理后台用的全局数字。"""
        with self._conn() as conn:
            users = conn.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
            student_users = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE role = 'student'"
            ).fetchone()["c"]
            tasks = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
            open_tasks = conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE done = 0").fetchone()["c"]
            with_deadline = conn.execute(
                "SELECT COUNT(*) AS c FROM tasks WHERE deadline != ''"
            ).fetchone()["c"]
            feedback = conn.execute("SELECT COUNT(*) AS c FROM feedback").fetchone()["c"]
            avg_score = conn.execute(
                "SELECT AVG(score) AS a FROM feedback WHERE score > 0"
            ).fetchone()["a"]
            active_7d = conn.execute(
                "SELECT COUNT(*) AS c FROM users WHERE last_login IS NOT NULL"
            ).fetchone()["c"]
        return {
            "users": int(users),
            "students": int(student_users),
            "tasks": int(tasks),
            "open_tasks": int(open_tasks),
            "tasks_with_deadline": int(with_deadline),
            "feedback": int(feedback),
            "avg_score": round(float(avg_score), 2) if avg_score else 0.0,
            "activated_users": int(active_7d),
        }
