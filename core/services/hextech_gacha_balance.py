"""EV guards and reference-value helpers for Hextech gacha effects.

The helpers deliberately return ``None`` when a pool contains an outcome that
cannot be priced from the configured sell prices or template shop costs. The
caller can then use the documented non-negative-value upper bounds instead of
silently treating an unknown reward as worthless.
"""

import math
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple


TIER_EV_BUDGETS = {"silver": 0.05, "gold": 0.065, "prismatic": 0.08}
GACHA_HEXTECH_IDS = {"C27", "C28", "S13", "S14", "G13", "P13"}


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _int_quantity(item: Any) -> int:
    try:
        return max(1, int(_get(item, "quantity", 1) or 1))
    except (TypeError, ValueError):
        return 1


def _positive_weight(item: Any) -> float:
    try:
        return max(0.0, float(_get(item, "weight", 0) or 0))
    except (TypeError, ValueError):
        return 0.0


def _rarity(item: Any, rarity_of: Callable[[Any], int]) -> int:
    try:
        return int(rarity_of(item) or 0)
    except (TypeError, ValueError):
        return 0


def _weighted_probabilities(
    items: Sequence[Any],
    rarity_of: Callable[[Any], int],
    multiplier: float = 1.0,
) -> List[Tuple[Any, float]]:
    max_rarity = max(
        (_rarity(item, rarity_of) for item in items
         if _get(item, "item_type") != "coins" and _positive_weight(item) > 0),
        default=0,
    )
    weights: List[float] = []
    for item in items:
        weight = _positive_weight(item)
        if (
            weight > 0 and multiplier > 1.0
            and _get(item, "item_type") != "coins"
            and _rarity(item, rarity_of) >= max_rarity > 0
        ):
            weight *= multiplier
        weights.append(max(0.0, weight))
    total = sum(weights)
    if total <= 0:
        return []
    return [(item, weight / total) for item, weight in zip(items, weights) if weight > 0]


def _forced_probabilities(
    items: Sequence[Any], max_rarity: int, rarity_of: Callable[[Any], int]
) -> List[Tuple[Any, float]]:
    candidates = [
        item for item in items
        if _get(item, "item_type") != "coins" and _rarity(item, rarity_of) >= max_rarity
    ]
    if not candidates:
        return _weighted_probabilities(items, rarity_of)
    total = sum(max(0.0, float(_get(item, "weight", 0) or 0)) for item in candidates)
    if total <= 0:
        return _weighted_probabilities(items, rarity_of)
    return [
        (item, max(0.0, float(_get(item, "weight", 0) or 0)) / total)
        for item in candidates
        if float(_get(item, "weight", 0) or 0) > 0
    ]


def _higher_rarity(first: Any, second: Any, rarity_of: Callable[[Any], int]) -> Any:
    return second if _rarity(second, rarity_of) > _rarity(first, rarity_of) else first


def _draw_distribution(
    items: Sequence[Any],
    rarity_of: Callable[[Any], int],
    effect_id: Optional[str],
    chance: float,
    state: int,
    pity_threshold: int,
    max_rarity: int,
    weight_multiplier: float = 1.0,
) -> List[Tuple[Any, float]]:
    hard_pity = pity_threshold > 0 and state >= pity_threshold - 1
    if hard_pity:
        return _forced_probabilities(items, max_rarity, rarity_of)

    base = _weighted_probabilities(
        items,
        rarity_of,
        multiplier=weight_multiplier if effect_id == "G13" else 1.0,
    )
    if not base or chance <= 0 or effect_id not in {"C27", "P13"}:
        return base

    full = _weighted_probabilities(items, rarity_of)
    lowest_rarity = min((_rarity(item, rarity_of) for item, _ in full), default=0)
    result: Dict[int, List[Any]] = {}

    def add(item: Any, probability: float) -> None:
        if probability <= 0:
            return
        key = id(item)
        if key not in result:
            result[key] = [item, 0.0]
        result[key][1] += probability

    if effect_id == "C27":
        # On a lowest-rarity first result, one optional second candidate is
        # accepted only when its rarity is strictly higher. Ties retain first.
        for first, first_p in base:
            if _rarity(first, rarity_of) != lowest_rarity:
                add(first, first_p)
                continue
            add(first, first_p * (1.0 - chance))
            for second, second_p in full:
                chosen = _higher_rarity(first, second, rarity_of)
                add(chosen, first_p * chance * second_p)
    else:  # P13: one optional second candidate for every non-pity draw.
        for first, first_p in base:
            add(first, first_p * (1.0 - chance))
            for second, second_p in full:
                chosen = _higher_rarity(first, second, rarity_of)
                add(chosen, first_p * chance * second_p)

    total = sum(float(row[1]) for row in result.values())
    return [(row[0], float(row[1]) / total) for row in result.values()] if total > 0 else base


