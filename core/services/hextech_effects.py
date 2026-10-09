"""Static daily Hextech effect catalog and card parameter snapshots.

The fishing service consumes the small parameter vocabulary produced here.  An
effect's dynamic rarity targets are intentionally resolved against the fish
pool at cast time, while every random numeric parameter is stored on the card.
"""

import logging
import random
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


TIERS = ("silver", "gold", "prismatic")
SLOT_COUNTS = {"silver": 2, "gold": 3, "prismatic": 4}
# 福袋赠卡保持旧版数量，主卡新增效果槽位不会扩大赠卡奖励。
GIFT_SLOT_COUNTS = dict(SLOT_COUNTS)
FISHING_STRENGTH = {"silver": 0.45, "gold": 0.60, "prismatic": 0.675}
V4_EV_BUDGETS = {"silver": 0.04, "gold": 0.055, "prismatic": 0.07}
GIFT_STRENGTH = 0.25

TIER_LABELS = {"silver": "白银", "gold": "黄金", "prismatic": "棱彩"}


def _entry(effect_id: str, name: str, pool: str, text: str,
           conflicts: Sequence[str] = ()) -> Dict[str, Any]:
    return {
        "id": effect_id,
        "name": name,
        "pool": pool,
        "description": text,
        "conflicts": tuple(conflicts),
    }


_RARITY_WEIGHT_IDS = ("C13", "C14", "S03", "S04", "G02", "G03", "P02", "P08", "P09")
_QUALITY_IDS = ("C12", "S07", "G06", "P04", "P07", "P08")
_SPECIES_REROLL_IDS = ("C18", "S06", "S08", "G10")
_PRICE_IDS = ("C05", "C06", "C07", "C08", "C09", "C10", "C11", "C17", "C19", "C20",
              "S02", "S03", "S04", "S05", "S06", "S07", "S08", "S09", "S10",
              "G02", "G03", "G04", "G06", "G07", "G08", "G09",
              "P01", "P03", "P04", "P05", "P08", "P09")

EFFECTS: Dict[str, Dict[str, Any]] = {
    "C01": _entry("C01", "轻装出海", "common", "每竿钓鱼费用降低。", ("C02", "P01", "P10")),
    "C02": _entry("C02", "空钩保障", "common", "平时减免费用；空竿时返还部分已付费用。", ("C01", "C17", "S01", "G01", "P01", "P06", "P10")),
    "C03": _entry("C03", "普通鱼保底", "common", "钓到 1～3 星鱼时返还部分本竿费用。", ("S02", "P05")),
    "C04": _entry("C04", "渔获保值", "common", "钓到 1～3 星鱼时，提高本竿渔获总价值保底。"),
    "C05": _entry("C05", "好价入塘", "common", "所有新钓获鱼提高结算单价。"),
    "C06": _entry("C06", "稀有赏金", "common", "钓到当前鱼池的稀有鱼时提高结算单价。"),
    "C07": _entry("C07", "高阶赏金", "common", "钓到当前鱼池的高阶鱼时提高结算单价。"),
    "C08": _entry("C08", "鱼王重赏", "common", "钓到当前鱼区最稀有的鱼时提高结算单价。"),
    "C09": _entry("C09", "闪光溢价", "common", "高品质鱼获得额外单价加成。"),
    "C10": _entry("C10", "重量溢价", "common", "原始重量处于鱼种范围前 25% 时加价。"),
    "C11": _entry("C11", "幸运估价", "common", "有概率使本次鱼价额外提高。"),
    "C12": _entry("C12", "品质再判", "common", "原品质判定失败时，追加一次高品质判定。", _QUALITY_IDS),
    "C13": _entry("C13", "稀有鱼讯", "common", "将部分普通鱼权重转移给当前鱼池的稀有鱼。", _RARITY_WEIGHT_IDS),
    "C14": _entry("C14", "高阶聚焦", "common", "提高当前鱼池高阶鱼的抽取权重。", _RARITY_WEIGHT_IDS),
    "C15": _entry("C15", "惊喜升级", "common", "有机会把渔获换成当前鱼区更稀有的鱼。", ("S05", "G04", "P03")),
    "C16": _entry("C16", "鱼池突破", "common", "配额耗尽时提高本竿使用完整鱼池概率的机会。", ("G08", "P02", "P09")),
    "C17": _entry("C17", "再抛一竿", "common", "空竿时有概率免费重判一次上钩；钓中鱼小幅加价。", ("C02", "S01", "G01", "P06")),
    "C18": _entry("C18", "择优选鱼", "common", "星级确定后有概率同星重抽一次，并保留基础价较高的鱼种。", _SPECIES_REROLL_IDS),
    "C19": _entry("C19", "鱼竿同行", "common", "有概率免除本竿鱼竿耐久消耗；新鱼加价。"),
    "C20": _entry("C20", "鱼饵同行", "common", "有概率保留本竿一次性鱼饵；新鱼加价。"),
    "S01": _entry("S01", "空钩转运", "silver", "空竿获得免费重试机会；仍空竿则返还部分费用。", ("C02", "C17", "G01", "P06")),
    "S02": _entry("S02", "普通鱼也值钱", "silver", "普通鱼获得鱼价加成和费用返还。", ("C03", "P05")),
    "S03": _entry("S03", "稀有护航", "silver", "提高稀有鱼权重；钓中后额外加价。", _RARITY_WEIGHT_IDS),
    "S04": _entry("S04", "高阶目光", "silver", "提高高阶鱼权重；钓中后额外加价。", _RARITY_WEIGHT_IDS),
    "S05": _entry("S05", "进阶之喜", "silver", "有机会换成当前鱼区更稀有的鱼；升级成功后额外加价。", ("C15", "G04", "P03")),
    "S06": _entry("S06", "清流寻宝", "silver", "低基础价鱼有机会同星重抽；最终鱼加价。", _SPECIES_REROLL_IDS),
    "S07": _entry("S07", "双重闪光", "silver", "追加高品质判定；高品质鱼额外加价。", _QUALITY_IDS),
    "S08": _entry("S08", "贵鱼偏爱", "silver", "增加同星择优重抽机会；最终鱼加价。", _SPECIES_REROLL_IDS),
    "S09": _entry("S09", "护竿丰收", "silver", "增加鱼竿免磨损机会；新鱼加价。"),
    "S10": _entry("S10", "省饵丰收", "silver", "增加鱼饵保留机会；新鱼加价。"),
    "G01": _entry("G01", "逆天改命", "gold", "空竿有较高机会免费重试；仍空竿也返还大部分费用。", ("C02", "C17", "S01", "P06")),
    "G02": _entry("G02", "稀有鱼潮", "gold", "提高稀有鱼权重；钓中后获得较高加价。", _RARITY_WEIGHT_IDS),
    "G03": _entry("G03", "顶峰追猎", "gold", "提高高阶鱼权重；顶星鱼额外加价。", _RARITY_WEIGHT_IDS),
    "G04": _entry("G04", "黄金跃迁", "gold", "提高一次升星机会；成功升星后按目标星级加价。", ("C15", "S05", "P03")),
    "G05": _entry("G05", "金币暴击", "gold", "有概率获得鱼价暴击，仍受星级价格上限约束。"),
    "G06": _entry("G06", "闪光丰收", "gold", "追加高品质判定；高品质鱼额外加价。", _QUALITY_IDS),
    "G07": _entry("G07", "渔场金矿", "gold", "提高普通鱼价值保底，并提高新鱼单价。"),
    "G08": _entry("G08", "破界寻鱼", "gold", "提高配额突破机会；突破后稀有鱼额外加价。", ("C16", "P02", "P09")),
    "G09": _entry("G09", "钓具大师", "gold", "提高鱼竿和一次性鱼饵保留机会；新鱼加价。"),
    "G10": _entry("G10", "珍稀筛选", "gold", "低价鱼可重抽，并增加同星择优机会；每竿最多重抽一次。", _SPECIES_REROLL_IDS),
    "P01": _entry("P01", "海神赐福", "prismatic", "大幅降低钓鱼费用，所有新鱼加价。", ("C01", "C02", "P10")),
    "P02": _entry("P02", "突破天命", "prismatic", "配额耗尽后提高突破机会；突破时提高高阶鱼权重。", ("C16", "G08", "P09") + _RARITY_WEIGHT_IDS),
    "P03": _entry("P03", "珍鱼降临", "prismatic", "有机会换成当前鱼区更稀有的鱼；鱼王额外加价。", ("C15", "S05", "G04")),
    "P04": _entry("P04", "神迹渔获", "prismatic", "追加高品质判定；高品质鱼进一步加价。", _QUALITY_IDS),
    "P05": _entry("P05", "黄金海域", "prismatic", "普通鱼返还大部分本竿费用；稀有鱼额外加价。", ("C03", "S02")),
    "P06": _entry("P06", "无尽回响", "prismatic", "空竿有很高机会免费重试；仍空竿则返还大部分费用。", ("C02", "C17", "S01", "G01")),
    "P07": _entry("P07", "命运鱼钩", "prismatic", "每竿随机获得费用返还、鱼价提高或额外品质判定之一。", _QUALITY_IDS),
    "P08": _entry("P08", "星海同辉", "prismatic", "提高稀有鱼权重；稀有鱼追加品质机会并加价。", _RARITY_WEIGHT_IDS),
    "P09": _entry("P09", "鱼王猎人", "prismatic", "更容易遇到珍贵鱼、鱼王额外加价并提高配额突破机会。", ("C16", "G08", "P02") + _RARITY_WEIGHT_IDS),
    "P10": _entry("P10", "海神庇佑", "prismatic", "降低钓鱼费用，并增加鱼竿免磨损和鱼饵保留机会。", ("C01", "C02", "P01")),
}


