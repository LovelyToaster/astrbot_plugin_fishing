import sqlite3
from astrbot.api import logger

def up(cursor: sqlite3.Cursor):
    logger.debug("正在执行 045_add_gacha_pity_system: 创建保底计数表...")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_gacha_pity (
            user_id TEXT NOT NULL,
            gacha_pool_id INTEGER NOT NULL,
            current_pity INTEGER DEFAULT 0,
            PRIMARY KEY (user_id, gacha_pool_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (gacha_pool_id) REFERENCES gacha_pools(gacha_pool_id) ON DELETE CASCADE
        )
    """)
    logger.info("045_add_gacha_pity_system: 表 user_gacha_pity 创建完成。")
