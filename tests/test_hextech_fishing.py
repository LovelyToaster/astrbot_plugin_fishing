import random
import sys
import types
import unittest
from datetime import datetime
from types import SimpleNamespace
from typing import get_type_hints
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

from core.domain.models import Fish
from core.services.fish_weight_service import FishWeightService
from core.services.fishing_service import FishingService
from core.services.hextech_effects import EFFECTS, _roll_params, describe_card, roll_card


class FakeUser(SimpleNamespace):
    def can_afford(self, amount):
        return self.coins >= amount


class FakeInventoryRepository:
    def __init__(self, zone, fish):
        self.zone = zone
        self.fish = fish
        self.added_fish = []
        self.bait_updates = []
        self.zone_updates = []
        self.bait_stock = {}

    def get_zone_by_id(self, zone_id):
        return self.zone if zone_id == self.zone.id else None

    def get_user_equipped_rod(self, user_id):
        return None

    def get_user_equipped_accessory(self, user_id):
        return None

    def get_specific_fish_ids_for_zone(self, zone_id):
        return self.zone.specific_fish_ids

    def get_fish_inventory(self, user_id):
        return []

    def add_fish_to_inventory(self, user_id, fish_id, quantity=1, quality_level=0, unit_value=None):
        self.added_fish.append((fish_id, quantity, quality_level, unit_value))

    def update_fishing_zone(self, zone):
        self.zone_updates.append(zone)

    def get_user_bait_inventory(self, user_id):
        return dict(self.bait_stock)

    def update_bait_quantity(self, user_id, bait_id, amount):
        self.bait_updates.append((user_id, bait_id, amount))

    def get_random_bait(self, user_id):
        return None


class FakeTemplateRepository:
    def __init__(self, fish, bait=None):
        self.fish = fish
        self.bait = bait

    def get_all_fish(self):
        return list(self.fish)

    def get_fish_by_id(self, fish_id):
        return next((item for item in self.fish if item.fish_id == fish_id), None)

    def get_fishes_by_rarity(self, rarity):
        return [item for item in self.fish if item.rarity == rarity]

    def get_random_fish(self, rarity):
        candidates = self.get_fishes_by_rarity(rarity)
        return candidates[0] if candidates else None

    def get_bait_by_id(self, bait_id):
        return self.bait if self.bait and self.bait.bait_id == bait_id else None


class FakeUserRepository:
    def __init__(self, user):
        self.user = user

    def get_by_id(self, user_id):
        return self.user if user_id == self.user.user_id else None

    def update(self, user):
        self.user = user


class FakeBuffRepository:
    def get_all_active_by_user(self, user_id):
        return []


class FakeLogRepository:
    def __init__(self):
        self.records = []

    def add_fishing_record(self, record):
        self.records.append(record)


class FakeHextechService:
    def __init__(self, card):
        self.card = card

    def get_selected_card(self, user_id):
        return self.card


def make_service(card, fish, distribution, quota=10, caught=0, cost=100, bait=None):
    zone = SimpleNamespace(
        id=1,
        name="测试鱼区",
        is_active=True,
        available_from=None,
        available_until=None,
        specific_fish_ids=[item.fish_id for item in fish],
        fishing_cost=cost,
        daily_rare_fish_quota=quota,
        rare_fish_quota_per_cycle=quota,
        rare_fish_caught_today=caught,
        rare_fish_caught_this_cycle=caught,
    )
    user = FakeUser(
        user_id="u1",
        fishing_zone_id=1,
        coins=1000,
        current_bait_id=bait.bait_id if bait else None,
        bait_start_time=None,
        equipped_rod_instance_id=None,
        equipped_accessory_instance_id=None,
        fish_pond_capacity=20,
        total_fishing_count=0,
        total_weight_caught=0,
        total_coins_earned=0,
        last_fishing_time=datetime(2026, 1, 1),
    )
    inventory = FakeInventoryRepository(zone, fish)
    if bait:
        inventory.bait_stock[bait.bait_id] = 2
    templates = FakeTemplateRepository(fish, bait)
    service = FishingService.__new__(FishingService)
    service.user_repo = FakeUserRepository(user)
    service.inventory_repo = inventory
    service.item_template_repo = templates
    service.log_repo = FakeLogRepository()
    service.buff_repo = FakeBuffRepository()
    service.fishing_zone_service = SimpleNamespace(
        get_strategy=lambda _zone_id: SimpleNamespace(
            get_fish_rarity_distribution=lambda _user: list(distribution)
        )
    )
    service.fish_weight_service = FishWeightService()
    service.config = {"quality_bonus_max_chance": 0.35}
    service.statistics_repo = None
    service.cat_service = None
    service.hextech_service = FakeHextechService(card) if card else None
    service._reset_rare_fish_pool_quota = lambda: False
    return service, user, zone, inventory