EXPANSION_GROUPS = {
    "steal": ("C21", "C22", "C23", "S11", "G11", "P11"),
    "electric": ("C24", "C25", "C26", "S12", "G12", "P12"),
    "gacha": ("C27", "C28", "S13", "S14", "G13", "P13"),
    "wipe": ("C29", "C30", "S15", "G14", "G15", "P14"),
    "wheel": ("C31", "C32", "S16", "G16", "P15", "P16"),
}

_EXPANSION_CATALOG = (
    ("C21", "顺手挑货", "common", "steal", "有机会从两条候选中偷走更值钱的一条。"),
    ("C22", "闪光直觉", "common", "steal", "偷到普通品质鱼时，有机会把同一条鱼变为高品质。"),
    ("C23", "熟门熟路", "common", "steal", "缩短成功偷鱼后的冷却。"),
    ("S11", "不拿便宜货", "silver", "steal", "遇到目标鱼塘中较便宜的鱼时，有机会再挑一次。"),
    ("G11", "三选一的艺术", "gold", "steal", "有机会从三条候选中偷走更值钱的一条。"),
    ("P11", "宝鱼雷达", "prismatic", "steal", "有机会改从目标鱼塘最高档的鱼中挑选。"),
    ("C24", "电弧回响", "common", "electric", "电鱼失败时，有机会免费重判一次。"),
    ("C25", "绝缘外套", "common", "electric", "减少最终失败时的天罚损失。"),
    ("C26", "捕获赏金", "common", "electric", "成功电鱼后，有机会获得系统额外赏金。"),
    ("S12", "多一点好运", "silver", "electric", "小成功有机会变为普通成功。"),
    ("G12", "精准电网", "gold", "electric", "捕获中最便宜的鱼，有机会与剩余鱼塘再抽的一条择优。"),
    ("P12", "雷霆盛宴", "prismatic", "electric", "小成功或普通成功有机会提升一档。"),
    ("C27", "拆包再看", "common", "gacha", "当前卡池最低档奖励有机会再抽一次，保留更高档结果。"),
    ("C28", "补给加量", "common", "gacha", "抽到鱼饵或可堆叠道具时，有机会增加数量。"),
    ("S13", "抽卡找零", "silver", "gacha", "金币付费抽卡结算后返还部分金币。"),
    ("S14", "小红包", "silver", "gacha", "抽中金币奖励时，有机会获得额外金币。"),
    ("G13", "金光偏爱", "gold", "gacha", "提高当前卡池最高档非金币奖励的权重。"),
    ("P13", "双重揭晓", "prismatic", "gacha", "有机会生成两个候选，只发放更高档的一个。"),
    ("C29", "擦肩而过", "common", "wipe", "擦弹回报低于投入一半时，有机会再抽一次并择优。"),
    ("C30", "安全落地", "common", "wipe", "擦弹最终亏损时，补回部分损失。"),
    ("S15", "差一点回本", "silver", "wipe", "擦弹回报接近本金时，有机会补到刚好回本。"),
    ("G14", "见红有喜", "gold", "wipe", "擦弹盈利时，追加一份小额奖励。"),
    ("G15", "区间择优", "gold", "wipe", "擦弹原奖励区间内有机会再抽一次并择优。"),
    ("P14", "幸运逃生", "prismatic", "wipe", "擦弹回报很低时获得额外择优机会，补助受限制。"),
    ("C31", "命运留门", "common", "wheel", "命运之轮第四层及以后最终失败时，有机会带回部分入场费。"),
    ("C32", "落袋有喜", "common", "wheel", "命运之轮盈利收手时，追加小额奖励。"),
    ("S16", "败而不空", "silver", "wheel", "命运之轮最终失败时，返还部分入场费。"),
    ("G16", "五层礼遇", "gold", "wheel", "命运之轮到达第五层后盈利结算，追加奖励。"),
    ("P15", "命运逆转", "prismatic", "wheel", "命运之轮第四层及以后最终失败时，有机会带回小额入场费。"),
    ("P16", "阶梯庆典", "prismatic", "wheel", "命运之轮达到第三、第六或第十层后结算，领取最高档庆典奖励。"),
)

for _id, _name, _pool, _operation, _text in _EXPANSION_CATALOG:
    EFFECTS[_id] = _entry(_id, _name, _pool, _text, EXPANSION_GROUPS[_operation])
    EFFECTS[_id]["operation"] = _operation
for _definition in EFFECTS.values():
    _definition.setdefault("operation", "fishing")

EFFECTS["C33"] = _entry("C33", "海克斯福袋", "common", "随机获得额外海克斯，赠卡的额外强度为普通卡的25%。")
EFFECTS["C33"]["operation"] = "bonus"

PREMIUM_EFFECT_IDS = ("C34", "S17", "G17", "P17")
PREMIUM_CONDITIONS = {
    "C34": "rare",
    "S17": "empty",
    "G17": "quality_rare",
    "P17": "top_rarity",
}
PREMIUM_BASE_CHANCES = {
    "C34": 0.032,
    "S17": 0.10,
    "G17": 0.16,
    "P17": 0.10,
}

EFFECTS["C34"] = _entry("C34", "瓶中微光", "common", "最终钓到稀有鱼（四星及以上）时，有概率获得1点高级货币。",
                        ("S17", "G17", "P17"))
