"""动作：按运营储备、奖品期望净价值和保底紧迫度抽卡。"""

import time

from astrbot.api import logger

from ..ai_context import AIContext
from .base import AIAction, parse_int_safe


class PaidGachaAction(AIAction):
    name = "paid_gacha"

    def __init__(
        self,
        paid_interval_seconds: int,
        spending_ratio: float,
        ten_pull_enabled: bool,
        ten_pull_multiplier: float,
    ):
        self.paid_interval_seconds = int(paid_interval_seconds)
        self.spending_ratio = float(spending_ratio)
        self.ten_pull_enabled = bool(ten_pull_enabled)
        self.ten_pull_multiplier = float(ten_pull_multiplier)

    def _record_skip(self, ctx: AIContext, reason: str, features=None) -> None:
        snapshot_id = ctx.snapshot.create(
            action_type=self.name,
            target_id=None,
            features=features or {"operation": self.name},
            decision_reason=reason,
            estimated_value=0,
            coins_before=int(getattr(ctx.ai_user, "coins", 0) or 0),
        )
        ctx.snapshot.complete(
            snapshot_id,
            executed=0,
            success=None,
            fail_reason=reason,
            reward_value=0,
            coins_after=int(getattr(ctx.ai_user, "coins", 0) or 0),
        )

    def _execute(self, ctx: AIContext) -> None:
        now = time.time()
        if now - ctx.state.last_paid_gacha_ts < self.paid_interval_seconds:
            return

        ctx.refresh_ai_user()
        ai_user = ctx.ai_user
        reserve = ctx.item_strategy.coin_reserve()
        free_coins = max(0, int(ai_user.coins or 0) - reserve)
        if free_coins <= 0:
            self._record_skip(ctx, "below_operating_reserve", {"reserve": reserve})
            return

        pools_result = ctx.gacha_service.get_all_pools()
        candidates = [
            pool
            for pool in pools_result.get("pools", [])
            if getattr(pool, "cost_premium_currency", 0) == 0
            and getattr(pool, "cost_coins", 0) > 0
        ]
        if not candidates:
            self._record_skip(ctx, "no_coin_pool")
            return

        single_budget = free_coins * self.spending_ratio
        ten_budget = free_coins * self.spending_ratio * self.ten_pull_multiplier
        ten_budget = min(ten_budget, free_coins * 0.25)

        scored = [(pool, ctx.gacha_strategy.score_pool(pool)) for pool in candidates]
        scored.sort(key=lambda pair: pair[1]["score"], reverse=True)
        selected = None
        num_draws = 1
        is_ten = False

        # 接近保底时只抽到保底所需次数；否则优先十连，但只使用自由金币。
        for pool, info in scored:
            cost = int(getattr(pool, "cost_coins", 0) or 0)
            draws_to_pity = info.get("draws_to_pity")
            if draws_to_pity is not None and 0 < draws_to_pity <= 10:
                required = cost * int(draws_to_pity)
                if required <= ten_budget and (draws_to_pity > 1 or cost <= single_budget):
                    selected, num_draws = pool, int(draws_to_pity)
                    is_ten = num_draws == 10
                    break
            if self.ten_pull_enabled and cost * 10 <= ten_budget:
                selected, num_draws, is_ten = pool, 10, True
                break

        if selected is None:
            for pool, info in scored:
                cost = int(getattr(pool, "cost_coins", 0) or 0)
                if cost <= single_budget and info["score"] > 0:
                    selected = pool
                    break

        if selected is None:
            self._record_skip(
                ctx,
                "no_pool_with_positive_expected_value",
                {"reserve": reserve, "free_coins": free_coins},
            )
            return

        cost = int(getattr(selected, "cost_coins", 0) or 0) * num_draws
        if cost > free_coins:
            self._record_skip(ctx, "selected_pool_exceeds_free_coins")
            return

        info = ctx.gacha_strategy.score_pool(selected)
        snapshot_id = ctx.snapshot.create(
            action_type=self.name,
            target_id=None,
            features={
                "pool_name": selected.name,
                "draws": num_draws,
                "is_ten": is_ten,
                "reserve": reserve,
                "free_coins": free_coins,
                **info,
            },
            predicted_prob=1.0,
            decision_reason="expected_net_value_and_pity",
            estimated_value=float(info.get("score", 0) or 0) * num_draws,
            coins_before=int(ai_user.coins),
            gacha_pool_id=int(selected.gacha_pool_id),
        )
        result = ctx.gacha_service.perform_draw(
            ctx.ai_user_id, selected.gacha_pool_id, num_draws
        )
        ctx.refresh_ai_user()
        if not result.get("success"):
            ctx.snapshot.complete(
                snapshot_id,
                executed=1,
                success=0,
                fail_reason=result.get("message", "抽卡失败"),
                reward_value=0,
                coins_after=int(ctx.ai_user.coins),
                result=result,
            )
            return

        ctx.state.set("last_paid_gacha_ts", now)
        realized = sum(
            parse_int_safe(reward.get("quantity", 0))
            for reward in result.get("results", [])
            if reward.get("type") == "coins"
        )
        ctx.snapshot.complete(
            snapshot_id,
            executed=1,
            success=1,
            fail_reason=None,
            reward_value=realized,
            coins_after=int(ctx.ai_user.coins),
            result=result,
        )
        logger.info(
            f"[AI] 金币抽卡成功: 池={selected.name}, 十连={is_ten}, "
            f"次数={num_draws}, 消耗={cost}, 预估分={info.get('score', 0):.2f}"
        )
        ctx.broadcast.gacha_result(selected.name, result.get("results", []))
