"""迁移059：修复历史展示柜装备仍出现在背包中的状态。"""

import sqlite3


def up(cursor: sqlite3.Cursor):
    """以 user_showcase 关系表为准，同步历史装备实例状态。"""
    # 先清理指向不存在实例的关系，避免把无效记录同步成幽灵装备。
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

    # 展示柜是装备的独立展示空间：保留装备实例，但不再作为背包装备、装备中
    # 或可操作装备返回。历史数据可能只写入了关系表，因此这里强制补齐状态。
    cursor.execute(
        """
        UPDATE user_rods
        SET is_in_showcase = 1, is_locked = 1, is_equipped = 0
        WHERE EXISTS (
            SELECT 1 FROM user_showcase
            WHERE user_showcase.item_type = 'rod'
              AND user_showcase.user_id = user_rods.user_id
              AND user_showcase.instance_id = user_rods.rod_instance_id
        )
        """
    )
    cursor.execute(
        """
        UPDATE user_accessories
        SET is_in_showcase = 1, is_locked = 1, is_equipped = 0
        WHERE EXISTS (
            SELECT 1 FROM user_showcase
            WHERE user_showcase.item_type = 'accessory'
              AND user_showcase.user_id = user_accessories.user_id
              AND user_showcase.instance_id = user_accessories.accessory_instance_id
        )
        """
    )

    # 清理用户表中的装备指针，避免钓鱼逻辑继续使用已展示的装备。
    cursor.execute(
        """
        UPDATE users
        SET equipped_rod_instance_id = NULL
        WHERE EXISTS (
            SELECT 1 FROM user_showcase
            WHERE user_showcase.item_type = 'rod'
              AND user_showcase.user_id = users.user_id
              AND user_showcase.instance_id = users.equipped_rod_instance_id
        )
        """
    )
    cursor.execute(
        """
        UPDATE users
        SET equipped_accessory_instance_id = NULL
        WHERE EXISTS (
            SELECT 1 FROM user_showcase
            WHERE user_showcase.item_type = 'accessory'
              AND user_showcase.user_id = users.user_id
              AND user_showcase.instance_id = users.equipped_accessory_instance_id
        )
        """
    )


def down(cursor: sqlite3.Cursor):
    # 修复是幂等的数据清理，不回滚为错误状态。
    pass