EFFECTS["S17"] = _entry("S17", "空钩奇遇", "silver", "实际付费钓鱼最终空竿时，有概率获得1点高级货币。",
                        ("C34", "G17", "P17"))
EFFECTS["G17"] = _entry("G17", "闪光结晶", "gold", "最终钓到高品质且四星以上稀有鱼时，有概率获得1点高级货币。",
                        ("C34", "S17", "P17"))
EFFECTS["P17"] = _entry("P17", "鱼王秘藏", "prismatic", "最终鱼星级等于当前鱼区最高可抽星级且最高达到四星以上时，有概率获得1点高级货币。",
                        ("C34", "S17", "G17"))
for _premium_id in PREMIUM_EFFECT_IDS:
    EFFECTS[_premium_id]["operation"] = "fishing"


EXPANSION_IDS = frozenset(effect_id for group in EXPANSION_GROUPS.values() for effect_id in group)


def _roll_expansion_params(effect_id: str, tier: str, rng: Any) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "ev_budget": {"silver": 0.05, "gold": 0.065, "prismatic": 0.08}[tier],
        "chance": 1.0,
    }
    if effect_id == "C23":
        params["cooldown_reduction"] = _roll_between(rng, _tier_range(
            tier, ((0.10, 0.15), (0.15, 0.20), (0.20, 0.25))))
    if effect_id == "C25":
        params["fraction"] = _roll_between(rng, _tier_range(
            tier, ((0.20, 0.30), (0.35, 0.45), (0.50, 0.60))))
    if effect_id == "C26":
        params.update({"chance": {"silver": 0.15, "gold": 0.25, "prismatic": 0.35}[tier],
                       "price_fraction": {"silver": 0.03, "gold": 0.05, "prismatic": 0.08}[tier],
                       "fraction": {"silver": 0.03, "gold": 0.05, "prismatic": 0.08}[tier],
                       "bonus_cap": {"silver": 300, "gold": 800, "prismatic": 1500}[tier]})
    if effect_id == "S12":
        params["chance"] = _roll_between(rng, (0.25, 0.35))
    if effect_id == "P12":
        params["chance"] = _roll_between(rng, (0.25, 0.35))
    if effect_id == "C28":
        params.update({"chance": {"silver": 0.15, "gold": 0.25, "prismatic": 0.35}[tier],
                       "fraction": 0.20})
    if effect_id == "S13":
        params.update({"fraction": _roll_between(rng, (0.05, 0.08)), "bonus_cap": 500})
    if effect_id == "S14":
        params.update({"chance": _roll_between(rng, (0.20, 0.30)), "bonus_cap": 0.05})
    if effect_id == "G13":
        params["weight_multiplier"] = _roll_between(rng, (1.10, 1.15))
    if effect_id in EXPANSION_GROUPS["wipe"]:
        params.update({"return_cap": {"silver": 1.01, "gold": 1.02, "prismatic": 1.03}[tier],
                       "bonus_cap": 20000})
    if effect_id == "C29":
        params.update({"chance": _roll_between(rng, _tier_range(
            tier, ((0.20, 0.25), (0.30, 0.35), (0.40, 0.50)))), "fraction": 0.20})
    if effect_id == "C30":
        params["fraction"] = _roll_between(rng, _tier_range(
            tier, ((0.05, 0.08), (0.10, 0.12), (0.15, 0.18))))
    if effect_id == "S15":
        params["chance"] = _roll_between(rng, (0.25, 0.35))
    if effect_id == "G14":
        params.update({"fraction": _roll_between(rng, (0.05, 0.08)), "price_fraction": 0.10})
    if effect_id == "G15":
        params["chance"] = _roll_between(rng, (0.25, 0.35))
    if effect_id == "P14":
        params["fraction"] = 0.20
    if effect_id == "C31":
        params.update({"chance": _roll_between(rng, _tier_range(
            tier, ((0.15, 0.20), (0.20, 0.25), (0.25, 0.30)))),
                       "fraction": {"silver": 0.03, "gold": 0.04, "prismatic": 0.05}[tier]})
    if effect_id == "C32":
        params.update({"fraction": _roll_between(rng, _tier_range(
            tier, ((0.05, 0.08), (0.10, 0.12), (0.15, 0.18)))),
                       "bonus_cap": {"silver": 0.05, "gold": 0.10, "prismatic": 0.15}[tier]})
    if effect_id == "S16":
        params["fraction"] = _roll_between(rng, (0.10, 0.15))
    if effect_id == "G16":
        params.update({"fraction": _roll_between(rng, (0.08, 0.12)), "bonus_cap": 0.20})
    if effect_id == "P15":
        params.update({"chance": _roll_between(rng, (0.40, 0.50)), "fraction": 0.06})
    if effect_id == "P16":
        params["milestones"] = {"3": 0.10, "6": 0.20, "10": 0.30}
    return params


def _tier_range(tier: str, values: Sequence[Tuple[float, float]]) -> Tuple[float, float]:
    return values[TIERS.index(tier)]


def _roll_between(rng: Any, bounds: Tuple[float, float]) -> float:
    return round(float(rng.uniform(bounds[0], bounds[1])), 4)


_PRICE_GENERAL = ((0.25, 0.40), (0.50, 0.80), (0.90, 1.30))
_PRICE_TARGETED = ((0.35, 0.70), (0.70, 1.20), (1.20, 1.80))
_PRICE_RARE = ((0.35, 0.70), (0.70, 1.20), (1.20, 1.80))
_PRICE_HIGH_VALUE = ((0.35, 0.70), (0.70, 1.20), (1.20, 1.80))
_PRICE_TOP = ((0.45, 0.80), (0.90, 1.40), (1.40, 1.80))
_PRICE_HIGH_STAR = ((0.08, 0.12), (0.15, 0.25), (0.25, 0.40))
_COST_DISCOUNT = ((0.30, 0.50), (0.55, 0.80), (0.80, 1.00))
_EMPTY_RETRY = ((0.25, 0.35), (0.45, 0.60), (0.70, 0.85))
_QUALITY_EXTRA = ((0.10, 0.15), (0.20, 0.25), (0.30, 0.35))
_RARE_TRANSFER = ((0.10, 0.15), (0.20, 0.30), (0.35, 0.45))
_LUCKY_CHANCE = ((0.10, 0.15), (0.20, 0.25), (0.30, 0.35))
_LOW_REROLL = ((0.50, 0.65), (0.75, 0.90), (1.00, 1.00))
_SPECIES_REROLL = ((0.40, 0.60), (0.70, 0.85), (1.00, 1.00))
_PROTECTION = ((0.50, 0.65), (0.75, 0.90), (1.00, 1.00))
_VALUE_FLOOR = ((0.75, 1.00), (1.25, 1.50), (1.75, 2.00))

