import json
import sys
import types
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


if "astrbot" not in sys.modules:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

if "requests" not in sys.modules:
    try:
        import requests  # noqa: F401
    except ImportError:
        # This focused test never makes the optional background upload call.
        sys.modules["requests"] = types.ModuleType("requests")

# Import as the plugin package so the service's package-relative core.utils
# import resolves the same way it does when AstrBot loads the plugin.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from astrbot_plugin_fishing.core.services.game_mechanics_service import GameMechanicsService
from astrbot_plugin_fishing.core.services.hextech_game_balance import (
    expected_conditional_reroll_gain,
    expected_electric_success_values,
    expected_electric_value_for_quantity,
    expected_wipe_base_payout_ratio,
    expected_wipe_profit_bonus,
    expected_wipe_reroll_bonus,
)
from astrbot_plugin_fishing.core.utils import get_now, get_today


GAME_SERVICE_MODULE = "astrbot_plugin_fishing.core.services.game_mechanics_service"


class FakeUser(SimpleNamespace):
    def can_afford(self, amount):
        return self.coins >= amount


class FakeUserRepository:
    def __init__(self, *users):
        self.users = {user.user_id: user for user in users}
        self.updates = []

    def get_by_id(self, user_id):
        return self.users.get(user_id)

    def update(self, user):
        self.users[user.user_id] = user
        self.updates.append(user)


class FakeInventoryRepository:
    def __init__(self, inventories=None):
        self.inventories = inventories or {}
        self.removed = []
        self.added = []

    def get_fish_inventory(self, user_id):
        return list(self.inventories.get(user_id, []))

    def get_user_equipped_accessory(self, _user_id):
        return None

    def update_fish_quantity(self, user_id, fish_id, delta, quality_level=0, unit_value=None):
        self.removed.append((user_id, fish_id, delta, quality_level, unit_value))

    def add_fish_to_inventory(self, user_id, fish_id, quantity=1, quality_level=0, unit_value=None):
        self.added.append((user_id, fish_id, quantity, quality_level, unit_value))

    def get_user_item_inventory(self, _user_id):
        return {}


class FakeTemplateRepository:
    def __init__(self, fish):
        self.fish = {item.fish_id: item for item in fish}

    def get_fish_by_id(self, fish_id):
        return self.fish.get(fish_id)

    def get_all_items(self):
        return []


class FakeBuffRepository:
    def get_active_by_user_and_type(self, _user_id, _buff_type):
        return None


class FakeLogRepository:
    def __init__(self):
        self.wipe_logs = []

    def add_wipe_bomb_log(self, entry):
        self.wipe_logs.append(entry)


class FakeHextechService:
    def __init__(self, card):
        self.card = card

    def get_selected_card(self, _actor_id):
        return self.card


class NoopThreadPool:
    def submit(self, *_args, **_kwargs):
        return None


def make_user(user_id, **values):
    defaults = {
        "user_id": user_id,
        "nickname": user_id,
        "coins": 10000,
        "last_steal_time": None,
        "last_electric_fish_time": None,
        "wipe_bomb_forecast": None,
        "wipe_bomb_attempts_today": 0,
        "last_wipe_bomb_date": None,
        "max_wipe_bomb_multiplier": 0.0,
        "min_wipe_bomb_multiplier": None,
        "in_wheel_of_fate": False,
        "wof_current_level": 0,
        "wof_current_prize": 0,
        "wof_entry_fee": 0,
        "wof_last_action_time": None,
        "last_wof_play_time": None,
        "wof_plays_today": 0,
        "last_wof_date": None,
        "wof_used_protection": False,
        "wof_hextech_snapshot": None,
    }
    defaults.update(values)
    return FakeUser(**defaults)


def make_service(users, inventories=None, fish=None, card=None, config=None):
    service = GameMechanicsService(
        user_repo=FakeUserRepository(*users),
        log_repo=FakeLogRepository(),
        inventory_repo=FakeInventoryRepository(inventories),
        item_template_repo=FakeTemplateRepository(fish or []),
        buff_repo=FakeBuffRepository(),
        config=config or {},
    )
    service.statistics_repo = None
    service.hextech_service = FakeHextechService(card) if card is not None else None
    service.thread_pool = NoopThreadPool()
    return service


