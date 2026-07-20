"""动作：使用最优鱼饵（无饵或过期时才触发）。"""

from astrbot.api import logger

from ....utils import get_now
from ..ai_context import AIContext
from .base import AIAction


class UseBestBaitAction(AIAction):
    name = "use_best_bait"

    def _execute(self, ctx: AIContext) -> None:
        ai_user = ctx.ai_user

        # 1. 检查当前鱼饵是否仍有效
        if ai_user.current_bait_id is not None:
            bait_template = ctx.item_template_repo.get_bait_by_id(
                ai_user.current_bait_id
            )
            if bait_template:
                duration = bait_template.duration_minutes
                if duration > 0 and ai_user.bait_start_time is not None:
                    # 持续时间鱼饵：仍在有效期
                    if (get_now() - ai_user.bait_start_time).total_seconds() < duration * 60:
                        return
                elif duration == 0:
                    # 一次性鱼饵：依赖 go_fish 用完后自动清空
                    return

        # 2. 从背包挑稀有度最高的鱼饵
        bait_result = ctx.inventory_service.get_user_bait_inventory(ctx.ai_user_id)
        baits = bait_result.get("baits", [])
        if not baits:
            return

        baits.sort(key=lambda b: -b.get("rarity", 0))
        best_bait = baits[0]
        use_result = ctx.inventory_service.use_bait(ctx.ai_user_id, best_bait["bait_id"])
        if use_result.get("success"):
            logger.info(
                f"[AI] 使用鱼饵: {best_bait.get('name')} (rarity={best_bait.get('rarity')})"
            )
            ctx.refresh_ai_user()
