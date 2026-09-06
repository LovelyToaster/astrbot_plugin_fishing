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
        coin_amount: int = 0,
    ) -> None:
        """写入一条统计日志"""
        try:
            now = get_now()
            with self._get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    INSERT INTO statistics_logs
                        (user_id, target_id, action_type, success, fish_count, coin_amount, details, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        target_id,
                        action_type,
                        1 if success else 0,
                        fish_count,
                        int(coin_amount or 0),
                        json.dumps(details, ensure_ascii=False) if details else None,
                        now.strftime(DATETIME_FORMAT),
                    ),
                )
                conn.commit()
        except Exception as e:
            logger.error(f"[统计] 写入统计日志失败: {e} (action={action_type}, user={user_id})")

    def get_period_report(
        self,
        start_time: datetime,
        end_time: datetime,
        limit: int = 1,
    ) -> Dict[str, Any]:
        """获取群发日报/周报需要的各项冠军数据。"""
        empty = {
            "coins_earned": None,
            "coins_spent": None,
            "coins_net": None,
            "fishing": None,
            "steal": None,
            "electric_fish": None,
            "totals": {
                "coins_earned": 0,
                "coins_spent": 0,
                "fish_count": 0,
                "steal_count": 0,
                "electric_fish_count": 0,
            },
        }

        start = start_time.strftime(DATETIME_FORMAT)
        end = end_time.strftime(DATETIME_FORMAT)

        def top_row(conn, sql: str, params):
            row = conn.execute(sql, params).fetchone()
            return dict(row) if row else None

        try:
            with self._get_connection() as conn:
                # SYSTEM 账户不参与群统计；AI 账户仍按正常玩家统计。
                user_filter = (
                    "AND u.user_id IS NOT NULL "
                    "AND COALESCE(u.is_system, 0) = 0"
                )

                earned = top_row(
                    conn,
                    f"""
                    SELECT sl.user_id, COALESCE(u.nickname, sl.user_id) AS nickname,
                           SUM(sl.coin_amount) AS amount
                    FROM statistics_logs sl
                    LEFT JOIN users u ON u.user_id = sl.user_id
                    WHERE sl.action_type = 'coin_earn'
                      AND sl.coin_amount > 0
                      AND sl.created_at >= ? AND sl.created_at <= ?
                      {user_filter}
                    GROUP BY sl.user_id
                    ORDER BY amount DESC, sl.user_id ASC
                    LIMIT ?
                    """,
                    (start, end, limit),
                )
                spent = top_row(
                    conn,
                    f"""
                    SELECT sl.user_id, COALESCE(u.nickname, sl.user_id) AS nickname,
                           SUM(ABS(sl.coin_amount)) AS amount
                    FROM statistics_logs sl
                    LEFT JOIN users u ON u.user_id = sl.user_id
                    WHERE sl.action_type = 'coin_spend'
                      AND sl.coin_amount < 0
                      AND sl.created_at >= ? AND sl.created_at <= ?
                      {user_filter}
                    GROUP BY sl.user_id
                    ORDER BY amount DESC, sl.user_id ASC
                    LIMIT ?
                    """,
                    (start, end, limit),
                )
                net = top_row(
                    conn,
                    f"""
                    SELECT sl.user_id, COALESCE(u.nickname, sl.user_id) AS nickname,
                           COALESCE(SUM(CASE
                               WHEN sl.action_type = 'coin_earn' AND sl.coin_amount > 0
                                   THEN sl.coin_amount
                               ELSE 0
                           END), 0) AS earned,
                           COALESCE(SUM(CASE
                               WHEN sl.action_type = 'coin_spend' AND sl.coin_amount < 0
                                   THEN ABS(sl.coin_amount)
                               ELSE 0
                           END), 0) AS spent,
                           COALESCE(SUM(CASE
                               WHEN sl.action_type = 'coin_earn' AND sl.coin_amount > 0
                                   THEN sl.coin_amount
                               WHEN sl.action_type = 'coin_spend' AND sl.coin_amount < 0
                                   THEN sl.coin_amount
                               ELSE 0
                           END), 0) AS amount
                    FROM statistics_logs sl
                    LEFT JOIN users u ON u.user_id = sl.user_id
                    WHERE sl.action_type IN ('coin_earn', 'coin_spend')
                      AND sl.created_at >= ? AND sl.created_at <= ?
                      {user_filter}
                    GROUP BY sl.user_id
                    ORDER BY amount DESC, sl.user_id ASC
                    LIMIT ?
                    """,
                    (start, end, limit),
                )
                fishing = top_row(
                    conn,
                    f"""
                    SELECT sl.user_id, COALESCE(u.nickname, sl.user_id) AS nickname,
                           SUM(sl.fish_count) AS count,
                           SUM(CASE WHEN sl.coin_amount > 0 THEN sl.coin_amount ELSE 0 END) AS value
                    FROM statistics_logs sl
                    LEFT JOIN users u ON u.user_id = sl.user_id
                    WHERE sl.action_type = 'fish' AND sl.success = 1
                      AND sl.created_at >= ? AND sl.created_at <= ?
                      {user_filter}
                    GROUP BY sl.user_id
                    ORDER BY count DESC, value DESC, sl.user_id ASC
                    LIMIT ?
                    """,
                    (start, end, limit),
                )

                social_sql = f"""
                    SELECT sl.user_id, COALESCE(u.nickname, sl.user_id) AS nickname,
                           COALESCE(SUM(sl.fish_count), 0) AS count,
                           SUM(CASE WHEN sl.coin_amount > 0 THEN sl.coin_amount ELSE 0 END) AS value
                    FROM statistics_logs sl
                    LEFT JOIN users u ON u.user_id = sl.user_id
                    WHERE sl.action_type = ? AND sl.success = 1
                      AND sl.created_at >= ? AND sl.created_at <= ?
                      {user_filter}
                    GROUP BY sl.user_id
                    ORDER BY count DESC, value DESC, sl.user_id ASC
                    LIMIT ?
                """
                steal = top_row(conn, social_sql, ("steal", start, end, limit))
                electric = top_row(
                    conn, social_sql, ("electric_fish", start, end, limit)
                )

                totals = conn.execute(
                    f"""
                    SELECT
                        COALESCE(SUM(CASE WHEN action_type = 'coin_earn' AND coin_amount > 0 THEN coin_amount ELSE 0 END), 0) AS coins_earned,
                        COALESCE(SUM(CASE WHEN action_type = 'coin_spend' AND coin_amount < 0 THEN ABS(coin_amount) ELSE 0 END), 0) AS coins_spent,
                        COALESCE(SUM(CASE WHEN action_type = 'fish' AND success = 1 THEN fish_count ELSE 0 END), 0) AS fish_count,
                        COALESCE(SUM(CASE WHEN action_type = 'steal' AND success = 1 THEN fish_count ELSE 0 END), 0) AS steal_count,
                        COALESCE(SUM(CASE WHEN action_type = 'electric_fish' AND success = 1 THEN fish_count ELSE 0 END), 0) AS electric_fish_count
                    FROM statistics_logs sl
                    LEFT JOIN users u ON u.user_id = sl.user_id
                    WHERE sl.created_at >= ? AND sl.created_at <= ?
                      {user_filter}
                    """,
                    (start, end),
                ).fetchone()

                empty.update(
                    {
                        "coins_earned": earned,
                        "coins_spent": spent,
                        "coins_net": net,
                        "fishing": fishing,
                        "steal": steal,
                        "electric_fish": electric,
                        "totals": dict(totals) if totals else empty["totals"],
                    }
                )
        except Exception as e:
            logger.error(f"[统计] 查询群统计失败: {e}")

        for key in (
            "coins_earned",
            "coins_spent",
            "coins_net",
            "fishing",
            "steal",
            "electric_fish",
        ):
            row = empty.get(key)
            if row:
                for value_key in ("amount", "count", "value", "earned", "spent"):
                    if value_key in row:
                        row[value_key] = int(row[value_key] or 0)
        empty["totals"] = {
            key: int(value or 0) for key, value in empty["totals"].items()
        }
        return empty

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

    # ==================== AI 决策辅助 ====================

    def get_top_attacker_of(
        self,
        target_id: str,
        action_type: str,
        hours: int = 24,
    ) -> Optional[str]:
        """
        查过去 N 小时内对某目标施暴（同动作类型）次数最多的攻击者 user_id。
        无攻击记录返回 None；异常返回 None 并记 debug。
        不区分 success（失败也算"有意图"）。
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT user_id
                FROM statistics_logs
                WHERE target_id = ?
                  AND action_type = ?
                  AND created_at >= datetime('now', '+8 hours', ?)
                GROUP BY user_id
                ORDER BY COUNT(*) DESC
                LIMIT 1
                """,
                (target_id, action_type, f"-{int(hours)} hours"),
            )
            row = cursor.fetchone()
            return row["user_id"] if row else None
        except Exception as e:
            logger.debug(f"[统计] get_top_attacker_of 查询失败: {e}")
            return None

    def get_incoming_attacker_counts(
        self,
        victim_id: str,
        action_type: str,
        hours: int = 24,
    ) -> Dict[str, int]:
        """按攻击者返回某用户在时间窗口内受到的攻击次数。"""
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT user_id, COUNT(*) AS cnt
                    FROM statistics_logs
                    WHERE target_id = ? AND action_type = ?
                      AND user_id <> 'SYSTEM'
                      AND created_at >= datetime('now', '+8 hours', ?)
                    GROUP BY user_id
                    """,
                    (victim_id, action_type, f"-{int(hours)} hours"),
                ).fetchall()
            return {row["user_id"]: int(row["cnt"] or 0) for row in rows}
        except Exception as e:
            logger.debug(f"[统计] get_incoming_attacker_counts 查询失败: {e}")
            return {}

    def get_top_actor(
        self,
        action_type: str,
        hours: int = 24,
        exclude_user_id: Optional[str] = None,
    ) -> Optional[str]:
        """
        查过去 N 小时内该动作类型总次数最多的发起者 user_id（不区分目标）。

        默认排除 SYSTEM；可通过 exclude_user_id 排除 AI 自己，避免 AI 把自己的
        行为算作"最活跃玩家"，导致加权决策的 B 头名（30% 权重）失效。
        无记录返回 None；异常返回 None 并记 debug。
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            params: List[Any] = [action_type, f"-{int(hours)} hours"]
            sql = """
                SELECT user_id
                FROM statistics_logs
                WHERE action_type = ?
                  AND created_at >= datetime('now', '+8 hours', ?)
                  AND user_id <> 'SYSTEM'
            """
            if exclude_user_id is not None:
                sql += " AND user_id <> ?"
                params.append(exclude_user_id)
            sql += """
                GROUP BY user_id
                ORDER BY COUNT(*) DESC
                LIMIT 1
            """
            cursor.execute(sql, params)
            row = cursor.fetchone()
            return row["user_id"] if row else None
        except Exception as e:
            logger.debug(f"[统计] get_top_actor 查询失败: {e}")
            return None

    def get_user_action_counts_in_window(
        self,
        action_type: str,
        hours: int = 24,
    ) -> Dict[str, int]:
        """
        查过去 N 小时内各个玩家主动发起某动作的总次数。

        Returns:
            {user_id: count} 字典
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT user_id, COUNT(*) AS cnt
                FROM statistics_logs
                WHERE action_type = ?
                  AND created_at >= datetime('now', '+8 hours', ?)
                  AND user_id <> 'SYSTEM'
                GROUP BY user_id
                """,
                (action_type, f"-{int(hours)} hours"),
            )
            return {row["user_id"]: row["cnt"] for row in cursor.fetchall()}
        except Exception as e:
            logger.debug(f"[统计] get_user_action_counts_in_window 查询失败: {e}")
            return {}

    def get_victim_counts_in_window(
        self,
        action_type: str,
        hours: int = 24,
    ) -> Dict[str, int]:
        """
        查过去 N 小时内各个玩家作为目标被施加某动作的总次数（受害次数）。

        Returns:
            {target_id: count} 字典
        """
        try:
            conn = self._get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT target_id, COUNT(*) AS cnt
                FROM statistics_logs
                WHERE action_type = ?
                  AND target_id IS NOT NULL
                  AND target_id <> 'SYSTEM'
                  AND created_at >= datetime('now', '+8 hours', ?)
                GROUP BY target_id
                """,
                (action_type, f"-{int(hours)} hours"),
            )
            return {row["target_id"]: row["cnt"] for row in cursor.fetchall()}
        except Exception as e:
            logger.debug(f"[统计] get_victim_counts_in_window 查询失败: {e}")
            return {}

    def get_successful_victim_counts_in_window(
        self,
        action_type: str,
        hours: int = 24,
    ) -> Dict[str, int]:
        """查询成功施加到各目标的次数，用于防御策略。"""
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT target_id, COUNT(*) AS cnt
                    FROM statistics_logs
                    WHERE action_type = ? AND success = 1
                      AND target_id IS NOT NULL
                      AND target_id <> 'SYSTEM'
                      AND created_at >= datetime('now', '+8 hours', ?)
                    GROUP BY target_id
                    """,
                    (action_type, f"-{int(hours)} hours"),
                ).fetchall()
            return {row["target_id"]: int(row["cnt"] or 0) for row in rows}
        except Exception as e:
            logger.debug(f"[统计] get_successful_victim_counts 查询失败: {e}")
            return {}

    def get_actor_target_counts_in_window(
        self,
        actor_id: str,
        action_type: str,
        hours: int = 24,
    ) -> Dict[str, int]:
        """查询 AI 在时间窗口内分别攻击过哪些目标。"""
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT target_id, COUNT(*) AS cnt
                    FROM statistics_logs
                    WHERE user_id = ? AND action_type = ?
                      AND target_id IS NOT NULL
                      AND created_at >= datetime('now', '+8 hours', ?)
                    GROUP BY target_id
                    """,
                    (actor_id, action_type, f"-{int(hours)} hours"),
                ).fetchall()
            return {row["target_id"]: int(row["cnt"] or 0) for row in rows}
        except Exception as e:
            logger.debug(f"[统计] get_actor_target_counts_in_window 查询失败: {e}")
            return {}

    def get_target_success_rates(
        self,
        action_type: str,
        hours: int = 168,
    ) -> Dict[str, tuple]:
        """返回目标维度的 (attempts, successes)，用于 Beta 平滑。"""
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT target_id,
                           COUNT(*) AS attempts,
                           SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successes
                    FROM statistics_logs
                    WHERE action_type = ? AND target_id IS NOT NULL
                      AND created_at >= datetime('now', '+8 hours', ?)
                    GROUP BY target_id
                    """,
                    (action_type, f"-{int(hours)} hours"),
                ).fetchall()
            return {
                row["target_id"]: (
                    int(row["attempts"] or 0),
                    int(row["successes"] or 0),
                )
                for row in rows
            }
        except Exception as e:
            logger.debug(f"[统计] get_target_success_rates 查询失败: {e}")
            return {}

    def get_recent_success_values(
        self,
        user_id: str,
        action_type: str,
        hours: int = 168,
        limit: int = 100,
    ) -> List[float]:
        """读取近期社交动作实际兑现的鱼价，供道具成本估算使用。"""
        try:
            with self._get_connection() as conn:
                rows = conn.execute(
                    """
                    SELECT details
                    FROM statistics_logs
                    WHERE user_id = ?
                      AND action_type = ?
                      AND success = 1
                      AND details IS NOT NULL
                      AND created_at >= datetime('now', '+8 hours', ?)
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (user_id, action_type, f"-{int(hours)} hours", int(limit)),
                ).fetchall()
            values = []
            for row in rows:
                try:
                    details = json.loads(row["details"] or "{}")
                    value = details.get("total_value", details.get("value", 0))
                    value = float(value or 0)
                    if value > 0:
                        values.append(value)
                except (TypeError, ValueError, json.JSONDecodeError):
                    continue
            return values
        except Exception as e:
            logger.debug(f"[统计] get_recent_success_values 查询失败: {e}")
            return []

