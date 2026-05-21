import sqlite3
import threading
import json
from typing import List, Dict, Any, Optional
from datetime import datetime

from astrbot.api import logger

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class SqliteNotificationRepository:
    """通知数据仓储的SQLite实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.connection = conn
        return conn

    def add_notification(
        self,
        recipient_id: str,
        sender_nickname: str,
        noti_type: str,
        details: dict
    ) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO notifications (recipient_id, sender_nickname, type, details, is_read, created_at)
                VALUES (?, ?, ?, ?, 0, ?)
                """,
                (
                    recipient_id,
                    sender_nickname,
                    noti_type,
                    json.dumps(details, ensure_ascii=False),
                    datetime.now().strftime(DATETIME_FORMAT),
                ),
            )
            conn.commit()
            return cursor.lastrowid

    def get_unread_count(self, recipient_id: str) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT COUNT(*) FROM notifications WHERE recipient_id = ? AND is_read = 0",
                (recipient_id,),
            )
            row = cursor.fetchone()
            return row[0] if row else 0

    def get_unread_notifications(self, recipient_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, recipient_id, sender_nickname, type, details, is_read, created_at
                FROM notifications
                WHERE recipient_id = ? AND is_read = 0
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (recipient_id, limit),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def get_all_notifications(self, recipient_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, recipient_id, sender_nickname, type, details, is_read, created_at
                FROM notifications
                WHERE recipient_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (recipient_id, limit),
            )
            return [self._row_to_dict(row) for row in cursor.fetchall()]

    def mark_as_read(self, notification_id: int):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE notifications SET is_read = 1 WHERE id = ?",
                (notification_id,),
            )
            conn.commit()

    def mark_all_as_read(self, recipient_id: str):
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE notifications SET is_read = 1 WHERE recipient_id = ? AND is_read = 0",
                (recipient_id,),
            )
            conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "id": row["id"],
            "recipient_id": row["recipient_id"],
            "sender_nickname": row["sender_nickname"],
            "type": row["type"],
            "details": json.loads(row["details"]) if row["details"] else {},
            "is_read": bool(row["is_read"]),
            "created_at": row["created_at"],
        }
