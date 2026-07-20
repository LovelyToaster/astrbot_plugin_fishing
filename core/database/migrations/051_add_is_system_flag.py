"""
迁移051：添加系统账户标志字段
在 users 表中添加 is_system 字段，用于标识系统内部账户（如银行托管、市场托管等）
AI 玩家选取偷/电目标时会跳过 is_system=1 的账户
同时自动标记已知的系统账户 SYSTEM 和 MARKET
"""

from astrbot.api import logger


def up(cursor):
    """添加 is_system 字段到 users 表，并标记已知系统账户"""

    try:
        logger.info("[迁移051] 添加系统账户标志字段 is_system")

        try:
            cursor.execute("""
                ALTER TABLE users ADD COLUMN is_system INTEGER NOT NULL DEFAULT 0
            """)
            logger.info("[迁移051] is_system 字段添加成功")
        except Exception as alter_err:
            # 幂等：字段已存在时忽略
            err_msg = str(alter_err).lower()
            if "duplicate column" in err_msg or "already exists" in err_msg:
                logger.info("[迁移051] is_system 字段已存在，跳过 ALTER")
            else:
                raise

        # 自动标记已知系统账户
        try:
            cursor.execute("""
                UPDATE users SET is_system = 1
                WHERE user_id IN ('SYSTEM', 'MARKET')
            """)
            affected = cursor.rowcount
            logger.info(f"[迁移051] 已标记 {affected} 个已知系统账户（SYSTEM / MARKET）")
        except Exception as update_err:
            logger.warning(f"[迁移051] 标记已知系统账户失败（不阻塞迁移）: {update_err}")

    except Exception as e:
        logger.error(f"[迁移051] 迁移失败: {e}")
        raise


def down(cursor):
    """回滚：移除 is_system 字段（SQLite 不支持直接 DROP COLUMN，此处仅记录日志）"""

    try:
        logger.info("[迁移051-回滚] 回滚 is_system 字段（SQLite 不支持直接 DROP COLUMN，需重建表）")
        logger.warning("[迁移051-回滚] 如需完整回滚，请备份数据后重建 users 表")

    except Exception as e:
        logger.error(f"[迁移051-回滚] 回滚失败: {e}")
        raise
