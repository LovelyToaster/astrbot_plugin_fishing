"""Daily offer generation, persistence, and presentation for Hextech cards."""

import random
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..utils import get_now
from .hextech_effects import describe_card, roll_card, effective_card


UTC_PLUS_8 = timezone(timedelta(hours=8))
TIERS = ("silver", "gold", "prismatic")
TIER_LABELS = {"silver": "白银", "gold": "黄金", "prismatic": "棱彩"}


class HextechService:
    """Owns one immutable daily offer set and at most one selected card per actor."""

    def __init__(
        self,
        repository,
        user_repo=None,
        inventory_repo=None,
        item_template_repo=None,
        fishing_zone_service=None,
        daily_reset_hour: int = 0,
        rng=None,
        clock: Optional[Callable[[], datetime]] = None,
    ):
        self.repository = repository
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.fishing_zone_service = fishing_zone_service
        self.daily_reset_hour = self._normalize_reset_hour(daily_reset_hour)
        self.rng = rng or random.SystemRandom()
        self.clock = clock or get_now

    @staticmethod
    def _normalize_reset_hour(value: Any) -> int:
        try:
            hour = int(value)
        except (TypeError, ValueError):
            return 0
        return hour if 0 <= hour <= 23 else 0

    def _now(self, now: Optional[datetime] = None) -> datetime:
        value = now or self.clock()
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC_PLUS_8)
        return value.astimezone(UTC_PLUS_8)

    def get_game_day(self, now: Optional[datetime] = None) -> str:
        local_now = self._now(now)
        game_date = local_now.date()
        if local_now.hour < self.daily_reset_hour:
            game_date -= timedelta(days=1)
        return game_date.isoformat()

    def _timestamp(self) -> str:
        return self._now().isoformat(timespec="seconds")

    def get_eligible_rarities(self, actor_id: str) -> List[int]:
        """Return positive-probability stars that have fish in the current zone."""
        if not self.item_template_repo:
            return []

        try:
            user = self.user_repo.get_by_id(str(actor_id)) if self.user_repo else None
        except Exception:
            user = None

        zone_id = getattr(user, "fishing_zone_id", 1) or 1
        zone = None
        try:
            zone = self.inventory_repo.get_zone_by_id(zone_id) if self.inventory_repo else None
        except Exception:
            zone = None

        try:
            all_fish = self.item_template_repo.get_all_fish()
        except Exception:
            all_fish = []

        specific_ids = getattr(zone, "specific_fish_ids", None)
        if specific_ids is None and zone is not None and self.inventory_repo:
            specific_ids = self.inventory_repo.get_specific_fish_ids_for_zone(zone_id)
        if specific_ids:
            allowed_ids = {int(fish_id) for fish_id in specific_ids}
            zone_fish = [fish for fish in all_fish if fish.fish_id in allowed_ids]
        else:
            zone_fish = all_fish
        available = {int(fish.rarity) for fish in zone_fish if getattr(fish, "rarity", None) is not None}

        probabilities = None
        if self.fishing_zone_service:
            try:
                strategy = self.fishing_zone_service.get_strategy(zone_id)
                probabilities = strategy.get_fish_rarity_distribution(user)
            except Exception:
                probabilities = None

        if probabilities is None:
            return sorted(available)
        return sorted(
            rarity
            for rarity in available
            if 1 <= rarity <= len(probabilities)
            and float(probabilities[rarity - 1] or 0.0) > 0
        )

    def _make_offers(self) -> List[Dict[str, Any]]:
        offers = []
        fishing_slot = self.rng.randrange(3)
        for index in range(3):
            tier = self.rng.choices(TIERS, weights=(50, 35, 15), k=1)[0]
            offers.append(roll_card(tier, self.rng, fishing_only=index == fishing_slot))
        return offers

    def ensure_daily_state(
        self, actor_id: str, now: Optional[datetime] = None
    ) -> Tuple[Optional[Dict[str, Any]], bool]:
        """Create the daily snapshot once; the unique key resolves concurrent triggers."""
        actor_id = str(actor_id or "").strip()
        if not actor_id:
            return None, False

        if self.user_repo:
            try:
                user = self.user_repo.get_by_id(actor_id)
                if user is not None and getattr(user, "is_ai", False):
                    return None, False
            except Exception:
                pass

        game_day = self.get_game_day(now)
        existing = self.repository.get_daily_state(actor_id, game_day)
        if existing is not None:
            return existing, False

        offers = self._make_offers()
        created_at = self._now(now).isoformat(timespec="seconds")
        # Keep the legacy NOT NULL column compatible; card tiers live in each offer.
        return self.repository.create_daily_state(actor_id, game_day, offers[0]["tier"], offers, created_at)

    def get_daily_state(self, actor_id: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        if not actor_id:
            return None
        return self.repository.get_daily_state(str(actor_id), self.get_game_day(now))

    def reset_all_users(self) -> Dict[str, int]:
        """Administrative reset; permission is checked against the real sender."""
        return self.repository.reset_all_users()

    def reroll(self, actor_id: str, now: Optional[datetime] = None) -> Tuple[Optional[Dict[str, Any]], str]:
        state, created = self.ensure_daily_state(actor_id, now)
        if state is None:
            return None, "unavailable"
        if created:
            return state, "created"
        if state["selected_index"] is not None:
            return state, "selected"
        if state["reroll_count"] >= 2:
            return state, "limit_reached"
        new_offers = self._make_offers()
        return self.repository.reroll_daily_offers(
            str(actor_id), self.get_game_day(now), new_offers
        )

    def choose(self, actor_id: str, selected_number: int, now: Optional[datetime] = None):
        state, created = self.ensure_daily_state(actor_id, now)
        if state is None:
            return None, "unavailable"
        if created:
            return state, "created"
        if selected_number not in (1, 2, 3):
            return state, "invalid_index"
        return self.repository.select_daily_card(
            str(actor_id),
            self.get_game_day(now),
            selected_number - 1,
            self._now(now).isoformat(timespec="seconds"),
        )

    def get_selected_card(self, actor_id: str, now: Optional[datetime] = None) -> Optional[Dict[str, Any]]:
        if not actor_id:
            return None
        # A calendar reset alone does not expire the last selected card.
        # Creating the next offer set expires it, even if that set stays unselected.
        state = self.repository.get_latest_daily_state(str(actor_id), self.get_game_day(now))
        if state is None or state["selected_index"] is None:
            return None
        card = state["offers"][state["selected_index"]]
        # Return a fresh JSON-compatible snapshot so callers cannot mutate persistence state.
        return effective_card(card)

    def render_card(self, card: Dict[str, Any], actor_id: str, number: Optional[int] = None, reveal_gifts: bool = True) -> str:
        prefix = f"{number}️⃣ " if number is not None else ""
        label = TIER_LABELS.get(card.get("tier"), card.get("tier", "未知"))
        lines = [f"{prefix}【{label}卡】"]
        lines.append(describe_card(card, self.get_eligible_rarities(actor_id)))
        if reveal_gifts:
            for index, gift in enumerate(card.get("gifts", []), start=1):
                gift_label = TIER_LABELS.get(gift.get("tier"), "未知")
                lines.append(f"🎁 赠卡{index}【{gift_label}卡】")
                lines.append(describe_card(gift, self.get_eligible_rarities(actor_id)))
        return "\n".join(lines)

    def render_offers(self, state: Dict[str, Any], actor_id: str) -> str:
        lines = ["🎴 今日海克斯候选"]
        lines.append("每张卡独立抽取品质：白银50%、黄金35%、棱彩15%。")
        if state["selected_index"] is not None:
            selected = state["selected_index"]
            lines.append(f"已选择第 {selected + 1} 张，今日效果已生效：")
            lines.append(self.render_card(state["offers"][selected], actor_id, selected + 1))
            return "\n".join(lines)

        lines.append(f"免费刷新：{state['reroll_count']}/2 次；选择后今日不可更改。")
        lines.extend(
            self.render_card(card, actor_id, index, reveal_gifts=False)
            for index, card in enumerate(state["offers"], start=1)
        )
        lines.append("使用 /海克斯 1、/海克斯 2 或 /海克斯 3 选择；使用 /海克斯 刷新重抽整组。")
        return "\n\n".join(lines)

    def render_new_offer_prompt(self, state: Dict[str, Any], actor_id: str) -> str:
        return "🎴 今日首次钓鱼插件指令已触发，海克斯候选如下：\n\n" + self.render_offers(state, actor_id)
