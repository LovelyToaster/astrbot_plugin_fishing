"""
迁移048：添加统计日志表
创建统计日志表，用于记录偷鱼、电鱼、卖鱼等行为的统计数据
"""

from astrbot.api import logger


def up(cursor):
    """创建统计日志表"""

    try:
        logger.info("[迁移048] 创建统计日志表")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS statistics_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                target_id TEXT,
                action_type TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 1,
                fish_count INTEGER NOT NULL DEFAULT 0,
                details TEXT,
                created_at TIMESTAMP NOT NULL
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_statistics_logs_user_time
            ON statistics_logs(user_id, created_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_statistics_logs_action_time
            ON statistics_logs(action_type, created_at)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_statistics_logs_created
            ON statistics_logs(created_at)
        """)

        logger.info("[迁移048] 统计日志表创建成功")

    except Exception as e:
        logger.error(f"[迁移048] 迁移失败: {e}")
        raise


def down(cursor):
    """回滚：删除统计日志表"""

    try:
        logger.info("[迁移048-回滚] 删除统计日志表")

        cursor.execute("DROP INDEX IF EXISTS idx_statistics_logs_user_time")
        cursor.execute("DROP INDEX IF EXISTS idx_statistics_logs_action_time")
        cursor.execute("DROP INDEX IF EXISTS idx_statistics_logs_created")
        cursor.execute("DROP TABLE IF EXISTS statistics_logs")

        logger.info("[迁移048-回滚] 统计日志表删除成功")

    except Exception as e:
        logger.error(f"[迁移048-回滚] 回滚失败: {e}")
        raise
