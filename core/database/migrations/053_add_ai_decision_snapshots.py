"""
迁移053：添加 AI 决策快照表
创建 ai_decision_snapshots 表，用于持续记录 AI 每次决策时的目标特征、
预测概率与执行结果，为 V2 及以后模型迭代提供干净的训练数据。
"""

from astrbot.api import logger


def up(cursor):
    """创建 ai_decision_snapshots 表及索引"""

    try:
        logger.info("[迁移053] 创建 AI 决策快照表 ai_decision_snapshots")

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ai_user_id TEXT NOT NULL,
                action_type TEXT NOT NULL,
                target_user_id TEXT,
                features_json TEXT NOT NULL,
                predicted_prob REAL,
                executed INTEGER NOT NULL DEFAULT 0,
                success INTEGER,
                fail_reason TEXT,
                reward_value INTEGER,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP
            )
        """)
        logger.info("[迁移053] ai_decision_snapshots 表创建成功")

        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_snapshots_action
            ON ai_decision_snapshots(action_type, executed, success)
        """)
        cursor.execute("""
            CREATE INDEX IF NOT EXISTS idx_ai_snapshots_created
            ON ai_decision_snapshots(created_at)
        """)
        logger.info("[迁移053] ai_decision_snapshots 索引创建成功")

    except Exception as e:
        err_msg = str(e).lower()
        if "already exists" in err_msg:
            logger.info("[迁移053] ai_decision_snapshots 表已存在，跳过")
        else:
            logger.error(f"[迁移053] 迁移失败: {e}")
            raise


def down(cursor):
    """回滚：SQLite 不支持直接删除表，此处仅记录日志"""

    try:
        logger.info("[迁移053-回滚] 回滚 ai_decision_snapshots 表（SQLite 不支持直接删除表，需手动处理）")
        logger.warning("[迁移053-回滚] 如需完整回滚，请备份数据后手动 DROP TABLE ai_decision_snapshots")

    except Exception as e:
        logger.error(f"[迁移053-回滚] 回滚失败: {e}")
        raise
