"""动作：根据金币余额自动切换钓鱼区域。"""

from typing import List

from astrbot.api import logger

from ....domain.models import FishingZone
from ....utils import get_now
from ..ai_context import AIContext
from .base import AIAction


class SwitchZoneAction(AIAction):
    name = "switch_zone"

    def __init__(
        self,
        upgrade_threshold: int,
        downgrade_threshold: int,
    ):
        self.upgrade_threshold = int(upgrade_threshold)
        self.downgrade_threshold = int(downgrade_threshold)

    def _execute(self, ctx: AIContext) -> None:
        now = get_now()
        zones: List[FishingZone] = ctx.inventory_repo.get_all_zones()

        if len(zones) <= 1:
            return

        # 过滤可进入的激活区域
        user_items = ctx.inventory_repo.get_user_item_inventory(ctx.ai_user_id)
        eligible: List[FishingZone] = []
        for zone in zones:
            if not zone.is_active:
                continue
            if zone.available_from and now < zone.available_from:
                continue
            if zone.available_until and now > zone.available_until:
                continue
            if zone.requires_pass and zone.required_item_id:
                if user_items.get(zone.required_item_id, 0) < 1:
                    continue
            eligible.append(zone)

        if len(eligible) <= 1:
            return

        coins = ctx.ai_user.coins
        current_zone_id = ctx.ai_user.fishing_zone_id
        current_zone = next((z for z in eligible if z.id == current_zone_id), None)

        # 按 ID 降序排列，贪心选择最高可负担区域
        eligible.sort(key=lambda z: z.id, reverse=True)

        # 降级判断优先
        if current_zone is not None:
            if coins < current_zone.fishing_cost * self.downgrade_threshold:
                target = self._pick_best_affordable(eligible, coins)
                if target and target.id != current_zone_id:
                    self._do_switch(ctx, current_zone_id, target)
        else:
            # 当前区域不在可选列表中（已过期/失去资格），自动切换到最佳可负担区域
            fallback = self._pick_best_affordable(eligible, coins)
            if fallback and fallback.id != current_zone_id:
                self._do_switch(ctx, current_zone_id, fallback)
            return

        # 升级判断
        best = self._pick_best_affordable(eligible, coins)
        if best is None:
            return
        if best.id <= current_zone_id:
            return
        if coins >= best.fishing_cost * self.upgrade_threshold:
            self._do_switch(ctx, current_zone_id, best)

    def _pick_best_affordable(self, zones: List[FishingZone], coins: int):
        """按 ID 降序选择第一个可负担钓鱼消耗的区域。"""
        for zone in zones:
            if coins >= zone.fishing_cost:
                return zone
        return None

    def _do_switch(self, ctx: AIContext, from_zone_id: int, to_zone: FishingZone) -> None:
        result = ctx.fishing_service.set_user_fishing_zone(ctx.ai_user_id, to_zone.id)
        if result.get("success"):
            logger.info(f"[AI] {self.name}: {from_zone_id} -> {to_zone.id} ({to_zone.name})")
            ctx.refresh_ai_user()
