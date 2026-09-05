"""
AI 动作集合。

`build_actions(ai_config)` 根据配置构造一个 AIAction 列表，
供 AIPlayerService.tick 按顺序调用。
"""

from typing import Any, Dict, List

from .base import AIAction
from .electric_fish import ElectricFishAction
from .equip_best_accessory import EquipBestAccessoryAction
from .equip_best_rod import EquipBestRodAction
from .free_gacha import FreeGachaAction
from .paid_gacha import PaidGachaAction
from .refine import RefineAction
from .repair_rod import RepairRodAction
from .sell_equipment import SellEquipmentAction
from .sell_fish import SellFishAction
from .steal_fish import StealFishAction
from .switch_zone import SwitchZoneAction
from .use_best_bait import UseBestBaitAction
from .use_items import UseItemsAction

__all__ = [
    "AIAction",
    "build_actions",
    "EquipBestRodAction",
    "EquipBestAccessoryAction",
    "UseBestBaitAction",
    "SellFishAction",
    "SellEquipmentAction",
    "RepairRodAction",
    "RefineAction",
    "SwitchZoneAction",
    "StealFishAction",
    "ElectricFishAction",
    "FreeGachaAction",
    "PaidGachaAction",
    "UseItemsAction",
]


def build_actions(ai_config: Dict[str, Any]) -> List[AIAction]:
    """
    根据 ai_config 构造有序动作列表。

    执行顺序：装备鱼竿 → 装备饰品 → 使用鱼饵 → 卖鱼 → 切换区域 → 修复鱼竿
     → 精炼装备 → 卖装备 → 普通道具 → 偷鱼 → 电鱼 → 免费抽卡 → 金币抽卡

    偷鱼/电鱼动作内部会在真正执行前为目标准备驱灵香、破灵符或暗影斗篷；
    准备成功后当前 tick 立即继续执行对应的社交动作。

    （修复鱼竿、精炼装备为无节流的条件触发动作；卖装备已去节流改为条件触发。）
    抽卡动作仅在 `gacha_enabled=true` 时启用。
    """
    # 策略参数固定在代码中，配置面只保留行为开关。
    sell_min_interval = 1800
    pond_threshold = 0.5

    actions: List[AIAction] = [
        EquipBestRodAction(),
        EquipBestAccessoryAction(),
        UseBestBaitAction(),
        SellFishAction(
            min_interval_seconds=sell_min_interval,
            pond_full_threshold=pond_threshold,
        ),
    ]

    if ai_config.get("zone_switch_enabled", True):
        actions.append(
            SwitchZoneAction(
                upgrade_threshold=200,
                downgrade_threshold=20,
            )
        )

    if ai_config.get("repair_enabled", True):
        actions.append(RepairRodAction())
    if ai_config.get("refine_enabled", True):
        actions.append(
            RefineAction(reserve_coins=200000)
        )

    # 精炼需要未锁定的重复装备；卖装备必须放在精炼之后，避免提前卖掉材料。
    actions.append(SellEquipmentAction())

    # 先处理通用道具，确保金币补充、防护和钓鱼增益在本 tick 的社交动作前生效。
    # 驱灵香属于目标专用道具，仍由下方偷/电鱼动作在选定目标后即时处理。
    if ai_config.get("item_strategy_enabled", True):
        actions.append(UseItemsAction())

    actions.extend(
        [
            StealFishAction(
                min_target_fish_count=1,
            ),
            ElectricFishAction(
                min_target_fish_count=100,
            ),
        ]
    )

    if ai_config.get("gacha_enabled", True):
        actions.append(FreeGachaAction())
        actions.append(
            PaidGachaAction(
                paid_interval_seconds=3600,
                spending_ratio=0.05,
                ten_pull_enabled=True,
                ten_pull_multiplier=5,
            )
        )

    return actions
