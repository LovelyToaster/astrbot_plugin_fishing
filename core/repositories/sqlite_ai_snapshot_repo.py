"""
AI 决策快照仓储的 SQLite 实现 (SqliteAIDecisionSnapshotRepository)

提供 ai_decision_snapshots 表的 create 和 complete 操作，
用于记录 AI 每次决策的目标特征、预测概率与执行结果，
为离线训练脚本提供干净的训练数据。
"""

import sqlite3
import threading
from typing import Optional

from .abstract_repository import AbstractAIDecisionSnapshotRepository


class SqliteAIDecisionSnapshotRepository(AbstractAIDecisionSnapshotRepository):
    """AI 决策快照数据仓储的 SQLite 实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(
                self.db_path,
                detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES,
            )
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.connection = conn
        return conn

    def create(
        self,
        ai_user_id: str,
        action_type: str,
        target_user_id: Optional[str],
        features_json: str,
        predicted_prob: Optional[float],
    ) -> int:
        """
        创建决策快照，返回自增 id。

        Args:
            ai_user_id: AI 用户 ID
            action_type: 动作类型（'steal' / 'electric_fish' 等）
            target_user_id: 目标用户 ID（可选）
            features_json: 特征 JSON 字符串
            predicted_prob: 模型预测概率（可选）

        Returns:
            自增 id
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO ai_decision_snapshots
                    (ai_user_id, action_type, target_user_id, features_json, predicted_prob, executed)
                VALUES (?, ?, ?, ?, ?, 0)
                """,
                (ai_user_id, action_type, target_user_id, features_json, predicted_prob),
            )
            conn.commit()
            return int(cursor.lastrowid)

    def complete(
        self,
        snapshot_id: int,
        executed: int,
        success: Optional[int],
        fail_reason: Optional[str],
        reward_value: Optional[int],
    ) -> None:
        """
        回填决策执行结果。

        Args:
            snapshot_id: 快照 id
            executed: 是否执行（1/0）
            success: 执行成功（1/0/None）
            fail_reason: 失败原因简短描述
            reward_value: 收益价值
        """
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE ai_decision_snapshots
                SET executed = ?,
                    success = ?,
                    fail_reason = ?,
                    reward_value = ?,
                    completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (executed, success, fail_reason, reward_value, snapshot_id),
            )
            conn.commit()
