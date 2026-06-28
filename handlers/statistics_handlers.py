import os
import time

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger

from ..draw.statistics import draw_user_statistics_image, draw_statistics_ranking_image
from ..core.services.statistics_service import StatisticsService, parse_period
from ..utils import sanitize_filename

from typing import TYPE_CHECKING, AsyncGenerator

if TYPE_CHECKING:
    from ..main import FishingPlugin


async def statistics(plugin: "FishingPlugin", event: AstrMessageEvent) -> AsyncGenerator:
    """
    /统计 命令处理入口。
    支持子命令：
        /统计                — 今日个人统计
        /统计 今天/今日       — 今日个人统计
        /统计 本周/周         — 本周个人统计
        /统计 本月/月         — 本月个人统计
        /统计 排行榜          — 今日排行榜
        /统计 排行榜 今天     — 今日排行榜
        /统计 排行榜 本周     — 本周排行榜
        /统计 排行榜 本月     — 本月排行榜
    """
    user_id = plugin._get_effective_user_id(event)
    args = event.message_str.strip().split()
    subcmd = args[1] if len(args) > 1 else None

    # 检查是否为排行榜子命令
    if subcmd == "排行榜":
        period_text = args[2] if len(args) > 2 else None
        period = parse_period(period_text)
        async for r in _send_leaderboard(plugin, event, user_id, period):
            yield r
        return

    # 个人统计
    period = parse_period(subcmd)
    async for r in _send_user_statistics(plugin, event, user_id, period):
        yield r


async def _send_user_statistics(
    plugin: "FishingPlugin",
    event: AstrMessageEvent,
    user_id: str,
    period: str,
) -> AsyncGenerator:
    """生成并发送个人统计图片"""
    try:
        data = plugin.statistics_service.get_user_statistics(user_id, period)
    except Exception as e:
        logger.error(f"[统计] 获取个人统计数据失败: {e}")
        yield event.plain_result("❌ 获取统计数据失败，请稍后再试。")
        return

    # 生成图片文件路径
    safe_uid = sanitize_filename(user_id)
    timestamp = int(time.time())
    output_path = os.path.join(
        plugin.tmp_dir,
        f"statistics_{safe_uid}_{period}_{timestamp}.png",
    )

    try:
        draw_user_statistics_image(data, output_path)
    except Exception as e:
        logger.error(f"[统计] 绘制个人统计图片失败: {e}")
        yield event.plain_result("❌ 生成统计图片失败，请稍后再试。")
        return

    yield event.image_result(output_path)


async def _send_leaderboard(
    plugin: "FishingPlugin",
    event: AstrMessageEvent,
    user_id: str,
    period: str,
) -> AsyncGenerator:
    """生成并发送排行榜图片"""
    try:
        rows = plugin.statistics_service.get_statistics_leaderboard(period, limit=5)
    except Exception as e:
        logger.error(f"[统计] 获取排行榜数据失败: {e}")
        yield event.plain_result("❌ 获取排行榜数据失败，请稍后再试。")
        return

    # 生成图片文件路径
    safe_uid = sanitize_filename(user_id)
    timestamp = int(time.time())
    output_path = os.path.join(
        plugin.tmp_dir,
        f"statistics_rank_{safe_uid}_{period}_{timestamp}.png",
    )

    period_label = plugin.statistics_service.get_period_label(period)

    try:
        draw_statistics_ranking_image(rows, output_path, period_label)
    except Exception as e:
        logger.error(f"[统计] 绘制排行榜图片失败: {e}")
        yield event.plain_result("❌ 生成排行榜图片失败，请稍后再试。")
        return

    yield event.image_result(output_path)
