"""动作：每日免费抽卡（一天 1 次）。"""

from astrbot.api import logger

from ....utils import get_today
from ..ai_context import AIContext
from .base import AIAction


class FreeGachaAction(AIAction):
    name = "free_gacha"

    def _execute(self, ctx: AIContext) -> None:
        today = get_today()
        if ctx.state.last_free_gacha_date == today:
            return

        pools_result = ctx.gacha_service.get_all_pools()
        pools = pools_result.get("pools", [])

        free_pool = None
        for pool in pools:
            cost_coins = getattr(pool, "cost_coins", 0)
            cost_premium = getattr(pool, "cost_premium_currency", 0)
            if cost_coins == 0 and cost_premium == 0:
                free_pool = pool
                break

        if not free_pool:
            return

        result = ctx.gacha_service.perform_draw(
            ctx.ai_user_id, free_pool.gacha_pool_id, 1
        )
        if not result.get("success"):
            return

        ctx.state.set("last_free_gacha_date", today)
        logger.info(f"[AI] 免费抽卡成功: 池={free_pool.name}")
        ctx.broadcast.gacha_result(free_pool.name, result.get("results", []))
