"""动作：按动态储备使用一个社交/钓鱼/金币道具。"""

from astrbot.api import logger

from ..ai_context import AIContext
from .base import AIAction


class UseItemsAction(AIAction):
    name = "use_items"

    def _execute(self, ctx: AIContext) -> None:
        if not ctx.ai_config.get("item_strategy_enabled", True):
            return
        result = ctx.item_strategy.use_one_utility_item()
        if result and result.get("success"):
            logger.info(f"[AI] 道具策略使用成功: {result.get('reason', 'unknown')}")
            ctx.refresh_ai_user()
