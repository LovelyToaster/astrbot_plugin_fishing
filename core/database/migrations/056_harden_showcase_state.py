"""迁移056：修复展示柜状态漂移并记录自动锁定前的状态。

展示柜同时维护关系表和装备实例标记。旧版本在部分删除、取出路径中可能只
更新其中一处；本迁移清理孤儿关系，并把实例标记重新同步到关系表。
"""

import sqlite3


def _columns(cursor: sqlite3.Cursor, table: str):
    cursor.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cursor.fetchall()}


def up(cursor: sqlite3.Cursor):
    showcase_columns = _columns(cursor, "user_showcase")
    if "locked_before" not in showcase_columns:
        cursor.execute(
            "ALTER TABLE user_showcase ADD COLUMN locked_before INTEGER NOT NULL DEFAULT 0"
        )

    # 旧版本无法知道展示柜放入前是否已经手动锁定。将历史展示项视为
    # 展示柜自动锁定，取出时恢复为未锁定，避免旧数据永久卡在锁定状态。
    cursor.execute("UPDATE user_showcase SET locked_before = 0 WHERE locked_before IS NULL")

    # 删除指向不存在实例的关系，避免展示柜出现空白且无法取出的槽位。
    cursor.execute(
        """
        DELETE FROM user_showcase
        WHERE (item_type = 'rod' AND NOT EXISTS (
            SELECT 1 FROM user_rods
            WHERE user_rods.user_id = user_showcase.user_id
              AND user_rods.rod_instance_id = user_showcase.instance_id
        ))
        OR (item_type = 'accessory' AND NOT EXISTS (
            SELECT 1 FROM user_accessories
            WHERE user_accessories.user_id = user_showcase.user_id
              AND user_accessories.accessory_instance_id = user_showcase.instance_id
        ))
        """
    )

    # 关系表是展示柜的事实来源，重新同步实例标记。
    cursor.execute(
        """
        UPDATE user_rods
        SET is_in_showcase = EXISTS (
            SELECT 1 FROM user_showcase
            WHERE item_type = 'rod'
              AND user_id = user_rods.user_id
              AND instance_id = user_rods.rod_instance_id
        )
        """
    )
    cursor.execute(
        """
        UPDATE user_accessories
        SET is_in_showcase = EXISTS (
            SELECT 1 FROM user_showcase
            WHERE item_type = 'accessory'
              AND user_id = user_accessories.user_id
              AND instance_id = user_accessories.accessory_instance_id
        )
        """
    )


def down(cursor: sqlite3.Cursor):
    # SQLite 旧版本不支持安全地删除列；保留该列不影响运行。
    pass
