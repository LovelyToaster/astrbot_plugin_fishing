import json
from datetime import timedelta
from typing import Dict, Any

from .abstract_effect import AbstractItemEffect
from ...domain.models import User, Item, UserBuff
from ...utils import get_now


class StealProtectionEffect(AbstractItemEffect):
    effect_type = "STEAL_PROTECTION_BUFF"

    def apply(
        self, user: User, item_template: Item, payload: Dict[str, Any], quantity: int = 1
    ) -> Dict[str, Any]:
        layers_per_use = payload.get("layers_per_use", 1)
        max_layers = payload.get("max_layers", 2)
        duration_hours = payload.get("duration_hours", 4)
        resist_chance = payload.get("resist_chance", 0.05)
        break_threshold = payload.get("break_threshold", 3)
        base_duration_hours = duration_hours  # quantity 已在 inventory_service 中循环处理
        
        existing_buff = self.buff_repo.get_active_by_user_and_type(
            user.user_id, self.effect_type
        )
        
        now = get_now().replace(tzinfo=None)

        if existing_buff:
            # 解析已有 payload，兼容旧格式（payload 为空或无字段，默认值）
            existing_payload = json.loads(existing_buff.payload or "{}")
            current_layers = existing_payload.get("layers", 1)
            
            # 层数叠加
            new_layers = min(current_layers + layers_per_use, max_layers)
            
            # 时间叠加减免：按剩余时间计算有效加成
            expires_at = existing_buff.expires_at
            if expires_at and expires_at.tzinfo:
                expires_at = expires_at.replace(tzinfo=None)
            remaining_h = (expires_at - now).total_seconds() / 3600 if expires_at else 0
            
            if remaining_h <= 4:
                factor = 1.0
            elif remaining_h <= 8:
                factor = 0.75
            elif remaining_h <= 12:
                factor = 0.5
            else:
                factor = 0.25
            
            effective_hours = base_duration_hours * factor
            new_expires_at = max(now, expires_at) + timedelta(hours=effective_hours)
            
            # 更新 payload（叠加时重置 broken_steals）
            existing_buff.payload = json.dumps({
                "layers": new_layers,
                "max_layers": max_layers,
                "resist_chance": resist_chance,
                "break_threshold": break_threshold,
                "broken_steals": 0,
            })
            existing_buff.expires_at = new_expires_at
            self.buff_repo.update(existing_buff)
            
            total_remaining_seconds = (new_expires_at - now).total_seconds()
            total_remaining_hours = total_remaining_seconds / 3600
            message = (
                f"🛡️ 守护海灵的层数已叠加至 {new_layers} 层"
                f"（上限 {max_layers} 层），"
                f"庇护时间延长至 {total_remaining_hours:.1f} 小时！"
            )
        else:
            # 创建新 buff
            new_expires_at = now + timedelta(hours=base_duration_hours)
            new_buff = UserBuff(
                id=0,
                user_id=user.user_id,
                buff_type=self.effect_type,
                payload=json.dumps({
                    "layers": layers_per_use,
                    "max_layers": max_layers,
                    "resist_chance": resist_chance,
                    "break_threshold": break_threshold,
                    "broken_steals": 0,
                }),
                started_at=now,
                expires_at=new_expires_at,
            )
            self.buff_repo.add(new_buff)
            message = (
                f"🌊 一个温和的海灵出现了，获得 {layers_per_use} 层守护"
                f"（上限 {max_layers} 层），"
                f"将在未来 {base_duration_hours} 小时内守护你的鱼塘！"
            )
            
        return {"success": True, "message": message}
