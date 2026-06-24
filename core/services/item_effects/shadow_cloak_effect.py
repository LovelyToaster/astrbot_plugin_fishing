import json
from typing import Dict, Any

from .abstract_effect import AbstractItemEffect
from ...domain.models import User, Item, UserBuff
from ...utils import get_now

class ShadowCloakEffect(AbstractItemEffect):
    effect_type = "SHADOW_CLOAK_BUFF"

    def apply(
        self, user: User, item_template: Item, payload: Dict[str, Any], quantity: int = 1
    ) -> Dict[str, Any]:
        """
        暗影斗篷效果：无限时间，使用 charges 计数，使用后消耗 1 charge
        """
        # 检查是否已有暗影斗篷效果
        existing_buff = self.buff_repo.get_active_by_user_and_type(
            user.user_id, self.effect_type
        )
        
        if existing_buff:
            # 解析已有 payload，兼容旧格式（空 payload 或无 charges 字段默认 1）
            existing_payload = json.loads(existing_buff.payload or "{}")
            current_charges = existing_payload.get("charges", 1)
            new_charges = current_charges + 1
            existing_buff.payload = json.dumps({"charges": new_charges})
            self.buff_repo.update(existing_buff)
            message = f"🌑 暗影斗篷的力量已叠加！当前共 {new_charges} 次反制机会！"
        else:
            # 创建新buff，设置为无限时间（expires_at为None表示永不过期）
            now = get_now().replace(tzinfo=None)
            new_buff = UserBuff(
                id=0,
                user_id=user.user_id,
                buff_type=self.effect_type,
                payload=json.dumps({"charges": 1}),
                started_at=now,
                expires_at=None,  # 无限时间
            )
            self.buff_repo.add(new_buff)
            message = f"🌑 暗影斗篷激活！你获得了 1 次无视海灵守护的反制机会！"
            
        return {"success": True, "message": message}
