"""AI 抽卡策略：按卡池用途、库存缺口和装备升级机会评估。"""

from typing import Any, Dict, Iterable, Optional


class GachaStrategy:
    """把卡池奖品转成可解释的运营价值。"""

    # 这些是策略安全线，不是抽卡频率；库存达到安全线后不再为重复道具加分。
    ITEM_TARGETS = {
        2: 8,   # 幸运药水
        3: 12,  # 声呐
        4: 10,  # 偷鱼重置
        14: 4,  # 普通守护
        16: 2,  # 破灵符
        17: 2,  # 驱灵香
        18: 4,  # 暗影斗篷
        21: 2,  # 高级圣水
        23: 2,  # 至尊守护
        26: 1,  # 雷鸣护符
    }
    BAIT_TARGET_UNITS = 8

    def __init__(self, context):
        self.ctx = context

    def _template(self, item_type: str, item_id: int):
        repo = self.ctx.item_template_repo
        if item_type == "rod":
            return repo.get_rod_by_id(item_id)
        if item_type == "accessory":
            return repo.get_accessory_by_id(item_id)
        if item_type == "bait":
            return repo.get_bait_by_id(item_id)
        if item_type == "item":
            return repo.get_by_id(item_id)
        return None

    def _inventory_quantity(self, item_type: str, item_id: int) -> int:
        try:
            if item_type == "bait":
                data = self.ctx.inventory_repo.get_user_bait_inventory(
                    self.ctx.ai_user_id
                )
                return int(data.get(item_id, 0) or 0)
            if item_type == "item":
                data = self.ctx.inventory_repo.get_user_item_inventory(
                    self.ctx.ai_user_id
                )
                return int(data.get(item_id, 0) or 0)
            if item_type == "rod":
                inventory = self.ctx.inventory_service.get_user_rod_inventory(
                    self.ctx.ai_user_id
                )
                return len(
                    [
                        item
                        for item in inventory.get("rods", [])
                        if int(item.get("rod_id", -1)) == item_id
                    ]
                )
            if item_type == "accessory":
                inventory = self.ctx.inventory_service.get_user_accessory_inventory(
                    self.ctx.ai_user_id
                )
                return len(
                    [
                        item
                        for item in inventory.get("accessories", [])
                        if int(item.get("accessory_id", -1)) == item_id
                    ]
                )
        except Exception:
            return 0
        return 0

    def _total_bait(self) -> int:
        try:
            inventory = self.ctx.inventory_repo.get_user_bait_inventory(
                self.ctx.ai_user_id
            )
            return sum(max(0, int(quantity or 0)) for quantity in inventory.values())
        except Exception:
            return 0

    def _current_gear_rarity(self, item_type: str) -> int:
        key = "rods" if item_type == "rod" else "accessories"
        getter = (
            self.ctx.inventory_service.get_user_rod_inventory
            if item_type == "rod"
            else self.ctx.inventory_service.get_user_accessory_inventory
        )
        try:
            inventory = getter(self.ctx.ai_user_id)
            return max(
                [int(entry.get("rarity", 0) or 0) for entry in inventory.get(key, [])]
                or [0]
            )
        except Exception:
            return 0

    def _current_highest_gear_rarity(self) -> int:
        return max(
            self._current_gear_rarity("rod"),
            self._current_gear_rarity("accessory"),
        )

    def _pool_kind(self, items) -> str:
        types = {getattr(item, "item_type", "") for item in items}
        if types and types <= {"rod", "accessory"}:
            return "equipment"
        if types and types <= {"item"}:
            return "item"
        if types and types <= {"bait"}:
            return "bait"
        if "rod" in types or "accessory" in types:
            return "equipment_mixed"
        if "item" in types:
            return "item_mixed"
        if "bait" in types:
            return "bait_mixed"
        return "other"

    def _fishing_value_per_cast(self) -> float:
        try:
            return max(
                0.0,
                float(self.ctx.item_strategy._estimated_fishing_net_value(1)),
            )
        except Exception:
            return 0.0

    def item_value(self, item) -> float:
        item_type = getattr(item, "item_type", "")
        item_id = int(getattr(item, "item_id", 0) or 0)
        quantity = max(1, int(getattr(item, "quantity", 1) or 1))
        if item_type == "coins":
            return float(quantity)

        template = self._template(item_type, item_id)
        rarity = float(getattr(template, "rarity", 0) or 0)
        owned = self._inventory_quantity(item_type, item_id)

        if item_type in ("rod", "accessory"):
            current = self._current_gear_rarity(item_type)
            if rarity > current:
                # 直接升级价值独立于出售价值，避免高价终极池永远输给低价池。
                return 150000.0 + (rarity - current) * 100000.0 + rarity * 10000.0
            return rarity * 8000.0 / max(1, owned)

        if item_type == "bait":
            deficit = max(0, self.BAIT_TARGET_UNITS - self._total_bait())
            if deficit > 0:
                return self._fishing_value_per_cast() * quantity + rarity * 2000.0
            return rarity * 1000.0 * quantity / max(1, owned + 1)

        if item_type == "item":
            target = self.ITEM_TARGETS.get(item_id, 0)
            missing = max(0, target - owned)
            if missing > 0:
                return (20000.0 + rarity * 10000.0) * min(quantity, missing)
            return rarity * 750.0 * quantity / max(1, owned // 10 + 1)

        return rarity * 1000.0

    def _profile(self, items, total_weight: int) -> Dict[str, Any]:
        current_gear = self._current_highest_gear_rarity()
        upgrade_weight = 0
        highest_upgrade_rarity = 0
        item_deficit_weight = 0
        bait_deficit_weight = 0
        target_item_id = None

        for item in items:
            weight = int(getattr(item, "weight", 0) or 0)
            item_type = getattr(item, "item_type", "")
            template = self._template(
                item_type, int(getattr(item, "item_id", 0) or 0)
            )
            rarity = int(getattr(template, "rarity", 0) or 0)
            if item_type in ("rod", "accessory"):
                current_type_rarity = self._current_gear_rarity(item_type)
                if rarity > current_type_rarity:
                    upgrade_weight += weight
                    highest_upgrade_rarity = max(highest_upgrade_rarity, rarity)
            elif item_type == "item":
                item_id = int(getattr(item, "item_id", 0) or 0)
                owned = self._inventory_quantity(item_type, item_id)
                if owned < self.ITEM_TARGETS.get(item_id, 0):
                    item_deficit_weight += weight
                    if target_item_id is None:
                        target_item_id = item_id
            elif item_type == "bait":
                if self._total_bait() < self.BAIT_TARGET_UNITS:
                    bait_deficit_weight += weight

        return {
            "pool_kind": self._pool_kind(items),
            "current_gear_rarity": current_gear,
            "highest_upgrade_rarity": highest_upgrade_rarity,
            "upgrade_probability": (
                float(upgrade_weight) / total_weight if total_weight else 0.0
            ),
            "direct_upgrade": upgrade_weight > 0,
            "item_deficit_probability": (
                float(item_deficit_weight) / total_weight if total_weight else 0.0
            ),
            "bait_deficit_probability": (
                float(bait_deficit_weight) / total_weight if total_weight else 0.0
            ),
            "target_item_id": target_item_id,
        }

    def score_pool(self, pool) -> Dict[str, Any]:
        items = list(getattr(pool, "items", []) or [])
        total_weight = sum(int(getattr(item, "weight", 0) or 0) for item in items)
        cost = int(getattr(pool, "cost_coins", 0) or 0)
        if total_weight <= 0:
            return {
                "score": 0.0,
                "expected_value": 0.0,
                "pity": 0,
                "draws_to_pity": None,
                "cost": cost,
                "pity_bonus": 0.0,
                "pool_kind": "other",
                "direct_upgrade": False,
                "decision_reason": "empty_pool",
            }

        profile = self._profile(items, total_weight)
        expected = sum(
            int(getattr(item, "weight", 0) or 0) * self.item_value(item)
            for item in items
        ) / total_weight

        pity = 0
        try:
            data = self.ctx.gacha_service.gacha_repo.get_user_pity(
                self.ctx.ai_user_id, int(pool.gacha_pool_id)
            )
            pity = int(getattr(data, "current_pity", 0) or 0) if data else 0
        except Exception:
            pass

        threshold = int(getattr(self.ctx.gacha_service, "pity_threshold", 80) or 80)
        draws_to_pity = max(0, threshold - pity) if threshold > 0 else None
        max_rarity = max(
            [
                int(
                    getattr(
                        self._template(item.item_type, item.item_id),
                        "rarity",
                        0,
                    )
                    or 0
                )
                for item in items
            ]
            or [0]
        )
        best_value = max([self.item_value(item) for item in items] or [0.0])
        pity_bonus = 0.0
        if draws_to_pity is not None and 0 < draws_to_pity <= 10:
            pity_bonus = best_value / max(1, draws_to_pity)

        demand_bonus = 0.0
        if profile["direct_upgrade"]:
            demand_bonus = 50000.0 + profile["highest_upgrade_rarity"] * 10000.0
        elif profile["item_deficit_probability"] > 0:
            demand_bonus = 10000.0 * profile["item_deficit_probability"]
        elif profile["bait_deficit_probability"] > 0:
            demand_bonus = 5000.0 * profile["bait_deficit_probability"]

        priority = 0
        if profile["direct_upgrade"]:
            priority = 3
        elif profile["pool_kind"] in ("equipment", "equipment_mixed"):
            priority = 2
        elif (
            profile["item_deficit_probability"] > 0
            or profile["bait_deficit_probability"] > 0
        ):
            priority = 1

        if profile["direct_upgrade"]:
            decision_reason = "direct_high_rarity_equipment_upgrade"
        elif profile["item_deficit_probability"] > 0:
            decision_reason = "strategic_item_inventory_gap"
        elif profile["bait_deficit_probability"] > 0:
            decision_reason = "bait_inventory_gap"
        elif profile["pool_kind"] in ("equipment", "equipment_mixed"):
            decision_reason = "highest_available_equipment_tier"
        else:
            decision_reason = "positive_expected_net_value"

        score = expected + pity_bonus + demand_bonus - cost
        return {
            "score": score,
            "expected_value": expected,
            "net_value": expected - cost,
            "pity": pity,
            "draws_to_pity": draws_to_pity,
            "cost": cost,
            "pity_bonus": pity_bonus,
            "max_rarity": max_rarity,
            "priority": priority,
            "decision_reason": decision_reason,
            **profile,
        }

    def choose(self, pools: Iterable) -> Optional[tuple]:
        scored = [(pool, self.score_pool(pool)) for pool in pools]
        scored = [
            pair
            for pair in scored
            if pair[1]["score"] > 0 or pair[1].get("cost", 0) == 0
        ]
        if not scored:
            return None
        scored.sort(
            key=lambda pair: (
                pair[1].get("priority", 0),
                pair[1].get("highest_upgrade_rarity", 0),
                pair[1].get("score", 0),
            ),
            reverse=True,
        )
        return scored[0]
