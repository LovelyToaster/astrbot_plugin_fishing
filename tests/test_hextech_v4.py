import importlib
import json
import math
import random
import sqlite3
import tempfile
import unittest
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_hextech_fishing import FishingService, make_service as fishing_service
from tests.test_hextech_expansion_gacha import make_service as gacha_service, rod_pool, FakeHextechService
from core.domain.models import Fish
from core.repositories.sqlite_hextech_repo import SqliteHextechRepository
from core.services.hextech_effects import (
    EFFECTS, TIERS, SLOT_COUNTS, V4_EV_BUDGETS, FISHING_STRENGTH,
    _v4_params, roll_card, effective_card, describe_card, upgrade_chance,
    high_weight_multiplier,
)
from core.services.hextech_game_balance import ev_budget, steal_cooldown
from core.services.hextech_service import HextechService
from tests.test_hextech_expansion_games import make_service as game_service, make_user, GAME_SERVICE_MODULE


def find_gift(tier):
    rng = random.Random(61001)
    for _ in range(2000):
        card = roll_card(tier, rng)
        if card.get("gifts"):
            return card
    raise AssertionError("missing gift")


class HextechV4Tests(unittest.TestCase):
    def test_all_slots_and_gifts_are_compatible_and_nonrecursive(self):
        rng = random.Random(44)
        mixes = {tier: set() for tier in TIERS}
        gift_tiers = Counter()
        for tier in TIERS:
            for _ in range(1500):
                card = roll_card(tier, rng)
                self.assertEqual(len(card["effects"]), SLOT_COUNTS[tier])
                pools = [EFFECTS[e["id"]]["pool"] for e in card["effects"]]
                self.assertIn("common", pools)
                self.assertIn(tier, pools)
                self.assertLessEqual(set(pools), {"common", tier})
                mixes[tier].add(pools.count("common"))
                if card.get("gifts"):
                    self.assertEqual(len(card["gifts"]), SLOT_COUNTS[tier])
                    for gift in card["gifts"]:
                        gift_tiers[gift["tier"]] += 1
                        self.assertNotIn("gifts", gift)
                        self.assertEqual(len(gift["effects"]), SLOT_COUNTS[gift["tier"]])
                        child_pools = [EFFECTS[e["id"]]["pool"] for e in gift["effects"]]
                        self.assertIn("common", child_pools)
                        self.assertIn(gift["tier"], child_pools)
                        self.assertNotIn("C33", [e["id"] for e in gift["effects"]])
                ids = [e["id"] for e in effective_card(card)["effects"]]
                self.assertEqual(len(ids), len(set(ids)))
                for i, key in enumerate(ids):
                    self.assertFalse(set(EFFECTS[key]["conflicts"]).intersection(ids[:i]))
                    self.assertTrue(all(key not in EFFECTS[other]["conflicts"] for other in ids[:i]))
        self.assertEqual(mixes, {"silver": {1}, "gold": {1, 2}, "prismatic": {1, 2, 3}})
        total = sum(gift_tiers.values())
        for tier, expected in zip(TIERS, (.5, .35, .15)):
            self.assertAlmostEqual(gift_tiers[tier] / total, expected, delta=.05)

    def test_parameter_scaling_preserves_range_positions_and_source_tier(self):
        for tier in TIERS:
            primary = _v4_params("C05", tier, random.Random(1))
            gift = _v4_params("C05", tier, random.Random(1), gift=True)
            self.assertAlmostEqual(gift["price_1_5"], primary["price_1_5"] * .25)
            for key in ("C14", "C15"):
                ordinary = _v4_params(key, tier, random.Random(1))
                child = _v4_params(key, tier, random.Random(1), gift=True)
                for strength in ("upgrade_strength", "high_weight_strength"):
                    if strength in child:
                        self.assertEqual(child[strength], ordinary[strength])
                self.assertAlmostEqual(child["strength_scale"], FISHING_STRENGTH[tier] * .25)
            params = _v4_params("C23", tier, random.Random(1), gift=True)
            self.assertAlmostEqual(params["ev_budget"], V4_EV_BUDGETS[tier] * .25)
            for parent in TIERS:
                card = {"tier": parent, "balance_version": 4, "effects": [
                    {"id": "C23", "tier": tier, "params": params}]}
                budget = ev_budget(card, params)
                self.assertLessEqual(budget, V4_EV_BUDGETS[parent])
                self.assertLessEqual(budget, V4_EV_BUDGETS[tier] * .25)
                cooldown, _ = steal_cooldown(10800, card)
                self.assertEqual(cooldown, math.ceil(10800 / (1 + budget)))

    def test_dynamic_weight_and_upgrade_scale_the_bonus_not_multiplier(self):
        self.assertAlmostEqual(high_weight_multiplier("prismatic", 1, 5, 4, .16875),
                               1 + .75 * .16875)
        self.assertAlmostEqual(upgrade_chance("prismatic", 1, 5, 4, .16875), .35 * .16875)
        card = {"tier": "silver", "balance_version": 4, "effects": [
            {"id": "C14", "tier": "prismatic", "params": {"high_weight_strength": 1, "strength_scale": .16875}}]}
        self.assertIn("×1.13", describe_card(card, [1, 4, 5]))
        self.assertIn("×1.01", describe_card(card, [1, 4, 8]))

    def test_gift_is_persisted_hidden_before_selection_and_expires_with_parent(self):
        migration = importlib.import_module("core.database.migrations.062_add_hextech_daily")
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "fish.db")
            connection = sqlite3.connect(path)
            with connection:
                migration.up(connection.cursor())
            connection.close()
            repo = SqliteHextechRepository(path)
            now = datetime(2026, 10, 1, 12, tzinfo=timezone(timedelta(hours=8)))
            service = HextechService(repo, clock=lambda: now)
            card = find_gift("prismatic")
            original = json.dumps(card, sort_keys=True)
            state, _ = repo.create_daily_state("player", service.get_game_day(), card["tier"],
                                              [card, card, card], now.isoformat())
            self.assertNotIn("🎁 赠卡", service.render_offers(state, "player"))
            self.assertIsNone(service.get_selected_card("player"))
            state, status = service.choose("player", 1)
            self.assertEqual(status, "selected")
            self.assertIn("🎁 赠卡4", service.render_offers(state, "player"))
            selected = service.get_selected_card("player")
            self.assertEqual(selected, effective_card(card))
            selected["effects"].clear()
            reopened = HextechService(repo, clock=lambda: now)
            self.assertEqual(reopened.get_selected_card("player"), effective_card(card))
            self.assertEqual(json.dumps(card, sort_keys=True), original)
            now += timedelta(days=1)
            self.assertEqual(reopened.get_selected_card("player"), effective_card(card))
            reopened.ensure_daily_state("player")
            self.assertIsNone(reopened.get_selected_card("player"))
            repo._get_connection().close()

    def test_actual_fishing_settles_gift_price_and_combined_caps(self):
        gift = {"tier": "prismatic", "balance_version": 4, "effects": [
            {"id": "C05", "tier": "prismatic", "params": _v4_params("C05", "prismatic", random.Random(1), True)}]}
        card = effective_card({"tier": "silver", "balance_version": 4, "effects": [], "gifts": [gift]})
        fish = Fish(1, "测试鱼", 4, 1000, 10, 10)
        service, _, _, inventory = fishing_service(card, [fish], [0, 0, 0, 1])
        with patch("core.services.fishing_service.random.random", side_effect=[0, .99]), \
                patch("core.services.fishing_service.random.choices", return_value=[3]):
            result = service.go_fish("u1")
        expected = math.ceil(1000 * (1 + gift["effects"][0]["params"]["price_1_5"]))
        self.assertEqual(result["fish"]["unit_value"], expected)
        self.assertEqual(inventory.added_fish[0][-1], expected)
        effects = [{"id": "C05", "params": {"price_1_5": 9, "price_6_8": 9}}]
        for tier, low, high in (("silver", .36, .054), ("gold", .63, .09), ("prismatic", .9, .135)):
            for rarity, cap in ((4, low), (6, high)):
                value = FishingService._hextech_price_bonus(effects, rarity, 0, 10, fish,
                                                          [4, 6], [4, 6], 6, False, False,
                                                          set(), None, tier, 4)
                self.assertAlmostEqual(value, cap)

    def test_actual_gacha_uses_gift_budget_and_one_final_reward(self):
        params = _v4_params("C27", "prismatic", random.Random(1), True)
        card_service = FakeHextechService("C27", params, tier="silver", version=4)
        service, _, _, _, logs = gacha_service(rod_pool(), card_service)
        effect = service._get_hextech_gacha_effect("player")
        self.assertEqual(service._hextech_gacha_budget(effect), .0175)
        with patch("core.services.gacha_service.random.random", return_value=0), \
                patch("core.services.gacha_service.random.uniform", side_effect=[0, 99.5]):
            result = service.perform_draw("player", 3)
        self.assertTrue(result["success"])
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(len(logs.records), 1)
        self.assertEqual(result["results"][0]["id"], 2)

    def test_actual_wheel_pays_the_scaled_gift_and_shows_its_saved_values(self):
        params = _v4_params("P16", "prismatic", random.Random(1), True)
        card = {"tier": "gold", "balance_version": 4, "effects": [
            {"id": "P16", "tier": "prismatic", "params": params}]}
        user = make_user("player", in_wheel_of_fate=True, wof_current_level=7,
                         wof_current_prize=1500, wof_entry_fee=1000,
                         wof_last_action_time=datetime.now(timezone(timedelta(hours=8))),
                         wof_hextech_snapshot=json.dumps(card))
        service = game_service([user])
        result = service.cash_out_wheel_of_fate("player")
        self.assertEqual(result["hextech_bonus"], int(1000 * params["milestones"]["6"]))
        self.assertIn("4.4%", describe_card(card, [1, 4, 8]))
        self.assertNotIn("10%／20%／30%", describe_card(card, [1, 4, 8]))

    def test_actual_wipe_gift_respects_the_scaled_absolute_cap(self):
        params = _v4_params("G15", "gold", random.Random(1), True)
        card = {"tier": "prismatic", "balance_version": 4, "effects": [
            {"id": "G15", "tier": "gold", "params": params}]}
        service = game_service([make_user("player", coins=2000000)], card=card)
        with patch(GAME_SERVICE_MODULE + ".weighted_random_choice", return_value=(50., 200., 7)), \
                patch(GAME_SERVICE_MODULE + ".random.uniform", side_effect=[50., 200.]), \
                patch(GAME_SERVICE_MODULE + ".random.random", return_value=0):
            result = service.perform_wipe_bomb("player", 1000000)
        self.assertTrue(result["success"])
        self.assertEqual(result["hextech_effect_id"], "G15")
        self.assertEqual(result["hextech_bonus"], int(params["bonus_cap"]))

    def test_old_snapshots_retain_old_budgets_and_dynamic_ranges(self):
        for tier, budget in zip(TIERS, (.05, .065, .08)):
            self.assertEqual(ev_budget({"tier": tier, "balance_version": 3}), budget)
        self.assertEqual(high_weight_multiplier("prismatic", 1, 5, 3), 1.75)
        self.assertEqual(upgrade_chance("prismatic", 1, 5, 3), .35)
        self.assertEqual(effective_card({"tier": "gold", "balance_version": 3, "effects": []}),
                         {"tier": "gold", "balance_version": 3, "effects": []})


if __name__ == "__main__":
    unittest.main()