# Balance version 1 is kept above so cards already stored in the daily-choice
# table retain their original numeric ranges. Version 3 keeps version 2 fishing
# parameters while adding the operation effects below.
_PRICE_GENERAL_V2 = ((0.15, 0.25), (0.25, 0.40), (0.40, 0.60))
_PRICE_TARGETED_V2 = ((0.25, 0.40), (0.40, 0.65), (0.60, 0.90))
_PRICE_HIGH_STAR_V2 = ((0.03, 0.05), (0.05, 0.08), (0.08, 0.12))
_PRICE_SUPPLEMENTAL_V2 = ((0.05, 0.10), (0.10, 0.15), (0.15, 0.20))
_PRICE_SUPPLEMENTAL_HIGH_STAR_V2 = ((0.01, 0.02), (0.02, 0.03), (0.03, 0.04))
_COST_DISCOUNT_V2 = ((0.15, 0.25), (0.25, 0.40), (0.40, 0.60))
_FISH_REFUND_V2 = ((0.20, 0.35), (0.35, 0.55), (0.50, 0.70))
_EMPTY_RETRY_V2 = ((0.25, 0.35), (0.40, 0.55), (0.60, 0.75))
_QUALITY_EXTRA_V2 = ((0.04, 0.07), (0.08, 0.12), (0.14, 0.18))
_RARE_TRANSFER_V2 = ((0.04, 0.07), (0.08, 0.12), (0.14, 0.20))
_LUCKY_CHANCE_V2 = ((0.10, 0.15), (0.15, 0.20), (0.20, 0.25))
_LOW_REROLL_V2 = ((0.45, 0.60), (0.65, 0.80), (0.85, 0.95))
_SPECIES_REROLL_V2 = ((0.35, 0.50), (0.55, 0.70), (0.75, 0.85))
_PROTECTION_V2 = ((0.40, 0.55), (0.60, 0.75), (0.80, 0.90))
_VALUE_FLOOR_V2 = ((0.60, 0.80), (0.80, 1.00), (1.00, 1.20))

_SUPPLEMENTAL_PRICE_IDS = {"C17", "C19", "C20", "S06", "S08", "S09", "S10", "G09"}


def _price_params(tier: str, rng: Any, targeted: bool = False,
                  balance_version: int = 2, supplemental: bool = False) -> Dict[str, float]:
    if balance_version >= 2 and supplemental:
        general_bounds = _PRICE_SUPPLEMENTAL_V2
        high_star_bounds = _PRICE_SUPPLEMENTAL_HIGH_STAR_V2
    elif balance_version >= 2:
        general_bounds = _PRICE_TARGETED_V2 if targeted else _PRICE_GENERAL_V2
        high_star_bounds = _PRICE_HIGH_STAR_V2
    else:
        general_bounds = _PRICE_TARGETED if targeted else _PRICE_GENERAL
        high_star_bounds = _PRICE_HIGH_STAR
    return {
        "price_1_5": _roll_between(rng, _tier_range(tier, general_bounds)),
        "price_6_8": _roll_between(rng, _tier_range(tier, high_star_bounds)),
    }


def _roll_params(effect_id: str, tier: str, rng: Any,
                 balance_version: int = 2) -> Dict[str, Any]:
    if effect_id in EXPANSION_IDS:
        return _roll_expansion_params(effect_id, tier, rng)
    if effect_id in PREMIUM_EFFECT_IDS:
        return {
            "premium_chance": PREMIUM_BASE_CHANCES[effect_id],
            "premium_condition": PREMIUM_CONDITIONS[effect_id],
        }
    params: Dict[str, Any] = {}
    is_v2 = balance_version >= 2
    cost_discount_ranges = _COST_DISCOUNT_V2 if is_v2 else _COST_DISCOUNT
    fish_refund_ranges = _FISH_REFUND_V2 if is_v2 else ((0.30, 0.50), (0.55, 0.80), (0.80, 1.00))
    value_floor_ranges = _VALUE_FLOOR_V2 if is_v2 else _VALUE_FLOOR
    quality_extra_ranges = _QUALITY_EXTRA_V2 if is_v2 else _QUALITY_EXTRA
    rare_transfer_ranges = _RARE_TRANSFER_V2 if is_v2 else _RARE_TRANSFER
    lucky_chance_ranges = _LUCKY_CHANCE_V2 if is_v2 else _LUCKY_CHANCE
    empty_retry_ranges = _EMPTY_RETRY_V2 if is_v2 else _EMPTY_RETRY
    species_reroll_ranges = _SPECIES_REROLL_V2 if is_v2 else _SPECIES_REROLL
    low_reroll_ranges = _LOW_REROLL_V2 if is_v2 else _LOW_REROLL
    protection_ranges = _PROTECTION_V2 if is_v2 else _PROTECTION
    if effect_id in ("C01", "P01", "P10"):
        params["cost_discount"] = _roll_between(rng, _tier_range(tier, cost_discount_ranges))
    if effect_id == "C02":
        small_discount = ((0.05, 0.08), (0.08, 0.12), (0.12, 0.16)) if is_v2 else (
            (0.08, 0.13), (0.10, 0.15), (0.13, 0.17))
        params.update({"cost_discount": _roll_between(rng, _tier_range(tier, small_discount)),
                       "empty_refund": _roll_between(rng, _tier_range(tier, fish_refund_ranges))})
    if effect_id in ("C03", "S02"):
        params["low_fish_refund"] = _roll_between(rng, _tier_range(tier, fish_refund_ranges))
    if effect_id in ("C04", "G07"):
        params["value_floor_multiple"] = _roll_between(rng, _tier_range(tier, value_floor_ranges))
    if effect_id in ("C05", "C17", "C19", "C20", "S02", "S06", "S08", "S09", "S10", "G07", "G09", "P01"):
        params.update(_price_params(tier, rng, targeted=effect_id in ("S02", "S06", "S08"),
                                    balance_version=balance_version,
                                    supplemental=effect_id in _SUPPLEMENTAL_PRICE_IDS))
    if effect_id in ("C06", "S03", "G02", "G08", "P05", "P08"):
        params.update(_price_params(tier, rng, targeted=True, balance_version=balance_version))
    if effect_id in ("C07", "S04", "G03"):
        params.update(_price_params(tier, rng, targeted=True, balance_version=balance_version))
    if effect_id in ("C08", "G03", "P03", "P09"):
        params.update(_price_params(tier, rng, targeted=True, balance_version=balance_version))
    if effect_id in ("C09", "S07", "G06", "P04"):
        quality_prices = _price_params(tier, rng, targeted=True, balance_version=balance_version)
        params["quality_price_1_5"] = quality_prices["price_1_5"]
        params["quality_price_6_8"] = quality_prices["price_6_8"]
    if effect_id == "C10":
        params.update(_price_params(tier, rng, targeted=True, balance_version=balance_version))
    if effect_id in ("C11", "G05"):
        params["lucky_chance"] = _roll_between(rng, _tier_range(tier, lucky_chance_ranges))
        params["lucky_price_1_5"] = _roll_between(rng, _tier_range(
            tier, _PRICE_TARGETED_V2 if is_v2 else _PRICE_TARGETED))
        params["lucky_price_6_8"] = _roll_between(rng, _tier_range(
            tier, _PRICE_HIGH_STAR_V2 if is_v2 else _PRICE_HIGH_STAR))
    if effect_id in ("C12", "S07", "G06", "P04"):
        params["quality_extra_chance"] = _roll_between(rng, _tier_range(tier, quality_extra_ranges))
    if effect_id in ("C13", "S03", "G02", "P08"):
        params["rare_transfer"] = _roll_between(rng, _tier_range(tier, rare_transfer_ranges))
    if effect_id in ("C14", "S04", "G03", "P02", "P09"):
        params["high_weight_strength"] = _roll_between(rng, (0.0, 1.0))
    if effect_id in ("C15", "S05", "G04", "P03"):
        params["upgrade_strength"] = _roll_between(rng, (0.0, 1.0))
    if effect_id in ("C16", "C16", "G08", "P02", "P09"):
        bonus = ({"silver": 0.005, "gold": 0.01, "prismatic": 0.015} if is_v2
                 else {"silver": 0.01, "gold": 0.015, "prismatic": 0.025})[tier]
        params["break_bonus"] = bonus
    if effect_id in ("C17", "S01", "G01", "P06"):
        params["empty_retry_chance"] = _roll_between(rng, _tier_range(tier, empty_retry_ranges))
    if effect_id in ("S01", "G01", "P06"):
        refund_ranges = fish_refund_ranges if effect_id == "S01" else (
            ((0.35, 0.55), (0.35, 0.55), (0.50, 0.70)) if is_v2 else
            ((0.30, 0.50), (0.60, 0.80), (1.00, 1.00)))
        params["empty_refund"] = _roll_between(rng, _tier_range(tier, refund_ranges))
    if effect_id in ("C18", "S08", "G10"):
        params["species_reroll_chance"] = _roll_between(rng, _tier_range(tier, species_reroll_ranges))
    if effect_id in ("S06", "G10"):
        params["low_value_reroll_chance"] = _roll_between(rng, _tier_range(tier, low_reroll_ranges))
    if effect_id in ("C19", "S09", "G09", "P10"):
        params["rod_preserve_chance"] = _roll_between(rng, _tier_range(tier, protection_ranges))
    if effect_id in ("C20", "S10", "G09", "P10"):
        params["bait_preserve_chance"] = _roll_between(rng, _tier_range(tier, protection_ranges))
    if effect_id == "P05":
        params["ordinary_refund"] = 0.75 if is_v2 else 1.0
    if effect_id == "P06":
        params["empty_refund"] = 0.85 if is_v2 else 1.0
    if effect_id == "P07":
        params["fate_options"] = ["refund", "price", "quality"]
        params["fate_refund"] = _roll_between(rng, _tier_range(
            tier, ((0.50, 0.70),) * 3 if is_v2 else _COST_DISCOUNT))
        params["fate_price_1_5"] = _roll_between(rng, _tier_range(
            tier, _PRICE_TARGETED_V2 if is_v2 else _PRICE_TARGETED))
        params["fate_price_6_8"] = _roll_between(rng, _tier_range(
            tier, _PRICE_HIGH_STAR_V2 if is_v2 else _PRICE_HIGH_STAR))
        params["fate_quality_chance"] = _roll_between(rng, _tier_range(tier, quality_extra_ranges))
    if effect_id == "P08":
        params["rare_quality_chance"] = _roll_between(rng, _tier_range(tier, quality_extra_ranges))
    if effect_id in ("S05", "G04"):
        targeted_prices = _PRICE_TARGETED_V2 if is_v2 else _PRICE_TARGETED
        high_star_prices = _PRICE_HIGH_STAR_V2 if is_v2 else _PRICE_HIGH_STAR
        params["upgrade_price_1_5"] = _roll_between(rng, _tier_range(tier, targeted_prices))
        params["upgrade_price_6_8"] = _roll_between(rng, _tier_range(tier, high_star_prices))
    return params