def card(effect_id, tier="silver", **params):
    return {
        "balance_version": 3,
        "tier": tier,
        "effects": [{"id": effect_id, "params": params}],
    }


class HextechGameExpansionTests(unittest.TestCase):
    def test_c21_uses_inventory_value_ev_and_actual_steal_path(self):
        cheap = SimpleNamespace(fish_id=1, quality_level=0, quantity=1, unit_value=100)
        valuable = SimpleNamespace(fish_id=2, quality_level=0, quantity=1, unit_value=1000)
        thief = make_user("thief")
        victim = make_user("victim")
        service = make_service(
            [thief, victim],
            {"victim": [cheap, valuable]},
            [
                SimpleNamespace(fish_id=1, name="小鱼", base_value=100, rarity=1),
                SimpleNamespace(fish_id=2, name="大鱼", base_value=1000, rarity=2),
            ],
            card("C21", ev_budget=0.05, chance=1.0),
        )

        with patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.choice", side_effect=[cheap, valuable]), \
             patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.random", return_value=0.0):
            result = service.steal_fish("thief", "victim")

        self.assertTrue(result["success"])
        self.assertEqual(service.inventory_repo.added[0][1:4], (2, 1, 0))
        self.assertEqual(result["hextech_effect_id"], "C21")
        self.assertEqual(result["hextech_bonus_value"], 900)

    def test_c22_upgrades_only_the_transferred_quality_and_keeps_removal_key(self):
        ordinary = SimpleNamespace(fish_id=1, quality_level=0, quantity=1, unit_value=100)
        thief = make_user("thief")
        victim = make_user("victim")
        service = make_service(
            [thief, victim],
            {"victim": [ordinary]},
            [SimpleNamespace(fish_id=1, name="小鱼", base_value=100, rarity=2)],
            card("C22", ev_budget=0.05, chance=1.0),
        )

        with patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.choice", return_value=ordinary), \
             patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.random", return_value=0.0):
            result = service.steal_fish("thief", "victim")

        self.assertTrue(result["success"])
        self.assertEqual(service.inventory_repo.removed[0][3], 0)
        self.assertEqual(service.inventory_repo.added[0][3], 1)
        self.assertEqual(result["hextech_bonus_value"], 100)

    def test_c24_retry_runs_inside_electric_fish_resolution(self):
        thief = make_user("thief", coins=1000)
        victim = make_user("victim")
        fish_inventory = [SimpleNamespace(fish_id=1, quality_level=0, quantity=100, unit_value=100)]
        service = make_service(
            [thief, victim],
            {"victim": fish_inventory},
            [SimpleNamespace(fish_id=1, name="鱼", base_value=100, rarity=1)],
            card("C24", ev_budget=0.05, chance=1.0),
            config={"electric_fish": {"base_success_rate": 0.5, "failure_penalty_max_rate": 0.5}},
        )

        with patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.random", side_effect=[0.9, 0.0, 0.1]), \
             patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.randint", return_value=20), \
             patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.sample", side_effect=lambda population, count: population[:count]):
            result = service.electric_fish("thief", "victim")

        self.assertTrue(result["success"])
        self.assertTrue(result["hextech_retry_saved"])
        self.assertIn("重判成功", result["message"])
        self.assertEqual(len(service.inventory_repo.added), 1)

    def test_wipe_reroll_uses_active_table_and_respects_absolute_bonus_cap(self):
        user = make_user("wiper", coins=200000)
        service = make_service(
            [user],
            card=card(
                "C29", tier="prismatic", ev_budget=0.08, chance=1.0,
                fraction=0.2, bonus_cap=20000, return_cap=1.03,
            ),
        )
        uniform_values = iter([0.0, 0.0, 0.0, 0.2])

        with patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.uniform", side_effect=lambda *_args: next(uniform_values)), \
             patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.random", return_value=0.0):
            result = service.perform_wipe_bomb("wiper", 100000)

        self.assertEqual(result["multiplier"], 0.0)
        self.assertEqual(result["raw_reward"], 0)
        self.assertEqual(result["hextech_bonus"], 20000)
        self.assertEqual(result["reward"], 20000)

    def test_wheel_freezes_card_at_start_and_pays_settlement_bonus(self):
        user = make_user("wheel", coins=10000)
        wheel_card = card("C32", tier="gold", fraction=0.10, bonus_cap=0.10)
        service = make_service([user], card=wheel_card)
        with patch("astrbot_plugin_fishing.core.services.game_mechanics_service.random.random", return_value=0.1):
            started = service.start_wheel_of_fate("wheel", 1000)
        self.assertEqual(started["status"], "ongoing")
        self.assertEqual(json.loads(user.wof_hextech_snapshot), wheel_card)

        # Daily selection can change after the round begins; settlement reads
        # only the persisted start-of-game card snapshot.
        service.hextech_service.card = card("P16", tier="prismatic")
        user.wof_current_level = 5
        user.wof_current_prize = 1500
        user.wof_last_action_time = get_now()
        result = service.cash_out_wheel_of_fate("wheel")

        self.assertEqual(result["hextech_effect_id"], "C32")
        self.assertEqual(result["hextech_bonus"], 50)
        self.assertEqual(user.coins, 10550)
        self.assertIsNone(user.wof_hextech_snapshot)

    def test_c26_bounty_chance_is_applied_to_real_electric_capture(self):
        fish = SimpleNamespace(fish_id=1, name="鱼", base_value=1000, rarity=1)
        inventory = [SimpleNamespace(fish_id=1, quality_level=0, quantity=100, unit_value=1000)]

        for chance_roll, expected_bonus in ((0.1, 300), (0.9, 0)):
            with self.subTest(chance_roll=chance_roll):
                thief = make_user("thief")
                victim = make_user("victim")
                service = make_service(
                    [thief, victim], {"victim": inventory}, [fish],
                    card("C26", chance=0.15, fraction=0.03, price_fraction=0.03, bonus_cap=300),
                    config={"electric_fish": {"base_success_rate": 1.0}},
                )
                with patch(f"{GAME_SERVICE_MODULE}.random.random", side_effect=[0.0, chance_roll]), \
                     patch(f"{GAME_SERVICE_MODULE}.random.randint", return_value=20), \
                     patch(f"{GAME_SERVICE_MODULE}.random.sample", side_effect=lambda population, count: population[:count]):
                    result = service.electric_fish("thief", "victim")

                self.assertTrue(result["success"])
                self.assertEqual(result["hextech_bonus_coins"], expected_bonus)
                self.assertEqual(thief.coins, 10000 + expected_bonus)

    def test_g14_large_suppressed_bet_stays_within_expected_return_cap(self):
        user = make_user("wiper", coins=200000)
        service = make_service(
            [user], card=card(
                "G14", tier="gold", fraction=0.08, price_fraction=0.10,
                return_cap=1.02, bonus_cap=20000,
            ),
        )
        service._server_suppressed = True
        service._last_suppression_date = get_today()
        suppressed = [
            (0.0, 0.2, 10000), (0.2, 0.5, 18000), (0.5, 0.8, 15000),
            (0.8, 1.2, 25000), (1.2, 2.0, 20000), (2.0, 3.0, 6000),
            (3.0, 6.0, 1000), (6.0, 15.0, 150), (15.0, 50.0, 0),
            (50.0, 200.0, 0), (200.0, 1500.0, 0),
        ]

        with patch(f"{GAME_SERVICE_MODULE}.weighted_random_choice", return_value=suppressed[4]), \
             patch(f"{GAME_SERVICE_MODULE}.random.uniform", return_value=1.9):
            result = service.perform_wipe_bomb("wiper", 100000)

        base_return = expected_wipe_base_payout_ratio(suppressed)
        expected_bonus = expected_wipe_profit_bonus(100000, suppressed, 0.08, 10000)
        self.assertTrue(result["success"])
        self.assertEqual(result["hextech_effect_id"], "G14")
        self.assertGreater(result["hextech_bonus"], 0)
        self.assertLessEqual(base_return + expected_bonus / 100000, 1.02)
        self.assertLessEqual(result["hextech_bonus"], 20000)

    def test_g15_caps_large_bet_interval_reroll_bonus_at_20000(self):
        user = make_user("wiper", coins=2000000)
        service = make_service(
            [user], card=card("G15", tier="gold", chance=0.35, return_cap=1.02),
        )
        high_band = (50.0, 200.0, 7)
        with patch(f"{GAME_SERVICE_MODULE}.weighted_random_choice", return_value=high_band), \
             patch(f"{GAME_SERVICE_MODULE}.random.uniform", side_effect=[50.0, 200.0]), \
             patch(f"{GAME_SERVICE_MODULE}.random.random", return_value=0.0):
            result = service.perform_wipe_bomb("wiper", 1000000)

        self.assertEqual(result["hextech_effect_id"], "G15")
        self.assertEqual(result["hextech_bonus"], 20000)

    def test_wheel_g16_and_p16_award_only_the_highest_eligible_settlement(self):
        g16_user = make_user(
            "g16", coins=9000, in_wheel_of_fate=True, wof_current_level=5,
            wof_current_prize=1500, wof_entry_fee=1000, wof_last_action_time=get_now(),
            wof_hextech_snapshot=json.dumps(card(
                "G16", tier="gold", fraction=0.12, bonus_cap=0.20,
            )),
        )
        p16_user = make_user(
            "p16", coins=9000, in_wheel_of_fate=True, wof_current_level=7,
            wof_current_prize=1500, wof_entry_fee=1000, wof_last_action_time=get_now(),
            wof_hextech_snapshot=json.dumps(card(
                "P16", tier="prismatic", milestones={"3": 0.10, "6": 0.20, "10": 0.30},
            )),
        )
        g16 = make_service([g16_user]).cash_out_wheel_of_fate("g16")
        p16 = make_service([p16_user]).cash_out_wheel_of_fate("p16")

        self.assertEqual((g16["hextech_effect_id"], g16["hextech_bonus"]), ("G16", 60))
        self.assertEqual((p16["hextech_effect_id"], p16["hextech_bonus"]), ("P16", 200))
        self.assertEqual(p16["hextech_details"]["milestone"], 6)

    def test_legacy_cards_do_not_add_random_calls_to_game_resolutions(self):
        fish = SimpleNamespace(fish_id=1, name="鱼", base_value=1000, rarity=1)
        inventory = [SimpleNamespace(fish_id=1, quality_level=0, quantity=100, unit_value=1000)]
        legacy_cards = [
            None,
            {"balance_version": 2, "tier": "prismatic", "effects": [{"id": "C26", "params": {"chance": 1.0}}]},
        ]

        for legacy_card in legacy_cards:
            with self.subTest(legacy_card=legacy_card):
                thief, victim = make_user("thief"), make_user("victim")
                service = make_service([thief, victim], {"victim": inventory}, [fish], legacy_card)
                with patch(f"{GAME_SERVICE_MODULE}.random.random", return_value=0.0) as roll, \
                     patch(f"{GAME_SERVICE_MODULE}.random.randint", return_value=20), \
                     patch(f"{GAME_SERVICE_MODULE}.random.sample", side_effect=lambda population, count: population[:count]):
                    result = service.electric_fish("thief", "victim")
                self.assertTrue(result["success"])
                self.assertEqual(roll.call_count, 1)
                self.assertEqual(thief.coins, 10000)
                self.assertEqual(result["hextech_bonus_coins"], 0)

                steal_thief, steal_victim = make_user("stealer"), make_user("target")
                steal_item = SimpleNamespace(
                    fish_id=1, quality_level=0, quantity=1, unit_value=1000,
                )
                steal_service = make_service(
                    [steal_thief, steal_victim], {"target": [steal_item]}, [fish], legacy_card,
                )
                with patch(f"{GAME_SERVICE_MODULE}.random.random", return_value=0.0) as steal_roll, \
                     patch(f"{GAME_SERVICE_MODULE}.random.choice", return_value=steal_item):
                    steal_result = steal_service.steal_fish("stealer", "target")
                self.assertTrue(steal_result["success"])
                self.assertEqual(steal_roll.call_count, 0)
                self.assertIsNone(steal_result["hextech_effect_id"])

                wiper = make_user("wiper", coins=10000)
                wipe_service = make_service([wiper], card=legacy_card)
                with patch(f"{GAME_SERVICE_MODULE}.random.random", return_value=0.0) as wipe_roll, \
                     patch(f"{GAME_SERVICE_MODULE}.weighted_random_choice", return_value=(0.0, 0.2, 10000)), \
                     patch(f"{GAME_SERVICE_MODULE}.random.uniform", return_value=0.1):
                    wipe_result = wipe_service.perform_wipe_bomb("wiper", 1000)
                self.assertTrue(wipe_result["success"])
                self.assertEqual(wipe_roll.call_count, 0)
                self.assertEqual(wipe_result["hextech_bonus"], 0)

                wheel_user = make_user("wheel", coins=10000)
                wheel_service = make_service([wheel_user], card=legacy_card)
                with patch(f"{GAME_SERVICE_MODULE}.random.random", return_value=0.0) as wheel_roll:
                    started = wheel_service.start_wheel_of_fate("wheel", 1000)
                    self.assertEqual(wheel_roll.call_count, 1)
                    wheel_user.wof_last_action_time = get_now()
                    settled = wheel_service.cash_out_wheel_of_fate("wheel")
                self.assertEqual(wheel_roll.call_count, 1)
                self.assertEqual(started["status"], "ongoing")
                self.assertEqual(settled["hextech_bonus"], 0)

    def test_electric_value_expectation_counts_high_rarity_replacement_rule(self):
        population = [(10, 10.0, False), (2, 1000.0, True)]
        self.assertEqual(expected_electric_value_for_quantity(population, 12, 5), 725.0)
        values = expected_electric_success_values(population, 12)
        self.assertGreaterEqual(values["great"], values["normal"])
        self.assertGreaterEqual(values["normal"], values["small"])

    def test_bottom_quartile_reroll_ev_includes_probability_of_qualifying_pick(self):
        # Only the lowest row qualifies at runtime; the helper includes its
        # 1/4 baseline selection probability because the trigger chance is
        # conditional on selecting that row.
        self.assertEqual(expected_conditional_reroll_gain([0, 10, 20, 30], [0]), 3.75)

    def test_wipe_ev_integral_matches_effective_normal_and_suppressed_tables(self):
        normal = [(0.0, 0.2, 10000), (0.2, 0.5, 18000), (0.5, 0.8, 15000), (0.8, 1.2, 25000), (1.2, 2.0, 14100), (2.0, 3.0, 4230), (3.0, 6.0, 705), (6.0, 15.0, 106), (15.0, 50.0, 21), (50.0, 200.0, 7), (200.0, 1500.0, 1)]
        suppressed = [(0.0, 0.2, 10000), (0.2, 0.5, 18000), (0.5, 0.8, 15000), (0.8, 1.2, 25000), (1.2, 2.0, 20000), (2.0, 3.0, 6000), (3.0, 6.0, 1000), (6.0, 15.0, 150), (15.0, 50.0, 0), (50.0, 200.0, 0), (200.0, 1500.0, 0)]
        self.assertAlmostEqual(expected_wipe_base_payout_ratio(normal), 0.9392910405, places=8)
        self.assertAlmostEqual(expected_wipe_base_payout_ratio(suppressed), 0.9997372570, places=8)
        normal_extra = expected_wipe_reroll_bonus(10000, normal, 0.5, 2000)
        suppressed_extra = expected_wipe_reroll_bonus(10000, suppressed, 0.5, 2000)
        self.assertLess(normal_extra / 10000 + expected_wipe_base_payout_ratio(normal), 1.01)
        self.assertLess(suppressed_extra / 10000 + expected_wipe_base_payout_ratio(suppressed), 1.03)


if __name__ == "__main__":
    unittest.main()
