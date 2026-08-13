"""动作：每日免费抽卡（一天 1 次）。"""

from astrbot.api import logger

from ....utils import get_today
from ..ai_context import AIContext
from .base import AIAction, record_ai_decision


class FreeGachaAction(AIAction):
    name = "free_gacha"

    def _execute(self, ctx: AIContext) -> None:
        today = get_today()
        if ctx.state.last_free_gacha_date == today:
            return

        pools_result = ctx.gacha_service.get_all_pools()
        pools = pools_result.get("pools", [])

        free_pools = [
            pool
            for pool in pools
            if getattr(pool, "cost_coins", 0) == 0
            and getattr(pool, "cost_premium_currency", 0) == 0
        ]
        selected = ctx.gacha_strategy.choose(free_pools)
        free_pool = selected[0] if selected else None

        if not free_pool:
            record_ai_decision(ctx, self.name, "no_free_pool")
            return

        before_coins = int(getattr(ctx.ai_user, "coins", 0) or 0)
        snapshot_id = ctx.snapshot.create(
            action_type=self.name,
            target_id=None,
            features={"pool_name": free_pool.name},
            predicted_prob=1.0,
            decision_reason="daily_free_gacha",
            estimated_value=selected[1].get("score", 0) if selected else 0,
            coins_before=before_coins,
            gacha_pool_id=int(free_pool.gacha_pool_id),
        )
        result = ctx.gacha_service.perform_draw(
            ctx.ai_user_id, free_pool.gacha_pool_id, 1
        )
        if not result.get("success"):
            ctx.snapshot.complete(
                snapshot_id,
                executed=1,
                success=0,
                fail_reason=result.get("message", "免费抽卡失败"),
                reward_value=0,
                coins_after=before_coins,
                result=result,
            )
            return

        ctx.state.set("last_free_gacha_date", today)
        ctx.refresh_ai_user()
        ctx.snapshot.complete(
            snapshot_id,
            executed=1,
            success=1,
            fail_reason=None,
            reward_value=sum(
                int(reward.get("quantity", 0) or 0)
                for reward in result.get("results", [])
                if reward.get("type") == "coins"
            ),
            coins_after=int(getattr(ctx.ai_user, "coins", before_coins) or before_coins),
            result=result,
        )
        logger.info(f"[AI] 免费抽卡成功: 池={free_pool.name}")
        ctx.broadcast.gacha_result(free_pool.name, result.get("results", []))
