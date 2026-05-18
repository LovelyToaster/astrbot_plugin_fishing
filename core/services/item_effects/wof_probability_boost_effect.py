import json
from datetime import datetime, timedelta
from typing import Dict, Any

from .abstract_effect import AbstractItemEffect
from ...domain.models import User, Item, UserBuff
from ...utils import get_now


class WofProbabilityBoostEffect(AbstractItemEffect):
    effect_type = "WOF_PROBABILITY_BOOST"

    def apply(
        self, user: User, item_template: Item, payload: Dict[str, Any], quantity: int = 1
    ) -> Dict[str, Any]:
        existing_buff = self.buff_repo.get_active_by_user_and_type(
            user.user_id, "WOF_PROBABILITY_BOOST"
        )
        if existing_buff:
            return {
                "success": False,
                "message": "你已经使用了【操纵现实】，效果将在下一次命运之轮游戏中生效。请先完成一局游戏后再使用。",
            }

        probability_multiplier = payload.get("probability_multiplier", 1.2)
        max_probability = payload.get("max_probability", 0.95)
        duration_days = payload.get("duration_days", 7)

        now = get_now().replace(tzinfo=None)
        expires_at = now + timedelta(days=duration_days)

        new_buff = UserBuff(
            id=None,
            user_id=user.user_id,
            buff_type="WOF_PROBABILITY_BOOST",
            payload=json.dumps({
                "probability_multiplier": probability_multiplier,
                "max_probability": max_probability,
            }),
            started_at=now,
            expires_at=expires_at,
        )
        self.buff_repo.add(new_buff)

        return {
            "success": True,
            "message": (
                f"你使用了【操纵现实】！下次命运之轮游戏中，每层成功率将获得 "
                f"{probability_multiplier} 倍提升（上限 {int(max_probability * 100)}%）。"
                f"效果持续至游戏结束或 {duration_days} 天未使用。"
            ),
        }
