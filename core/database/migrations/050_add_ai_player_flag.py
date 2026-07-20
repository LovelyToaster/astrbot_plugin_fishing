"""
迁移050：添加 AI 玩家标志字段
在 users 表中添加 is_ai 字段，用于标识 AI 玩家账号
"""

from astrbot.api import logger


def up(cursor):
    """添加 is_ai 字段到 users 表"""

    try:
        logger.info("[迁移050] 添加 AI 玩家标志字段 is_ai")

        cursor.execute("""
            ALTER TABLE users ADD COLUMN is_ai INTEGER NOT NULL DEFAULT 0
        """)

        logger.info("[迁移050] is_ai 字段添加成功")

    except Exception as e:
        logger.error(f"[迁移050] 迁移失败: {e}")
        raise


def down(cursor):
    """回滚：移除 is_ai 字段（SQLite 不支持直接 DROP COLUMN，此处仅记录日志）"""

    try:
        logger.info("[迁移050-回滚] 回滚 is_ai 字段（SQLite 不支持直接 DROP COLUMN，需重建表）")
        # SQLite 不支持直接 DROP COLUMN，需要重建表
        # 此处仅记录日志，实际回滚需手动处理
        logger.warning("[迁移050-回滚] 如需完整回滚，请备份数据后重建 users 表")

    except Exception as e:
        logger.error(f"[迁移050-回滚] 回滚失败: {e}")
        raise
