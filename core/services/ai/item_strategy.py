"""AI 道具策略与动态资源储备。"""

import json
import time
from statistics import median
from typing import Any, Dict, Optional

from ...utils import calculate_fish_unit_value



class AIItemStrategy:
    """只根据当前资源、Buff 和游戏状态使用社交/钓鱼道具。"""

    REFINE_RESERVE_COINS = 200000
    COIN_TRIGGER_RATIO = 0.75
    RARE_FISH_MIN_EFFECTIVE_CASTS = 5
    RARE_FISH_MIN_REMAINING_QUOTA = 8
    RARE_FISH_MIN_BAIT_UNITS = 5
    SONAR_MIN_NET_VALUE = 3000
    SONAR_MIN_COOLDOWN_RATIO = 0.75
    SONAR_MIN_REMAINING_BAIT = 3
    SONAR_STOCK_RESERVE = 20
    STEAL_RESET_MIN_EXPECTED_VALUE = 25000
    STEAL_RESET_MIN_REMAINING_RATIO = 0.75
    STEAL_RESET_STOCK_RESERVE = 10

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

    @staticmethod
    def _effect_payload(template: Any) -> Dict[str, Any]:
        payload = getattr(template, "effect_payload", None)
        if isinstance(payload, dict):
            return payload
        try:
            parsed = json.loads(payload or "{}")
            return parsed if isinstance(parsed, dict) else {}
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}

    def _coin_bag_estimate(self, template: Any) -> float:
        payload = self._effect_payload(template)
        if payload.get("amount") is not None:
            try:
                return max(0.0, float(payload["amount"]))
            except (TypeError, ValueError):
                return 0.0
        try:
            low = float(payload.get("min_amount", 0) or 0)
            high = float(payload.get("max_amount", low) or low)
            return max(0.0, (low + high) / 2.0)
        except (TypeError, ValueError):
            return 0.0

    def _select_coin_bag(self, coins: int, reserve: int):
        """选择尽量接近缺口的钱袋，避免每次只开最小面额。"""
        if reserve <= 0 or coins >= reserve * self.COIN_TRIGGER_RATIO:
            return None

        candidates = [
            (template, quantity, self._coin_bag_estimate(template))
            for template, quantity in self._find_by_effect("ADD_COINS")
            if quantity > 0 and self._coin_bag_estimate(template) > 0
        ]
        if not candidates:
            return None

        # 金币尚未跌到储备金 25% 以下时，不主动动用至尊钱袋。
        if coins >= reserve * 0.25:
            filtered = [
                item for item in candidates if int(getattr(item[0], "rarity", 0) or 0) < 5
            ]
            if filtered:
                candidates = filtered

        target = max(reserve, int(reserve * 1.05))
        gap = max(1, target - coins)
        candidates.sort(key=lambda item: item[2])
        close_enough = [item for item in candidates if item[2] <= gap * 1.25]
        return max(close_enough or candidates, key=lambda item: item[2])[0]

    def _has_active_buff(self, buff_type: str) -> bool:
        try:
            return bool(
                self.ctx.game_mechanics_service.buff_repo.get_active_by_user_and_type(
                    self.ctx.ai_user_id, buff_type
                )
            )
        except Exception:
            return False

    def _fishing_cooldown(self) -> int:
        cooldown = max(
            60,
            int(self.ctx.global_config.get("fishing", {}).get("cooldown_seconds", 180)),
        )
        try:
            accessory = self.ctx.inventory_repo.get_user_equipped_accessory(
                self.ctx.ai_user_id
            )
            if accessory:
                template = self.ctx.item_template_repo.get_accessory_by_id(
                    accessory.accessory_id
                )
                if template and template.name == "海洋之心":
                    cooldown = max(30, int(cooldown / 2))
        except Exception:
            pass
        return cooldown

    def _fishing_cooldown_remaining(self) -> float:
        """读取当前钓鱼原生冷却剩余时间，不引入 AI 自己的计时器。"""
        last_fishing_time = getattr(self.ctx.ai_user, "last_fishing_time", None)
        if last_fishing_time is None or getattr(last_fishing_time, "year", 2) <= 1:
            return 0.0
        try:
            elapsed = max(0.0, time.time() - last_fishing_time.timestamp())
        except (AttributeError, TypeError, ValueError, OSError):
            return 0.0
        return max(0.0, float(self._fishing_cooldown()) - elapsed)

    def _effective_casts(self, duration_seconds: int) -> int:
        if not getattr(self.ctx.ai_user, "auto_fishing_enabled", False):
            return 0
        return max(0, int(duration_seconds // self._fishing_cooldown()))

    def _rare_fish_available(self) -> bool:
        return self._rare_fish_remaining() > 0

    def _rare_fish_remaining(self) -> int:
        try:
            zone = self.ctx.inventory_repo.get_zone_by_id(self.ctx.ai_user.fishing_zone_id)
            quota = getattr(zone, "rare_fish_quota_per_cycle", None)
            caught = getattr(zone, "rare_fish_caught_this_cycle", None)
            if quota is None:
                quota = getattr(zone, "daily_rare_fish_quota", 0)
            if caught is None:
                caught = getattr(zone, "rare_fish_caught_today", 0)
            return max(0, int(quota or 0) - int(caught or 0))
        except Exception:
            return 0

    def _available_bait_units(self) -> int:
        try:
            inventory = self.ctx.inventory_repo.get_user_bait_inventory(
                self.ctx.ai_user_id
            )
            return sum(max(0, int(quantity or 0)) for quantity in inventory.values())
        except Exception:
            return 0

    def _pond_count(self) -> int:
        try:
            return sum(
                max(0, int(item.quantity or 0))
                for item in self.ctx.inventory_repo.get_fish_inventory(
                    self.ctx.ai_user_id
                )
            )
        except Exception:
            return 0

    def _pond_has_room(self, expected_casts: int) -> bool:
        capacity = int(getattr(self.ctx.ai_user, "fish_pond_capacity", 0) or 0)
        if capacity <= 0:
            return True
        return self._pond_count() + max(1, expected_casts) <= capacity

    def _recent_fishing_gross_value(self) -> float:
        """优先使用近期实际鱼价，避免总收入把旧版本收益带入决策。"""
        try:
            log_repo = getattr(self.ctx.fishing_service, "log_repo", None)
            records = log_repo.get_fishing_records(self.ctx.ai_user_id, 50)
            values = [
                float(getattr(record, "value", 0) or 0)
                for record in records
                if float(getattr(record, "value", 0) or 0) > 0
            ]
            if values:
                return float(median(values))
        except Exception:
            pass
        return 0.0

    def _estimated_fishing_net_value(self, casts: int = 1) -> float:
        """使用 AI 历史钓鱼收入做保守估算，避免声呐只看金币余额。"""
        if casts <= 0:
            return 0.0
        try:
            zone = self.ctx.inventory_repo.get_zone_by_id(self.ctx.ai_user.fishing_zone_id)
            zone_cost = float(getattr(zone, "fishing_cost", 10) or 10)
        except Exception:
            zone_cost = 10.0

        recent_gross = self._recent_fishing_gross_value()
        catches = int(getattr(self.ctx.ai_user, "total_fishing_count", 0) or 0)
        earned = float(getattr(self.ctx.ai_user, "total_coins_earned", 0) or 0)
        long_term_gross = earned / catches if catches > 0 and earned > 0 else 0.0
        if recent_gross > 0 and long_term_gross > 0:
            # 近期中位数作为主值，同时不允许异常高价把收益估计抬得过高。
            gross_per_success = min(long_term_gross, recent_gross * 1.25)
        elif recent_gross > 0:
            gross_per_success = recent_gross
        elif long_term_gross > 0:
            gross_per_success = long_term_gross
        else:
            try:
                fishes = self.ctx.item_template_repo.get_all_fish()
                gross_per_success = sum(
                    float(getattr(fish, "base_value", 0) or 0) for fish in fishes
                ) / max(1, len(fishes))
            except Exception:
                gross_per_success = 0.0

        # go_fish 的基础成功率为 70%，未把装备/鱼饵额外收益计入，保持保守。
        return max(0.0, casts * (gross_per_success * 0.7 - zone_cost))

    def _recent_social_value(self, operation: str) -> float:
        try:
            values = self.ctx.statistics_repo.get_recent_success_values(
                self.ctx.ai_user_id, operation, 168, 100
            )
            return float(median(values)) if values else 0.0
        except Exception:
            return 0.0

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
        refine_floor = self.REFINE_RESERVE_COINS
        return max(refine_floor, fishing_cost + electric_buffer)

    def _count(self, effect_type: str) -> int:
        return sum(quantity for _, quantity in self._find_by_effect(effect_type))

    def _pond_value(self) -> float:
        total = 0.0
        try:
            for item in self.ctx.inventory_repo.get_fish_inventory(self.ctx.ai_user_id):
                template = self.ctx.item_template_repo.get_fish_by_id(item.fish_id)
                if template:
                    unit_val = getattr(item, "unit_value", 0) or calculate_fish_unit_value(
                        template.base_value, getattr(item, "quality_level", 0) or 0, 0.0
                    )
                    total += float(unit_val * int(item.quantity))
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
        affected_target_id = result.get("target_id")
        features = {
            "item_id": item_id,
            "category": result.get("category", "utility"),
        }
        if result.get("decision_target_id"):
            features["decision_target_id"] = result["decision_target_id"]
        snapshot_id = self.ctx.snapshot.create(
            action_type="item_use",
            target_id=affected_target_id,
            features=features,
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
        if result.get("success"):
            self.ctx.broadcast.item_used(
                result.get("item_name", f"道具#{item_id}"),
                result.get("category", "utility"),
                target_id=affected_target_id,
            )
            if self.ctx.notification_service and affected_target_id:
                self.ctx.notification_service.notify_social_result(
                    action_type=(
                        "dispel_protection"
                        if result.get("reason") == "high_value_target_disperse"
                        else "item_use"
                    ),
                    recipient_id=affected_target_id,
                    sender_id=self.ctx.ai_user_id,
                    sender_nickname=self.ctx.ai_nickname,
                    result=result,
                )
        else:
            self.ctx.broadcast.item_failed(
                result.get("item_name", f"道具#{item_id}"),
                result.get("message", "未知错误"),
            )

    def _use_generic(
        self,
        item_id: int,
        *,
        category: str,
        reason: str,
        estimated_value: float = 0.0,
        target_id: Optional[str] = None,
        decision_target_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        before = int(getattr(self.ctx.ai_user, "coins", 0) or 0)
        result = dict(self.ctx.inventory_service.use_item(self.ctx.ai_user_id, item_id))
        try:
            template = self.ctx.item_template_repo.get_item_by_id(item_id)
            result["item_name"] = getattr(template, "name", f"道具#{item_id}")
        except Exception:
            result["item_name"] = f"道具#{item_id}"
        result.update(
            {
                "category": category,
                "reason": reason,
                "estimated_value": estimated_value,
                "target_id": target_id,
                "decision_target_id": decision_target_id,
            }
        )
        self._record_item_use(item_id, before, result)
        return result

    def prepare_social_target(
        self, target_id: str, features: Dict[str, Any], operation: str
    ) -> Dict[str, Any]:
        """为护盾目标准备道具；准备成功后当前动作继续执行。"""
        layers = int(features.get("target_protection_layers", 0) or 0)
        if layers <= 0:
            return {"ready": True, "prepared": False}
        if self._has_active_buff("STEAL_PENETRATION_BUFF") or self._has_active_buff(
            "SHADOW_CLOAK_BUFF"
        ):
            return {"ready": True, "prepared": False}
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
                    "item_name": getattr(template, "name", f"道具#{template.item_id}"),
                    "category": "social",
                    "reason": "high_value_target_disperse",
                    "estimated_value": value,
                    "target_id": target_id,
                }
            )
            self._record_item_use(template.item_id, int(self.ctx.ai_user.coins), result)
            prepared = bool(result.get("success"))
            return {"ready": prepared, "prepared": prepared, "result": result}

        # 没有驱灵香时只在高价值目标上预装穿透/斗篷，准备成功后当前 tick 继续攻击。
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
                decision_target_id=target_id,
            )
            prepared = bool(result.get("success"))
            return {"ready": prepared, "prepared": prepared, "result": result}
        return {"ready": False, "prepared": False, "reason": "protected_without_economical_item"}

    def prepare_electric_fish(
        self, target_id: str, expected_value: float
    ) -> Optional[Dict[str, Any]]:
        """在有效电鱼前激活雷鸣护符，避免该道具只进库存不被使用。"""
        if expected_value <= 0 or self._has_active_buff("ELECTRIC_FISH_SUCCESS_BOOST"):
            return None
        options = sorted(
            self._find_by_effect("ELECTRIC_FISH_SUCCESS_BOOST"),
            key=lambda pair: int(getattr(pair[0], "rarity", 0) or 0),
        )
        if not options:
            return None
        template, _ = options[0]
        return self._use_generic(
            template.item_id,
            category="social",
            reason="prepare_electric_fish_success_boost",
            estimated_value=expected_value,
            decision_target_id=target_id,
        )

    def use_steal_reset(self, target_id: str, expected_value: float) -> Optional[Dict[str, Any]]:
        """仅在剩余游戏冷却和目标预期收益都足够高时重置偷鱼。"""
        now = time.time()
        recent_value = self._recent_social_value("steal")
        min_expected = max(
            self.STEAL_RESET_MIN_EXPECTED_VALUE,
            recent_value * 4.0,
        )
        if expected_value < min_expected:
            return None

        cooldown = max(
            60,
            int(self.ctx.global_config.get("steal", {}).get("cooldown_seconds", 14400)),
        )
        try:
            elapsed = max(0.0, now - self.ctx.ai_user.last_steal_time.timestamp())
        except (AttributeError, TypeError, ValueError, OSError):
            elapsed = 0.0
        remaining = max(0.0, cooldown - elapsed)
        if remaining < cooldown * self.STEAL_RESET_MIN_REMAINING_RATIO:
            return None

        options = self._find_by_effect("RESET_STEAL_COOLDOWN")
        if not options:
            return None
        template, quantity = options[0]
        # 以库存安全线控制消耗，不再单纯按 tick 或时间限制。
        if quantity <= self.STEAL_RESET_STOCK_RESERVE:
            return None
        return self._use_generic(
            template.item_id,
            category="social",
            reason="high_value_revenge_target_cooldown_reset",
            estimated_value=expected_value,
            decision_target_id=target_id,
        )

    def use_one_utility_item(self) -> Optional[Dict[str, Any]]:
        """根据当前资源和 Buff 状态选择一个通用道具，不使用人工时间节流。"""
        coins = int(getattr(self.ctx.ai_user, "coins", 0) or 0)
        reserve = self.coin_reserve()

        # 只在金币明显低于储备金时补充，并选择接近缺口的面额。
        bag = self._select_coin_bag(coins, reserve)
        if bag is not None:
            return self._use_generic(
                bag.item_id,
                category="utility",
                reason="below_operating_reserve",
                estimated_value=max(0, reserve - coins),
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
            if not self._has_active_buff(effect):
                max_rarity = 3
                if pond_value >= 1000000:
                    max_rarity = 6
                elif pond_value >= 500000:
                    max_rarity = 4
                options = [
                    pair
                    for pair in self._find_by_effect(effect)
                    if int(getattr(pair[0], "rarity", 0) or 0) <= max_rarity
                ]
                options.sort(
                    key=lambda pair: -int(getattr(pair[0], "rarity", 0) or 0)
                )
                if options:
                    template, quantity = options[0]
                    return self._use_generic(
                        template.item_id,
                        category="social",
                        reason="incoming_attack_or_valuable_pond",
                        estimated_value=pond_value,
                    )

        # 稀有鱼配额未耗尽时，使用低级幸运药水；高级圣水只在低级库存不足时使用。
        rare_remaining = self._rare_fish_remaining()
        if (
            rare_remaining >= self.RARE_FISH_MIN_REMAINING_QUOTA
            and not self._has_active_buff("RARE_FISH_BOOST")
        ):
            options = sorted(
                self._find_by_effect("RARE_FISH_BOOST"),
                key=lambda pair: int(getattr(pair[0], "rarity", 0) or 0),
            )
            for template, quantity in options:
                reserve_units = 5 if int(getattr(template, "rarity", 0) or 0) < 5 else 1
                duration = int(self._effect_payload(template).get("duration_seconds", 600) or 600)
                effective_casts = self._effective_casts(duration)
                if (
                    quantity > reserve_units
                    and effective_casts >= self.RARE_FISH_MIN_EFFECTIVE_CASTS
                    and rare_remaining >= max(
                        self.RARE_FISH_MIN_REMAINING_QUOTA, effective_casts
                    )
                    and self._available_bait_units() >= self.RARE_FISH_MIN_BAIT_UNITS
                    and self._pond_has_room(effective_casts)
                    and self._estimated_fishing_net_value(effective_casts) > 0
                ):
                    return self._use_generic(
                        template.item_id,
                        category="fishing",
                        reason="rare_fish_quota_available",
                        estimated_value=self._estimated_fishing_net_value(effective_casts),
                    )

        # 声呐只在当前钓鱼原生冷却尚未结束时介入，是否开启自动钓鱼不参与判断。
        # 冷却已结束时，让正常钓鱼流程处理，避免把声呐当成固定频率的额外钓鱼券。
        cooldown = float(self._fishing_cooldown())
        cooldown_remaining = self._fishing_cooldown_remaining()
        if cooldown_remaining > 0 and not self._has_active_buff("RARE_FISH_BOOST"):
            sonar = self._find_by_effect("RESET_FISHING_COOLDOWN")
            estimated_net_value = self._estimated_fishing_net_value()
            if (
                sonar
                and coins >= reserve
                and estimated_net_value >= self.SONAR_MIN_NET_VALUE
                and cooldown_remaining >= cooldown * self.SONAR_MIN_COOLDOWN_RATIO
                and self._available_bait_units() >= self.SONAR_MIN_REMAINING_BAIT
                and self._pond_has_room(1)
            ):
                template, quantity = sonar[0]
                if quantity > self.SONAR_STOCK_RESERVE:
                    return self._use_generic(
                        template.item_id,
                        category="fishing",
                        reason="profitable_extra_fishing",
                        estimated_value=estimated_net_value,
                    )
        return None
