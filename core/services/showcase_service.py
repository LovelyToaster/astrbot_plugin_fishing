from typing import Dict, Any, List, Optional
from datetime import datetime

from astrbot.api import logger
from ..repositories.abstract_repository import (
    AbstractInventoryRepository,
    AbstractUserRepository,
    AbstractItemTemplateRepository,
)
from ..domain.models import User, UserShowcaseItem, UserRodInstance, UserAccessoryInstance
from ..utils import calculate_after_refine, to_base36, from_base36


class ShowcaseService:
    """展示柜服务：管理玩家装备的放入、取出、宣言修改与信息组装"""

    def __init__(
        self,
        inventory_repo: AbstractInventoryRepository,
        user_repo: AbstractUserRepository,
        item_template_repo: AbstractItemTemplateRepository,
    ):
        self.inventory_repo = inventory_repo
        self.user_repo = user_repo
        self.item_template_repo = item_template_repo

    def resolve_token(self, token: str) -> tuple[Optional[str], Optional[int]]:
        """解析装备短码 (如 R1, A2) 为 (item_type, instance_id)"""
        if not token:
            return None, None
        tok = str(token).strip().upper()
        if tok.startswith("R"):
            try:
                return "rod", from_base36(tok[1:])
            except Exception:
                return None, None
        elif tok.startswith("A"):
            try:
                return "accessory", from_base36(tok[1:])
            except Exception:
                return None, None
        return None, None

    def put_in_showcase(self, user_id: str, token: str) -> Dict[str, Any]:
        """将装备放入展示柜"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        item_type, instance_id = self.resolve_token(token)
        if not item_type or not instance_id:
            return {"success": False, "message": "无效的装备短码！格式格式如：R1（鱼竿）或 A1（饰品）"}

        # 获取已有展示柜列表
        current_showcase = self.inventory_repo.get_user_showcase(user_id)
        if len(current_showcase) >= user.showcase_capacity:
            return {
                "success": False,
                "message": f"展示柜已满！当前容量上限为 {user.showcase_capacity} 个槽位。"
            }

        # 检查是否已在展示柜中
        for item in current_showcase:
            if item.item_type == item_type and item.instance_id == instance_id:
                return {"success": False, "message": "该装备已经在展示柜中！"}

        item_name = ""
        # 处理鱼竿
        if item_type == "rod":
            rod_instance = self.inventory_repo.get_user_rod_instance_by_id(user_id, instance_id)
            if not rod_instance:
                return {"success": False, "message": "未找到对应的鱼竿装备！"}
            rod_template = self.item_template_repo.get_rod_by_id(rod_instance.rod_id)
            item_name = rod_template.name if rod_template else "鱼竿"
            
            # 若正在装备中，取消装备状态
            if rod_instance.is_equipped:
                self.inventory_repo.set_equipment_status(user_id, rod_instance_id=None, accessory_instance_id=user.equipped_accessory_instance_id)

        # 处理饰品
        elif item_type == "accessory":
            acc_instance = self.inventory_repo.get_user_accessory_instance_by_id(user_id, instance_id)
            if not acc_instance:
                return {"success": False, "message": "未找到对应的饰品装备！"}
            acc_template = self.item_template_repo.get_accessory_by_id(acc_instance.accessory_id)
            item_name = acc_template.name if acc_template else "饰品"

            # 若正在装备中，取消装备状态
            if acc_instance.is_equipped:
                self.inventory_repo.set_equipment_status(user_id, rod_instance_id=user.equipped_rod_instance_id, accessory_instance_id=None)

        # 寻空槽位
        used_slots = {item.slot_index for item in current_showcase}
        target_slot = 0
        for slot in range(user.showcase_capacity):
            if slot not in used_slots:
                target_slot = slot
                break

        self.inventory_repo.add_to_showcase(user_id, item_type, instance_id, target_slot)

        return {
            "success": True,
            "message": f"成功将装备【{item_name}】(短码: {token.upper()}) 放入展示柜！"
        }

    def take_out_showcase(self, user_id: str, token: str) -> Dict[str, Any]:
        """将装备从展示柜移回背包"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        item_type, instance_id = self.resolve_token(token)
        if not item_type or not instance_id:
            return {"success": False, "message": "无效的装备短码！格式格式如：R1（鱼竿）或 A1（饰品）"}

        current_showcase = self.inventory_repo.get_user_showcase(user_id)
        target_item = next((item for item in current_showcase if item.item_type == item_type and item.instance_id == instance_id), None)

        if not target_item:
            return {"success": False, "message": "展示柜中未找到该装备！"}

        self.inventory_repo.remove_from_showcase(user_id, item_type, instance_id)

        return {
            "success": True,
            "message": f"已成功将装备(短码: {token.upper()}) 从展示柜取出移回背包。"
        }

    def set_signature(self, user_id: str, signature: str) -> Dict[str, Any]:
        """设置展示柜个性签名"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        sig = (signature or "").strip()
        if len(sig) > 30:
            return {"success": False, "message": "个性签名不能超过30个字！"}

        user.showcase_signature = sig or "快来参观我的展示柜吧！"
        self.user_repo.update(user)

        return {
            "success": True,
            "message": f"展示柜个性签名更新成功：『{user.showcase_signature}』"
        }

    def get_showcase_data(self, user_id: str) -> Dict[str, Any]:
        """组装展示柜丰富数据供渲染"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        raw_items = self.inventory_repo.get_user_showcase(user_id)
        slots_data = [None] * user.showcase_capacity

        for item in raw_items:
            if item.slot_index >= user.showcase_capacity:
                continue

            if item.item_type == "rod":
                inst = self.inventory_repo.get_user_rod_instance_by_id(user_id, item.instance_id)
                if inst:
                    tmpl = self.item_template_repo.get_rod_by_id(inst.rod_id)
                    if tmpl:
                        slots_data[item.slot_index] = {
                            "item_type": "rod",
                            "display_code": f"R{to_base36(inst.rod_instance_id)}",
                            "name": tmpl.name,
                            "rarity": tmpl.rarity,
                            "refine_level": inst.refine_level,
                            "bonus_quality": calculate_after_refine(tmpl.bonus_fish_quality_modifier, inst.refine_level, tmpl.rarity),
                            "bonus_quantity": calculate_after_refine(tmpl.bonus_fish_quantity_modifier, inst.refine_level, tmpl.rarity),
                            "bonus_rare": calculate_after_refine(tmpl.bonus_rare_fish_chance, inst.refine_level, tmpl.rarity),
                            "obtained_at": inst.obtained_at,
                        }
            elif item.item_type == "accessory":
                inst = self.inventory_repo.get_user_accessory_instance_by_id(user_id, item.instance_id)
                if inst:
                    tmpl = self.item_template_repo.get_accessory_by_id(inst.accessory_id)
                    if tmpl:
                        slots_data[item.slot_index] = {
                            "item_type": "accessory",
                            "display_code": f"A{to_base36(inst.accessory_instance_id)}",
                            "name": tmpl.name,
                            "rarity": tmpl.rarity,
                            "refine_level": inst.refine_level,
                            "bonus_quality": calculate_after_refine(tmpl.bonus_fish_quality_modifier, inst.refine_level, tmpl.rarity),
                            "bonus_quantity": calculate_after_refine(tmpl.bonus_fish_quantity_modifier, inst.refine_level, tmpl.rarity),
                            "bonus_rare": calculate_after_refine(tmpl.bonus_rare_fish_chance, inst.refine_level, tmpl.rarity),
                            "bonus_coin": calculate_after_refine(tmpl.bonus_coin_modifier, inst.refine_level, tmpl.rarity),
                            "obtained_at": inst.obtained_at,
                        }

        return {
            "success": True,
            "user_id": user.user_id,
            "nickname": user.nickname or "未知捕快",
            "signature": user.showcase_signature,
            "capacity": user.showcase_capacity,
            "count": len([s for s in slots_data if s is not None]),
            "slots": slots_data
        }
