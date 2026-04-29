# 迁移脚本 044: 为 users 表添加每日深海探险次数追踪字段

import sqlite3
from astrbot.api import logger

def up(cursor: sqlite3.Cursor):
    """
    应用此迁移：为 users 表添加 deep_sea_attempts_today 和 last_deep_sea_date 字段。
    """
    logger.debug("正在执行 044_add_deep_sea_daily_tracking: 添加每日深海探险追踪字段...")

    try:
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]

        if 'deep_sea_attempts_today' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN deep_sea_attempts_today INTEGER NOT NULL DEFAULT 0")
            logger.info("成功为 users 表添加 'deep_sea_attempts_today' 字段。")
        else:
            logger.info("'deep_sea_attempts_today' 字段已存在，无需添加。")

        if 'last_deep_sea_date' not in columns:
            cursor.execute("ALTER TABLE users ADD COLUMN last_deep_sea_date TEXT DEFAULT NULL")
            logger.info("成功为 users 表添加 'last_deep_sea_date' 字段。")
        else:
            logger.info("'last_deep_sea_date' 字段已存在，无需添加。")

    except sqlite3.Error as e:
        logger.error(f"在迁移 044_add_deep_sea_daily_tracking 期间发生错误: {e}")
        raise
