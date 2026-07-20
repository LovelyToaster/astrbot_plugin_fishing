"""动作：装备最优饰品（幂等）。

参见 `equip_best_rod.py` 的说明：AI 层显式按**精炼后综合属性评分**
寻找理论最优，避免 InventoryService 排序把已装备的固定放在最前。

评分函数：在鱼竿评分基础上额外加 `bonus_coin_modifier`
（缺失值以 0 兜底），不再依赖 rarity / refine_level 排序。
"""

from astrbot.api import logger

from ..ai_context import AIContext
from .base import AIAction


def _acc_score(a: dict) -> float:
    return (
        (a.get("bonus_fish_quality_modifier") or 0)
        + (a.get("bonus_fish_quantity_modifier") or 0)
        + (a.get("bonus_rare_fish_chance") or 0)
        + (a.get("bonus_coin_modifier") or 0)
    )


class EquipBestAccessoryAction(AIAction):
    name = "equip_best_accessory"

    def _execute(self, ctx: AIContext) -> None:
        result = ctx.inventory_service.get_user_accessory_inventory(ctx.ai_user_id)
        accessories = result.get("accessories", [])
        if not accessories:
            return

        best = max(accessories, key=_acc_score)
        if best.get("is_equipped", False):
            return

        equip_result = ctx.inventory_service.equip_item(
            ctx.ai_user_id, best["instance_id"], "accessory"
        )
        if equip_result.get("success"):
            name = best.get("name", "未知")
            rarity = int(best.get("rarity", 0) or 0)
            logger.info(f"[AI] 装备最优饰品: {name} (rarity={rarity})")
            ctx.broadcast.equipped_accessory(name, rarity)
            ctx.refresh_ai_user()
