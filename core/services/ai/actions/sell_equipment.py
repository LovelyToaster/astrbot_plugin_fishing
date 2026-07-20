"""动作：有未装备且未锁定的多余鱼竿 / 饰品即卖（条件触发，无时间节流）。

每次 tick 检查背包：只要存在"未装备且未锁定"的鱼竿或饰品，就通过
`InventoryService.sell_all_rods` / `sell_all_accessories` 卖出
（这两个方法内部会自动跳过已装备与上锁的实例）。没有任何可卖装备时
直接返回，避免无谓调用。
"""

from astrbot.api import logger

from ..ai_context import AIContext
from .base import AIAction, parse_int_safe


class SellEquipmentAction(AIAction):
    name = "sell_equipment"

    def __init__(self):
        pass

    def _execute(self, ctx: AIContext) -> None:
        rod_res = ctx.inventory_service.get_user_rod_inventory(ctx.ai_user_id)
        acc_res = ctx.inventory_service.get_user_accessory_inventory(ctx.ai_user_id)

        sellable_rods = [
            r
            for r in rod_res.get("rods", [])
            if not r.get("is_equipped", False) and not r.get("is_locked", False)
        ]
        sellable_accs = [
            a
            for a in acc_res.get("accessories", [])
            if not a.get("is_equipped", False) and not a.get("is_locked", False)
        ]

        # 没有任何可卖装备，直接返回
        if not sellable_rods and not sellable_accs:
            return

        rod_result = (
            ctx.inventory_service.sell_all_rods(ctx.ai_user_id)
            if sellable_rods
            else {"success": False}
        )
        acc_result = (
            ctx.inventory_service.sell_all_accessories(ctx.ai_user_id)
            if sellable_accs
            else {"success": False}
        )

        if not (rod_result.get("success") or acc_result.get("success")):
            return

        logger.info(
            f"[AI] 卖装备: 鱼竿={rod_result.get('success', False)}, "
            f"饰品={acc_result.get('success', False)}"
        )

        total_n = 0
        total_v = 0
        for r in (rod_result, acc_result):
            if not r.get("success"):
                continue
            msg_text = r.get("message", "")
            # 格式: "💰 成功卖出 N 根鱼竿/件饰品，获得 V 金币"
            parts = msg_text.split("卖出")
            if len(parts) > 1:
                n_part = parts[1].split("根")[0].split("件")[0].strip()
                total_n += parse_int_safe(n_part)
            if "获得" in msg_text:
                after = msg_text.split("获得", 1)[1].strip()
                if "金币" in after:
                    total_v += parse_int_safe(after.split("金币")[0].strip())

        if total_n > 0:
            ctx.broadcast.sold_equipment(total_n, total_v)

        # 卖装备可能改变金币，刷新
        ctx.refresh_ai_user()
