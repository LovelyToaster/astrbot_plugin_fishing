from typing import Dict, Any, List, Optional
from astrbot.api import logger
from ..repositories.abstract_repository import AbstractItemTemplateRepository, AbstractGachaRepository
from ..domain.models import Fish, Rod, Bait, Accessory, GachaPool, Item, Title


class ItemTemplateService:
    """封装所有游戏模板数据的后台管理业务逻辑"""

    def __init__(
            self,
            item_template_repo: AbstractItemTemplateRepository,
            gacha_repo: AbstractGachaRepository
    ):
        self.item_template_repo = item_template_repo
        self.gacha_repo = gacha_repo

    # --- Fish Methods ---
    def get_fish_by_id(self, fish_id: int) -> Optional[Fish]:
        return self.item_template_repo.get_fish_by_id(fish_id)

    def get_all_fish(self) -> List[Fish]:
        return self.item_template_repo.get_all_fish()

    def add_fish_template(self, data: Dict[str, Any]):
        # 服务层可以添加数据验证逻辑，支持任意稀有度级别
        self.item_template_repo.add_fish_template(data)

    def update_fish_template(self, fish_id: int, data: Dict[str, Any]):
        self.item_template_repo.update_fish_template(fish_id, data)

    def delete_fish_template(self, fish_id: int):
        self.item_template_repo.delete_fish_template(fish_id)

    # --- Rod Methods ---
    def get_rod_by_id(self, rod_id: int) -> Optional[Rod]:
        return self.item_template_repo.get_rod_by_id(rod_id)

    def get_all_rods(self) -> List[Rod]:
        return self.item_template_repo.get_all_rods()

    def add_rod_template(self, data: Dict[str, Any]):
        self.item_template_repo.add_rod_template(data)

    def update_rod_template(self, rod_id: int, data: Dict[str, Any]):
        self.item_template_repo.update_rod_template(rod_id, data)
        self._reconcile_gacha_ups()

    def delete_rod_template(self, rod_id: int):
        self.item_template_repo.delete_rod_template(rod_id)
        self._reconcile_gacha_ups()

    # --- Bait Methods ---
    def get_bait_by_id(self, bait_id: int) -> Optional[Bait]:
        return self.item_template_repo.get_bait_by_id(bait_id)

    def get_all_baits(self) -> List[Bait]:
        return self.item_template_repo.get_all_baits()

    def add_bait_template(self, data: Dict[str, Any]):
        self.item_template_repo.add_bait_template(data)

    def update_bait_template(self, bait_id: int, data: Dict[str, Any]):
        self.item_template_repo.update_bait_template(bait_id, data)
        self._reconcile_gacha_ups()

    def delete_bait_template(self, bait_id: int):
        self.item_template_repo.delete_bait_template(bait_id)
        self._reconcile_gacha_ups()

    # --- Accessory Methods ---
    def get_accessory_by_id(self, accessory_id: int) -> Optional[Accessory]:
        return self.item_template_repo.get_accessory_by_id(accessory_id)

    def get_all_accessories(self) -> List[Accessory]:
        return self.item_template_repo.get_all_accessories()

    def add_accessory_template(self, data: Dict[str, Any]):
        self.item_template_repo.add_accessory_template(data)

    def update_accessory_template(self, accessory_id: int, data: Dict[str, Any]):
        self.item_template_repo.update_accessory_template(accessory_id, data)
        self._reconcile_gacha_ups()

    def delete_accessory_template(self, accessory_id: int):
        self.item_template_repo.delete_accessory_template(accessory_id)
        self._reconcile_gacha_ups()

    # --- Item Methods ---
    def get_item_by_id(self, item_id: int) -> Optional[Item]:
        return self.item_template_repo.get_item_by_id(item_id)

    def get_all_items(self) -> List[Item]:
        return self.item_template_repo.get_all_items()

    def add_item_template(self, data: Dict[str, Any]):
        self.item_template_repo.add_item_template(data)

    def update_item_template(self, item_id: int, data: Dict[str, Any]):
        self.item_template_repo.update_item_template(item_id, data)
        self._reconcile_gacha_ups()

    def delete_item_template(self, item_id: int):
        self.item_template_repo.delete_item_template(item_id)
        self._reconcile_gacha_ups()

    # --- Title Methods ---
    def get_title_by_id(self, title_id: int) -> Optional[Title]:
        return self.item_template_repo.get_title_by_id(title_id)

    def get_title_by_name(self, name: str) -> Optional[Title]:
        return self.item_template_repo.get_title_by_name(name)

    def update_title_template(self, title_id: int, data: Dict[str, Any]):
        self.item_template_repo.update_title_template(title_id, data)
        self._reconcile_gacha_ups()

    def delete_title_template(self, title_id: int):
        self.item_template_repo.delete_title_template(title_id)
        self._reconcile_gacha_ups()

    # --- Gacha Pool Methods ---
    def get_all_gacha_pools(self) -> List[GachaPool]:
        return self.gacha_repo.get_all_pools()

    def add_pool_template(self, data: Dict[str, Any]):
        # 服务层可以包含验证逻辑，例如检查名称是否重复等
        self.gacha_repo.add_pool_template(data)

    def update_pool_template(self, pool_id: int, data: Dict[str, Any]):
        self.gacha_repo.update_pool_template(pool_id, data)

    def delete_pool_template(self, pool_id: int):
        self.gacha_repo.delete_pool_template(pool_id)

    def copy_pool_template(self, pool_id: int) -> int:
        """复制一个抽卡池及其所有物品"""
        return self.gacha_repo.copy_pool_template(pool_id)

    def get_pool_details_for_admin(self, pool_id: int) -> Dict[str, Any]:
        pool = self.gacha_repo.get_pool_by_id(pool_id)
        # 为后台提供所有可添加的物品选项
        all_rods = self.item_template_repo.get_all_rods()
        all_baits = self.item_template_repo.get_all_baits()
        all_accessories = self.item_template_repo.get_all_accessories()
        return {
            "pool": pool,
            "all_rods": all_rods,
            "all_baits": all_baits,
            "all_accessories": all_accessories
        }

    # --- Gacha Pool Item Methods ---
    def add_item_to_pool(self, pool_id: int, data: Dict[str, Any]):
        self.gacha_repo.add_item_to_pool(pool_id, data)

    def update_pool_item(self, item_pool_id: int, data: Dict[str, Any]):
        old_identity = self._pool_item_identity(item_pool_id)
        self.gacha_repo.update_pool_item(item_pool_id, data)
        new_identity = self._requested_item_identity(data) or old_identity
        if old_identity and new_identity and old_identity != new_identity:
            invalidate = getattr(self.gacha_repo, "invalidate_user_ups_by_item", None)
            if callable(invalidate):
                invalidate(item_pool_id, "所选奖品条目的物品身份已修改")
                logger.warning(
                    "Invalidated personal gacha UP choices because pool item %s changed identity",
                    item_pool_id,
                )
        self._reconcile_gacha_ups()

    def delete_pool_item(self, item_pool_id: int):
        self.gacha_repo.delete_pool_item(item_pool_id)
        self._reconcile_gacha_ups()

    def _pool_item_identity(self, item_pool_id: int):
        for pool in self.gacha_repo.get_all_pools():
            for item in pool.items:
                if int(item.gacha_pool_item_id) == int(item_pool_id):
                    return item.item_type, int(item.item_id)
        return None

    @staticmethod
    def _requested_item_identity(data: Dict[str, Any]):
        item_full_id = data.get("item_full_id")
        if not item_full_id:
            return None
        parts = str(item_full_id).split("-", 1)
        if len(parts) != 2:
            return None
        try:
            return parts[0], int(parts[1])
        except (TypeError, ValueError):
            return None

    def _template_for_pool_item(self, item):
        if item.item_type == "rod":
            return self.item_template_repo.get_rod_by_id(item.item_id)
        if item.item_type == "accessory":
            return self.item_template_repo.get_accessory_by_id(item.item_id)
        if item.item_type == "bait":
            return self.item_template_repo.get_bait_by_id(item.item_id)
        if item.item_type == "item":
            return self.item_template_repo.get_by_id(item.item_id)
        if item.item_type == "titles":
            return self.item_template_repo.get_title_by_id(item.item_id)
        return None

    def _reconcile_gacha_ups(self):
        """Invalidate saved choices made invalid by a catalog/template edit."""
        get_choices = getattr(self.gacha_repo, "get_all_user_up_choices", None)
        invalidate_choice = getattr(self.gacha_repo, "invalidate_user_up", None)
        delete_choice = getattr(self.gacha_repo, "delete_user_up", None)
        if not callable(get_choices) or not (callable(invalidate_choice) or callable(delete_choice)):
            return
        try:
            pools = {
                int(pool.gacha_pool_id): pool for pool in self.gacha_repo.get_all_pools()
            }
            for choice in get_choices():
                pool_id = int(choice.gacha_pool_id)
                pool = pools.get(pool_id)
                reason = None
                if pool is None:
                    reason = "所选卡池已删除"
                else:
                    target = next(
                        (item for item in pool.items
                         if int(item.gacha_pool_item_id) == int(choice.up_pool_item_id)),
                        None,
                    )
                    if target is None:
                        reason = "所选奖品条目已删除"
                    elif target.item_type == "coins":
                        reason = "金币奖励不能设置为UP"
                    elif float(target.weight or 0) <= 0:
                        reason = "所选奖品权重已不再大于0"
                    else:
                        template = self._template_for_pool_item(target)
                        rarity = int(getattr(template, "rarity", 0) or 0)
                        if rarity <= 0:
                            reason = "所选奖品模板已删除或星级无效"
                        elif not any(
                            item.item_type != "coins"
                            and (item.item_type, int(item.item_id)) != (target.item_type, int(target.item_id))
                            and float(item.weight or 0) > 0
                            and int(getattr(self._template_for_pool_item(item), "rarity", 0) or 0) == rarity
                            for item in pool.items
                        ):
                            reason = "该星级已没有其他不同物品身份的正权重奖品"
                if reason:
                    if callable(invalidate_choice):
                        invalidate_choice(str(choice.user_id), pool_id, reason)
                    else:
                        delete_choice(str(choice.user_id), pool_id)
                    logger.warning(
                        "Invalidated user %s personal UP for pool %s: %s",
                        choice.user_id,
                        pool_id,
                        reason,
                    )
        except Exception as exc:
            logger.error("Could not reconcile personal gacha UP choices: %s", exc)
