import sqlite3
import json
import threading
from datetime import datetime
from typing import Dict, Any, Optional, List

from astrbot.api import logger

from ..utils import get_now

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


class SqliteStatisticsRepository:
    """统计数据仓储的SQLite实现"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, detect_types=sqlite3.PARSE_DECLTYPES | sqlite3.PARSE_COLNAMES)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON;")
            self._local.connection = conn
        return conn

    def add_log(
        self,
        user_id: str,
        action_type: str,
        success: bool = True,
        target_id: Optional[str] = None,
        fish_count: int = 0,
        details: Optional[dict] = None,
    ) -> None:
        """写入一条统计日志"""
        try:
            now = get_now()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO statistics_logs
                        (user_id, target_id, action_type, success, fish_count, details, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        target_id,
                        action_type,
                        1 if success else 0,
                        fish_count,
                        json.dumps(details, ensure_ascii=False) if details else None,
                        now.strftime(DATETIME_FORMAT),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[统计] 写入统计日志失败: {e} (action={action_type}, user={user_id})")

    def get_user_summary(
        self,
        user_id: str,
        start_time: datetime,
        end_time: datetime,
    ) -> Dict[str, Any]:
        """
        查询用户在指定时间范围内的统计汇总。
        返回包含以下字段的字典：
            total_actions, steal_count, electric_fish_count, sell_fish_count,
            success_count, fail_count, fish_count,
            steal_fish_cnt, electric_fish_cnt, sell_fish_cnt
        """
        result = {
            "total_actions": 0,
            "steal_count": 0,
            "electric_fish_count": 0,
            "sell_fish_count": 0,
            "success_count": 0,
            "fail_count": 0,
            "fish_count": 0,
            # 按动作类型拆分鱼数，避免展示口径误导
            "steal_fish_cnt": 0,
            "electric_fish_cnt": 0,
            "sell_fish_cnt": 0,
        }

        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # 查询各 action_type 的汇总
                cursor.execute(
                    """
                    SELECT
                        action_type,
                        COUNT(*) AS cnt,
                        SUM(CASE WHEN action_type IN ('steal', 'electric_fish') AND success = 1 THEN 1 ELSE 0 END) AS success_cnt,
                        SUM(CASE WHEN action_type IN ('steal', 'electric_fish') AND success = 0 THEN 1 ELSE 0 END) AS fail_cnt,
                        COALESCE(SUM(fish_count), 0) AS total_fish
                    FROM statistics_logs
                    WHERE user_id = ? AND created_at >= ? AND created_at <= ?
                    GROUP BY action_type
                    """,
                    (user_id, start_time.strftime(DATETIME_FORMAT), end_time.strftime(DATETIME_FORMAT)),
                )

                rows = cursor.fetchall()
                for row in rows:
                    action_type = row["action_type"]
                    cnt = row["cnt"]
                    total_fish = row["total_fish"]
                    result["total_actions"] += cnt
                    result["success_count"] += row["success_cnt"]
                    result["fail_count"] += row["fail_cnt"]
                    result["fish_count"] += total_fish

                    if action_type == "steal":
                        result["steal_count"] += cnt
                        result["steal_fish_cnt"] += total_fish
                    elif action_type == "electric_fish":
                        result["electric_fish_count"] += cnt
                        result["electric_fish_cnt"] += total_fish
                    elif action_type == "sell_fish":
                        result["sell_fish_count"] += cnt
                        result["sell_fish_cnt"] += total_fish

        except Exception as e:
            logger.error(f"[统计] 查询用户统计汇总失败: {e} (user={user_id})")

        return result

    def get_leaderboard(
        self,
        start_time: datetime,
        end_time: datetime,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        查询统计排行榜。
        按 total_actions DESC, success_count DESC, fish_count DESC 排序。
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    SELECT
                        user_id,
                        COUNT(*) AS total_actions,
                        SUM(CASE WHEN action_type = 'steal' THEN 1 ELSE 0 END) AS steal_count,
                        SUM(CASE WHEN action_type = 'electric_fish' THEN 1 ELSE 0 END) AS electric_fish_count,
                        SUM(CASE WHEN action_type = 'sell_fish' THEN 1 ELSE 0 END) AS sell_fish_count,
                        SUM(CASE WHEN action_type IN ('steal', 'electric_fish') AND success = 1 THEN 1 ELSE 0 END) AS success_count,
                        SUM(CASE WHEN action_type IN ('steal', 'electric_fish') AND success = 0 THEN 1 ELSE 0 END) AS fail_count,
                        COALESCE(SUM(fish_count), 0) AS fish_count
                    FROM statistics_logs
                    WHERE created_at >= ? AND created_at <= ?
                    GROUP BY user_id
                    ORDER BY total_actions DESC, success_count DESC, fish_count DESC
                    LIMIT ?
                    """,
                    (start_time.strftime(DATETIME_FORMAT), end_time.strftime(DATETIME_FORMAT), limit),
                )

                return [
                    {
                        "user_id": row["user_id"],
                        "total_actions": row["total_actions"],
                        "steal_count": row["steal_count"],
                        "electric_fish_count": row["electric_fish_count"],
                        "sell_fish_count": row["sell_fish_count"],
                        "success_count": row["success_count"],
                        "fail_count": row["fail_count"],
                        "fish_count": row["fish_count"],
                    }
                    for row in cursor.fetchall()
                ]
        except Exception as e:
            logger.error(f"[统计] 查询排行榜失败: {e}")
            return []