def expected_cycle_value(
    items: Sequence[Any],
    rarity_of: Callable[[Any], int],
    value_of: Callable[[Any], Optional[float]],
    pity_threshold: int = 0,
    effect_id: Optional[str] = None,
    chance: float = 0.0,
    weight_multiplier: float = 1.0,
) -> Optional[float]:
    """Return expected reference reward value per draw, including hard pity.

    ``None`` means at least one positive-probability outcome has no defensible
    reference value. With hard pity, a renewal cycle starts immediately after
    the previous highest-rarity reward and ends at the next one.
    """
    probabilities = expected_cycle_probabilities(
        items, rarity_of, pity_threshold, effect_id, chance, weight_multiplier
    )
    if not probabilities:
        return None
    by_id = {id(item): item for item in items}
    total = 0.0
    for item_id, probability in probabilities.items():
        value = value_of(by_id[item_id])
        if value is None:
            return None
        try:
            numeric_value = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(numeric_value) or numeric_value < 0:
            return None
        total += probability * numeric_value
    return total


def expected_cycle_probabilities(
    items: Sequence[Any],
    rarity_of: Callable[[Any], int],
    pity_threshold: int = 0,
    effect_id: Optional[str] = None,
    chance: float = 0.0,
    weight_multiplier: float = 1.0,
) -> Dict[int, float]:
    """Return every reward's long-run probability per draw, keyed by entry id.

    Computing this indicator vector once per candidate chance avoids revaluing
    every catalog item and gives an explicit per-prize bound for pools whose
    reward utilities do not have a reliable price.
    """
    if not items:
        return {}
    base_probs = _weighted_probabilities(items, rarity_of)
    if not base_probs:
        return {}
    max_rarity = max(
        (_rarity(item, rarity_of) for item, _ in base_probs
         if _get(item, "item_type") != "coins"),
        default=0,
    )
    pity_enabled = pity_threshold > 0 and max_rarity > 0
    if not pity_enabled:
        distribution = _draw_distribution(
            items, rarity_of, effect_id, chance, 0, 0, max_rarity,
            weight_multiplier,
        )
        return {id(item): probability for item, probability in distribution}

    # Every non-pity state has the same pool distribution. Compute its cycle
    # visit weight and distribution once, then combine it with the hard-pity
    # state. This keeps budget searches independent of the threshold length.
    normal_distribution = _draw_distribution(
        items, rarity_of, effect_id, chance, 0, pity_threshold,
        max_rarity, weight_multiplier,
    )
    hard_distribution = _draw_distribution(
        items, rarity_of, effect_id, chance, pity_threshold - 1,
        pity_threshold, max_rarity, weight_multiplier,
    )
    if not normal_distribution or not hard_distribution:
        return {}
    normal_top_probability = sum(
        probability for item, probability in normal_distribution
        if _get(item, "item_type") != "coins"
        and _rarity(item, rarity_of) >= max_rarity
    )
    survival = 1.0
    normal_visits = 0.0
    for _ in range(max(0, pity_threshold - 1)):
        normal_visits += survival
        survival *= max(0.0, 1.0 - normal_top_probability)
        if survival <= 1e-15:
            break
    denominator = normal_visits + survival
    if denominator <= 0:
        return {}

    probabilities: Dict[int, float] = {}
    for item, probability in normal_distribution:
        probabilities[id(item)] = normal_visits * probability / denominator
    for item, probability in hard_distribution:
        probabilities[id(item)] = (
            probabilities.get(id(item), 0.0) + survival * probability / denominator
        )
    return probabilities


