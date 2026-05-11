import sqlite3
from astrbot.api import logger

def up(cursor: sqlite3.Cursor):
    logger.debug("正在执行 046_add_makeup_checkin_fields: 为 users 表添加补签计数字段...")
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN makeup_count_month INTEGER DEFAULT NULL")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN makeup_count INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    logger.info("046_add_makeup_checkin_fields: 补签计数字段添加完成。")
