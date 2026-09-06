"""迁移060：为统计日志增加金币变动金额。"""

import sqlite3
import json

from astrbot.api import logger


def up(cursor: sqlite3.Cursor):
    """为统计日志增加可聚合的金币金额字段和索引。"""
    cursor.execute("PRAGMA table_info(statistics_logs)")
    columns = {row[1] for row in cursor.fetchall()}
    if "coin_amount" not in columns:
        cursor.execute(
            "ALTER TABLE statistics_logs ADD COLUMN coin_amount INTEGER NOT NULL DEFAULT 0"
        )

    # 兼容迁移前已经记录的社交统计：这些日志原本把鱼价放在 details 中。
    cursor.execute(
        "SELECT id, action_type, details FROM statistics_logs "
        "WHERE coin_amount = 0 AND details IS NOT NULL "
        "AND action_type IN ('steal', 'electric_fish')"
    )
    for row in cursor.fetchall():
        try:
            details = json.loads(row[2] or "{}")
            value = details.get("value") if row[1] == "steal" else details.get("total_value")
            value = int(value or 0)
        except (TypeError, ValueError, json.JSONDecodeError):
            value = 0
        if value > 0:
            cursor.execute(
                "UPDATE statistics_logs SET coin_amount = ? WHERE id = ?",
                (value, row[0]),
            )

    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_statistics_logs_coin_time
        ON statistics_logs(coin_amount, created_at)
        """
    )
    logger.info("[迁移060] 统计日志金币金额字段创建成功")


def down(cursor: sqlite3.Cursor):
    """SQLite 不支持安全地直接删除列，回滚时保留字段。"""
    cursor.execute("DROP INDEX IF EXISTS idx_statistics_logs_coin_time")