def max_chance_for_probability_budget(
    items: Sequence[Any],
    rarity_of: Callable[[Any], int],
    budget: float,
    requested_chance: float,
    pity_threshold: int,
    effect_id: str,
) -> float:
    """Cap an unpriced selector so no individual reward's cycle probability
    rises by more than the budget. This bounds EV for every non-negative
    assignment of reward values without inventing prices.
    """
    budget = min(0.08, max(0.0, float(budget or 0.0)))
    requested_chance = min(1.0, max(0.0, float(requested_chance or 0.0)))
    if budget <= 0 or requested_chance <= 0:
        return 0.0
    baseline = expected_cycle_probabilities(items, rarity_of, pity_threshold)
    if not baseline:
        return 0.0

    def fits(chance: float) -> bool:
        adjusted = expected_cycle_probabilities(
            items, rarity_of, pity_threshold, effect_id, chance
        )
        for item_id, base_probability in baseline.items():
            adjusted_probability = adjusted.get(item_id, 0.0)
            if adjusted_probability > base_probability * (1.0 + budget) + 1e-12:
                return False
        return any(
            base_probability > 0
            for base_probability in baseline.values()
        ) and all(item_id in baseline or probability <= 1e-12
                   for item_id, probability in adjusted.items())

    if fits(requested_chance):
        return requested_chance
    low, high = 0.0, requested_chance
    for _ in range(48):
        middle = (low + high) / 2.0
        if fits(middle):
            low = middle
        else:
            high = middle
    return low


def max_weight_multiplier_for_probability_budget(
    items: Sequence[Any],
    rarity_of: Callable[[Any], int],
    budget: float,
    requested_multiplier: float,
    pity_threshold: int,
) -> float:
    """Per-reward long-run probability guard for an unpriced G13 pool."""
    budget = min(0.08, max(0.0, float(budget or 0.0)))
    requested_multiplier = max(1.0, float(requested_multiplier or 1.0))
    if budget <= 0 or requested_multiplier <= 1.0:
        return 1.0
    baseline = expected_cycle_probabilities(items, rarity_of, pity_threshold)
    if not baseline:
        return 1.0

    def fits(multiplier: float) -> bool:
        adjusted = expected_cycle_probabilities(
            items, rarity_of, pity_threshold,
            effect_id="G13", weight_multiplier=multiplier,
        )
        for item_id, base_probability in baseline.items():
            if adjusted.get(item_id, 0.0) > base_probability * (1.0 + budget) + 1e-12:
                return False
        return all(item_id in baseline or probability <= 1e-12
                   for item_id, probability in adjusted.items())

    if fits(requested_multiplier):
        return requested_multiplier
    low, high = 1.0, requested_multiplier
    for _ in range(48):
        middle = (low + high) / 2.0
        if fits(middle):
            low = middle
        else:
            high = middle
    return low


