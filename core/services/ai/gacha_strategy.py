"""AI 抽卡卡池价值评估。"""

from typing import Any, Dict, Iterable, Optional


class GachaStrategy:
    """按可兑现价值、重复折损和保底紧迫度选择卡池。"""

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
                data = self.ctx.inventory_repo.get_user_bait_inventory(self.ctx.ai_user_id)
                return int(data.get(item_id, 0) or 0)
            if item_type == "item":
                return int(
                    self.ctx.inventory_repo.get_user_item_inventory(self.ctx.ai_user_id).get(item_id, 0)
                )
            if item_type == "rod":
                return len([
                    item for item in self.ctx.inventory_service.get_user_rod_inventory(self.ctx.ai_user_id).get("rods", [])
                    if int(item.get("rod_id", -1)) == item_id
                ])
            if item_type == "accessory":
                return len([
                    item for item in self.ctx.inventory_service.get_user_accessory_inventory(self.ctx.ai_user_id).get("accessories", [])
                    if int(item.get("accessory_id", -1)) == item_id
                ])
        except Exception:
            return 0
        return 0

    def item_value(self, item) -> float:
        item_type = getattr(item, "item_type", "")
        item_id = int(getattr(item, "item_id", 0) or 0)
        quantity = int(getattr(item, "quantity", 1) or 1)
        if item_type == "coins":
            return float(quantity)
        template = self._template(item_type, item_id)
        rarity = float(getattr(template, "rarity", 0) or 0)
        owned = self._inventory_quantity(item_type, item_id)
        if item_type in ("rod", "accessory"):
            # 重复装备仍可出售，但价值显著低于可替换的更高稀有度装备。
            current = 0
            try:
                inventory = (
                    self.ctx.inventory_service.get_user_rod_inventory(self.ctx.ai_user_id)
                    if item_type == "rod"
                    else self.ctx.inventory_service.get_user_accessory_inventory(self.ctx.ai_user_id)
                )
                key = "rarity"
                current = max(
                    [int(entry.get(key, 0) or 0) for entry in inventory.get("rods" if item_type == "rod" else "accessories", [])]
                    or [0]
                )
            except Exception:
                pass
            return (rarity * 25000.0 if rarity > current else rarity * 5000.0) / max(1, owned)
        if item_type == "bait":
            return rarity * 120.0 * quantity / max(1, owned // 20 + 1)
        if item_type == "item":
            return rarity * 5000.0 / max(1, owned // 10 + 1)
        return rarity * 1000.0

    def score_pool(self, pool) -> Dict[str, Any]:
        items = list(getattr(pool, "items", []) or [])
        total_weight = sum(int(getattr(item, "weight", 0) or 0) for item in items)
        if total_weight <= 0:
            return {"score": 0.0, "expected_value": 0.0, "pity": 0, "draws_to_pity": None}
        expected = sum(
            int(getattr(item, "weight", 0) or 0) * self.item_value(item)
            for item in items
        ) / total_weight
        cost = int(getattr(pool, "cost_coins", 0) or 0)
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
        pity_bonus = 0.0
        if draws_to_pity is not None and draws_to_pity <= 10:
            max_rarity = max(
                [getattr(self._template(item.item_type, item.item_id), "rarity", 0) or 0 for item in items]
                or [0]
            )
            pity_bonus = max_rarity * 10000.0 / max(1, draws_to_pity)
        return {
            "score": expected + pity_bonus - cost,
            "expected_value": expected,
            "pity": pity,
            "draws_to_pity": draws_to_pity,
            "cost": cost,
            "pity_bonus": pity_bonus,
        }

    def choose(self, pools: Iterable) -> Optional[tuple]:
        scored = [(pool, self.score_pool(pool)) for pool in pools]
        scored = [pair for pair in scored if pair[1]["score"] > 0]
        if not scored:
            return None
        scored.sort(key=lambda pair: pair[1]["score"], reverse=True)
        return scored[0]