def _conflict_ids(effect_id: str) -> Set[str]:
    return set(EFFECTS[effect_id]["conflicts"])


def _choose(rng: Any, pool: Sequence[str], excluded: Set[str]) -> str:
    candidates = [effect_id for effect_id in pool if effect_id not in excluded]
    if not candidates:
        raise ValueError("no compatible Hextech effects remain")
    return rng.choice(candidates)


def _v4_params(effect_id: str, tier: str, rng: Any, gift: bool = False) -> Dict[str, Any]:
    if effect_id == "C33":
        return {"gift_count": GIFT_SLOT_COUNTS[tier]}
    if effect_id in PREMIUM_EFFECT_IDS:
        base_chance = PREMIUM_BASE_CHANCES[effect_id]
        chance = round(base_chance * GIFT_STRENGTH, 4) if gift else base_chance
        return {
            "premium_chance": chance,
            "premium_condition": PREMIUM_CONDITIONS[effect_id],
            "is_gift": gift,
        }
    params = _roll_params(effect_id, tier, rng, balance_version=2)
    gift_scale = GIFT_STRENGTH if gift else 1.0
    if effect_id in EXPANSION_IDS:
        # Operation effects share one conflict group, so extra slots broaden
        # coverage rather than granting another full budget for the same action.
        params["ev_budget"] = V4_EV_BUDGETS[tier] * gift_scale
        reward_scale = V4_EV_BUDGETS[tier] / {"silver": .05, "gold": .065, "prismatic": .08}[tier] * gift_scale
        params["ev_scale"] = reward_scale
        # Reward-bearing procs reduce the reward, not both reward and chance.
        reward_keys = {"fraction", "price_fraction", "bonus_cap", "milestones"}
        for key in reward_keys & params.keys():
            value = params[key]
            if isinstance(value, dict):
                params[key] = {k: v * reward_scale for k, v in value.items()}
            else:
                params[key] = value * reward_scale
        if "weight_multiplier" in params:
            params["weight_multiplier"] = 1 + (params["weight_multiplier"] - 1) * reward_scale
        if not reward_keys & params.keys():
            params["chance"] *= reward_scale
        # A cooldown effect is also bounded by its EV budget at action time.
        if "cooldown_reduction" in params:
            params["cooldown_reduction"] *= reward_scale
    else:
        scale = FISHING_STRENGTH[tier] * gift_scale
        for key, value in list(params.items()):
            if isinstance(value, (int, float)) and key not in {"high_weight_strength", "upgrade_strength"}:
                params[key] = value * scale
        # These two parameters index dynamic ranges; scale their resolved
        # probability / excess weight, never the random range position itself.
        params["strength_scale"] = scale
    return params


def _compatible(effect_id: str, selected: Sequence[str]) -> bool:
    return effect_id not in selected and all(
        other not in _conflict_ids(effect_id) and effect_id not in _conflict_ids(other)
        for other in selected
    )


def _weighted_permutation(
    rng: Any,
    candidates: Sequence[str],
    history_weights: Optional[Dict[str, float]] = None,
    sibling_effect_ids: Optional[Set[str]] = None,
    same_group_weight: float = 1.0,
) -> List[str]:
    """Return a weighted random ordering without removing hard-compatible fallbacks.

    The compatibility search still considers every candidate. History and
    same-offer repetition affect only ordering, never the hard conflict rules.
    """
    remaining = list(candidates)
    history_weights = history_weights or {}
    sibling_effect_ids = sibling_effect_ids or set()
    weights = {
        effect_id: max(0.0, float(history_weights.get(effect_id, 1.0)))
        * (same_group_weight if effect_id in sibling_effect_ids else 1.0)
        for effect_id in remaining
    }
    if all(abs(weights[effect_id] - 1.0) < 1e-12 for effect_id in remaining):
        rng.shuffle(remaining)
        return remaining

    ordered: List[str] = []
    while remaining:
        total = sum(weights[effect_id] for effect_id in remaining)
        if total <= 0:
            rng.shuffle(remaining)
            ordered.extend(remaining)
            break
        value = rng.random() * total
        cumulative = 0.0
        chosen = remaining[-1]
        for effect_id in remaining:
            cumulative += weights[effect_id]
            if value < cumulative:
                chosen = effect_id
                break
        ordered.append(chosen)
        remaining.remove(chosen)
    return ordered


