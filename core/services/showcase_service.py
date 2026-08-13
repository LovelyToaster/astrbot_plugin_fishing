from typing import Any, Dict, Optional, Tuple

from ..repositories.abstract_repository import (
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractUserRepository,
)
from ..utils import calculate_after_refine, from_base36, to_base36
from ..showcase_themes import (
    format_showcase_theme_options,
    get_showcase_theme_label,
    is_valid_showcase_theme,
    normalize_showcase_theme,
)


class ShowcaseService:
    """展示柜业务：管理槽位，并为渲染层提供稳定、完整的数据。"""

    DEFAULT_SIGNATURE = "快来参观我的展示柜吧！"

    def __init__(
        self,
        inventory_repo: AbstractInventoryRepository,
        user_repo: AbstractUserRepository,
        item_template_repo: AbstractItemTemplateRepository,
    ):
        self.inventory_repo = inventory_repo
        self.user_repo = user_repo
        self.item_template_repo = item_template_repo

    def resolve_token(self, token: str) -> Tuple[Optional[str], Optional[int]]:
        """解析装备短码（如 R1、A2）为 ``(item_type, instance_id)``。"""
        if not token:
            return None, None
        value = str(token).strip().upper()
        prefix = value[:1]
        if prefix not in {"R", "A"}:
            return None, None
        try:
            instance_id = from_base36(value[1:])
        except (TypeError, ValueError):
            return None, None
        if instance_id <= 0:
            return None, None
        return ("rod" if prefix == "R" else "accessory"), instance_id

    @staticmethod
    def _invalid_token_message() -> str:
        return "无效的装备短码！格式如：R1（鱼竿）或 A1（饰品）"

    @staticmethod
    def _capacity(user: Any) -> int:
        try:
            return max(1, int(getattr(user, "showcase_capacity", 6) or 6))
        except (TypeError, ValueError):
            return 6

    def _get_instance_and_name(
        self, user_id: str, item_type: str, instance_id: int
    ) -> Tuple[Optional[Any], str]:
        if item_type == "rod":
            instance = self.inventory_repo.get_user_rod_instance_by_id(user_id, instance_id)
            template = (
                self.item_template_repo.get_rod_by_id(instance.rod_id)
                if instance
                else None
            )
            return instance, template.name if template else "鱼竿"

        instance = self.inventory_repo.get_user_accessory_instance_by_id(user_id, instance_id)
        template = (
            self.item_template_repo.get_accessory_by_id(instance.accessory_id)
            if instance
            else None
        )
        return instance, template.name if template else "饰品"

    def put_in_showcase(self, user_id: str, token: str) -> Dict[str, Any]:
        """将一件未展示的装备放入第一个空槽位。"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        item_type, instance_id = self.resolve_token(token)
        if not item_type or instance_id is None:
            return {"success": False, "message": self._invalid_token_message()}

        capacity = self._capacity(user)
        current_showcase = self.inventory_repo.get_user_showcase(user_id)
        if any(
            item.item_type == item_type and item.instance_id == instance_id
            for item in current_showcase
        ):
            return {"success": False, "message": "该装备已经在展示柜中！"}
        if len(current_showcase) >= capacity:
            return {
                "success": False,
                "message": f"展示柜已满！当前容量上限为 {capacity} 个槽位。",
            }

        instance, item_name = self._get_instance_and_name(user_id, item_type, instance_id)
        if not instance:
            return {"success": False, "message": "未找到对应的装备实例！"}
        if getattr(instance, "is_in_showcase", False):
            return {
                "success": False,
                "message": "该装备的展示柜状态异常，请稍后重试或联系管理员修复。",
            }

        used_slots = {
            item.slot_index
            for item in current_showcase
            if 0 <= item.slot_index < capacity
        }
        target_slot = next(
            (slot for slot in range(capacity) if slot not in used_slots), None
        )
        if target_slot is None:
            return {"success": False, "message": "展示柜没有可用槽位。"}

        # 展示柜内的装备不可同时装备；仓储层还会再次强制清理 is_equipped。
        if getattr(instance, "is_equipped", False):
            if item_type == "rod":
                user.equipped_rod_instance_id = None
            else:
                user.equipped_accessory_instance_id = None
            self.inventory_repo.set_equipment_status(
                user_id,
                rod_instance_id=user.equipped_rod_instance_id,
                accessory_instance_id=user.equipped_accessory_instance_id,
            )
            self.user_repo.update(user)

        if not self.inventory_repo.add_to_showcase(
            user_id, item_type, instance_id, target_slot
        ):
            return {"success": False, "message": "放入展示柜失败，装备状态可能刚刚发生变化。"}

        return {
            "success": True,
            "message": f"成功将装备【{item_name}】（短码：{str(token).strip().upper()}）放入展示柜！",
        }

    def take_out_showcase(self, user_id: str, token: str) -> Dict[str, Any]:
        """将装备从展示柜取回背包，并恢复放入前的锁定状态。"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        item_type, instance_id = self.resolve_token(token)
        if not item_type or instance_id is None:
            return {"success": False, "message": self._invalid_token_message()}

        current_showcase = self.inventory_repo.get_user_showcase(user_id)
        if not any(
            item.item_type == item_type and item.instance_id == instance_id
            for item in current_showcase
        ):
            return {"success": False, "message": "展示柜中未找到该装备！"}

        if not self.inventory_repo.remove_from_showcase(user_id, item_type, instance_id):
            return {"success": False, "message": "取出展示柜失败，装备状态可能刚刚发生变化。"}

        return {
            "success": True,
            "message": f"已成功将装备（短码：{str(token).strip().upper()}）从展示柜取出，已移回背包。",
        }

    def set_signature(self, user_id: str, signature: str) -> Dict[str, Any]:
        """设置展示柜个性签名。"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        value = (signature or "").strip()
        if len(value) > 30:
            return {"success": False, "message": "个性签名不能超过30个字！"}

        user.showcase_signature = value or self.DEFAULT_SIGNATURE
        self.user_repo.update(user)
        return {
            "success": True,
            "message": f"展示柜个性签名更新成功：『{user.showcase_signature}』",
        }

    def _resolve_theme_slot(
        self, user_id: str, selector: str, capacity: int
    ) -> Tuple[Optional[int], Optional[str]]:
        """将位置编号或装备短码解析为展示位置。"""
        value = str(selector or "").strip()
        if not value:
            return None, None

        try:
            position = int(value)
        except (TypeError, ValueError):
            position = None
        if position is not None:
            if 1 <= position <= capacity:
                return position - 1, str(position)
            return None, None

        item_type, instance_id = self.resolve_token(value)
        if not item_type or instance_id is None:
            return None, None
        for item in self.inventory_repo.get_user_showcase(user_id):
            if item.item_type == item_type and item.instance_id == instance_id:
                return item.slot_index, str(value).upper()
        return None, None

    def set_theme(self, user_id: str, selector: str, theme: str) -> Dict[str, Any]:
        """设置指定展示位置的预设主题；支持位置编号或装备短码。"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        value = str(theme or "").strip()
        if not value:
            return {"success": False, "message": format_showcase_theme_options()}
        if not is_valid_showcase_theme(value):
            return {
                "success": False,
                "message": f"未找到颜色选项“{value}”。\n\n{format_showcase_theme_options()}",
            }

        slot_index, target_label = self._resolve_theme_slot(
            user_id, selector, self._capacity(user)
        )
        if slot_index is None:
            return {
                "success": False,
                "message": "未找到该展示位置。请使用1开始的位置编号，或使用展示柜中的装备短码。",
            }

        normalized = normalize_showcase_theme(value)
        if not self.inventory_repo.set_showcase_theme(user_id, slot_index, normalized):
            return {"success": False, "message": "保存展示位置颜色失败，请稍后重试。"}
        return {
            "success": True,
            "message": f"展示位置【{target_label}】的颜色已切换为【{get_showcase_theme_label(normalized)}】。",
        }

    @staticmethod
    def get_theme_options() -> str:
        return format_showcase_theme_options()

    def _build_slot_data(self, user_id: str, item: Any) -> Optional[Dict[str, Any]]:
        instance, _ = self._get_instance_and_name(user_id, item.item_type, item.instance_id)
        if not instance:
            return None

        if item.item_type == "rod":
            template = self.item_template_repo.get_rod_by_id(instance.rod_id)
            bonus_coin = None
            code = f"R{to_base36(instance.rod_instance_id)}"
        elif item.item_type == "accessory":
            template = self.item_template_repo.get_accessory_by_id(instance.accessory_id)
            bonus_coin = calculate_after_refine(
                template.bonus_coin_modifier, instance.refine_level, template.rarity
            ) if template else None
            code = f"A{to_base36(instance.accessory_instance_id)}"
        else:
            return None
        if not template:
            return None

        return {
            "item_type": item.item_type,
            "display_code": code,
            "name": template.name,
            "rarity": template.rarity,
            "refine_level": instance.refine_level,
            "refine_display": f"精炼等级 {max(1, int(instance.refine_level or 1))}",
            "bonus_quality": calculate_after_refine(
                template.bonus_fish_quality_modifier, instance.refine_level, template.rarity
            ),
            "bonus_quantity": calculate_after_refine(
                template.bonus_fish_quantity_modifier, instance.refine_level, template.rarity
            ),
            "bonus_rare": calculate_after_refine(
                template.bonus_rare_fish_chance, instance.refine_level, template.rarity
            ),
            "bonus_coin": bonus_coin,
            "obtained_at": instance.obtained_at,
            "theme": normalize_showcase_theme(getattr(item, "theme", "ocean")),
        }

    def get_showcase_data(self, user_id: str) -> Dict[str, Any]:
        """组装渲染所需数据；无效关系只跳过，不让图片生成失败。"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        capacity = self._capacity(user)
        slots = [None] * capacity
        slot_themes = ["ocean"] * capacity
        for slot_index, theme in self.inventory_repo.get_showcase_slot_themes(user_id).items():
            if 0 <= slot_index < capacity:
                slot_themes[slot_index] = normalize_showcase_theme(theme)
        for item in self.inventory_repo.get_user_showcase(user_id):
            if not 0 <= item.slot_index < capacity or slots[item.slot_index] is not None:
                continue
            slots[item.slot_index] = self._build_slot_data(user_id, item)

        return {
            "success": True,
            "user_id": user.user_id,
            "nickname": user.nickname or "未知钓客",
            "signature": user.showcase_signature or self.DEFAULT_SIGNATURE,
            "capacity": capacity,
            "count": sum(slot is not None for slot in slots),
            "slots": slots,
            "slot_themes": slot_themes,
        }
