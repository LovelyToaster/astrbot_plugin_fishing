"""
迁移054：添加展示柜系统数据表及字段
1. 创建 user_showcase 表记录展示柜槽位与装备关系
2. 在 user_rods 和 user_accessories 中添加 is_in_showcase 字段
3. 在 users 中添加 showcase_capacity 和 showcase_signature 字段
"""

from astrbot.api import logger


def up(cursor):
    """升级数据库"""
    try:
        logger.info("[迁移054] 开始安装展示柜系统数据库构架...")

        # 1. 创建 user_showcase 表
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_showcase (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                item_type TEXT NOT NULL,
                instance_id INTEGER NOT NULL,
                slot_index INTEGER NOT NULL,
                added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(user_id, item_type, instance_id),
                UNIQUE(user_id, slot_index)
            );
        """)

        # 检查并添加 user_rods 字段
        cursor.execute("PRAGMA table_info(user_rods)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'is_in_showcase' not in columns:
            cursor.execute("ALTER TABLE user_rods ADD COLUMN is_in_showcase INTEGER DEFAULT 0")

        # 检查并添加 user_accessories 字段
        cursor.execute("PRAGMA table_info(user_accessories)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'is_in_showcase' not in columns:
            cursor.execute("ALTER TABLE user_accessories ADD COLUMN is_in_showcase INTEGER DEFAULT 0")

        # 检查并添加 users 字段
        cursor.execute("PRAGMA table_info(users)")
        columns = [row[1] for row in cursor.fetchall()]
        if 'showcase_capacity' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN showcase_capacity INTEGER DEFAULT 6")
        if 'showcase_signature' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN showcase_signature TEXT DEFAULT '快来参观我的展示柜吧！'")

        logger.info("[迁移054] 展示柜系统数据库构架安装完成")

    except Exception as e:
        logger.error(f"[迁移054] 迁移失败: {e}")
        raise


def down(cursor):
    """回滚"""
    try:
        logger.info("[迁移054-回滚] 开始删除 user_showcase 表...")
        cursor.execute("DROP TABLE IF EXISTS user_showcase")
        logger.info("[迁移054-回滚] 表删除成功，新增列保留记录")
    except Exception as e:
        logger.error(f"[迁移054-回滚] 回滚失败: {e}")
        raise