def _roll_single(tier: str, rng: Any, selected: Sequence[str], fishing_only: bool,
                 allow_gift: bool, gift: bool = False, effect_count: Optional[int] = None,
                 history_weights: Optional[Dict[str, float]] = None,
                 sibling_effect_ids: Optional[Set[str]] = None,
                 same_group_weight: float = 1.0,
                 balance_version: int = 4) -> Dict[str, Any]:
    available = {key: effect for key, effect in EFFECTS.items()
                 if (not fishing_only or effect["operation"] == "fishing")
                 and (allow_gift or key != "C33")}
    pools = {name: [key for key, effect in available.items() if effect["pool"] == name]
             for name in ("common", tier)}
    effect_count = SLOT_COUNTS[tier] if effect_count is None else int(effect_count)
    if not 2 <= effect_count <= 5:
        raise ValueError("effect_count must be between 2 and 5")
    choices = ["common", tier] + [
        "common" if rng.random() < 0.5 else tier
        for _ in range(effect_count - 2)
    ]

    def fill(index: int, result: List[str]) -> Optional[List[str]]:
        if index == len(choices):
            return result
        preferred = choices[index]
        order = [preferred]
        if index >= 2:
            order.append(tier if preferred == "common" else "common")
        for pool in order:
            candidates = [
                key for key in pools[pool]
                if _compatible(key, list(selected) + result)
            ]
            ordered = _weighted_permutation(
                rng,
                candidates,
                history_weights,
                sibling_effect_ids,
                same_group_weight,
            )
            for key in ordered:
                completed = fill(index + 1, result + [key])
                if completed is not None:
                    return completed
        return None

    ids = fill(0, [])
    if ids is None:
        raise ValueError("no compatible Hextech effects remain")
    return {"tier": tier, "balance_version": balance_version, "effects": [
        {"id": key, "tier": tier, "params": _v4_params(key, tier, rng, gift)}
        for key in ids
    ]}


def _roll_card_once(
    tier: str,
    rng: Any,
    fishing_only: bool,
    effect_count: int,
    history_weights: Optional[Dict[str, float]],
    sibling_effect_ids: Optional[Set[str]],
    same_group_weight: float,
) -> Dict[str, Any]:
    balance_version = 4 if effect_count == SLOT_COUNTS[tier] else 5
    card = _roll_single(
        tier,
        rng,
        [],
        fishing_only,
        True,
        effect_count=effect_count,
        history_weights=history_weights,
        sibling_effect_ids=sibling_effect_ids,
        same_group_weight=same_group_weight,
        balance_version=balance_version,
    )
    if any(effect["id"] == "C33" for effect in card["effects"]):
        selected = [effect["id"] for effect in card["effects"]]
        gifts = []
        for _ in range(GIFT_SLOT_COUNTS[tier]):
            value = rng.random()
            gift_tier = "silver" if value < 0.50 else "gold" if value < 0.85 else "prismatic"
            child = _roll_single(
                gift_tier,
                rng,
                selected,
                False,
                False,
                gift=True,
                effect_count=GIFT_SLOT_COUNTS[gift_tier],
                balance_version=4,
            )
            gifts.append(child)
            selected.extend(effect["id"] for effect in child["effects"])
        card["gifts"] = gifts
    return card


def roll_card(
    tier: str,
    rng: Optional[Any] = None,
    fishing_only: bool = False,
    *,
    effect_counts: Optional[Dict[str, int]] = None,
    history_weights: Optional[Dict[str, float]] = None,
    sibling_effect_ids: Optional[Set[str]] = None,
    same_group_weight: float = 1.0,
) -> Dict[str, Any]:
    """Two guaranteed pools, then independent 50/50 pool slots.

    Gifts are hidden, persisted rolls revealed on selection. They are never
    regenerated by rendering, service reads or restarts.
    """
    tier = str(tier).lower()
    if tier not in TIERS:
        raise ValueError("tier must be silver, gold, or prismatic")
    rng = rng or random
    requested_count = SLOT_COUNTS[tier]
    if effect_counts:
        requested_count = int(effect_counts.get(tier, requested_count))
    if not 2 <= requested_count <= 5:
        raise ValueError("configured effect count must be between 2 and 5")

    try:
        return _roll_card_once(
            tier,
            rng,
            fishing_only,
            requested_count,
            history_weights,
            sibling_effect_ids,
            same_group_weight,
        )
    except ValueError:
        if requested_count == SLOT_COUNTS[tier]:
            raise
        logging.getLogger(__name__).warning(
            "Configured %s Hextech card with %s effects had no compatible roll; "
            "falling back to the legacy %s-effect card",
            tier,
            requested_count,
            SLOT_COUNTS[tier],
        )
        return _roll_card_once(
            tier,
            rng,
            fishing_only,
            SLOT_COUNTS[tier],
            history_weights,
            sibling_effect_ids,
            same_group_weight,
        )


def effective_card(card: Dict[str, Any]) -> Dict[str, Any]:
    """Flatten persisted gifts once for every game service and wheel snapshot."""
    from copy import deepcopy
    result = deepcopy(card)
    gifts = result.pop("gifts", [])
    for gift in gifts:
        result.setdefault("effects", []).extend(gift.get("effects", []))
    return result


_UPGRADE_RANGES = {
    "silver": {4: (0.10, 0.20), 5: (0.10, 0.20), 6: (0.03, 0.06), 7: (0.005, 0.01), 8: (0.001, 0.003)},
    "gold": {4: (0.25, 0.40), 5: (0.25, 0.40), 6: (0.08, 0.12), 7: (0.015, 0.03), 8: (0.004, 0.008)},
    "prismatic": {4: (0.45, 0.65), 5: (0.45, 0.65), 6: (0.15, 0.22), 7: (0.04, 0.06), 8: (0.01, 0.015)},
}


_UPGRADE_RANGES_V2 = {
    "silver": {4: (0.06, 0.10), 5: (0.06, 0.10), 6: (0.01, 0.02), 7: (0.002, 0.004), 8: (0.0005, 0.001)},
    "gold": {4: (0.12, 0.20), 5: (0.12, 0.20), 6: (0.03, 0.05), 7: (0.005, 0.01), 8: (0.0015, 0.003)},
    "prismatic": {4: (0.25, 0.35), 5: (0.25, 0.35), 6: (0.06, 0.09), 7: (0.015, 0.025), 8: (0.004, 0.006)},
}


def upgrade_chance(tier: str, strength: float, target_rarity: int,
                   balance_version: int = 1, strength_scale: float = 1.0) -> float:
    """Resolve a stored strength roll against the destination star's safe range."""
    ranges = _UPGRADE_RANGES_V2 if balance_version >= 2 else _UPGRADE_RANGES
    bounds = ranges.get(tier, ranges["silver"]).get(int(target_rarity))
    if not bounds:
        return 0.0
    return (bounds[0] + (bounds[1] - bounds[0]) * max(0.0, min(1.0, float(strength)))) * strength_scale


def high_weight_multiplier(tier: str, strength: float, max_rarity: int,
                           balance_version: int = 1, strength_scale: float = 1.0) -> float:
    """Resolve the H-dependent high-rarity multiplier from the stored roll."""
    if balance_version >= 2:
        if max_rarity <= 5:
            bounds = {"silver": (1.10, 1.20), "gold": (1.25, 1.45), "prismatic": (1.50, 1.75)}[tier]
        elif max_rarity == 6:
            bounds = {"silver": (1.04, 1.08), "gold": (1.10, 1.16), "prismatic": (1.20, 1.30)}[tier]
        else:
            bounds = {"silver": (1.01, 1.02), "gold": (1.025, 1.04), "prismatic": (1.05, 1.07)}[tier]
    elif max_rarity <= 5:
        bounds = {"silver": (1.25, 1.45), "gold": (1.6, 2.0), "prismatic": (2.2, 2.8)}[tier]
    elif max_rarity == 6:
        bounds = {"silver": (1.10, 1.20), "gold": (1.25, 1.45), "prismatic": (1.55, 1.80)}[tier]
    else:
        bounds = {"silver": (1.02, 1.04), "gold": (1.05, 1.08), "prismatic": (1.10, 1.15)}[tier]
    strength = max(0.0, min(1.0, float(strength)))
    return 1 + (bounds[0] + (bounds[1] - bounds[0]) * strength - 1) * strength_scale


