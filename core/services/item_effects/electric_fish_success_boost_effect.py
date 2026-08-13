import json
from typing import Any, Dict

from .abstract_effect import AbstractItemEffect
from ...domain.models import Item, User, UserBuff
from ...utils import get_now


class ElectricFishSuccessBoostEffect(AbstractItemEffect):
    """为下一次有效电鱼提供成功率和抽取数量加成。"""

    effect_type = "ELECTRIC_FISH_SUCCESS_BOOST"

    def apply(
        self, user: User, item_template: Item, payload: Dict[str, Any], quantity: int = 1
    ) -> Dict[str, Any]:
        if not self.buff_repo:
            return {"success": False, "message": "电鱼概率效果仓储不可用。"}

        if quantity != 1:
            return {
                "success": False,
                "message": f"【{item_template.name}】不可叠加，请一次使用一个。",
            }

        try:
            bonus_rate = float(payload.get("bonus_rate", 0.2))
            max_rate = float(payload.get("max_rate", 1.0))
            fish_count_multiplier = float(
                payload.get("fish_count_multiplier", 1.1)
            )
        except (TypeError, ValueError):
            return {"success": False, "message": "电鱼概率效果配置无效。"}

        if bonus_rate <= 0 or fish_count_multiplier < 1.0:
            return {"success": False, "message": "电鱼概率加成配置无效。"}

        bonus_rate = min(1.0, bonus_rate)
        max_rate = min(1.0, max(0.0, max_rate))
        buff_type = self.effect_type
        existing_buff = self.buff_repo.get_active_by_user_and_type(
            user.user_id, buff_type
        )
        if existing_buff:
            return {
                "success": False,
                "message": f"你已经激活了【{item_template.name}】，请先完成本次电鱼后再使用。",
            }

        now = get_now().replace(tzinfo=None)
        new_buff = UserBuff(
            id=0,
            user_id=user.user_id,
            buff_type=buff_type,
            payload=json.dumps(
                {
                    "bonus_rate": bonus_rate,
                    "max_rate": max_rate,
                    "fish_count_multiplier": fish_count_multiplier,
                }
            ),
            started_at=now,
            expires_at=None,
        )
        self.buff_repo.add(new_buff)

        return {
            "success": True,
            "message": (
                f"⚡ {item_template.name}已激活，下一次有效电鱼成功率"
                f"提高 {bonus_rate * 100:.1f}%；成功时抽取鱼量提升"
                f" {(fish_count_multiplier - 1) * 100:.1f}%。"
            ),
        }
