"""动作：装备最优鱼竿（幂等）。

`InventoryService.get_user_rod_inventory` 排序会把"已装备"放在最前，
即使背包里有综合属性更强的鱼竿也不会主动换装。AI 层必须自己按
**精炼后综合属性评分**选出"理论最优"，只有当它 ≠ 当前装备时才切换。

评分函数：`bonus_fish_quality_modifier + bonus_fish_quantity_modifier
+ bonus_rare_fish_chance`（缺失值以 0 兜底），不再依赖 rarity /
refine_level 排序。
"""

from astrbot.api import logger

from ..ai_context import AIContext
from .base import AIAction


def _rod_score(r: dict) -> float:
    return (
        (r.get("bonus_fish_quality_modifier") or 0)
        + (r.get("bonus_fish_quantity_modifier") or 0)
        + (r.get("bonus_rare_fish_chance") or 0)
    )


class EquipBestRodAction(AIAction):
    name = "equip_best_rod"

    def _execute(self, ctx: AIContext) -> None:
        result = ctx.inventory_service.get_user_rod_inventory(ctx.ai_user_id)
        rods = result.get("rods", [])
        if not rods:
            return

        # 按精炼后综合属性评分选出理论最优，忽略"已装备"标志
        best = max(rods, key=_rod_score)

        # 已经装备着最优的？跳过
        if best.get("is_equipped", False):
            return

        equip_result = ctx.inventory_service.equip_item(
            ctx.ai_user_id, best["instance_id"], "rod"
        )
        if equip_result.get("success"):
            name = best.get("name", "未知")
            rarity = int(best.get("rarity", 0) or 0)
            logger.info(f"[AI] 装备最优鱼竿: {name} (rarity={rarity})")
            ctx.broadcast.equipped_rod(name, rarity)
            # 装备变化，刷新用户对象（同时清候选缓存）
            ctx.refresh_ai_user()