def _eligible(eligible_rarities: Iterable[int]) -> List[int]:
    result = []
    for value in eligible_rarities or ():
        try:
            rarity = int(value)
        except (TypeError, ValueError):
            continue
        if rarity > 0 and rarity not in result:
            result.append(rarity)
    return sorted(result)


def _expansion_description(effect: Dict[str, Any]) -> str:
    effect_id = effect["id"]
    params = effect.get("params") or {}
    coins = lambda value: int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    pct = lambda key: "{:.1f}%".format(float(params.get(key, 0.0)) * 100)
    descriptions = {
        "C21": "有机会抽取两条候选，偷走更值钱的一条，每次仍只拿一条鱼",
        "C22": "偷到普通品质鱼时，有机会把同一条鱼变成高品质；鱼种与稀有度不变",
        "C23": "成功偷鱼后的冷却缩短，按今日收获提升目标调整",
        "S11": "初选鱼属于目标鱼塘价值最低的四分之一时，有机会再挑一次并保留更值钱的一条",
        "G11": "有机会抽取三条候选，只偷走更值钱的一条",
        "P11": "有机会改从目标鱼塘当前最高档的鱼中挑选，每次仍只拿一条鱼",
        "C24": "电鱼失败时有机会免费重判一次，最终失败才结算天罚",
        "C25": "电鱼最终失败时减少天罚，最多减免 " + pct("fraction"),
        "C26": "成功电鱼后有机会获得捕获价值 " + pct("fraction") + " 的系统赏金，每次最多 {} 金币".format(coins(params.get("bonus_cap", 0))),
        "S12": "电鱼小成功有机会提升为普通成功，再按对应规则决定捕获数量",
        "G12": "成功电鱼后，有机会将捕获中最便宜的鱼与剩余鱼塘再抽的一条择优，总数量不增加",
        "P12": "电鱼小成功或普通成功有机会提升一档，最多提升一次",
        "C27": "抽到当前卡池最低档奖励时，有机会再抽一次，只发放更高档结果；保底结果不会重抽",
        "C28": "抽到鱼饵或可堆叠道具时，有机会增加 " + pct("fraction") + " 数量，至少增加一个",
        "S13": "金币付费抽卡后返还部分实付金币，最多返还 " + pct("fraction") + "，每抽最多 {} 金币；免费及高级货币抽卡不返费".format(coins(params.get("bonus_cap", 0))),
        "S14": "金币付费抽卡抽中金币奖励时，有机会额外获得最多单抽费用 {:.1f}% 的小红包".format(float(params.get("bonus_cap", 0)) * 100),
        "G13": "提高当前卡池最高档非金币奖励的权重，最多 ×{:.2f}".format(float(params.get("weight_multiplier", 1))),
        "P13": "非保底抽取有机会生成两个候选，只发放更高档的一个；同档保留第一个",
        "C29": "擦弹回报低于投入一半时，有机会重抽一次并择优，新增金额最多为投入的 " + pct("fraction"),
        "C30": "擦弹最终亏损时补回部分损失，最多补回亏损的 " + pct("fraction"),
        "S15": "擦弹回报在投入的80%至100%之间时，有机会补到刚好回本",
        "G14": "擦弹盈利时追加净利润的 " + pct("fraction") + "，最多增加投入的 " + pct("price_fraction"),
        "G15": "擦弹有机会在原奖励区间内再抽一次，保留更高的回报",
        "P14": "擦弹回报低于投入一半时获得额外择优机会，新增金额最多为投入的 " + pct("fraction"),
        "C31": "命运之轮第四层及以后最终失败时，有 " + pct("chance") + " 机会带回入场费的 " + pct("fraction") + "，随后结束游戏",
        "C32": "命运之轮盈利结算时追加净利润的 " + pct("fraction") + "，最多增加入场费 {:.1f}%".format(float(params.get("bonus_cap", 0)) * 100),
        "S16": "命运之轮最终失败时，有机会返还入场费的 " + pct("fraction") + "，随后结束游戏",
        "G16": "命运之轮到达第五层后盈利结算，追加净利润的 " + pct("fraction") + "，最多增加入场费 " + pct("bonus_cap"),
        "P15": "命运之轮第四层及以后最终失败时，有 " + pct("chance") + " 机会带回入场费的 " + pct("fraction") + "，随后结束游戏",
        "P16": "命运之轮到达第3／6／10层后成功结算，额外获得入场费的" + "／".join(
            "{:.1f}%".format(float(params.get("milestones", {}).get(k, default)) * 100)
            for k, default in (("3", .1), ("6", .2), ("10", .3))) + "，只领取最高一档",
    }
    text = descriptions[effect_id]
    operation = EFFECTS[effect_id]["operation"]
    if operation in ("steal", "electric", "gacha"):
        text += "；额外收益按当前玩法控制，提升目标最多 " + pct("ev_budget")
    elif operation == "wipe":
        text += "；额外补助最多 {} 金币，今日效果的长期返还率最多 {:.1f}%".format(
            coins(params.get("bonus_cap", 20000)), float(params.get("return_cap", 1)) * 100)
    return "{}：{}".format(EFFECTS[effect_id]["name"], text)


