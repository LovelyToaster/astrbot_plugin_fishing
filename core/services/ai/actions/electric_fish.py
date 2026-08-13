"""动作：按反击压力、鱼塘价值和成功率选择电鱼目标。"""

import time

from astrbot.api import logger

from ..ai_context import AIContext
from .base import AIAction, parse_int_safe, seconds_since


class ElectricFishAction(AIAction):
    name = "electric_fish"

    def __init__(self, min_target_fish_count: int):
        self.min_target_fish_count = int(min_target_fish_count)

    def _skip(self, ctx: AIContext, reason: str, features=None) -> None:
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
        cooldown = ctx.global_config.get("electric_fish", {}).get(
            "cooldown_seconds", 7200
        )
        if ctx.ai_user.last_electric_fish_time is not None:
            if seconds_since(ctx.ai_user.last_electric_fish_time) < cooldown:
                return
        if time.time() - ctx.state.last_electric_failure_ts < min(cooldown, 900):
            return

        scores = ctx.target_strategy.score(
            "electric_fish", self.min_target_fish_count
        )
        target = ctx.target_strategy.choose(scores)
        if target is None:
            self._skip(ctx, "no_profitable_target", {"candidate_count": len(scores)})
            return

        prepare = ctx.item_strategy.prepare_social_target(
            target.target_id, target.features, "electric_fish"
        )
        if not prepare.get("ready"):
            if prepare.get("prepared"):
                ctx.get_candidates(force=True)
            self._skip(
                ctx,
                prepare.get("reason") or "shield_prepared_next_tick",
                target.as_features(),
            )
            return

        before_coins = int(getattr(ctx.ai_user, "coins", 0) or 0)
        snapshot_id = ctx.snapshot.create(
            action_type=self.name,
            target_id=target.target_id,
            features=target.as_features(),
            predicted_prob=target.success_probability,
            decision_reason="revenge_value_success",
            estimated_value=target.expected_net_value,
            coins_before=before_coins,
        )
        result = ctx.game_mechanics_service.electric_fish(
            ctx.ai_user_id, target.target_id
        )
        target_nickname = ctx.resolve_target_nickname(target.target_id)
        after_user = ctx.user_repo.get_by_id(ctx.ai_user_id)
        after_coins = int(getattr(after_user, "coins", before_coins) or before_coins)
        if result.get("success"):
            notification = result.get("victim_notification", {})
            fish_count = notification.get("stolen_count", 0)
            value = notification.get("total_value", 0)
            logger.info(f"[AI] 电鱼成功: 目标={target_nickname or target.target_id}")
            ctx.broadcast.electric_success(
                target_id=target.target_id,
                target_nickname=target_nickname,
                fish_count=fish_count,
                value=value,
            )
            ctx.snapshot.complete(
                snapshot_id,
                executed=1,
                success=1,
                fail_reason=None,
                reward_value=parse_int_safe(value),
                coins_after=after_coins,
                result=result,
            )
            ctx.refresh_ai_user()
            ctx.get_candidates(force=True)
            return

        err_msg = result.get("message", "电鱼失败")
        if "冷却" not in err_msg:
            ctx.state.set("last_electric_failure_ts", time.time())
        ctx.broadcast.electric_failure(
            target_id=target.target_id,
            target_nickname=target_nickname,
            err_msg=err_msg,
        )
        executed = 0 if "冷却" in err_msg else 1
        ctx.snapshot.complete(
            snapshot_id,
            executed=executed,
            success=None if executed == 0 else 0,
            fail_reason=err_msg,
            reward_value=0,
            coins_after=after_coins,
            result=result,
        )
        if any(token in err_msg for token in ("空的", "鱼太少", "守护海灵")):
            ctx.get_candidates(force=True)
