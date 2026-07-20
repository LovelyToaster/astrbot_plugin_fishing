"""
迁移052：添加 AI 玩家状态持久化表
创建 ai_player_state 表，用于持久化 AI 玩家的节流/惩罚时间戳，
防止插件重启后 AI 立即触发全部动作。
"""

from astrbot.api import logger


def up(cursor):
    """创建 ai_player_state 表"""

    try:
        logger.info("[迁移052] 创建 AI 玩家状态表 ai_player_state")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_player_state (
                user_id TEXT PRIMARY KEY,
                last_sell_fish_ts REAL NOT NULL DEFAULT 0,
                last_sell_equipment_ts REAL NOT NULL DEFAULT 0,
                last_paid_gacha_ts REAL NOT NULL DEFAULT 0,
                last_free_gacha_date TEXT NOT NULL DEFAULT '',
                last_steal_failure_ts REAL NOT NULL DEFAULT 0,
                last_electric_failure_ts REAL NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
            )
        """)
        logger.info("[迁移052] ai_player_state 表创建成功")

    except Exception as e:
        err_msg = str(e).lower()
        if "already exists" in err_msg:
            logger.info("[迁移052] ai_player_state 表已存在，跳过")
        else:
            logger.error(f"[迁移052] 迁移失败: {e}")
            raise


def down(cursor):
    """回滚：SQLite 不支持直接删除表，此处仅记录日志"""

    try:
        logger.info("[迁移052-回滚] 回滚 ai_player_state 表（SQLite 不支持直接删除表，需手动处理）")
        logger.warning("[迁移052-回滚] 如需完整回滚，请备份数据后手动 DROP TABLE ai_player_state")

    except Exception as e:
        logger.error(f"[迁移052-回滚] 回滚失败: {e}")
        raise
