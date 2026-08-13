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
        self._write_lock = threading.RLock()

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
        details: dict,
        *,
        aggregate_key: Optional[str] = None,
        aggregate_window_seconds: int = 0,
        merge_fields: Optional[List[str]] = None,
    ) -> int:
        """写入通知；指定聚合键时合并近期相同的未读通知。"""
        payload = dict(details or {})
        if aggregate_key:
            payload["_aggregation_key"] = aggregate_key
            payload["_aggregation_count"] = int(payload.get("_aggregation_count", 1) or 1)

        with self._write_lock:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                now = datetime.now()
                now_text = now.strftime(DATETIME_FORMAT)

                if aggregate_key and aggregate_window_seconds > 0:
                    row = cursor.execute(
                        """
                        SELECT id, details, created_at
                        FROM notifications
                        WHERE recipient_id = ?
                          AND sender_nickname = ?
                          AND type = ?
                          AND is_read = 0
                        ORDER BY id DESC
                        LIMIT 1
                        """,
                        (recipient_id, sender_nickname, noti_type),
                    ).fetchone()
                    if row:
                        old_details = self._decode_details(row["details"])
                        old_key = old_details.get("_aggregation_key")
                        age = self._notification_age_seconds(row["created_at"], now)
                        if old_key == aggregate_key and age <= aggregate_window_seconds:
                            merged = dict(old_details)
                            merged["_aggregation_count"] = int(
                                old_details.get("_aggregation_count", 1) or 1
                            ) + int(payload.get("_aggregation_count", 1) or 1)
                            for field in merge_fields or []:
                                old_value = old_details.get(field)
                                new_value = payload.get(field)
                                if isinstance(old_value, (int, float)) and isinstance(
                                    new_value, (int, float)
                                ):
                                    merged[field] = old_value + new_value
                                elif isinstance(old_value, list) and isinstance(
                                    new_value, list
                                ):
                                    merged[field] = old_value + new_value
                            cursor.execute(
                                """
                                UPDATE notifications
                                SET details = ?, created_at = ?
                                WHERE id = ?
                                """,
                                (
                                    json.dumps(merged, ensure_ascii=False),
                                    now_text,
                                    row["id"],
                                ),
                            )
                            conn.commit()
                            return int(row["id"])

                cursor.execute(
                    """
                    INSERT INTO notifications (recipient_id, sender_nickname, type, details, is_read, created_at)
                    VALUES (?, ?, ?, ?, 0, ?)
                    """,
                    (
                        recipient_id,
                        sender_nickname,
                        noti_type,
                        json.dumps(payload, ensure_ascii=False),
                        now_text,
                    ),
                )
                conn.commit()
                return cursor.lastrowid

    @staticmethod
    def _decode_details(raw_details: Optional[str]) -> Dict[str, Any]:
        if not raw_details:
            return {}
        try:
            value = json.loads(raw_details)
            return value if isinstance(value, dict) else {}
        except (TypeError, ValueError):
            return {}

    @staticmethod
    def _notification_age_seconds(created_at: Any, now: datetime) -> float:
        try:
            created = created_at
            if isinstance(created, datetime):
                created_dt = created
            else:
                created_dt = datetime.strptime(str(created)[:19], DATETIME_FORMAT)
            return max(0.0, (now - created_dt).total_seconds())
        except (TypeError, ValueError, OverflowError):
            return float("inf")

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
            "details": self._decode_details(row["details"]),
            "is_read": bool(row["is_read"]),
            "created_at": row["created_at"],
        }
