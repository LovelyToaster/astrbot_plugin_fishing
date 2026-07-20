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
]


def build_actions(ai_config: Dict[str, Any]) -> List[AIAction]:
    """
    根据 ai_config 构造有序动作列表。

     执行顺序：装备鱼竿 → 装备饰品 → 使用鱼饵 → 卖鱼 → 切换区域 → 卖装备
     → 修复鱼竿 → 精炼装备 → 偷鱼 → 电鱼 → 免费抽卡 → 金币抽卡

    （修复鱼竿、精炼装备为无节流的条件触发动作；卖装备已去节流改为条件触发。）
    抽卡动作仅在 `gacha_enabled=true` 时启用。
    """
    sell_min_interval = int(ai_config.get("sell_min_interval_seconds", 1800))
    pond_threshold = float(ai_config.get("pond_full_threshold", 0.5))

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
                upgrade_threshold=int(ai_config.get("zone_upgrade_threshold_multiplier", 200)),
                downgrade_threshold=int(ai_config.get("zone_downgrade_threshold_multiplier", 20)),
            )
        )

    actions.append(SellEquipmentAction())

    if ai_config.get("repair_enabled", True):
        actions.append(RepairRodAction())
    if ai_config.get("refine_enabled", True):
        actions.append(
            RefineAction(reserve_coins=int(ai_config.get("refine_reserve_coins", 200000)))
        )

    actions.extend(
        [
            StealFishAction(
                min_target_fish_count=int(
                    ai_config.get("steal_min_target_fish_count", 1)
                ),
            ),
            ElectricFishAction(
                min_target_fish_count=int(
                    ai_config.get("electric_min_target_fish_count", 100)
                ),
            ),
        ]
    )

    if ai_config.get("gacha_enabled", True):
        actions.append(FreeGachaAction())
        actions.append(
            PaidGachaAction(
                paid_interval_seconds=int(
                    ai_config.get("gacha_paid_interval_seconds", 3600)
                ),
                spending_ratio=float(ai_config.get("gacha_spending_ratio", 0.05)),
                ten_pull_enabled=ai_config.get("gacha_ten_pull_enabled", True),
                ten_pull_multiplier=float(
                    ai_config.get("gacha_ten_pull_multiplier", 5)
                ),
            )
        )

    return actions
