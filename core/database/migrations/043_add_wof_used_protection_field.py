import sqlite3
from astrbot.api import logger

def up(cursor: sqlite3.Cursor):
    """
    应用此迁移：为 users 表添加 wof_used_protection 字段，用于记录命运之轮单局保护道具使用情况。
    """
    logger.debug("正在执行 043_add_wof_used_protection_field: 为 users 表添加 wof_used_protection 字段...")

    try:
        # 检查现有列，避免重复添加
        cursor.execute("PRAGMA table_info(users)")
        columns = [info[1] for info in cursor.fetchall()]

        field_name = 'wof_used_protection'
        field_type = 'BOOLEAN'

        if field_name not in columns:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {field_name} {field_type} DEFAULT 0")
            logger.info(f"成功为 users 表添加 '{field_name}' 字段。")
        else:
            logger.info(f"'{field_name}' 字段已存在于 users 表中，无需添加。")

    except sqlite3.Error as e:
        logger.error(f"在迁移 043_add_wof_used_protection_field 期间发生错误: {e}")
        raise
