"""Budget helpers for Hextech effects on non-fishing game actions.

Card parameters are snapshots.  This module only computes deterministic EV
bounds from the current operation inputs; it does not keep gameplay state.
"""

import math
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


TIER_EV_BUDGETS = {"silver": 0.05, "gold": 0.065, "prismatic": 0.08}
V4_TIER_EV_BUDGETS = {"silver": 0.04, "gold": 0.055, "prismatic": 0.07}
WIPE_RETURN_CAPS = {"silver": 1.01, "gold": 1.02, "prismatic": 1.03}


def clamp(value: Any, minimum: float = 0.0, maximum: float = 1.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return minimum
    if not math.isfinite(number):
        return minimum
    return max(minimum, min(maximum, number))


def valid_card(card: Any) -> bool:
    """Only v3 snapshots receive the new game-action effects."""
    if not isinstance(card, dict):
        return False
    try:
        return int(card.get("balance_version", 0)) >= 3
    except (TypeError, ValueError):
        return False


def first_effect(card: Any, effect_ids: Iterable[str]) -> Optional[Dict[str, Any]]:
    if not valid_card(card):
        return None
    allowed = set(effect_ids)
    for effect in card.get("effects") or []:
        if isinstance(effect, dict) and effect.get("id") in allowed:
            return effect
    return None


def effect_params(effect: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not isinstance(effect, dict):
        return {}
    params = effect.get("params")
    return params if isinstance(params, dict) else {}


def ev_budget(card: Any, params: Optional[Dict[str, Any]] = None) -> float:
    params = params or {}
    tier = str(card.get("tier", "silver")).lower() if isinstance(card, dict) else "silver"
    budgets = V4_TIER_EV_BUDGETS if valid_card(card) and int(card.get("balance_version", 0)) >= 4 else TIER_EV_BUDGETS
    fallback = budgets.get(tier, budgets["silver"])
    return clamp(params.get("ev_budget", fallback), 0.0, fallback)


def steal_cooldown(base_seconds: int, card: Any) -> Tuple[int, float]:
    """Use the same effective cooldown for action checks and status display."""
    seconds = max(0, int(base_seconds))
    effect = first_effect(card, ("C21", "C22", "C23", "S11", "G11", "P11"))
    if not effect or effect.get("id") != "C23":
        return seconds, 0.0
    params = effect_params(effect)
    budget = ev_budget(card, params)
    reduction = min(clamp(params.get("cooldown_reduction", 0.0), 0.0, 0.5),
                    budget / (1.0 + budget))
    return max(0, math.ceil(seconds * (1.0 - reduction))), reduction


def budgeted_chance(
    baseline_flow: float,
    gain_per_trigger: float,
    budget: float,
    configured_chance: Any = 1.0,
) -> float:
    """Return a proc probability whose expected gain is within ``budget``.

    ``baseline_flow`` is the positive reference flow D specified by the effect
    design, not net EV.  ``gain_per_trigger`` is the expected additional flow
    conditional on the proc.  A stored chance is treated as a ceiling.
    """
    ceiling = clamp(configured_chance)
    if baseline_flow <= 0 or gain_per_trigger <= 0 or budget <= 0:
        return 0.0
    return min(ceiling, max(0.0, budget * baseline_flow / gain_per_trigger))


def expected_best_value(values: Sequence[float], draws: int) -> float:
    """Expected maximum of ``draws`` independent choices from equally likely rows."""
    clean = sorted(float(value) for value in values)
    if not clean:
        return 0.0
    draws = max(1, int(draws))
    count = len(clean)
    return sum(
        value * ((rank + 1) ** draws - rank**draws) / (count**draws)
        for rank, value in enumerate(clean)
    )


def expected_conditional_reroll_gain(values: Sequence[float], selected_indexes: Sequence[int]) -> float:
    """Expected gain per whole action when only selected rows qualify.

    The stored chance is rolled only after the baseline pick is in the selected
    set, so this includes the probability that the baseline row qualifies.
    """
    if not values or not selected_indexes:
        return 0.0
    count = len(values)
    total = 0.0
    for index in selected_indexes:
        current = float(values[index])
        total += sum(max(0.0, float(candidate) - current) for candidate in values) / count
    return total / len(values)


def expected_electric_value_for_quantity(
    population: Sequence[Tuple[int, float, bool]], total_count: int, quantity: int
) -> float:
    """Expected transfer value after the actual one-high-rarity catch rule.

    Each row in ``population`` is (count, unit value, is_high_rarity).  Catching
    is uniform without replacement.  When a sample has multiple 5+ star fish,
    the service keeps one high fish and replaces extras with remaining lower
    rarity fish where possible.  Exchangeability reduces the exact expectation
    to a hypergeometric probability that the sample contains no high fish.
    """
    total_count = max(0, int(total_count))
    quantity = max(0, min(int(quantity), total_count))
    if total_count == 0 or quantity == 0:
        return 0.0

    high_count = 0
    high_value_sum = 0.0
    low_count = 0
    low_value_sum = 0.0
    for count, value, is_high in population:
        count = max(0, int(count))
        if is_high:
            high_count += count
            high_value_sum += count * float(value)
        else:
            low_count += count
            low_value_sum += count * float(value)

    # Be tolerant of stale/filtered inventory input and keep the denominator
    # consistent with the actual population supplied by the caller.
    population_count = high_count + low_count
    if population_count <= 0:
        return 0.0
    total_count = min(total_count, population_count)
    quantity = min(quantity, total_count)
    high_count = min(high_count, total_count)
    low_count = total_count - high_count
    if low_count <= 0:
        # The current electric-fish rule can retain only one high fish and has
        # no lower-rarity replacements available.
        return (high_value_sum / max(1, high_count)) if quantity else 0.0

    low_mean = low_value_sum / max(1, low_count)
    high_mean = high_value_sum / max(1, high_count) if high_count else 0.0
    if high_count <= 0:
        return quantity * low_mean

    probability_no_high = 0.0
    if quantity <= low_count:
        log_probability = (
            math.lgamma(low_count + 1)
            - math.lgamma(quantity + 1)
            - math.lgamma(low_count - quantity + 1)
            - math.lgamma(total_count + 1)
            + math.lgamma(quantity + 1)
            + math.lgamma(total_count - quantity + 1)
        )
        probability_no_high = math.exp(min(0.0, log_probability))

    # If enough low fish remain to replace every extra high fish, every sample
    # containing a high fish ends with n-1 low fish and one high fish.  If the
    # catch covers nearly the whole pond, all low fish are used and the same
    # single high fish survives.
    retained_low_count = quantity - 1 if quantity + high_count <= total_count + 1 else low_count
    value_if_high = retained_low_count * low_mean + high_mean
    value_if_no_high = quantity * low_mean
    return probability_no_high * value_if_no_high + (1.0 - probability_no_high) * value_if_high


def expected_electric_success_values(
    population: Sequence[Tuple[int, float, bool]],
    total_count: int,
    fish_count_multiplier: float = 1.0,
) -> Dict[str, float]:
    """Compute conditional success value by the service's real count bands."""
    total_count = max(0, int(total_count))
    if total_count <= 0:
        return {"great": 0.0, "normal": 0.0, "small": 0.0}
    multiplier = max(1.0, float(fish_count_multiplier or 1.0))
    if total_count > 400:
        base_ranges = {
            "great": (max(1, int(total_count * 0.15)), max(1, int(total_count * 0.20))),
            "normal": (max(1, int(total_count * 0.10)), max(1, int(total_count * 0.15))),
            "small": (max(1, int(total_count * 0.05)), max(1, int(total_count * 0.10))),
        }
    else:
        base_ranges = {"great": (20, 30), "normal": (10, 20), "small": (5, 10)}

    def mean_for_band(bounds: Tuple[int, int]) -> float:
        lower, upper = bounds
        if upper < lower:
            upper = lower
        state_count = max(1, upper - lower + 1)
        # These are the exact integer outcomes of random.randint's inclusive
        # quantity bands.  Keep the EV inputs exact instead of approximating a
        # large interval with a left-edge grid that can understate grade gains.
        return sum(
            expected_electric_value_for_quantity(
                population, total_count,
                min(total_count, max(1, int(base_quantity * multiplier))),
            )
            for base_quantity in range(lower, upper + 1)
        ) / state_count

    return {key: mean_for_band(value) for key, value in base_ranges.items()}


def expected_wipe_reroll_bonus(
    amount: int,
    ranges: Sequence[Tuple[float, float, float]],
    chance: float = 1.0,
    cap: Optional[float] = None,
    original_below: float = 0.5,
) -> float:
    """Exact continuous-table expectation for a capped, better-of-two reroll."""
    amount = max(0, int(amount))
    if amount <= 0 or chance <= 0:
        return 0.0
    cap_value = float(cap) if cap is not None else float("inf")
    if cap_value <= 0:
        return 0.0
    positive_ranges = [(float(a), float(b), float(w)) for a, b, w in ranges if float(w) > 0 and float(b) > float(a)]
    total_weight = sum(weight for _, _, weight in positive_ranges)
    if total_weight <= 0:
        return 0.0
    cap_multiplier = cap_value / amount

    def positive_difference_integral(x0: float, x1: float, y0: float, y1: float) -> float:
        def primitive(value: float) -> float:
            return max(0.0, value) ** 3 / 6.0
        return max(0.0, primitive(y1 - x0) - primitive(y0 - x0)
                   - primitive(y1 - x1) + primitive(y0 - x1))

    def capped_difference_integral(x0: float, x1: float, y0: float, y1: float) -> float:
        uncapped = positive_difference_integral(x0, x1, y0, y1)
        over_cap = positive_difference_integral(x0, x1, y0 - cap_multiplier, y1 - cap_multiplier)
        return max(0.0, uncapped - over_cap)

    expected = 0.0
    for x_start, x_end, x_weight in positive_ranges:
        eligible_end = min(x_end, original_below)
        if eligible_end <= x_start:
            continue
        x_width = x_end - x_start
        eligible_width = eligible_end - x_start
        original_mass = (x_weight / total_weight) * (eligible_width / x_width)
        for y_start, y_end, y_weight in positive_ranges:
            y_width = y_end - y_start
            pair_mean = capped_difference_integral(x_start, eligible_end, y_start, y_end)
            pair_mean /= max(1e-12, eligible_width * y_width)
            reroll_mass = y_weight / total_weight
            expected += original_mass * reroll_mass * pair_mean * amount
    return expected * clamp(chance)


def expected_wipe_base_payout_ratio(ranges: Sequence[Tuple[float, float, float]]) -> float:
    positive_ranges = [(float(a), float(b), float(w)) for a, b, w in ranges if float(w) > 0 and float(b) >= float(a)]
    total_weight = sum(weight for _, _, weight in positive_ranges)
    if total_weight <= 0:
        return 0.0
    return sum(((lower + upper) / 2.0) * weight for lower, upper, weight in positive_ranges) / total_weight


def expected_wipe_loss_ratio(ranges: Sequence[Tuple[float, float, float]]) -> float:
    """Expected ``max(1-multiplier, 0)`` for the weighted uniform table."""
    positive_ranges = [(float(a), float(b), float(w)) for a, b, w in ranges if float(w) > 0 and float(b) > float(a)]
    total_weight = sum(weight for _, _, weight in positive_ranges)
    if total_weight <= 0:
        return 0.0
    total = 0.0
    for lower, upper, weight in positive_ranges:
        end = min(upper, 1.0)
        if end > lower:
            width = end - lower
            total += weight * width * (1.0 - (lower + end) / 2.0) / (upper - lower)
    return total / total_weight


def expected_wipe_profit_ratio(ranges: Sequence[Tuple[float, float, float]]) -> float:
    """Expected ``max(multiplier-1, 0)`` for the weighted uniform table."""
    positive_ranges = [(float(a), float(b), float(w)) for a, b, w in ranges if float(w) > 0 and float(b) > float(a)]
    total_weight = sum(weight for _, _, weight in positive_ranges)
    if total_weight <= 0:
        return 0.0
    total = 0.0
    for lower, upper, weight in positive_ranges:
        start = max(lower, 1.0)
        if upper > start:
            width = upper - start
            total += weight * width * ((start + upper) / 2.0 - 1.0) / (upper - lower)
    return total / total_weight


def expected_wipe_interval_best_bonus(
    amount: int, ranges: Sequence[Tuple[float, float, float]], chance: float = 1.0
) -> float:
    """Expected amount from rerolling once inside the original multiplier band."""
    amount = max(0, int(amount))
    chance = clamp(chance)
    positive_ranges = [(float(a), float(b), float(w)) for a, b, w in ranges if float(w) > 0 and float(b) > float(a)]
    total_weight = sum(weight for _, _, weight in positive_ranges)
    if amount <= 0 or chance <= 0 or total_weight <= 0:
        return 0.0
    expected_multiplier_gain = sum(
        (weight / total_weight) * ((upper - lower) / 6.0)
        for lower, upper, weight in positive_ranges
    )
    return amount * expected_multiplier_gain * chance


def expected_wipe_profit_bonus(
    amount: int,
    ranges: Sequence[Tuple[float, float, float]],
    fraction: float,
    cap: Optional[float] = None,
    chance: float = 1.0,
) -> float:
    amount = max(0, int(amount))
    fraction = clamp(fraction, 0.0, 1.0)
    chance = clamp(chance)
    if amount <= 0 or fraction <= 0 or chance <= 0:
        return 0.0
    cap_value = float(cap) if cap is not None else float("inf")
    positive_ranges = [(float(a), float(b), float(w)) for a, b, w in ranges if float(w) > 0 and float(b) > float(a)]
    total_weight = sum(weight for _, _, weight in positive_ranges)
    if total_weight <= 0:
        return 0.0

    # Integrate min(fraction * amount * (multiplier - 1), cap) over each band.
    bonus = 0.0
    for lower, upper, weight in positive_ranges:
        start = max(lower, 1.0)
        if upper <= start:
            continue
        slope = amount * fraction
        cap_delta = cap_value / slope if slope > 0 else 0.0
        uncapped_end = max(start, min(upper, 1.0 + cap_delta))
        integral = 0.0
        if uncapped_end > start:
            integral += slope * ((uncapped_end - 1.0) ** 2 - (start - 1.0) ** 2) / 2.0
        capped_start = max(start, uncapped_end)
        if upper > capped_start and math.isfinite(cap_value):
            integral += cap_value * (upper - capped_start)
        elif upper > capped_start:
            integral += slope * ((upper - 1.0) ** 2 - (capped_start - 1.0) ** 2) / 2.0
        bonus += weight * integral / (upper - lower) / total_weight
    return bonus * chance


def expected_wipe_fill_bonus(
    amount: int, ranges: Sequence[Tuple[float, float, float]], chance: float = 1.0
) -> float:
    """Expected payout to exactly break even when original multiplier is 0.8..1."""
    amount = max(0, int(amount))
    chance = clamp(chance)
    positive_ranges = [(float(a), float(b), float(w)) for a, b, w in ranges if float(w) > 0 and float(b) > float(a)]
    total_weight = sum(weight for _, _, weight in positive_ranges)
    if amount <= 0 or chance <= 0 or total_weight <= 0:
        return 0.0
    expected_ratio = 0.0
    for lower, upper, weight in positive_ranges:
        start = max(lower, 0.8)
        end = min(upper, 1.0)
        if end > start:
            expected_ratio += weight * ((end - start) - (end * end - start * start) / 2.0) / (upper - lower)
    return amount * expected_ratio / total_weight * chance


