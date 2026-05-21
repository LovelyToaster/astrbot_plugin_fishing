"""
迁移047：添加通知系统
创建通知表，用于存储偷鱼和电鱼等操作的通知消息
"""

from astrbot.api import logger


def up(cursor):
    """创建通知系统表"""

    try:
        logger.info("[迁移047] 创建通知系统表")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient_id TEXT NOT NULL,
                sender_nickname TEXT,
                type TEXT NOT NULL,
                details TEXT,
                is_read INTEGER DEFAULT 0,
                created_at TIMESTAMP NOT NULL
            )
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_notifications_recipient
            ON notifications(recipient_id, is_read)
        """)

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_notifications_created
            ON notifications(recipient_id, created_at)
        """)

        logger.info("[迁移047] 通知系统表创建成功")

    except Exception as e:
        logger.error(f"[迁移047] 迁移失败: {e}")
        raise


def down(cursor):
    """回滚：删除通知系统表"""

    try:
        logger.info("[迁移047-回滚] 删除通知系统表")

        cursor.execute("DROP INDEX IF EXISTS idx_notifications_recipient")
        cursor.execute("DROP INDEX IF EXISTS idx_notifications_created")
        cursor.execute("DROP TABLE IF EXISTS notifications")

        logger.info("[迁移047-回滚] 通知系统表删除成功")

    except Exception as e:
        logger.error(f"[迁移047-回滚] 回滚失败: {e}")
        raise
