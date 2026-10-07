import importlib
import os
import random
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from core.repositories.sqlite_hextech_repo import SqliteHextechRepository
from core.services.hextech_service import HextechService
from core.services.hextech_effects import effective_card


hextech_migration = importlib.import_module("core.database.migrations.062_add_hextech_daily")


class TierSequenceRandom(random.Random):
    def __init__(self, tiers):
        super().__init__(17)
        self.tiers = iter(tiers)
        self.tier_draws = []

    def choices(self, population, weights=None, *, cum_weights=None, k=1):
        self.tier_draws.append((tuple(population), tuple(weights), k))
        return [next(self.tiers)]


class FakeUserRepository:
    def get_by_id(self, user_id):
        return SimpleNamespace(user_id=user_id, fishing_zone_id=3, is_ai=False)


class FakeInventoryRepository:
    def get_zone_by_id(self, zone_id):
        return SimpleNamespace(specific_fish_ids=[1, 4])


class FakeItemTemplateRepository:
    def get_all_fish(self):
        return [
            SimpleNamespace(fish_id=1, rarity=1),
            SimpleNamespace(fish_id=4, rarity=5),
            SimpleNamespace(fish_id=8, rarity=8),
        ]


class FakeZoneService:
    def get_strategy(self, zone_id):
        return SimpleNamespace(get_fish_rarity_distribution=lambda user: [0.5, 0, 0, 0, 0.5, 0, 0, 0])


class HextechSelectionTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        try:
            hextech_migration.up(conn.cursor())
            conn.commit()
        finally:
            conn.close()
        self.repo = SqliteHextechRepository(self.db_path)
        self.fixed_now = datetime(2026, 9, 29, 3, 59, tzinfo=timezone(timedelta(hours=8)))
        self.service = HextechService(
            repository=self.repo,
            user_repo=FakeUserRepository(),
            inventory_repo=FakeInventoryRepository(),
            item_template_repo=FakeItemTemplateRepository(),
            fishing_zone_service=FakeZoneService(),
            daily_reset_hour=4,
            rng=random.Random(17),
            clock=lambda: self.fixed_now,
        )

    def tearDown(self):
        self.repo._get_connection().close()
        os.unlink(self.db_path)

    def test_game_day_uses_utc_plus_8_reset_hour(self):
        self.assertEqual(self.service.get_game_day(), "2026-09-28")
        self.fixed_now = datetime(2026, 9, 29, 4, 0, tzinfo=timezone(timedelta(hours=8)))
        self.assertEqual(self.service.get_game_day(), "2026-09-29")

    def test_old_card_survives_reset_until_next_offer_set_is_created(self):
        self.service.ensure_daily_state("player")
        self.service.choose("player", 1)
        selected = self.service.get_selected_card("player")
        self.fixed_now += timedelta(days=2)
        self.assertIsNone(self.service.get_daily_state("player"))
        self.assertEqual(self.service.get_selected_card("player"), selected)
        # A restarted service recovers the same carried card from SQLite.
        restarted = HextechService(self.repo, daily_reset_hour=4, clock=lambda: self.fixed_now)
        self.assertEqual(restarted.get_selected_card("player"), selected)
        state, created = self.service.ensure_daily_state("player")
        self.assertTrue(created)
        self.assertIsNone(state["selected_index"])
        self.assertIsNone(self.service.get_selected_card("player"))
        self.service.reroll("player")
        self.assertIsNone(self.service.get_selected_card("player"))
        self.fixed_now += timedelta(days=1)
        self.assertIsNone(self.service.get_selected_card("player"))
        # Selecting the new day's card replaces the expired effect.
        self.service.ensure_daily_state("player")
        self.service.choose("player", 2)
        state = self.service.get_daily_state("player")
        self.assertEqual(self.service.get_selected_card("player"), state["offers"][1])

    def test_unselected_newer_day_blocks_old_card_and_future_days_are_ignored(self):
        self.service.ensure_daily_state("player")
        self.service.choose("player", 1)
        selected = self.service.get_selected_card("player")
        self.repo.create_daily_state("player", "2026-10-01", "silver", [selected] * 3, "future")
        self.assertEqual(self.service.get_selected_card("player"), selected)
        self.fixed_now += timedelta(days=1)
        self.service.choose("player", 1)  # First direct choose only creates offers.
        self.assertIsNone(self.service.get_selected_card("player"))
        self.assertIsNone(self.service.get_selected_card("another-player"))

    def test_selected_card_display_follows_current_zone_without_changing_snapshot(self):
        user = SimpleNamespace(fishing_zone_id=1, is_ai=False)
        self.service.user_repo = SimpleNamespace(get_by_id=lambda actor: user)
        self.service.inventory_repo = SimpleNamespace(get_zone_by_id=lambda zone_id: SimpleNamespace(
            specific_fish_ids=[1, 4] if zone_id == 1 else [1, 8]))
        self.service.fishing_zone_service = SimpleNamespace(get_strategy=lambda zone_id: SimpleNamespace(
            get_fish_rarity_distribution=lambda actor: [0.5, 0, 0, 0, 0.5, 0, 0, 0]
            if zone_id == 1 else [0.5, 0, 0, 0, 0, 0, 0, 0.5]))
        card = {"tier": "silver", "effects": [{"id": "C08", "params": {"price_1_5": 0.7, "price_6_8": 0.2}}]}
        self.repo.create_daily_state("player", self.service.get_game_day(), "silver", [card] * 3, "now")
        self.service.choose("player", 1)
        before = self.service.get_selected_card("player")
        first = self.service.render_offers(self.service.get_daily_state("player"), "player")
        self.assertIn("鱼王（当前鱼区最高档的鱼）：加价 70.0%", first)
        self.assertNotIn("20.0%", first)
        user.fishing_zone_id = 2
        second = self.service.render_offers(self.service.get_daily_state("player"), "player")
        self.assertIn("鱼王（当前鱼区最高档的鱼）：加价 20.0%", second)
        self.assertNotIn("70.0%", second)
        self.assertEqual(self.service.get_eligible_rarities("player"), [1, 8])
        self.assertEqual(self.service.get_selected_card("player"), before)

    def test_daily_offers_are_independent_persisted_and_selected_once(self):
        self.service.rng = TierSequenceRandom(["silver", "gold", "prismatic"])
        state, created = self.service.ensure_daily_state("player-1")
        self.assertTrue(created)
        self.assertEqual(len(state["offers"]), 3)
        self.assertTrue(all(card.get("balance_version") == 4 for card in state["offers"]))
        self.assertEqual([card["tier"] for card in state["offers"]], ["silver", "gold", "prismatic"])
        self.assertEqual([len(card["effects"]) for card in state["offers"]], [2, 3, 4])
        self.assertEqual(self.service.rng.tier_draws, [(('silver', 'gold', 'prismatic'), (50, 35, 15), 1)] * 3)

        stored_snapshot = state["offers"]
        repeated, created_again = self.service.ensure_daily_state("player-1")
        self.assertFalse(created_again)
        self.assertEqual(repeated["offers"], stored_snapshot)

        chosen, status = self.service.choose("player-1", 2)
        self.assertEqual(status, "selected")
        self.assertEqual(chosen["selected_index"], 1)
        selected_card = self.service.get_selected_card("player-1")
        self.assertEqual(selected_card, effective_card(stored_snapshot[1]))
        self.assertEqual(selected_card["tier"], "gold")
        self.assertIn("【棱彩卡】", self.service.render_card(stored_snapshot[2], "player-1"))

        unchanged, status = self.service.choose("player-1", 1)
        self.assertEqual(status, "already_selected")
        self.assertEqual(unchanged["selected_index"], 1)
        still_selected, status = self.service.reroll("player-1")
        self.assertEqual(status, "selected")
        self.assertEqual(still_selected["offers"], stored_snapshot)

    def test_two_atomic_rerolls_redraw_each_tier_and_dynamic_zone_stars(self):
        tier_groups = [["silver", "gold", "prismatic"], ["gold", "prismatic", "silver"], ["prismatic", "silver", "gold"]]
        self.service.rng = TierSequenceRandom([tier for group in tier_groups for tier in group])
        state, _ = self.service.ensure_daily_state("player-2")
        for expected_count in (1, 2):
            state, status = self.service.reroll("player-2")
            self.assertEqual(status, "rerolled")
            self.assertEqual([card["tier"] for card in state["offers"]], tier_groups[expected_count])
            self.assertEqual(state["tier"], state["offers"][0]["tier"])
            self.assertEqual(state["reroll_count"], expected_count)

        state, status = self.service.reroll("player-2")
        self.assertEqual(status, "limit_reached")
        self.assertEqual(state["reroll_count"], 2)
        self.assertEqual(self.service.get_eligible_rarities("player-2"), [1, 5])
        self.assertEqual(self.repo.get_daily_state("player-2", "2026-09-28")["offers"], state["offers"])

    def test_independent_draws_can_coincidentally_have_same_tier(self):
        self.service.rng = TierSequenceRandom(["silver"] * 3)
        state, _ = self.service.ensure_daily_state("player-3")
        self.assertEqual([card["tier"] for card in state["offers"]], ["silver"] * 3)
        self.assertEqual(len(self.service.rng.tier_draws), 3)


if __name__ == "__main__":
    unittest.main()
