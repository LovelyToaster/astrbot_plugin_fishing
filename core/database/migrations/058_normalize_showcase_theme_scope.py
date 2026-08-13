"""迁移058：将旧的装备级展示主题统一迁移为位置级设置。"""

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

    # 如果某个数据库已经执行过旧版057，则把已有的装备级颜色提升为位置级颜色。
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
    # 保留设置表，避免回滚时丢失用户自定义颜色。
    pass
