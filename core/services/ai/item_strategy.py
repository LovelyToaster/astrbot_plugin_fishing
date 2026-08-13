"""AI 道具策略与动态资源储备。"""

import time
from typing import Any, Dict, Optional

from astrbot.api import logger


class AIItemStrategy:
    """按资源储备和预期收益使用社交/钓鱼道具。"""

    ITEM_INTERVAL = 600
    SOCIAL_ITEM_INTERVAL = 600
    FISHING_ITEM_INTERVAL = 1800

    def __init__(self, context):
        self.ctx = context

    def _templates(self) -> Dict[int, Any]:
        try:
            return {
                int(item.item_id): item
                for item in self.ctx.item_template_repo.get_all_items()
            }
        except Exception:
            return {}

    def _inventory(self) -> Dict[int, int]:
        try:
            return self.ctx.inventory_repo.get_user_item_inventory(self.ctx.ai_user_id)
        except Exception:
            return {}

    def _find_by_effect(self, effect_type: str):
        templates = self._templates()
        inventory = self._inventory()
        return [
            (template, int(inventory.get(item_id, 0) or 0))
            for item_id, template in templates.items()
            if template.effect_type == effect_type and inventory.get(item_id, 0) > 0
        ]

    def _has_active_buff(self, buff_type: str) -> bool:
        try:
            return bool(
                self.ctx.game_mechanics_service.buff_repo.get_active_by_user_and_type(
                    self.ctx.ai_user_id, buff_type
                )
            )
        except Exception:
            return False

    def coin_reserve(self) -> int:
        """估算未来 24 小时运营成本，并保留现有精炼门槛作为下限。"""
        zone_cost = 10
        try:
            zone = self.ctx.inventory_repo.get_zone_by_id(self.ctx.ai_user.fishing_zone_id)
            zone_cost = int(getattr(zone, "fishing_cost", 10) or 10)
        except Exception:
            pass
        fishing_cfg = self.ctx.global_config.get("fishing", {})
        cooldown = max(60, int(fishing_cfg.get("cooldown_seconds", 180)))
        expected_casts = 86400 // cooldown
        fishing_cost = expected_casts * zone_cost
        electric_cfg = self.ctx.global_config.get("electric_fish", {})
        penalty_rate = float(
            electric_cfg.get("failure_penalty_expected_rate", 0.025)
        )
        electric_buffer = int(
            float(getattr(self.ctx.ai_user, "coins", 0) or 0)
            * penalty_rate
            * max(0.05, 1.0 - float(electric_cfg.get("base_success_rate", 0.6)))
        )
        refine_floor = int(self.ctx.ai_config.get("refine_reserve_coins", 200000))
        return max(refine_floor, fishing_cost + electric_buffer)

    def _count(self, effect_type: str) -> int:
        return sum(quantity for _, quantity in self._find_by_effect(effect_type))

    def _pond_value(self) -> float:
        total = 0.0
        try:
            for item in self.ctx.inventory_repo.get_fish_inventory(self.ctx.ai_user_id):
                template = self.ctx.item_template_repo.get_fish_by_id(item.fish_id)
                if template:
                    total += float(template.base_value) * int(item.quantity) * (
                        1 + int(getattr(item, "quality_level", 0) or 0)
                    )
        except Exception:
            return 0.0
        return total

    def can_handle_protection(self, operation: str, features: Dict[str, Any]) -> bool:
        if int(features.get("target_protection_layers", 0) or 0) <= 0:
            return True
        value = float(features.get("target_fish_value", 0) or 0)
        if value < 50000:
            return False
        if self._count("STEAL_PROTECTION_REMOVAL") > 0:
            return True
        return (
            self._count("STEAL_PENETRATION_BUFF") > 1
            or self._count("SHADOW_CLOAK_BUFF") > 1
        )

    def estimate_social_item_cost(self, operation: str, features: Dict[str, Any]) -> int:
        if int(features.get("target_protection_layers", 0) or 0) <= 0:
            return 0
        if self._count("STEAL_PROTECTION_REMOVAL") > 0:
            return 50000
        if self._count("STEAL_PENETRATION_BUFF") > 1:
            return 25000
        return 100000

    def _record_item_use(self, item_id: int, before_coins: int, result: Dict[str, Any]):
        after_user = self.ctx.refresh_ai_user()
        self.ctx.state.set("last_item_use_ts", time.time())
        category = result.get("category")
        if category == "social":
            self.ctx.state.set("last_social_item_ts", time.time())
        elif category == "fishing":
            self.ctx.state.set("last_fishing_item_ts", time.time())
        snapshot_id = self.ctx.snapshot.create(
            action_type="item_use",
            target_id=result.get("target_id"),
            features={"item_id": item_id, "category": result.get("category", "utility")},
            predicted_prob=1.0 if result.get("success") else 0.0,
            decision_reason=result.get("reason"),
            estimated_value=result.get("estimated_value"),
            coins_before=before_coins,
            item_id=item_id,
        )
        self.ctx.snapshot.complete(
            snapshot_id,
            executed=1,
            success=1 if result.get("success") else 0,
            fail_reason=None if result.get("success") else result.get("message"),
            reward_value=int(
                result.get("reward_value", 0)
                or max(0, int(getattr(after_user, "coins", before_coins) or before_coins) - before_coins)
            ),
            coins_after=int(getattr(after_user, "coins", before_coins) or before_coins),
            item_delta={str(item_id): -1 if result.get("success") else 0},
            result=result,
        )

    def _use_generic(
        self,
        item_id: int,
        *,
        category: str,
        reason: str,
        estimated_value: float = 0.0,
        target_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        before = int(getattr(self.ctx.ai_user, "coins", 0) or 0)
        result = dict(self.ctx.inventory_service.use_item(self.ctx.ai_user_id, item_id))
        result.update(
            {
                "category": category,
                "reason": reason,
                "estimated_value": estimated_value,
                "target_id": target_id,
            }
        )
        self._record_item_use(item_id, before, result)
        return result

    def prepare_social_target(
        self, target_id: str, features: Dict[str, Any], operation: str
    ) -> Dict[str, Any]:
        """为护盾目标准备道具；破盾后本 tick 不立即重复攻击。"""
        layers = int(features.get("target_protection_layers", 0) or 0)
        if layers <= 0:
            return {"ready": True, "prepared": False}
        if self._has_active_buff("STEAL_PENETRATION_BUFF") or self._has_active_buff(
            "SHADOW_CLOAK_BUFF"
        ):
            return {"ready": True, "prepared": False}
        if time.time() - self.ctx.state.last_social_item_ts < self.SOCIAL_ITEM_INTERVAL:
            return {"ready": False, "prepared": False, "reason": "social_item_cooldown"}

        value = float(features.get("target_fish_value", 0) or 0)
        removal = self._find_by_effect("STEAL_PROTECTION_REMOVAL")
        if removal and value >= 50000:
            template, _ = removal[0]
            result = self.ctx.game_mechanics_service.dispel_steal_protection(target_id)
            result = dict(result or {})
            if result.get("success"):
                self.ctx.inventory_repo.decrease_item_quantity(
                    self.ctx.ai_user_id, template.item_id, 1
                )
            result.update(
                {
                    "category": "social",
                    "reason": "high_value_target_disperse",
                    "estimated_value": value,
                    "target_id": target_id,
                }
            )
            self._record_item_use(template.item_id, int(self.ctx.ai_user.coins), result)
            return {"ready": False, "prepared": bool(result.get("success")), "result": result}

        # 没有驱灵香时只在高价值目标上预装穿透/斗篷，下一 tick 才攻击。
        for effect_type, threshold in (
            ("STEAL_PENETRATION_BUFF", 100000),
            ("SHADOW_CLOAK_BUFF", 200000),
        ):
            if value < threshold or self._has_active_buff(
                "STEAL_PENETRATION_BUFF" if effect_type == "STEAL_PENETRATION_BUFF" else "SHADOW_CLOAK_BUFF"
            ):
                continue
            options = self._find_by_effect(effect_type)
            if not options:
                continue
            template, quantity = options[0]
            reserve = 1
            if quantity <= reserve:
                continue
            result = self._use_generic(
                template.item_id,
                category="social",
                reason="prepare_shield_target",
                estimated_value=value,
                target_id=target_id,
            )
            return {"ready": False, "prepared": bool(result.get("success")), "result": result}
        return {"ready": False, "prepared": False, "reason": "protected_without_economical_item"}

    def use_steal_reset(self, target_id: str, expected_value: float) -> Optional[Dict[str, Any]]:
        """在明确的高收益目标出现时使用偷鱼冷却重置。"""
        if expected_value <= 1000:
            return None
        options = self._find_by_effect("RESET_STEAL_COOLDOWN")
        if not options:
            return None
        template, quantity = options[0]
        # 至少保留 5 个，避免 AI 在短期反击中耗光资源。
        if quantity <= 5:
            return None
        return self._use_generic(
            template.item_id,
            category="social",
            reason="high_value_revenge_target_cooldown_reset",
            estimated_value=expected_value,
            target_id=target_id,
        )

    def use_one_utility_item(self) -> Optional[Dict[str, Any]]:
        """每 tick 最多使用一个通用道具，避免库存因循环快速耗尽。"""
        now = time.time()
        if now - self.ctx.state.last_item_use_ts < self.ITEM_INTERVAL:
            return None
        coins = int(getattr(self.ctx.ai_user, "coins", 0) or 0)
        reserve = self.coin_reserve()

        # 先补充不可避免的运营资金，使用最小面额。
        if coins < reserve:
            bags = sorted(
                self._find_by_effect("ADD_COINS"),
                key=lambda pair: (
                    int(getattr(pair[0], "rarity", 1) or 1),
                    int(getattr(pair[0], "item_id", 0) or 0),
                ),
            )
            for template, quantity in bags:
                if quantity <= 0:
                    continue
                return self._use_generic(
                    template.item_id,
                    category="utility",
                    reason="below_operating_reserve",
                    estimated_value=reserve - coins,
                )

        # 受到成功社交攻击或鱼塘估值较高时启用防护。
        pond_value = self._pond_value()
        incoming = 0
        try:
            incoming = sum(
                int(self.ctx.statistics_repo.get_successful_victim_counts_in_window(action, 24).get(self.ctx.ai_user_id, 0))
                for action in ("steal", "electric_fish")
            )
        except Exception:
            pass
        if incoming > 0 or pond_value >= 100000:
            effect = "STEAL_PROTECTION_BUFF"
            options = sorted(
                self._find_by_effect(effect),
                key=lambda pair: -int(getattr(pair[0], "rarity", 0) or 0),
            )
            if options and not self._has_active_buff(effect):
                template, quantity = options[0]
                if quantity > 1 or pond_value >= 500000:
                    return self._use_generic(
                        template.item_id,
                        category="social",
                        reason="incoming_attack_or_valuable_pond",
                        estimated_value=pond_value,
                    )

        # 稀有鱼配额未耗尽时，使用低级幸运药水；高级圣水只在低级库存不足时使用。
        if now - self.ctx.state.last_fishing_item_ts >= self.FISHING_ITEM_INTERVAL:
            try:
                zone = self.ctx.inventory_repo.get_zone_by_id(self.ctx.ai_user.fishing_zone_id)
                quota = int(getattr(zone, "rare_fish_quota_per_cycle", 0) or 0)
                caught = int(getattr(zone, "rare_fish_caught_this_cycle", 0) or 0)
            except Exception:
                quota, caught = 0, 0
            if quota <= 0 or caught < quota:
                options = sorted(
                    self._find_by_effect("RARE_FISH_BOOST"),
                    key=lambda pair: int(getattr(pair[0], "rarity", 0) or 0),
                )
                for template, quantity in options:
                    reserve_units = 5 if int(getattr(template, "rarity", 0) or 0) < 5 else 1
                    if quantity > reserve_units:
                        return self._use_generic(
                            template.item_id,
                            category="fishing",
                            reason="rare_fish_quota_available",
                            estimated_value=pond_value,
                        )

        # 声呐只作为低频额外钓鱼，不与自动钓鱼高频叠加。
        if now - self.ctx.state.last_fishing_item_ts >= self.FISHING_ITEM_INTERVAL:
            sonar = self._find_by_effect("RESET_FISHING_COOLDOWN")
            if sonar and coins >= reserve:
                template, quantity = sonar[0]
                if quantity > 10:
                    return self._use_generic(
                        template.item_id,
                        category="fishing",
                        reason="profitable_extra_fishing",
                        estimated_value=max(0, coins - reserve),
                    )
        return None
