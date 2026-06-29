"""
迁移049：重构稀有鱼池为周期刷新模型

新增字段：
  - rare_fish_quota_per_cycle       INTEGER   （每周期稀有鱼配额）
  - rare_fish_caught_this_cycle     INTEGER   （当前周期已捕获稀有鱼数量）
  - rare_fish_quota_last_reset_at   TEXT      （最近一次鱼池刷新周期起点，可空）

数据迁移规则：
  - rare_fish_quota_per_cycle = 旧 daily_rare_fish_quota
  - rare_fish_caught_this_cycle = 旧 rare_fish_caught_today
  - rare_fish_quota_last_reset_at = NULL（首次刷新检查时补齐）

兼容策略：
  保留旧字段 daily_rare_fish_quota 和 rare_fish_caught_today，
  业务代码写入新字段时同步回写旧字段，避免残留旧逻辑读到过时数据。
  SQLite 对删除/重命名列支持有限，不删除旧列。
"""

from astrbot.api import logger


def up(cursor):
    """新增三个周期字段，并复制旧数据"""

    try:
        logger.info("[迁移049] 开始重构稀有鱼池为周期刷新模型")

        # 先检查表是否存在
        cursor.execute("PRAGMA table_info(fishing_zones)")
        columns = {row[1] for row in cursor.fetchall()}

        # 新增字段（幂等：如果字段已存在则跳过）
        if "rare_fish_quota_per_cycle" not in columns:
            cursor.execute(
                "ALTER TABLE fishing_zones ADD COLUMN rare_fish_quota_per_cycle INTEGER DEFAULT 0"
            )
            logger.info("[迁移049] 新增字段 rare_fish_quota_per_cycle")

        if "rare_fish_caught_this_cycle" not in columns:
            cursor.execute(
                "ALTER TABLE fishing_zones ADD COLUMN rare_fish_caught_this_cycle INTEGER DEFAULT 0"
            )
            logger.info("[迁移049] 新增字段 rare_fish_caught_this_cycle")

        if "rare_fish_quota_last_reset_at" not in columns:
            cursor.execute(
                "ALTER TABLE fishing_zones ADD COLUMN rare_fish_quota_last_reset_at TEXT"
            )
            logger.info("[迁移049] 新增字段 rare_fish_quota_last_reset_at")

        # 复制旧数据：只有新字段为 NULL/0 时才填充，避免重复迁移覆盖人工调整
        cursor.execute("""
            UPDATE fishing_zones
            SET rare_fish_quota_per_cycle = daily_rare_fish_quota
            WHERE (rare_fish_quota_per_cycle IS NULL OR rare_fish_quota_per_cycle = 0)
              AND daily_rare_fish_quota > 0
        """)
        cursor.execute("""
            UPDATE fishing_zones
            SET rare_fish_caught_this_cycle = rare_fish_caught_today
            WHERE (rare_fish_caught_this_cycle IS NULL OR rare_fish_caught_this_cycle = 0)
              AND rare_fish_caught_today > 0
        """)

        logger.info("[迁移049] 稀有鱼池周期刷新模型迁移完成")

    except Exception as e:
        logger.error(f"[迁移049] 迁移失败: {e}")
        raise


def down(cursor):
    """回滚：将新字段数据同步回旧字段（保留新字段，SQLite 不删除列）"""

    try:
        logger.info("[迁移049-回滚] 同步周期字段数据回旧字段")

        # 检查新字段是否存在
        cursor.execute("PRAGMA table_info(fishing_zones)")
        columns = {row[1] for row in cursor.fetchall()}

        if "rare_fish_quota_per_cycle" in columns:
            # 将新数据同步回旧字段，不删除新列
            cursor.execute("""
                UPDATE fishing_zones
                SET daily_rare_fish_quota = rare_fish_quota_per_cycle
            """)

        if "rare_fish_caught_this_cycle" in columns:
            cursor.execute("""
                UPDATE fishing_zones
                SET rare_fish_caught_today = rare_fish_caught_this_cycle
            """)

        logger.info("[迁移049-回滚] 数据同步完成（SQLite 兼容，保留新列不删除）")

    except Exception as e:
        logger.error(f"[迁移049-回滚] 回滚失败: {e}")
        raise
