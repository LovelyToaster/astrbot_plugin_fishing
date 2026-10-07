import random
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

# Allow isolated service tests to run outside an installed AstrBot process.
try:
    import astrbot.api  # noqa: F401
except ModuleNotFoundError:
    astrbot_module = types.ModuleType("astrbot")
    astrbot_api_module = types.ModuleType("astrbot.api")
    astrbot_api_module.logger = SimpleNamespace(
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    sys.modules["astrbot"] = astrbot_module
    sys.modules["astrbot.api"] = astrbot_api_module

from core.domain.models import GachaPool, GachaPoolItem
from core.services.gacha_service import GachaService
from core.services.hextech_gacha_balance import (
    expected_cycle_value,
    expected_cycle_probabilities,
    max_chance_for_budget,
    max_chance_for_probability_budget,
    max_quantity_bonus_chance,
    max_weight_multiplier_for_probability_budget,
    quantity_bonus,
)


class FakeGachaRepository:
    def __init__(self, pool, pity=0, free=False):
        self.pool = pool
        self.pity = pity
        self.free = free
        self.pity_writes = []

    def get_pool_by_id(self, pool_id):
        return self.pool if int(pool_id) == self.pool.gacha_pool_id else None

    def get_all_pools(self):
        return [self.pool]

    def get_free_pools(self):
        return [self.pool] if self.free else []

    def get_user_pity(self, user_id, pool_id):
        return SimpleNamespace(current_pity=self.pity)

    def set_user_pity(self, user_id, pool_id, value):
        self.pity = value
        self.pity_writes.append(value)


class FakeUserRepository:
    def __init__(self, coins=100000):
        class FakeUser:
            def __init__(self, value):
                self.user_id = "player"
                self.coins = value
                self.premium_currency = 0

            def can_afford(self, amount):
                return self.coins >= amount

        self.user = FakeUser(coins)
        self.updates = 0

    def get_by_id(self, user_id):
        return self.user if str(user_id) == "player" else None

    def update(self, user):
        self.updates += 1


class FakeInventoryRepository:
    def __init__(self):
        self.rod_awards = []
        self.bait_awards = []
        self.item_awards = []

    def add_rod_instance(self, user_id, rod_id, durability):
        self.rod_awards.append((rod_id, durability))

    def add_accessory_instance(self, user_id, accessory_id):
        pass

    def update_bait_quantity(self, user_id, bait_id, quantity):
        self.bait_awards.append((bait_id, quantity))

    def update_item_quantity(self, user_id, item_id, quantity):
        self.item_awards.append((item_id, quantity))


class FakeItemTemplateRepository:
    def __init__(self):
        self.rods = {
            1: SimpleNamespace(rod_id=1, name="普通竿", rarity=1, durability=20),
            2: SimpleNamespace(rod_id=2, name="高阶竿", rarity=10, durability=80),
            3: SimpleNamespace(rod_id=3, name="不可抽取的测试竿", rarity=20, durability=100),
        }
        self.baits = {5: SimpleNamespace(bait_id=5, name="蚯蚓", rarity=1, cost=100)}
        self.items = {7: SimpleNamespace(item_id=7, name="补给包", rarity=2, cost=250)}

    def get_rod_by_id(self, item_id):
        return self.rods.get(item_id)

    def get_accessory_by_id(self, item_id):
        return None

    def get_bait_by_id(self, item_id):
        return self.baits.get(item_id)

    def get_by_id(self, item_id):
        return self.items.get(item_id)

    def get_title_by_id(self, item_id):
        return None


class FakeLogRepository:
    def __init__(self):
        self.records = []

    def get_gacha_records_count_today(self, user_id, pool_id):
        return 0

    def add_gacha_records_batch(self, records):
        self.records.extend(records)


class FakeAchievementRepository:
    def __init__(self):
        self.titles = []

    def grant_title_to_user(self, user_id, title_id):
        self.titles.append((user_id, title_id))


class FakeHextechService:
    def __init__(self, effect_id, params, tier="prismatic", version=3):
        self.card = {
            "balance_version": version,
            "tier": tier,
            "effects": [{"id": effect_id, "params": params}],
        }

    def get_selected_card(self, actor_id):
        return self.card


def make_pool(items, cost=100, premium=0, pool_id=3, name="付费补给"):
    return GachaPool(
        gacha_pool_id=pool_id,
        name=name,
        cost_coins=cost,
        cost_premium_currency=premium,
        items=items,
    )


def make_service(pool, card=None, pity=0, threshold=80, free=False, coin_balance=100000, prices=None):
    gacha_repo = FakeGachaRepository(pool, pity=pity, free=free)
    user_repo = FakeUserRepository(coins=coin_balance)
    inventory_repo = FakeInventoryRepository()
    templates = FakeItemTemplateRepository()
    log_repo = FakeLogRepository()
    service = GachaService(
        gacha_repo, user_repo, inventory_repo, templates, log_repo,
        FakeAchievementRepository(), pity_threshold=threshold,
    )
    service.game_config = {"sell_prices": prices or {}}
    service.hextech_service = card
    return service, gacha_repo, user_repo, inventory_repo, log_repo


def rod_pool(cost=100):
    return make_pool([
        GachaPoolItem(1, 3, "rod", 1, 99, 1),
        GachaPoolItem(2, 3, "rod", 2, 1, 1),
    ], cost=cost)


class HextechGachaExpansionTests(unittest.TestCase):
    def test_unpriced_c27_chance_uses_budget_upper_bound_and_commits_one_final_reward(self):
        pool = rod_pool()
        # This zero-weight, rarity-zero title must not suppress C27's active
        # minimum rarity candidate.
        pool.items.append(GachaPoolItem(3, 3, "titles", 99, 0, 1))
        service, gacha_repo, _, _, log_repo = make_service(
            pool, FakeHextechService("C27", {"ev_budget": 0.08, "chance": 1.0})
        )
        # First candidate is the lowest rarity; optional second candidate is the high rod.
        with patch("core.services.gacha_service.random.random", return_value=0.0), patch(
            "core.services.gacha_service.random.uniform", side_effect=[0.0, 99.5]
        ):
            result = service.perform_draw("player", 3)

        self.assertTrue(result["success"])
        self.assertGreater(result["hextech_effect"]["chance"], 0.08)
        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["id"], 2)
        self.assertEqual(len(log_repo.records), 1)
        self.assertEqual(log_repo.records[0].item_id, 2)
        self.assertEqual(gacha_repo.pity, 0)
        self.assertEqual(result["hextech_effect"]["triggered_count"], 1)
        self.assertGreater(result["hextech_effect"]["chance"], 0)

    def test_c27_does_not_reroll_a_hard_pity_result(self):
        service, gacha_repo, _, _, log_repo = make_service(
            rod_pool(), FakeHextechService("C27", {"ev_budget": 0.08, "chance": 1.0}),
            pity=0, threshold=1,
        )
        with patch("core.services.gacha_service.random.random") as random_roll, patch(
            "core.services.gacha_service.random.uniform", return_value=0.0
        ), patch("core.services.gacha_service._perform_single_weighted_draw") as normal_draw:
            result = service.perform_draw("player", 3)

        self.assertTrue(result["success"])
        self.assertEqual(result["results"][0]["id"], 2)
        random_roll.assert_not_called()
        normal_draw.assert_not_called()
        self.assertEqual(len(log_repo.records), 1)
        self.assertEqual(gacha_repo.pity, 0)

    def test_p13_uses_one_final_candidate_for_results_log_and_pity(self):
        service, gacha_repo, _, _, log_repo = make_service(
            rod_pool(), FakeHextechService("P13", {"ev_budget": 0.08, "chance": 1.0})
        )
        with patch("core.services.gacha_service.random.random", return_value=0.0), patch(
            "core.services.gacha_service.random.uniform", side_effect=[0.0, 99.5]
        ):
            result = service.perform_draw("player", 3)

        self.assertEqual(len(result["results"]), 1)
        self.assertEqual(result["results"][0]["id"], 2)
        self.assertEqual(len(log_repo.records), 1)
        self.assertEqual(log_repo.records[0].item_id, 2)
        self.assertEqual(gacha_repo.pity, 0)
        self.assertGreater(result["hextech_effect"]["chance"], 0)
        self.assertEqual(result["hextech_effect"]["triggered_count"], 1)

    def test_c28_accounts_for_single_item_rounding_in_budget_and_log_quantity(self):
        pool = make_pool([GachaPoolItem(1, 3, "bait", 5, 100, 1)])
        service, _, _, inventory, log_repo = make_service(
            pool,
            FakeHextechService("C28", {"ev_budget": 0.08, "chance": 0.35, "fraction": 0.20}),
        )
        with patch("core.services.gacha_service.random.random", return_value=0.0), patch(
            "core.services.gacha_service.random.uniform", return_value=0.0
        ):
            result = service.perform_draw("player", 3)

        self.assertEqual(result["hextech_effect"]["chance"], 0.08)
        self.assertEqual(inventory.bait_awards, [(5, 2)])
        self.assertEqual(result["results"][0]["quantity"], 2)
        self.assertEqual(log_repo.records[0].quantity, 2)
        self.assertEqual(result["hextech_effect"]["triggered_count"], 1)

    def test_s13_coin_refund_is_capped_by_long_run_reward_ev(self):
        pool = make_pool([GachaPoolItem(1, 3, "coins", 0, 100, 1000)], cost=10000)
        service, _, user_repo, _, log_repo = make_service(
            pool,
            FakeHextechService("S13", {
                "ev_budget": 0.08, "fraction": 0.08, "bonus_cap": 500,
            }),
            coin_balance=10000,
        )
        result = service.perform_draw("player", 3)

        self.assertEqual(result["hextech_refund_coins"], 80)
        self.assertEqual(user_repo.user.coins, 1080)
        self.assertEqual(result["results"], [{"type": "coins", "quantity": 1000}])
        self.assertEqual(len(log_repo.records), 1)
        self.assertEqual(log_repo.records[0].quantity, 1000)

    def test_s14_coin_bonus_is_per_coin_reward_and_inside_ev_budget(self):
        pool = make_pool([GachaPoolItem(1, 3, "coins", 0, 100, 1000)], cost=1000)
        service, _, user_repo, _, log_repo = make_service(
            pool,
            FakeHextechService("S14", {
                "ev_budget": 0.08, "chance": 0.30, "bonus_cap": 0.05,
            }),
            coin_balance=10000,
        )
        with patch("core.services.gacha_service.random.random", return_value=0.0), patch(
            "core.services.gacha_service.random.uniform", return_value=0.0
        ):
            result = service.perform_draw("player", 3)

        self.assertEqual(result["results"][0]["quantity"], 1050)
        self.assertEqual(log_repo.records[0].quantity, 1050)
        self.assertEqual(user_repo.user.coins, 10050)
        self.assertEqual(result["hextech_effect"]["chance"], 0.30)
        self.assertEqual(result["hextech_effect"]["triggered_count"], 1)
        self.assertEqual(result["hextech_effect"]["bonus_coins_total"], 50)

    def test_s13_and_s14_do_not_add_coins_to_free_draws(self):
        pool = make_pool([GachaPoolItem(1, 3, "coins", 0, 100, 100)], cost=0, name="每日签到补给")
        service, gacha_repo, user_repo, _, _ = make_service(
            pool,
            FakeHextechService("S13", {
                "ev_budget": 0.08, "fraction": 0.08, "bonus_cap": 500,
            }),
            coin_balance=1000,
            free=True,
        )
        result = service.perform_draw("player", 3)

        self.assertEqual(result["hextech_refund_coins"], 0)
        self.assertEqual(result["pity_threshold"], 0)
        self.assertEqual(user_repo.user.coins, 1100)
        self.assertEqual(gacha_repo.pity_writes, [])

        s14, _, s14_user, _, _ = make_service(
            make_pool([GachaPoolItem(1, 3, "coins", 0, 100, 100)], cost=0, name="每日签到补给"),
            FakeHextechService("S14", {
                "ev_budget": 0.05, "chance": 0.30, "bonus_cap": 0.05,
            }, tier="silver"),
            coin_balance=1000,
            free=True,
        )
        s14_result = s14.perform_draw("player", 3)
        self.assertEqual(s14_result["results"][0]["quantity"], 100)
        self.assertEqual(s14_result["hextech_effect"]["chance"], 0.0)
        self.assertEqual(s14_result["hextech_effect"]["bonus_coins_total"], 0)
        self.assertEqual(s14_user.user.coins, 1100)

    def test_g13_scales_the_highest_rarity_group_and_stays_within_budget(self):
        pool = make_pool([
            GachaPoolItem(1, 3, "rod", 1, 90, 1),
            GachaPoolItem(2, 3, "rod", 2, 10, 1),
            GachaPoolItem(3, 3, "rod", 3, 0, 1),
        ])
        service, _, _, _, _ = make_service(
            pool,
            FakeHextechService("G13", {
                "ev_budget": 0.08, "weight_multiplier": 1.15,
            }),
        )
        # The zero-weight rarity-20 template must not hide the active rarity-10
        # group from either EV calibration or the actual sampler.
        with patch(
            "core.services.gacha_service.random.uniform", return_value=90.4
        ) as weighted_roll:
            result = service.perform_draw("player", 3)

        self.assertEqual(result["results"][0]["id"], 2)
        self.assertGreater(result["hextech_effect"]["weight_multiplier"], 1.08)
        self.assertAlmostEqual(
            weighted_roll.call_args.args[1],
            90 + 10 * result["hextech_effect"]["weight_multiplier"],
        )

    def test_batch_and_split_draws_follow_the_same_effect_and_pity_stream(self):
        pool_one = rod_pool(cost=1)
        card = FakeHextechService("C27", {"ev_budget": 0.05, "chance": 1.0}, tier="silver")
        prices = {"rod": {"1": 100, "10": 1000}}
        batch, batch_repo, _, _, batch_logs = make_service(
            pool_one, card, threshold=3, coin_balance=1000, prices=prices
        )
        random.seed(901)
        batch_result = batch.perform_draw("player", 3, num_draws=10)

        split, split_repo, _, _, split_logs = make_service(
            rod_pool(cost=1), card, threshold=3, coin_balance=1000, prices=prices
        )
        random.seed(901)
        split_results = [split.perform_draw("player", 3) for _ in range(10)]

        self.assertTrue(batch_result["success"])
        self.assertTrue(all(result["success"] for result in split_results))
        self.assertEqual(batch_repo.pity, split_repo.pity)
        self.assertEqual(
            [(row.item_type, row.item_id, row.quantity) for row in batch_logs.records],
            [(row.item_type, row.item_id, row.quantity) for row in split_logs.records],
        )
        self.assertEqual(
            [reward["id"] for reward in batch_result["results"]],
            [result["results"][0]["id"] for result in split_results],
        )

    def test_unpriced_pool_guards_and_stack_rounding_helpers(self):
        items = [
            GachaPoolItem(1, 3, "bait", 5, 1, 1),
            GachaPoolItem(2, 3, "titles", 7, 1, 1),
        ]
        self.assertEqual(quantity_bonus(1, 0.20), 1)
        self.assertEqual(quantity_bonus(8, 0.20), 2)
        self.assertEqual(max_quantity_bonus_chance(items[:1], 0.08, 0.35, 0.20), 0.08)

        rarity = lambda item: 0 if item.item_type == "coins" else 1
        chance = max_chance_for_budget(
            items, rarity, lambda item: None, 0.08, 1.0,
            effect_id="C27",
        )
        self.assertGreater(chance, 0.08)
        self.assertIsNone(expected_cycle_value(items, rarity, lambda item: None))

    def test_priced_c27_budget_uses_the_hard_pity_cycle(self):
        items = [
            GachaPoolItem(1, 3, "rod", 1, 90, 1),
            GachaPoolItem(2, 3, "rod", 2, 10, 1),
        ]
        rarity = lambda item: 1 if item.item_id == 1 else 10
        value = lambda item: 100 if item.item_id == 1 else 1000
        baseline = expected_cycle_value(items, rarity, value, pity_threshold=3)
        chance = max_chance_for_budget(
            items, rarity, value, budget=0.08, requested_chance=1.0,
            pity_threshold=3, effect_id="C27",
        )
        adjusted = expected_cycle_value(
            items, rarity, value, pity_threshold=3,
            effect_id="C27", chance=chance,
        )

        self.assertAlmostEqual(baseline, 1171 / 2.71)
        self.assertLessEqual(adjusted, baseline * 1.08 + 1e-9)
        self.assertGreater(chance, 0.08)

        # Free draws omit pity, so their reference value is one ordinary draw.
        self.assertAlmostEqual(expected_cycle_value(items, rarity, value), 190)

    def test_unpriced_pity_pool_caps_each_reward_probability_increase(self):
        items = [
            GachaPoolItem(1, 3, "rod", 1, 80, 1),
            GachaPoolItem(2, 3, "rod", 2, 15, 1),
            GachaPoolItem(3, 3, "rod", 3, 4, 1),
            GachaPoolItem(4, 3, "rod", 4, 1, 1),
        ]
        rarities = {1: 1, 2: 5, 3: 10, 4: 10}
        rarity = lambda item: rarities[item.item_id]
        budget = 0.08
        baseline = expected_cycle_probabilities(items, rarity, pity_threshold=80)

        for effect_id in ("C27", "P13"):
            chance = max_chance_for_probability_budget(
                items, rarity, budget, 1.0, 80, effect_id
            )
            adjusted = expected_cycle_probabilities(
                items, rarity, 80, effect_id=effect_id, chance=chance
            )
            self.assertGreater(chance, 0)
            for item in items:
                increase = adjusted[id(item)] / baseline[id(item)] - 1.0
                self.assertLessEqual(increase, budget + 1e-9)

        multiplier = max_weight_multiplier_for_probability_budget(
            items, rarity, budget, 1.15, 80
        )
        adjusted = expected_cycle_probabilities(
            items, rarity, 80, effect_id="G13", weight_multiplier=multiplier
        )
        for item in items:
            increase = adjusted[id(item)] / baseline[id(item)] - 1.0
            self.assertLessEqual(increase, budget + 1e-9)


if __name__ == "__main__":
    unittest.main()
