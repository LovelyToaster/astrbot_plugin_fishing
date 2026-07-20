"""动作：耐久降到 ≤1/2 时修复鱼竿（无节流，装备中优先）。"""

from ..ai_context import AIContext
from .base import AIAction


class RepairRodAction(AIAction):
    name = "repair_rod"

    def __init__(self):
        pass

    def _execute(self, ctx: AIContext) -> None:
        result = ctx.inventory_service.get_user_rod_inventory(ctx.ai_user_id)
        rods = result.get("rods", [])
        if not rods:
            return

        # 候选：耐久 ≤ 1/2 且未锁定（无限耐久 current_durability=None 会被跳过）
        candidates = [
            r
            for r in rods
            if r.get("current_durability") is not None
            and r.get("max_durability") is not None
            and r.get("current_durability") * 2 <= r.get("max_durability")
            and not r.get("is_locked", False)
        ]
        if not candidates:
            return

        # 装备中的优先（is_equipped=True 排在前）
        candidates = sorted(
            candidates,
            key=lambda r: (not r.get("is_equipped", False), r.get("instance_id")),
        )

        for r in candidates:
            res = ctx.inventory_service.repair_rod(ctx.ai_user_id, r["instance_id"])
            if res.get("success"):
                ctx.broadcast.repaired(
                    r.get("name", "未知"),
                    res.get("new_durability", r.get("max_durability")),
                )
                # 修复扣金币，刷新用户对象
                ctx.refresh_ai_user()
