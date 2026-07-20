"""
AI 玩家状态仓储的 SQLite 实现 (SqliteAIPlayerStateRepository)

提供 ai_player_state 表的 get_or_create 和 update_field 操作，
用于持久化 AI 玩家的节流/惩罚时间戳，防止重启后滥用。
"""

import sqlite3
import threading
from typing import Optional

from astrbot.api import logger

from ..domain.models import AIPlayerState
from .abstract_repository import AbstractAIPlayerStateRepository


class SqliteAIPlayerStateRepository(AbstractAIPlayerStateRepository):
    """AI 玩家状态数据仓储的 SQLite 实现"""

    # 白名单：允许 update_field 更新的字段名（防 SQL 注入）
    _ALLOWED_FIELDS = {
        "last_sell_fish_ts",
        "last_sell_equipment_ts",
        "last_paid_gacha_ts",
        "last_free_gacha_date",
    }

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

    def get_or_create(self, user_id: str) -> AIPlayerState:
        """
        获取 AI 用户的状态行，若不存在则插入默认行并返回。

        Args:
            user_id: AI 用户 ID

        Returns:
            AIPlayerState 对象
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM ai_player_state WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()

            if row:
                return AIPlayerState(
                    user_id=row["user_id"],
                    last_sell_fish_ts=row["last_sell_fish_ts"],
                    last_sell_equipment_ts=row["last_sell_equipment_ts"],
                    last_paid_gacha_ts=row["last_paid_gacha_ts"],
                    last_free_gacha_date=row["last_free_gacha_date"],
                )

            # 不存在则插入默认行
            cursor.execute(
                "INSERT INTO ai_player_state (user_id) VALUES (?)",
                (user_id,)
            )
            conn.commit()

            # 重新查询返回完整对象
            cursor.execute(
                "SELECT * FROM ai_player_state WHERE user_id = ?",
                (user_id,)
            )
            row = cursor.fetchone()
            return AIPlayerState(
                user_id=row["user_id"],
                last_sell_fish_ts=row["last_sell_fish_ts"],
                last_sell_equipment_ts=row["last_sell_equipment_ts"],
                last_paid_gacha_ts=row["last_paid_gacha_ts"],
                last_free_gacha_date=row["last_free_gacha_date"],
            )

    def update_field(self, user_id: str, field: str, value) -> None:
        """
        更新 AI 用户状态的单个字段。

        Args:
            user_id: AI 用户 ID
            field: 字段名（必须在 _ALLOWED_FIELDS 白名单中）
            value: 字段值

        Raises:
            ValueError: 如果 field 不在白名单中
        """
        if field not in self._ALLOWED_FIELDS:
            raise ValueError(
                f"不允许的字段名 '{field}'，允许的字段: {self._ALLOWED_FIELDS}"
            )

        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 先确保行存在
            cursor.execute(
                "INSERT OR IGNORE INTO ai_player_state (user_id) VALUES (?)",
                (user_id,)
            )
            # 再更新字段
            sql = f"UPDATE ai_player_state SET {field} = ?, updated_at = CURRENT_TIMESTAMP WHERE user_id = ?"
            cursor.execute(sql, (value, user_id))
            conn.commit()
