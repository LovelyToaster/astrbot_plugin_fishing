"""
动作：智能金币抽卡（间隔节流 + 单抽/十连决策 + 按池权重期望稀有度决策）。

原有逻辑：每隔 paid_interval_seconds 触发一次，按"单抽消耗 ≤ 当前金币 × spending_ratio"
筛选可负担的金币池，挑选 cost_coins 最高的池进行一次单抽。

本次升级：
- 新增「十连」支持：当 ten_pull_enabled 且十连总消耗（cost_coins × 10）落在
  coins × spending_ratio × ten_pull_multiplier 预算内时，优先抽十连；否则回退单抽。
- 引入「按池权重（期望稀有度）决策」：不再简单挑最贵的池，而是对每个候选池计算
  score = Σ(weight_i × value_i) / Σ(weight_i)，取期望值最高的池下手。
  value 取值：rod/accessory/bait/item → template.rarity；coins → max(1, quantity // 100000)；
  titles → 0；其它 → 0。
"""

import time

from astrbot.api import logger

from ..ai_context import AIContext
from .base import AIAction


def score_pool(ctx: AIContext, pool) -> float:
    """按池内物品权重计算期望稀有度评分（越高越值得抽）。

    返回归一化到 [0, +∞) 的期望值；无法计算或无物品时返回 0.0。
    """
    items = getattr(pool, "items", [])
    if not items:
        return 0.0

    total = sum((getattr(it, "weight", 0) or 0) for it in items)
    if total <= 0:
        return 0.0

    score = 0.0
    for it in items:
        w = getattr(it, "weight", 0) or 0
        itype = getattr(it, "item_type", "")
        iid = getattr(it, "item_id", 0)

        if itype == "coins":
            value = max(1, (getattr(it, "quantity", 0) or 0) // 100000)
        elif itype == "titles":
            value = 0
        elif itype in ("rod", "accessory", "bait", "item"):
            if itype == "rod":
                tmpl = ctx.item_template_repo.get_rod_by_id(iid)
            elif itype == "accessory":
                tmpl = ctx.item_template_repo.get_accessory_by_id(iid)
            elif itype == "bait":
                tmpl = ctx.item_template_repo.get_bait_by_id(iid)
            else:  # item
                tmpl = ctx.item_template_repo.get_by_id(iid)
            value = getattr(tmpl, "rarity", 0) or 0
        else:
            value = 0

        score += w * value

    return score / total


class PaidGachaAction(AIAction):
    name = "paid_gacha"

    def __init__(
        self,
        paid_interval_seconds: int,
        spending_ratio: float,
        ten_pull_enabled: bool,
        ten_pull_multiplier: float,
    ):
        self.paid_interval_seconds = int(paid_interval_seconds)
        self.spending_ratio = float(spending_ratio)
        self.ten_pull_enabled = bool(ten_pull_enabled)
        self.ten_pull_multiplier = float(ten_pull_multiplier)

    def _execute(self, ctx: AIContext) -> None:
        # 1. 间隔节流（原有逻辑保留）
        if time.time() - ctx.state.last_paid_gacha_ts < self.paid_interval_seconds:
            return

        # 2. 重新拉取，以获取准确金币数
        ctx.refresh_ai_user()
        ai_user = ctx.ai_user
        if not ai_user:
            return

        # 3. 拉取全部卡池
        pools_result = ctx.gacha_service.get_all_pools()
        pools = pools_result.get("pools", [])

        # 4. 只筛选金币池：cost_premium_currency == 0 且 cost_coins > 0
        candidates = [
            p
            for p in pools
            if getattr(p, "cost_premium_currency", 0) == 0
            and getattr(p, "cost_coins", 0) > 0
        ]
        if not candidates:
            return

        # 5. 预算计算
        single_budget = ai_user.coins * self.spending_ratio
        ten_budget = ai_user.coins * self.spending_ratio * self.ten_pull_multiplier

        # 6. 决策：十连优先，单抽兜底
        best = None
        num = 1
        is_ten = False

        if self.ten_pull_enabled:
            ten_candidates = [
                p
                for p in candidates
                if getattr(p, "cost_coins", 0) * 10 <= ten_budget
            ]
            if ten_candidates:
                best = max(ten_candidates, key=lambda p: score_pool(ctx, p))
                num = 10
                is_ten = True

        if best is None:
            single_candidates = [
                p
                for p in candidates
                if getattr(p, "cost_coins", 0) <= single_budget
            ]
            if not single_candidates:
                return
            best = max(single_candidates, key=lambda p: score_pool(ctx, p))
            num = 1

        # 7. 执行抽卡
        result = ctx.gacha_service.perform_draw(
            ctx.ai_user_id, best.gacha_pool_id, num
        )
        if not result.get("success"):
            return

        # 8. 记录节流时间戳 + 广播
        ctx.state.set("last_paid_gacha_ts", time.time())
        cost = getattr(best, "cost_coins", 0) * num
        logger.info(
            f"[AI] 金币抽卡成功: 池={best.name}, "
            f"十连={is_ten}, 次数={num}, 消耗={cost}"
        )
        ctx.broadcast.gacha_result(best.name, result.get("results", []))
