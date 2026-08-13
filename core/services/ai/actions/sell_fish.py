"""动作：鱼塘超过阈值且间隔到期时卖光鱼。"""

import time

from astrbot.api import logger

from ..ai_context import AIContext
from .base import AIAction, parse_int_safe, record_ai_decision


class SellFishAction(AIAction):
    name = "sell_fish"

    def __init__(self, min_interval_seconds: int, pond_full_threshold: float):
        self.min_interval_seconds = int(min_interval_seconds)
        self.pond_full_threshold = float(pond_full_threshold)

    def _execute(self, ctx: AIContext) -> None:
        now = time.time()
        if now - ctx.state.last_sell_fish_ts < self.min_interval_seconds:
            return

        pond_result = ctx.inventory_service.get_user_fish_pond_capacity(ctx.ai_user_id)
        if not pond_result.get("success"):
            return

        current_count = pond_result.get("current_fish_count", 0)
        capacity = pond_result.get("fish_pond_capacity", 1)
        if capacity <= 0:
            capacity = 1

        if current_count / capacity < self.pond_full_threshold:
            return

        sell_result = ctx.inventory_service.sell_all_fish(ctx.ai_user_id, keep_one=False)
        if not sell_result.get("success"):
            record_ai_decision(ctx, self.name, "sell_service_failed")
            return

        ctx.state.set("last_sell_fish_ts", now)
        logger.info(f"[AI] 卖鱼成功: 鱼塘占用 {current_count}/{capacity}")

        # 从消息中抠出金额用于广播（保持与旧版行为一致）
        msg_text = sell_result.get("message", "")
        value_str = "?"
        if "获得" in msg_text:
            after = msg_text.split("获得", 1)[1].strip()
            if "金币" in after:
                value_str = (
                    after.split("金币")[0].strip().replace(",", "").replace("，", "")
                )
        sold_value = parse_int_safe(sell_result.get("sold_value", value_str))
        record_ai_decision(
            ctx,
            self.name,
            "pond_threshold_reached",
            features={"current_fish_count": current_count, "capacity": capacity},
            executed=1,
            success=1,
            reward_value=sold_value,
            coins_after=int(
                getattr(ctx.user_repo.get_by_id(ctx.ai_user_id), "coins", 0) or 0
            ),
        )
        ctx.broadcast.sold_fish(value_str)

        # 卖鱼后金币变化，刷新用户对象供后续动作使用
        ctx.refresh_ai_user()