def max_chance_for_budget(
    items: Sequence[Any],
    rarity_of: Callable[[Any], int],
    value_of: Callable[[Any], Optional[float]],
    budget: float,
    requested_chance: float,
    pity_threshold: int = 0,
    effect_id: Optional[str] = None,
    weight_multiplier: float = 1.0,
) -> float:
    """Solve the largest chance whose long-run reference EV fits the budget."""
    requested_chance = min(1.0, max(0.0, float(requested_chance or 0.0)))
    budget = min(0.08, max(0.0, float(budget or 0.0)))
    if requested_chance <= 0 or budget <= 0:
        return 0.0
    baseline = expected_cycle_value(items, rarity_of, value_of, pity_threshold)
    if baseline is None or baseline <= 0:
        return max_chance_for_probability_budget(
            items, rarity_of, budget, requested_chance, pity_threshold,
            str(effect_id or ""),
        )

    def fits(chance: float) -> bool:
        adjusted = expected_cycle_value(
            items, rarity_of, value_of, pity_threshold,
            effect_id=effect_id, chance=chance,
        )
        return adjusted is not None and adjusted <= baseline * (1.0 + budget + 1e-12)

    if fits(requested_chance):
        return requested_chance
    low, high = 0.0, requested_chance
    for _ in range(48):
        middle = (low + high) / 2.0
        if fits(middle):
            low = middle
        else:
            high = middle
    return low


def max_weight_multiplier_for_budget(
    items: Sequence[Any],
    rarity_of: Callable[[Any], int],
    value_of: Callable[[Any], Optional[float]],
    budget: float,
    requested_multiplier: float,
    pity_threshold: int = 0,
) -> float:
    requested_multiplier = max(1.0, float(requested_multiplier or 1.0))
    budget = min(0.08, max(0.0, float(budget or 0.0)))
    if budget <= 0:
        return 1.0
    max_rarity = max(
        (_rarity(item, rarity_of) for item in items
         if _get(item, "item_type") != "coins" and _positive_weight(item) > 0),
        default=0,
    )
    if max_rarity <= 0 or not any(
        _get(item, "item_type") != "coins"
        and _rarity(item, rarity_of) == max_rarity
        and _positive_weight(item) > 0
        for item in items
    ):
        return 1.0
    baseline = expected_cycle_value(items, rarity_of, value_of, pity_threshold)
    if baseline is None or baseline <= 0:
        return max_weight_multiplier_for_probability_budget(
            items, rarity_of, budget, requested_multiplier, pity_threshold
        )

    def fits(multiplier: float) -> bool:
        adjusted = expected_cycle_value(
            items, rarity_of, value_of, pity_threshold,
            effect_id="G13", weight_multiplier=multiplier,
        )
        return adjusted is not None and adjusted <= baseline * (1.0 + budget + 1e-12)

    if fits(requested_multiplier):
        return requested_multiplier
    low, high = 1.0, requested_multiplier
    for _ in range(48):
        middle = (low + high) / 2.0
        if fits(middle):
            low = middle
        else:
            high = middle
    return low


def configured_reward_value(
    item: Any,
    template_of: Callable[[str, int], Any],
    game_config: Optional[Dict[str, Any]],
) -> Optional[float]:
    """Reference price: coins, configured equipment sale price, or shop cost."""
    item_type = str(_get(item, "item_type", ""))
    item_id = int(_get(item, "item_id", 0) or 0)
    quantity = _int_quantity(item)
    if item_type == "coins":
        return float(max(0, int(_get(item, "quantity", 0) or 0)))

    template = template_of(item_type, item_id)
    if template is None:
        return None
    if item_type in {"rod", "accessory"}:
        rarity = _get(template, "rarity")
        sell_prices = (game_config or {}).get("sell_prices", {})
        type_prices = sell_prices.get(item_type, {}) if isinstance(sell_prices, dict) else {}
        if rarity is None or str(rarity) not in type_prices:
            return None
        try:
            price = float(type_prices[str(rarity)])
        except (TypeError, ValueError):
            return None
        return price if price >= 0 else None
    if item_type in {"bait", "item"}:
        cost = _get(template, "cost")
        if cost is None:
            return None
        try:
            cost = float(cost)
        except (TypeError, ValueError):
            return None
        # A zero-price template is not enough evidence that its gameplay value
        # is zero; leave it in the conservative, unpriced path.
        if cost <= 0:
            return None
        return cost * quantity
    # Titles and unsupported reward kinds have no stable reference price.
    return None


