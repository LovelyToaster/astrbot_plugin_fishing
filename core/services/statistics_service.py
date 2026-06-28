from datetime import datetime, timedelta
from typing import Dict, Any, List, Tuple, Optional

from ..utils import get_now
from ..repositories.sqlite_statistics_repo import SqliteStatisticsRepository
from ..repositories.sqlite_user_repo import SqliteUserRepository


PERIOD_ALIASES = {
    "今天": "today",
    "今日": "today",
    "本周": "week",
    "周": "week",
    "本月": "month",
    "月": "month",
}


def parse_period(text: Optional[str]) -> str:
    """解析用户输入的时段文本，返回标准 period 名称。"""
    if not text:
        return "today"
    return PERIOD_ALIASES.get(text.strip(), "today")


def get_period_range(period: str) -> Tuple[datetime, datetime]:
    """
    根据 period 返回 (start_time, end_time)。
    period: 'today', 'week', 'month'
    """
    now = get_now()

    if period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        # 本周一 00:00:00
        monday = now - timedelta(days=now.weekday())
        start = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        # 今天 00:00:00
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)

    return start, now


class StatisticsService:
    """统计服务：封装统计查询与数据处理"""

    def __init__(
        self,
        statistics_repo: SqliteStatisticsRepository,
        user_repo: SqliteUserRepository,
    ):
        self.statistics_repo = statistics_repo
        self.user_repo = user_repo

    def get_user_statistics(self, user_id: str, period: str) -> Dict[str, Any]:
        """
        获取用户的个人统计数据。

        Returns:
            包含统计数据及用户信息的字典，供绘图使用。
        """
        start_time, end_time = get_period_range(period)
        summary = self.statistics_repo.get_user_summary(user_id, start_time, end_time)

        # 补充用户信息
        user = self.user_repo.get_by_id(user_id)
        nickname = user.nickname if user and user.nickname else user_id
        coins = user.coins if user else 0

        # 计算成功率
        success_total = summary["success_count"] + summary["fail_count"]
        if success_total > 0:
            success_rate = summary["success_count"] / success_total * 100
        else:
            success_rate = 0.0

        return {
            "user_id": user_id,
            "nickname": nickname,
            "coins": coins,
            "period": period,
            "total_actions": summary["total_actions"],
            "steal_count": summary["steal_count"],
            "electric_fish_count": summary["electric_fish_count"],
            "sell_fish_count": summary["sell_fish_count"],
            "success_count": summary["success_count"],
            "fail_count": summary["fail_count"],
            "success_rate": round(success_rate, 1),
            "fish_count": summary["fish_count"],
            # 按动作类型拆分鱼数
            "steal_fish_cnt": summary.get("steal_fish_cnt", 0),
            "electric_fish_cnt": summary.get("electric_fish_cnt", 0),
            "sell_fish_cnt": summary.get("sell_fish_cnt", 0),
        }

    def get_statistics_leaderboard(
        self,
        period: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        获取统计排行榜数据。
        返回包含用户信息的排行榜列表。
        """
        start_time, end_time = get_period_range(period)
        rows = self.statistics_repo.get_leaderboard(start_time, end_time, limit=limit)

        # 补充用户昵称
        for row in rows:
            user = self.user_repo.get_by_id(row["user_id"])
            row["nickname"] = user.nickname if user and user.nickname else row["user_id"]
            row["coins"] = user.coins if user else 0

            success_total = row["success_count"] + row["fail_count"]
            row["success_rate"] = round(row["success_count"] / success_total * 100, 1) if success_total > 0 else 0.0

        return rows

    @staticmethod
    def get_period_label(period: str) -> str:
        """获取时段的中文标签"""
        return {
            "today": "今天",
            "week": "本周",
            "month": "本月",
        }.get(period, "今天")