class HextechCatalogTests(unittest.TestCase):
    def test_fishing_type_annotations_resolve(self):
        # Python 3.14 defers annotation evaluation; older runtimes evaluate on import.
        for name, member in vars(FishingService).items():
            if isinstance(member, (staticmethod, classmethod)):
                member = member.__func__
            if isinstance(member, types.FunctionType):
                with self.subTest(method=name):
                    get_type_hints(member)

    def test_catalog_has_exact_ids_and_pool_sizes(self):
        self.assertEqual(len(EFFECTS), 81)
        self.assertEqual(set(EFFECTS), {
            "C{:02d}".format(i) for i in range(1, 34)
        } | {"S{:02d}".format(i) for i in range(1, 17)}
          | {"G{:02d}".format(i) for i in range(1, 17)}
          | {"P{:02d}".format(i) for i in range(1, 17)})
        self.assertEqual(
            {pool: sum(item["pool"] == pool for item in EFFECTS.values())
             for pool in ("common", "silver", "gold", "prismatic")},
            {"common": 33, "silver": 16, "gold": 16, "prismatic": 16},
        )

    def test_roll_card_composition_and_parameter_snapshot(self):
        silver = roll_card("silver", random.Random(2))
        gold = roll_card("gold", random.Random(2))
        prism = roll_card("prismatic", random.Random(3))
        self.assertEqual(len(silver["effects"]), 2)
        self.assertEqual(len(gold["effects"]), 3)
        self.assertEqual({EFFECTS[e["id"]]["pool"] for e in gold["effects"]}, {"common", "gold"})
        self.assertEqual(len(prism["effects"]), 4)
        self.assertGreaterEqual(sum(EFFECTS[e["id"]]["pool"] == "common" for e in prism["effects"]), 1)
        self.assertGreaterEqual(sum(EFFECTS[e["id"]]["pool"] == "prismatic" for e in prism["effects"]), 1)
        self.assertEqual(len({e["id"] for e in prism["effects"]}), 4)

    def test_all_effects_format_and_dynamic_upgrade_target_tracks_pool(self):
        pool_tiers = {"common": "silver", "silver": "silver", "gold": "gold", "prismatic": "prismatic"}
        for effect_id, definition in EFFECTS.items():
            tier = pool_tiers[definition["pool"]]
            card = {"tier": tier, "effects": [{"id": effect_id, "params": _roll_params(effect_id, tier, random.Random(1))}]}
            self.assertIn(definition["name"], describe_card(card, [1, 2, 3, 4, 5, 6, 7, 8]))

        upgrade = {"tier": "silver", "effects": [{"id": "C15", "params": {"upgrade_strength": 1.0}}]}
        five_star_pool = describe_card(upgrade, [1, 2, 3, 4, 5])
        eight_star_pool = describe_card(upgrade, [1, 2, 3, 4, 5, 6, 7, 8])
        self.assertIn("20.0%", five_star_pool)
        self.assertIn("0.3%～20.0%", eight_star_pool)
        self.assertIn("当前鱼区更稀有的鱼", five_star_pool)
        self.assertNotIn("→", eight_star_pool)

        rare = {"tier": "silver", "effects": [{"id": "C06", "params": {"price_1_5": 0.7, "price_6_8": 0.2}}]}
        self.assertIn("稀有鱼（四星及以上）", describe_card(rare, [1, 4, 8]))