def _effect_description(effect: Dict[str, Any], tier: str, eligible: Sequence[int],
                        balance_version: int = 1) -> str:
    effect_id = effect.get("id")
    if effect_id == "C33":
        count = (effect.get("params") or {}).get("gift_count", 1)
        return f"海克斯福袋：随机获得{count}张额外海克斯；品质概率为白银50%、黄金35%、棱彩15%；赠卡额外强度为普通卡的25%"
    if effect_id in EXPANSION_IDS:
        return _expansion_description(effect)
    if effect_id in PREMIUM_EFFECT_IDS:
        name = EFFECTS.get(effect_id, {}).get("name", effect_id or "未知效果")
        params = effect.get("params") or {}
        chance = float(params.get("premium_chance", PREMIUM_BASE_CHANCES[effect_id]))
        chance_val = round(chance * 100, 3)
        if abs(chance_val - round(chance_val, 1)) < 1e-6:
            chance_pct = "{:.1f}%".format(chance_val)
        else:
            chance_pct = "{:.2f}%".format(chance_val)
        gift_note = "（赠卡缩减至25%）" if (params.get("is_gift") or chance < PREMIUM_BASE_CHANCES[effect_id]) else ""
        scale_note = "；实际概率随钓鱼冷却缩放（基准120秒）"
        if effect_id == "C34":
            return f"{name}：最终钓到稀有鱼（四星及以上）时，有 {chance_pct} 概率获得1点高级货币{gift_note}{scale_note}"
        elif effect_id == "S17":
            return f"{name}：付费钓鱼最终空竿时，有 {chance_pct} 概率获得1点高级货币{gift_note}{scale_note}"
        elif effect_id == "G17":
            return f"{name}：最终钓到高品质稀有鱼（四星及以上）时，有 {chance_pct} 概率获得1点高级货币{gift_note}{scale_note}"
        elif effect_id == "P17":
            top_val = max(eligible) if eligible else 0
            zone_info = f"（当前鱼区最高{top_val}星）" if top_val >= 4 else "（当前鱼区最高未达四星）"
            return f"{name}：最终鱼星级等于当前鱼区最高可抽星级且最高达到四星以上{zone_info}时，有 {chance_pct} 概率获得1点高级货币{gift_note}{scale_note}"
    params = effect.get("params") or {}
    name = EFFECTS.get(effect_id, {}).get("name", effect_id or "未知效果")
    rare = [rarity for rarity in eligible if rarity >= 4]
    high = rare[-2:]
    top = eligible[-1:]  # Each display resolves targets from the current zone.
    ordinary_label = "普通鱼（一至三星）"
    rare_label = "稀有鱼（四星及以上）"
    high_label = "珍贵鱼（当前鱼区稀有鱼中最高的两档）"
    top_label = "鱼王（当前鱼区最高档的鱼）"
    parts = []

    def percent(key: str) -> str:
        return "{:.1f}%".format(float(params.get(key, 0)) * 100)

    def prices(prefix: str = "price", targets=None) -> str:
        active = eligible if targets is None else targets
        if not active:
            return "当前鱼区暂无这类鱼"
        low_bonus = float(params.get(prefix + "_1_5", 0)) * 100
        high_bonus = float(params.get(prefix + "_6_8", 0)) * 100
        has_low = any(rarity <= 5 for rarity in active)
        has_high = any(rarity >= 6 for rarity in active)
        if has_low and has_high:
            return "加价 {:.1f}%（六星及以上的鱼按 {:.1f}% 加价）".format(low_bonus, high_bonus)
        return "加价 {:.1f}%".format(low_bonus if has_low else high_bonus)

    if "cost_discount" in params:
        parts.append("钓鱼费用降低 " + percent("cost_discount"))
    if "low_fish_refund" in params:
        parts.append("钓到{}时返还已付费用 {}".format(ordinary_label, percent("low_fish_refund")))
    if "ordinary_refund" in params:
        parts.append("钓到{}时返还本竿已付费用 {}".format(ordinary_label, percent("ordinary_refund")))
    if "value_floor_multiple" in params:
        parts.append("{}本竿总价值至少为鱼区费用 {:.2f} 倍".format(ordinary_label, params["value_floor_multiple"]))
    if "empty_retry_chance" in params:
        parts.append("空竿时有 {} 机会免费再试一次".format(percent("empty_retry_chance")))
    if "empty_refund" in params:
        condition = "再试仍空竿" if "empty_retry_chance" in params else "空竿"
        parts.append("{}时返还已付费用 {}".format(condition, percent("empty_refund")))
    if "rare_transfer" in params:
        parts.append("将{}的 {} 抽取机会转给{}".format(ordinary_label, percent("rare_transfer"), rare_label)
                     if rare else "当前鱼区暂无稀有鱼，换区后自动适配")
    if "high_weight_strength" in params:
        multiplier = high_weight_multiplier(tier, params["high_weight_strength"],
                                            max(eligible or [1]), balance_version, params.get("strength_scale", 1.0))
        condition = "配额突破时，" if effect_id == "P02" else ""
        parts.append("{}{}更容易出现（抽取权重 ×{:.2f}）".format(condition, high_label, multiplier)
                     if high else "当前鱼区暂无珍贵鱼，换区后自动适配")
    if "upgrade_strength" in params:
        chances = [upgrade_chance(tier, params["upgrade_strength"], target, balance_version, params.get("strength_scale", 1.0))
                   for target in eligible[1:]]
        chances = [chance for chance in chances if chance > 0]
        if chances:
            low, upper = min(chances) * 100, max(chances) * 100
            low_text, upper_text = "{:.2f}".format(low), "{:.2f}".format(upper)
            if low_text.endswith("0"):
                low_text = low_text[:-1]
            if upper_text.endswith("0"):
                upper_text = upper_text[:-1]
            chance_text = low_text + "%" if low == upper else low_text + "%～" + upper_text + "%"
            parts.append("有 {} 机会换成当前鱼区更稀有的鱼，越稀有提升越难".format(chance_text))
        else:
            parts.append("当前鱼区暂无可升级目标，换区后自动适配")
    if "species_reroll_chance" in params:
        parts.append("有 {} 机会在同档鱼种中再选一次，保留更值钱的鱼".format(percent("species_reroll_chance")))
    if "low_value_reroll_chance" in params:
        parts.append("遇到同档中较便宜的鱼时，有 {} 机会重新挑选".format(percent("low_value_reroll_chance")))
    if "lucky_chance" in params:
        parts.append("有 {} 机会触发鱼价暴击：{}".format(percent("lucky_chance"), prices("lucky_price")))
    if "quality_extra_chance" in params:
        parts.append("未成为高品质鱼时，再获得 {} 的品质提升机会".format(percent("quality_extra_chance")))
    if "rare_quality_chance" in params:
        parts.append("{}额外获得 {} 的品质提升机会".format(rare_label, percent("rare_quality_chance")))
    if "break_bonus" in params:
        parts.append("配额用完后，继续遇到{}的突破系数增加 {}".format(rare_label, percent("break_bonus")))
    if "rod_preserve_chance" in params:
        parts.append("鱼竿有 {} 机会免磨损".format(percent("rod_preserve_chance")))
    if "bait_preserve_chance" in params:
        parts.append("一次性鱼饵有 {} 机会不消耗".format(percent("bait_preserve_chance")))

    if "price_1_5" in params:
        targets = None
        subject = "新钓获鱼"
        if effect_id in ("C06", "S03", "G02", "P05", "P08", "G08"):
            targets, subject = rare, rare_label
            if effect_id == "G08":
                subject = "配额突破后钓到的" + rare_label
        elif effect_id in ("C07", "S04"):
            targets, subject = high, high_label
        elif effect_id in ("C08", "G03", "P03", "P09"):
            targets, subject = top, top_label
        elif effect_id == "S02":
            targets, subject = [rarity for rarity in eligible if rarity <= 3], ordinary_label
        elif effect_id == "C10":
            subject = "原始重量处于该鱼种最重四分之一的鱼"
        parts.append("{}：{}".format(subject, prices(targets=targets)))
    if "quality_price_1_5" in params:
        parts.append("高品质鱼：" + prices("quality_price"))
    if "upgrade_price_1_5" in params:
        targets = [target for target in eligible[1:]
                   if upgrade_chance(tier, params.get("upgrade_strength", 0.5), target,
                                     balance_version) > 0]
        parts.append("升级成功的鱼：" + prices("upgrade_price", targets))
    if effect_id == "P07":
        parts.append("每竿随机获得一项：返还已付费用 {}、{}，或额外品质提升机会 {}".format(
            percent("fate_refund"), prices("fate_price"), percent("fate_quality_chance")))
    return "{}：{}".format(name, "；".join(parts) or EFFECTS.get(effect_id, {}).get("description", "效果参数已保存"))


def describe_card(card: Dict[str, Any], eligible_rarities: Iterable[int]) -> str:
    """Format an effect card, resolving R/T/H and upgrade targets dynamically."""
    if not isinstance(card, dict):
        return ""
    tier = str(card.get("tier", "silver")).lower()
    if tier not in TIERS:
        tier = "silver"
    try:
        balance_version = int(card.get("balance_version", 1))
    except (TypeError, ValueError):
        balance_version = 1
    eligible = _eligible(eligible_rarities)
    return "\n".join(
        _effect_description(effect, effect.get("tier", tier), eligible, balance_version)
        for effect in (card.get("effects") or [])
        if isinstance(effect, dict)
    )

