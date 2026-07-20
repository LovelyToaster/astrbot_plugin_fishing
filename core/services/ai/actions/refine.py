"""动作：精炼装备（无时间节流 + 预算闸门 + 成功后自动装备）。

决策：
- 先按 `reserve_coins` 预算闸门过滤（金币 < 储备金则整轮跳过）。
- 拉取 rod/accessory 库存，按模板（`rod_id`/`accessory_id`）分组，仅视未锁定
  实例为候选。
- 候选组：未锁定实例数 ≥ 2 且至少 1 个 `refine_level < 10`。
- 组内选"精炼等级最高且 < 10"的作精炼目标。
- 候选目标排序键 `(is_equipped 升序, rarity 降序, refine_level 升序)`——
  优先精炼未装备的高稀有度、低精炼等级（成功率高、费用低、不冒场上装备被毁风险）。
- 成功 → 广播 + 自动穿上 + 刷新 + 跳出（本轮只精炼一次）。
"""

from ..ai_context import AIContext
from .base import AIAction


class RefineAction(AIAction):
    name = "refine"

    def __init__(self, reserve_coins: int):
        self.reserve_coins = int(reserve_coins)

    def _execute(self, ctx: AIContext) -> None:
        # 预算闸门：金币不足储备金则整轮放弃（无时间节流）
        ctx.refresh_ai_user()
        if ctx.ai_user.coins < self.reserve_coins:
            return

        rod_res = ctx.inventory_service.get_user_rod_inventory(ctx.ai_user_id)
        acc_res = ctx.inventory_service.get_user_accessory_inventory(ctx.ai_user_id)
        rods = rod_res.get("rods", [])
        accessories = acc_res.get("accessories", [])

        rod_groups = self._group_by_template(rods)
        acc_groups = self._group_by_template(accessories)

        targets = []
        for item_type, groups in (("rod", rod_groups), ("accessory", acc_groups)):
            for template_id, instances in groups.items():
                # 候选组：未锁定实例数 ≥ 2 且至少 1 个 refine_level < 10
                if len(instances) < 2:
                    continue
                if not any(inst.get("refine_level", 1) < 10 for inst in instances):
                    continue
                # 组内选"精炼等级最高且 < 10"的作目标
                eligible = [i for i in instances if i.get("refine_level", 1) < 10]
                if not eligible:
                    continue
                target = dict(max(eligible, key=lambda i: i.get("refine_level", 1)))
                target["_item_type"] = item_type
                targets.append(target)

        if not targets:
            return

        # 排序：优先精炼未装备、高稀有度、低精炼等级
        targets.sort(
            key=lambda r: (
                r.get("is_equipped", False),
                -r.get("rarity", 0),
                r.get("refine_level", 1),
            )
        )

        for target in targets:
            item_type = target.get("_item_type")
            result = ctx.inventory_service.refine(
                ctx.ai_user_id, target["instance_id"], item_type
            )
            result = result or {}
            message = result.get("message", "") or ""

            # 成功（含 success 且非 failed）
            if result.get("success") and not result.get("failed"):
                new_level = target["refine_level"] + 1
                ctx.broadcast.refined(target.get("name", "未知"), new_level)
                # 精炼成功后自动穿上
                ctx.inventory_service.equip_item(
                    ctx.ai_user_id, target["instance_id"], item_type
                )
                ctx.refresh_ai_user()
                break

            # 金币不足 → 整体放弃本轮
            if "金币不足" in message:
                break

            # 材料/满级不匹配 → 试下一个候选
            if "需要至少两个" in message or "最高精炼" in message:
                continue

            # 随机失败（已扣费）→ 跳出
            if result.get("failed"):
                break

    @staticmethod
    def _group_by_template(items) -> dict:
        """按模板（rod_id/accessory_id）分组，仅未锁定实例纳入。"""
        groups = {}
        for inst in items:
            if inst.get("is_locked", False):
                continue
            template_id = inst.get("rod_id") or inst.get("accessory_id")
            if template_id is None:
                continue
            groups.setdefault(template_id, []).append(inst)
        return groups
