"""迁移055：扩展 AI 策略状态与决策流水字段。

旧版本已经创建了 ai_player_state 和 ai_decision_snapshots；本迁移只补充
可选列，不改写历史记录，保证旧数据库可以平滑升级。
"""

import sqlite3

from astrbot.api import logger


def _add_columns(cursor: sqlite3.Cursor, table: str, columns: dict) -> None:
    cursor.execute(f"PRAGMA table_info({table})")
    existing = {row[1] for row in cursor.fetchall()}
    for name, definition in columns.items():
        if name in existing:
            continue
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def up(cursor: sqlite3.Cursor):
    _add_columns(
        cursor,
        "ai_player_state",
        {
            "last_item_use_ts": "REAL NOT NULL DEFAULT 0",
            "last_social_item_ts": "REAL NOT NULL DEFAULT 0",
            "last_fishing_item_ts": "REAL NOT NULL DEFAULT 0",
        },
    )
    _add_columns(
        cursor,
        "ai_decision_snapshots",
        {
            "decision_reason": "TEXT",
            "estimated_value": "REAL",
            "coins_before": "INTEGER",
            "coins_after": "INTEGER",
            "item_id": "INTEGER",
            "gacha_pool_id": "INTEGER",
            "item_delta_json": "TEXT",
            "result_json": "TEXT",
            "strategy_version": "TEXT NOT NULL DEFAULT 'v2'",
        },
    )
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ai_snapshots_strategy_action "
        "ON ai_decision_snapshots(action_type, strategy_version, created_at)"
    )
    logger.info("[迁移055] AI 策略状态与决策流水字段已补充")


def down(cursor: sqlite3.Cursor):
    logger.warning("[迁移055-回滚] SQLite 不安全支持删除新增列，保留字段")
