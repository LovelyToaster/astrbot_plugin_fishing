"""迁移057：为每个展示柜位置增加独立的预设主题。"""

import sqlite3


def _columns(cursor: sqlite3.Cursor, table: str):
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def up(cursor: sqlite3.Cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_showcase_slot_settings (
            user_id TEXT NOT NULL,
            slot_index INTEGER NOT NULL,
            theme TEXT NOT NULL DEFAULT 'ocean',
            PRIMARY KEY (user_id, slot_index)
        )
        """
    )

    # 兼容迁移脚本尚未发布前可能已经生成的 user_showcase.theme 列。
    # 正式数据源是位置设置表，旧列保留不影响运行。
    if "theme" in _columns(cursor, "user_showcase"):
        cursor.execute(
            """
            INSERT OR REPLACE INTO user_showcase_slot_settings (user_id, slot_index, theme)
            SELECT user_id, slot_index,
                   CASE WHEN theme IS NULL OR theme = '' THEN 'ocean' ELSE theme END
            FROM user_showcase
            """
        )
    else:
        cursor.execute(
            """
            INSERT OR IGNORE INTO user_showcase_slot_settings (user_id, slot_index, theme)
            SELECT user_id, slot_index, 'ocean'
            FROM user_showcase
            """
        )


def down(cursor: sqlite3.Cursor):
    cursor.execute("DROP TABLE IF EXISTS user_showcase_slot_settings")
