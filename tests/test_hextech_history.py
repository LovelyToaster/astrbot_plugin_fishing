import importlib
import os
import random
import sqlite3
import tempfile
import unittest
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Barrier
from unittest.mock import patch

from core.services import hextech_effects
from core.repositories.sqlite_hextech_repo import SqliteHextechRepository
from core.services.hextech_effects import EFFECTS, SLOT_COUNTS, effective_card, roll_card
from core.services.hextech_service import HextechService


MIGRATION = importlib.import_module(
    "core.database.migrations.064_add_hextech_offer_history"
)


def card_with_effects(*effect_ids, tier="silver", gifts=None):
    card = {
        "tier": tier,
        "balance_version": 4,
        "effects": [{"id": effect_id, "tier": tier, "params": {}}
                    for effect_id in effect_ids],
    }
    if gifts is not None:
        card["gifts"] = gifts
    return card


class HextechHistoryTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = str(Path(self.temp_dir.name) / "fish.db")
        connection = sqlite3.connect(self.db_path)
        try:
            importlib.import_module(
                "core.database.migrations.062_add_hextech_daily"
            ).up(connection.cursor())
            MIGRATION.up(connection.cursor())
            MIGRATION.up(connection.cursor())
            connection.commit()
        finally:
            connection.close()
        self.repo = SqliteHextechRepository(self.db_path)

    def tearDown(self):
        self.repo._get_connection().close()
        self.temp_dir.cleanup()

    def test_history_weights_survive_restart_and_expire_by_game_day(self):
        today = date(2026, 10, 9)
        for days_ago, effect_id in ((7, "C06"), (2, "C05"), (0, "C01")):
            game_day = (today - timedelta(days=days_ago)).isoformat()
            offers = [card_with_effects(effect_id)] * 3
            self.repo.create_daily_state(
                "player", game_day, "silver", offers, game_day,
                shown_effect_counts={effect_id: 1},
            )

        restarted_repo = SqliteHextechRepository(self.db_path)
        self.assertEqual(
            restarted_repo.get_offer_history_weights(
                "player", today.isoformat(), 7, 0.15, 0.5
            ),
            {"C01": 0.15, "C05": 0.5},
        )
        self.assertEqual(
            restarted_repo._get_connection().execute(
                "SELECT COUNT(*) FROM hextech_offer_history WHERE effect_id='C06'"
            ).fetchone()[0],
            0,
        )
        restarted_repo._get_connection().close()

    def test_create_race_records_only_the_insert_winner(self):
        barrier = Barrier(2)
        cards = [card_with_effects("C01"), card_with_effects("C05")]

        def create(index):
            repo = SqliteHextechRepository(self.db_path)
            barrier.wait()
            result = repo.create_daily_state(
                "race", "2026-10-09", cards[index]["tier"], [cards[index]] * 3,
                "2026-10-09T12:00:00+08:00",
                shown_effect_counts={cards[index]["effects"][0]["id"]: index + 1},
            )
            repo._get_connection().close()
            return result

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(create, range(2)))
        self.assertEqual(sum(created for _, created in results), 1)
        state = self.repo.get_daily_state("race", "2026-10-09")
        winning_effect = state["offers"][0]["effects"][0]["id"]
        rows = self.repo._get_connection().execute(
            "SELECT effect_id, shown_count FROM hextech_offer_history WHERE actor_id='race'"
        ).fetchall()
        self.assertEqual([(row["effect_id"], row["shown_count"]) for row in rows],
                         [(winning_effect, 1 if winning_effect == "C01" else 2)])

    def test_reroll_history_is_atomic_and_hidden_gifts_are_not_counted(self):
        service = HextechService(self.repo)
        visible = card_with_effects(
            "C01",
            gifts=[{"tier": "silver", "effects": [{"id": "P17"}]}],
        )
        self.repo.create_daily_state(
            "player", "2026-10-09", "silver", [visible] * 3, "now",
            shown_effect_counts=service._visible_effect_counts([visible] * 3),
        )
        self.assertEqual(
            self.repo.get_offer_history_weights("player", "2026-10-09"),
            {"C01": 0.15},
        )

        first = [card_with_effects("C05"), card_with_effects("C06"), card_with_effects("C07")]
        state, status = self.repo.reroll_daily_offers(
            "player", "2026-10-09", first,
            shown_effect_counts={"C05": 2}, shown_at="2026-10-09T12:01:00+08:00",
        )
        self.assertEqual(status, "rerolled")
        self.assertEqual(state["reroll_count"], 1)
        self.assertEqual(
            self.repo.get_offer_history_weights("player", "2026-10-09")["C05"],
            0.15,
        )

        self.repo.reroll_daily_offers("player", "2026-10-09", first)
        _, status = self.repo.reroll_daily_offers(
            "player", "2026-10-09", [card_with_effects("C08")] * 3,
            shown_effect_counts={"C08": 3}, shown_at="never",
        )
        self.assertEqual(status, "limit_reached")
        weights = self.repo.get_offer_history_weights("player", "2026-10-09")
        self.assertNotIn("C08", weights)
        row = self.repo._get_connection().execute(
            """SELECT shown_count FROM hextech_offer_history
            WHERE actor_id='player' AND effect_id='C05'"""
        ).fetchone()
        self.assertEqual(row[0], 2)

    def test_service_records_the_visible_offer_set_on_create_and_successful_reroll(self):
        now = datetime(2026, 10, 9, 12, tzinfo=timezone(timedelta(hours=8)))
        service = HextechService(
            self.repo,
            rng=random.Random(910),
            clock=lambda: now,
            config={
                "enabled": True,
                "history_window_days": 7,
                "same_day_weight": 0.15,
                "recent_weight": 0.5,
                "same_group_weight": 0.15,
                "silver_effect_count": 2,
                "gold_effect_count": 3,
                "prismatic_effect_count": 4,
            },
        )
        state, created = service.ensure_daily_state("service-player")
        self.assertTrue(created)
        self.assertEqual(
            service.effect_counts,
            {"silver": 2, "gold": 3, "prismatic": 4},
        )

        expected = Counter(service._visible_effect_counts(state["offers"]))
        rows = self.repo._get_connection().execute(
            """SELECT effect_id, shown_count FROM hextech_offer_history
            WHERE actor_id='service-player'"""
        ).fetchall()
        self.assertEqual(
            {row["effect_id"]: row["shown_count"] for row in rows}, dict(expected)
        )
        rerolled, status = service.reroll("service-player")
        self.assertEqual(status, "rerolled")
        expected.update(service._visible_effect_counts(rerolled["offers"]))
        rows = self.repo._get_connection().execute(
            """SELECT effect_id, shown_count FROM hextech_offer_history
            WHERE actor_id='service-player'"""
        ).fetchall()
        self.assertEqual(
            {row["effect_id"]: row["shown_count"] for row in rows}, dict(expected)
        )

    def test_reset_clears_exposure_history(self):
        offer = card_with_effects("C01")
        self.repo.create_daily_state(
            "reset-player", "2026-10-09", "silver", [offer] * 3, "now",
            shown_effect_counts={"C01": 3},
        )
        self.repo.reset_all_users()
        self.assertEqual(
            self.repo.get_offer_history_weights("reset-player", "2026-10-09"), {}
        )

    def test_zero_history_window_disables_history_without_changing_card_count(self):
        now = datetime(2026, 10, 9, 12, tzinfo=timezone(timedelta(hours=8)))
        service = HextechService(
            self.repo,
            rng=random.Random(18),
            clock=lambda: now,
            config={"enabled": True, "history_window_days": 0},
        )
        state, created = service.ensure_daily_state("no-history")
        self.assertTrue(created)
        self.assertEqual([len(card["effects"]) for card in state["offers"]], [
            SLOT_COUNTS[card["tier"]] for card in state["offers"]
        ])
        self.assertEqual(
            self.repo._get_connection().execute(
                "SELECT COUNT(*) FROM hextech_offer_history WHERE actor_id='no-history'"
            ).fetchone()[0],
            0,
        )

    def test_configured_counts_preserve_gift_baseline_and_legacy_cards(self):
        counts = {"silver": 3, "gold": 4, "prismatic": 5}
        rng = random.Random(20261009)
        saw_gift = False
        for tier in ("silver", "gold", "prismatic"):
            for _ in range(100):
                card = roll_card(tier, rng, effect_counts=counts)
                self.assertEqual(len(card["effects"]), counts[tier])
                self.assertEqual(card["balance_version"], 5)
                all_ids = [effect["id"] for effect in effective_card(card)["effects"]]
                self.assertEqual(len(all_ids), len(set(all_ids)))
                for index, effect_id in enumerate(all_ids):
                    conflicts = set(EFFECTS[effect_id]["conflicts"])
                    self.assertFalse(conflicts.intersection(all_ids[:index]))
                    self.assertTrue(all(
                        effect_id not in EFFECTS[other]["conflicts"]
                        for other in all_ids[:index]
                    ))
                if card.get("gifts"):
                    saw_gift = True
                    self.assertEqual(len(card["gifts"]), SLOT_COUNTS[tier])
                    for gift in card["gifts"]:
                        self.assertEqual(len(gift["effects"]), SLOT_COUNTS[gift["tier"]])
                        self.assertEqual(gift["balance_version"], 4)

        legacy = roll_card("prismatic", random.Random(42))
        self.assertEqual(len(legacy["effects"]), SLOT_COUNTS["prismatic"])
        self.assertEqual(legacy["balance_version"], 4)
        self.assertTrue(saw_gift)

    def test_impossible_configured_count_falls_back_to_legacy_count(self):
        legacy_card = {"tier": "silver", "balance_version": 4, "effects": []}
        with patch.object(
            hextech_effects,
            "_roll_card_once",
            side_effect=[ValueError("incompatible"), legacy_card],
        ) as roll_once:
            card = roll_card(
                "silver", random.Random(7), effect_counts={"silver": 3}
            )
        self.assertIs(card, legacy_card)
        self.assertEqual(roll_once.call_args_list[0].args[3], 3)
        self.assertEqual(roll_once.call_args_list[1].args[3], SLOT_COUNTS["silver"])

    def test_history_weighted_simulation_improves_per_user_coverage(self):
        def simulate(seed, weighted):
            rng = random.Random(seed)
            seen = set()
            history = {}
            for _refresh in range(3):
                sibling_ids = set()
                for _slot in range(3):
                    tier = rng.choices(
                        ("silver", "gold", "prismatic"), weights=(50, 35, 15), k=1
                    )[0]
                    card = roll_card(
                        tier,
                        rng,
                        history_weights=history if weighted else {},
                        sibling_effect_ids=sibling_ids,
                        same_group_weight=0.15 if weighted else 1.0,
                    )
                    ids = {effect["id"] for effect in card["effects"]}
                    seen.update(ids)
                    sibling_ids.update(ids)
                    if weighted:
                        history.update({effect_id: 0.15 for effect_id in ids})
            return len(seen)

        baseline = [simulate(seed, False) for seed in range(40)]
        optimized = [simulate(seed, True) for seed in range(40)]
        baseline_average = sum(baseline) / len(baseline)
        optimized_average = sum(optimized) / len(optimized)
        self.assertGreater(optimized_average, baseline_average + 0.5)


if __name__ == "__main__":
    unittest.main()