class HextechFishingTests(unittest.TestCase):
    def test_new_card_cost_and_refund_share_tier_savings_budget(self):
        effects = [{"id": "C01", "params": {"cost_discount": 1.0}}]
        for tier, maximum_saved in (("silver", 60), ("gold", 75), ("prismatic", 85)):
            with self.subTest(tier=tier):
                paid, _ = FishingService._hextech_payment(100, effects, tier, 2)
                refund = FishingService._hextech_refund_amount(
                    paid, 100, paid, tier, 2
                )
                self.assertEqual(100 - paid + refund, maximum_saved)

        prism_effects = [{"id": "C01", "params": {"cost_discount": 0.5}}]
        paid, _ = FishingService._hextech_payment(100, prism_effects, "prismatic", 2)
        self.assertEqual(paid, 50)
        self.assertEqual(
            FishingService._hextech_refund_amount(100, 100, paid, "prismatic", 2),
            35,
        )

        # Cards saved before balance_version was introduced keep their old rules.
        paid, _ = FishingService._hextech_payment(100, effects, "silver", 1)
        self.assertEqual(paid, 0)
        self.assertEqual(FishingService._hextech_refund_amount(100, 100, paid, "silver", 1), 0)

        fish = Fish(1, "普通鱼", 3, 50, 10, 10)
        new_card = {"tier": "silver", "balance_version": 2, "effects": effects}
        service, _, _, _ = make_service(new_card, [fish], [0, 0, 1])
        self.assertEqual(service.get_hextech_discounted_cost("u1", 100), 40)

        legacy_card = {"tier": "silver", "effects": effects}
        service, _, _, _ = make_service(legacy_card, [fish], [0, 0, 1])
        self.assertEqual(service.get_hextech_discounted_cost("u1", 100), 0)

    def test_new_card_price_and_quality_caps_are_tier_specific(self):
        fish4 = Fish(1, "四星鱼", 4, 100, 10, 10)
        effects = [
            {"id": "C05", "params": {"price_1_5": 1.0}},
            {"id": "C17", "params": {"price_1_5": 1.0}},
        ]
        for tier, cap in (("silver", 0.40), ("gold", 0.70), ("prismatic", 1.0)):
            with self.subTest(tier=tier, rarity=4):
                self.assertEqual(FishingService._hextech_price_bonus(
                    effects, 4, 0, 10, fish4, [4], [4], 4, False, False, set(), None,
                    tier=tier, balance_version=2,
                ), cap)

        fish6 = Fish(2, "六星鱼", 6, 100, 10, 10)
        effects[0]["params"]["price_6_8"] = 1.0
        effects[1]["params"]["price_6_8"] = 1.0
        for tier, cap in (("silver", 0.06), ("gold", 0.10), ("prismatic", 0.15)):
            with self.subTest(tier=tier, rarity=6):
                self.assertEqual(FishingService._hextech_price_bonus(
                    effects, 6, 0, 10, fish6, [6], [6], 6, False, False, set(), None,
                    tier=tier, balance_version=2,
                ), cap)

        self.assertEqual(FishingService._hextech_combined_quality_chance(0.35, 0.5, 2), 0.5)
        self.assertAlmostEqual(FishingService._hextech_combined_quality_chance(0.35, 0.5, 1), 0.60)

    def test_same_selected_card_follows_zone_after_switch(self):
        fish4 = Fish(1, "鱼区一鱼王", 4, 100, 10, 10)
        fish8 = Fish(2, "鱼区二鱼王", 8, 100, 10, 10)
        card = {"tier": "silver", "effects": [{"id": "C08", "params": {"price_1_5": 0.7, "price_6_8": 0.2}}]}
        service, user, zone, inventory = make_service(card, [fish4, fish8], [0, 0, 0, 1, 0, 0, 0, 0])
        zone.specific_fish_ids = [1]
        with patch("core.services.fishing_service.random.random", side_effect=[0.0, 0.99]), \
                patch("core.services.fishing_service.random.choices", return_value=[3]):
            first = service.go_fish("u1")
        self.assertEqual(first["fish"]["unit_value"], 170)

        second_zone = SimpleNamespace(**vars(zone))
        second_zone.id = 2
        second_zone.specific_fish_ids = [2]
        second_zone.rare_fish_caught_this_cycle = 0
        user.fishing_zone_id = 2
        inventory.zone = second_zone
        service.fishing_zone_service = SimpleNamespace(get_strategy=lambda zone_id: SimpleNamespace(
            get_fish_rarity_distribution=lambda user: [0, 0, 0, 0, 0, 0, 0, 1]))
        with patch("core.services.fishing_service.random.random", side_effect=[0.0, 0.99]), \
                patch("core.services.fishing_service.random.choices", return_value=[7]):
            second = service.go_fish("u1")
        self.assertEqual(second["fish"]["unit_value"], 120)
        self.assertEqual([entry[0] for entry in inventory.added_fish], [1, 2])
        self.assertEqual(service._get_selected_hextech_card("u1"), card)

    def test_discounted_cost_value_snapshot_and_quantity_quota_count(self):
        fish = Fish(1, "测试稀有鱼", 4, 100, 10, 10)
        card = {
            "tier": "silver",
            "effects": [
                {"id": "C01", "params": {"cost_discount": 0.5}},
                {"id": "C05", "params": {"price_1_5": 0.5, "price_6_8": 0.3}},
            ],
        }
        service, user, zone, inventory = make_service(card, [fish], [0, 0, 0, 1], quota=10)
        with patch("core.services.fishing_service.random.random", side_effect=[0.0, 0.99]), \
                patch("core.services.fishing_service.random.choices", return_value=[3]):
            result = service.go_fish("u1")

        self.assertTrue(result["success"])
        self.assertEqual(user.coins, 950)
        self.assertEqual(result["fish"]["unit_value"], 150)
        self.assertEqual(inventory.added_fish, [(1, 1, 0, 150)])
        self.assertEqual(zone.rare_fish_caught_this_cycle, 1)

    def test_rare_quota_counts_every_fish_in_a_multi_catch(self):
        fish = Fish(1, "测试稀有鱼", 4, 100, 10, 10)
        bait = SimpleNamespace(
            bait_id=9,
            duration_minutes=0,
            quantity_modifier=2.0,
            rare_chance_modifier=0.0,
            success_rate_modifier=0.0,
            garbage_reduction_modifier=None,
            value_modifier=1.0,
        )
        card = {
            "tier": "silver",
            "effects": [{"id": "C05", "params": {"price_1_5": 0.5, "price_6_8": 0.3}}],
        }
        service, _, zone, inventory = make_service(card, [fish], [0, 0, 0, 1], bait=bait)
        with patch("core.services.fishing_service.random.random", side_effect=[0.0, 0.99]), \
                patch("core.services.fishing_service.random.choices", return_value=[3]):
            result = service.go_fish("u1")
        self.assertTrue(result["success"])
        self.assertEqual(result["fish"]["catches"], 2)
        self.assertEqual(inventory.added_fish, [(1, 2, 0, 150)])
        self.assertEqual(zone.rare_fish_caught_this_cycle, 2)

    def test_promotion_uses_only_real_positive_stars_in_current_pool(self):
        fish4 = Fish(1, "四星鱼", 4, 100, 10, 10)
        fish5 = Fish(2, "五星鱼", 5, 200, 10, 10)
        # 星级 6 有概率配置，但当前区域限定鱼种中不存在 6 星鱼。
        card = {"tier": "silver", "effects": [{"id": "C15", "params": {"upgrade_strength": 1.0}}]}
        service, _, _, _ = make_service(card, [fish4, fish5], [0, 0, 0, 0.8, 0.1, 0.1, 0, 0])
        with patch("core.services.fishing_service.random.random", side_effect=[0.0, 0.0, 0.99]), \
                patch("core.services.fishing_service.random.choices", return_value=[3]):
            result = service.go_fish("u1")
        self.assertTrue(result["success"])
        self.assertEqual(result["fish"]["rarity"], 5)

    def test_selected_card_can_break_exhausted_quota_but_uses_real_pool(self):
        fish3 = Fish(1, "普通鱼", 3, 50, 10, 10)
        fish4 = Fish(2, "四星鱼", 4, 100, 10, 10)
        card = {"tier": "silver", "effects": [{"id": "C16", "params": {"break_bonus": 0.01}}]}
        service, _, zone, _ = make_service(card, [fish3, fish4], [0, 0, 0.5, 0.5], quota=0, caught=0)
        with patch("core.services.fishing_service.random.random", side_effect=[0.0, 0.0, 0.99]), \
                patch("core.services.fishing_service.random.choices", return_value=[3]):
            result = service.go_fish("u1")
        self.assertTrue(result["success"])
        self.assertEqual(result["fish"]["rarity"], 4)
        self.assertEqual(zone.rare_fish_caught_this_cycle, 1)


if __name__ == "__main__":
    unittest.main()