def quantity_bonus(base_quantity: Any, fraction: Any) -> int:
    """Apply a fractional stack increase, rounding upward and adding at least 1."""
    quantity = _int_quantity({"quantity": base_quantity})
    try:
        ratio = max(0.0, float(fraction or 0.0))
    except (TypeError, ValueError):
        ratio = 0.0
    return max(1, int(math.ceil(quantity * ratio)))


def max_quantity_bonus_chance(
    items: Iterable[Any], budget: float, requested_chance: float, fraction: float
) -> float:
    """Use exact stack rounding to bound the increase for arbitrary non-negative values."""
    budget = min(0.08, max(0.0, float(budget or 0.0)))
    requested_chance = min(1.0, max(0.0, float(requested_chance or 0.0)))
    if budget <= 0 or requested_chance <= 0:
        return 0.0
    max_ratio = 0.0
    for item in items:
        if _get(item, "item_type") not in {"bait", "item"}:
            continue
        quantity = _int_quantity(item)
        bonus = quantity_bonus(quantity, fraction)
        max_ratio = max(max_ratio, bonus / float(quantity))
    if max_ratio <= 0:
        return 0.0
    return min(requested_chance, budget / max_ratio)


def max_bonus_chance_for_value_budget(
    items: Sequence[Any],
    rarity_of: Callable[[Any], int],
    value_of: Callable[[Any], Optional[float]],
    bonus_value_of: Callable[[Any], float],
    budget: float,
    requested_chance: float,
    pity_threshold: int = 0,
) -> float:
    """Bound a value-only random bonus; uses a hard generic bound if unpriced."""
    budget = min(0.08, max(0.0, float(budget or 0.0)))
    requested_chance = min(1.0, max(0.0, float(requested_chance or 0.0)))
    if budget <= 0 or requested_chance <= 0:
        return 0.0
    baseline = expected_cycle_value(items, rarity_of, value_of, pity_threshold)
    bonus_value = expected_cycle_value(items, rarity_of, bonus_value_of, pity_threshold)
    if baseline is not None and bonus_value is not None and baseline > 0:
        return min(requested_chance, budget * baseline / bonus_value) if bonus_value > 0 else 0.0
    # For coin-only bonuses, use the coins' own expected value as the floor:
    # other unpriced prizes are non-negative and can only increase total EV.
    coin_value = expected_cycle_value(
        items,
        rarity_of,
        lambda item: float(_get(item, "quantity", 0) or 0)
        if _get(item, "item_type") == "coins" else 0.0,
        pity_threshold,
    )
    if coin_value is not None and coin_value > 0 and bonus_value is not None:
        return min(requested_chance, budget * coin_value / bonus_value) if bonus_value > 0 else 0.0
    return 0.0


def max_coin_refund_fraction(
    budget: float, long_run_reward_value: Optional[float], coin_cost: int,
    requested_fraction: float, bonus_cap: int,
) -> float:
    """Cap a deterministic coin-purchase refund against prize reference EV."""
    try:
        budget = min(0.08, max(0.0, float(budget or 0.0)))
        requested_fraction = min(1.0, max(0.0, float(requested_fraction or 0.0)))
        coin_cost = max(0, int(coin_cost or 0))
        bonus_cap = max(0, int(bonus_cap or 0))
    except (TypeError, ValueError):
        return 0.0
    if budget <= 0 or coin_cost <= 0 or bonus_cap <= 0 or long_run_reward_value is None:
        return 0.0
    if long_run_reward_value <= 0:
        return 0.0
    return min(
        requested_fraction,
        float(bonus_cap) / coin_cost,
        budget * long_run_reward_value / coin_cost,
    )

