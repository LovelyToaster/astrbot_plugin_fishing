"""Shared probability mapping for a user's personal gacha UP choice."""

import random
from typing import Callable, List, Optional, Sequence, Tuple, TypeVar


ItemT = TypeVar("ItemT")


def _identity(item) -> Tuple[str, int]:
    return str(getattr(item, "item_type", "")), int(getattr(item, "item_id", 0) or 0)


def apply_personal_up_to_distribution(
    distribution: Sequence[Tuple[ItemT, float]],
    pool_items: Sequence[ItemT],
    rarity_of: Callable[[ItemT], int],
    up_item: Optional[ItemT],
) -> List[Tuple[ItemT, float]]:
    """Map half of each final UP-rarity outcome to UP, then reweight alternatives.

    The non-UP half is distributed by the pool's original entry weights, with
    every entry sharing the UP item's ``(type, id)`` identity excluded.
    """
    if up_item is None:
        return list(distribution)
    up_rarity = int(rarity_of(up_item) or 0)
    target_identity = _identity(up_item)
    alternatives = [
        item for item in pool_items
        if _identity(item) != target_identity
        and int(rarity_of(item) or 0) == up_rarity
        and float(getattr(item, "weight", 0) or 0) > 0
    ]
    alternative_weight = sum(float(getattr(item, "weight", 0) or 0) for item in alternatives)
    if up_rarity <= 0 or alternative_weight <= 0:
        return list(distribution)

    up_mass = sum(
        max(0.0, float(probability))
        for item, probability in distribution
        if int(rarity_of(item) or 0) == up_rarity
    )
    if up_mass <= 0:
        return list(distribution)

    output: List[Tuple[ItemT, float]] = []
    up_probability = up_mass * 0.5
    accumulated = {}

    def add(item: ItemT, probability: float) -> None:
        if probability <= 0:
            return
        key = id(item)
        if key not in accumulated:
            accumulated[key] = [item, 0.0]
        accumulated[key][1] += probability

    for item, probability in distribution:
        probability = max(0.0, float(probability))
        if int(rarity_of(item) or 0) != up_rarity:
            add(item, probability)

    add(up_item, up_probability)
    for item in alternatives:
        weight = float(getattr(item, "weight", 0) or 0)
        add(item, up_mass * 0.5 * weight / alternative_weight)

    output = [(row[0], float(row[1])) for row in accumulated.values()]
    total = sum(probability for _, probability in output)
    if total <= 0:
        return list(distribution)
    return [(item, probability / total) for item, probability in output]


def apply_personal_up_to_draw(
    drawn_item: ItemT,
    pool_items: Sequence[ItemT],
    rarity_of: Callable[[ItemT], int],
    up_item: Optional[ItemT],
    random_value: Optional[Callable[[], float]] = None,
) -> Tuple[ItemT, bool]:
    """Apply the 50/50 UP branch after a final rarity has been chosen."""
    if up_item is None or int(rarity_of(drawn_item) or 0) != int(rarity_of(up_item) or 0):
        return drawn_item, False

    alternatives = [
        item for item in pool_items
        if _identity(item) != _identity(up_item)
        and int(rarity_of(item) or 0) == int(rarity_of(up_item) or 0)
        and float(getattr(item, "weight", 0) or 0) > 0
    ]
    total_weight = sum(float(getattr(item, "weight", 0) or 0) for item in alternatives)
    if total_weight <= 0:
        return drawn_item, False

    roll = (random_value or random.random)()
    if roll < 0.5:
        return up_item, True

    pick = (random_value or random.random)() * total_weight
    current = 0.0
    for item in alternatives:
        current += float(getattr(item, "weight", 0) or 0)
        if pick < current:
            return item, False
    return alternatives[-1], False
