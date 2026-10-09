import importlib.util
import os
import sqlite3
import sys
import threading
import tempfile
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

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
from core.repositories.sqlite_gacha_repo import SqliteGachaRepository
from core.services.gacha_service import GachaService
from core.services.gacha_up import apply_personal_up_to_draw
from core.services.item_template_service import ItemTemplateService
from core.services.hextech_gacha_balance import (
    expected_cycle_probabilities,
    expected_cycle_value,
    max_bonus_chance_for_value_budget,
    max_chance_for_budget,
)


class FakeGachaRepository:
    def __init__(self, pool, free=False, pity=0, choices=None):
        self.pool = pool
        self.pools = {int(pool.gacha_pool_id): pool}
        self.free = free
        self.pity = pity
        self.choices = choices if choices is not None else {}
        self.invalidations = {}
        self.pity_writes = []

    def get_pool_by_id(self, pool_id):
        return self.pools.get(int(pool_id))

    def get_all_pools(self):
        return list(self.pools.values())

    def update_pool_item(self, item_pool_id, data):
        item = next(
            item for pool in self.pools.values() for item in pool.items
            if item.gacha_pool_item_id == int(item_pool_id)
        )
        full_id = data.get("item_full_id")
        if full_id:
            item.item_type, raw_id = full_id.split("-", 1)
            item.item_id = int(raw_id)
        if "weight" in data:
            item.weight = float(data["weight"])

    def get_pool_items(self, pool_id):
        pool = self.get_pool_by_id(pool_id)
        return list(pool.items) if pool else []

    def get_free_pools(self):
        return list(self.pools.values()) if self.free else []

    def get_user_pity(self, user_id, pool_id):
        return SimpleNamespace(current_pity=self.pity)

    def set_user_pity(self, user_id, pool_id, value):
        self.pity = value
        self.pity_writes.append(value)

    def get_user_up(self, user_id, pool_id):
        item_id = self.choices.get((str(user_id), int(pool_id)))
        if item_id is None:
            return None
        return SimpleNamespace(
            user_id=str(user_id),
            gacha_pool_id=int(pool_id),
            up_pool_item_id=item_id,
        )

    def get_user_up_choices(self, user_id):
        return [
            SimpleNamespace(user_id=user_id, gacha_pool_id=pool_id, up_pool_item_id=item_id)
            for (owner_id, pool_id), item_id in self.choices.items()
            if owner_id == str(user_id)
        ]

    def get_all_user_up_choices(self):
        return [
            SimpleNamespace(user_id=user_id, gacha_pool_id=pool_id, up_pool_item_id=item_id)
            for (user_id, pool_id), item_id in self.choices.items()
        ]

    def set_user_up(self, user_id, pool_id, item_pool_id):
        key = (str(user_id), int(pool_id))
        self.choices[key] = int(item_pool_id)
        self.invalidations.pop(key, None)

    def delete_user_up(self, user_id, pool_id):
        self.choices.pop((str(user_id), int(pool_id)), None)

    def invalidate_user_up(self, user_id, pool_id, reason):
        key = (str(user_id), int(pool_id))
        self.choices.pop(key, None)
        self.invalidations[key] = reason

    def invalidate_user_ups_by_item(self, item_pool_id, reason):
        for key, value in list(self.choices.items()):
            if value == int(item_pool_id):
                del self.choices[key]
                self.invalidations[key] = reason

    def take_user_up_invalidation(self, user_id, pool_id):
        return self.invalidations.pop((str(user_id), int(pool_id)), None)

    def clear_user_up_invalidation(self, user_id, pool_id):
        self.invalidations.pop((str(user_id), int(pool_id)), None)


class FakeUserRepository:
    def __init__(self, coins=100000, registered=None):
        self.registered = set(registered or {"alice", "bob"})
        self.users = {
            user_id: SimpleNamespace(
                user_id=user_id,
                coins=coins,
                premium_currency=0,
                can_afford=lambda amount, owner=user_id: self.users[owner].coins >= amount,
            )
            for user_id in self.registered
        }
        self.updates = 0

    def get_by_id(self, user_id):
        return self.users.get(str(user_id))

    def update(self, user):
        self.updates += 1
        self.users[user.user_id] = user

    def adjust_balance(
        self,
        user_id,
        coins_delta=0,
        premium_currency_delta=0,
        required_coins=0,
        required_premium_currency=0,
    ):
        user = self.get_by_id(user_id)
        if not user:
            return False
        if user.coins < required_coins or user.premium_currency < required_premium_currency:
            return False
        if user.coins + coins_delta < 0 or user.premium_currency + premium_currency_delta < 0:
            return False
        user.coins += coins_delta
        user.premium_currency += premium_currency_delta
        return True


class FakeInventoryRepository:
    def __init__(self):
        self.awards = []

    def add_rod_instance(self, user_id, rod_id, durability):
        self.awards.append((user_id, "rod", rod_id, durability))

    def add_accessory_instance(self, user_id, accessory_id):
        self.awards.append((user_id, "accessory", accessory_id, None))

    def update_bait_quantity(self, user_id, bait_id, quantity):
        self.awards.append((user_id, "bait", bait_id, quantity))

    def update_item_quantity(self, user_id, item_id, quantity):
        self.awards.append((user_id, "item", item_id, quantity))


class FakeTemplateRepository:
    def __init__(self):
        self.rods = {
            1: SimpleNamespace(name="UP竿", rarity=5, durability=90),
            2: SimpleNamespace(name="同星竿", rarity=5, durability=60),
            3: SimpleNamespace(name="普通竿", rarity=1, durability=20),
        }
        self.baits = {5: SimpleNamespace(name="稀有鱼饵", rarity=5, cost=100)}
        self.items = {7: SimpleNamespace(name="稀有道具", rarity=5, cost=200)}

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
        self.count_today = 0

    def get_gacha_records_count_today(self, user_id, pool_id):
        return self.count_today

    def add_gacha_records_batch(self, records):
        self.records.extend(records)
        self.count_today += len(records)


class FakeAchievementRepository:
    def grant_title_to_user(self, user_id, title_id):
        pass


def make_pool():
    return GachaPool(
        gacha_pool_id=3,
        name="测试卡池",
        cost_coins=100,
        items=[
            GachaPoolItem(101, 3, "rod", 1, 1, 1),
            GachaPoolItem(102, 3, "bait", 5, 3, 1),
            GachaPoolItem(103, 3, "rod", 3, 96, 1),
        ],
    )


def make_service(pool=None, free=False, pity=0, threshold=80, max_draws=100, coins=100000):
    pool = pool or make_pool()
    gacha_repo = FakeGachaRepository(pool, free=free, pity=pity)
    user_repo = FakeUserRepository(coins=coins)
    inventory_repo = FakeInventoryRepository()
    templates = FakeTemplateRepository()
    log_repo = FakeLogRepository()
    service = GachaService(
        gacha_repo,
        user_repo,
        inventory_repo,
        templates,
        log_repo,
        FakeAchievementRepository(),
        pity_threshold=threshold,
        max_draws_per_request=max_draws,
    )
    service.game_config = {"sell_prices": {"rod": {"5": 500, "1": 10}}}
    return service, gacha_repo, user_repo, inventory_repo, log_repo, templates


class PersonalGachaUpTests(unittest.TestCase):
    def test_choices_are_independent_by_user_and_pool(self):
        service, repo, *_ = make_service()
        other_pool = GachaPool(
            gacha_pool_id=4,
            name="第二卡池",
            cost_coins=100,
            items=[
                GachaPoolItem(201, 4, "rod", 1, 1, 1),
                GachaPoolItem(202, 4, "bait", 5, 3, 1),
                GachaPoolItem(203, 4, "rod", 3, 96, 1),
            ],
        )
        repo.pools[4] = other_pool
        service.set_user_up("alice", 3, 101)
        service.set_user_up("alice", 4, 202)
        service.set_user_up("bob", 3, 102)

        self.assertEqual(service.get_user_up("alice", 3)["up"]["entry_id"], 101)
        self.assertEqual(service.get_user_up("alice", 4)["up"]["entry_id"], 202)
        self.assertEqual(service.get_user_up("bob", 3)["up"]["entry_id"], 102)
        self.assertIsNone(service.get_user_up("bob", 4)["up"])

    def test_setting_requires_positive_same_rarity_alternative(self):
        pool = make_pool()
        pool.items = [pool.items[0], pool.items[2]]
        service, repo, *_ = make_service(pool=pool)
        result = service.set_user_up("alice", 3, 101)
        self.assertFalse(result["success"])
        self.assertIn("没有其他正权重奖品", result["message"])
        self.assertIsNone(repo.get_user_up("alice", 3))

    def test_details_show_entry_ids_and_personal_probabilities(self):
        service, *_ = make_service()
        service.set_user_up("alice", 3, 101)
        details = service.get_pool_details(3, user_id="alice")
        probabilities = {
            row["gacha_pool_item_id"]: row for row in details["probabilities"]
        }
        self.assertAlmostEqual(probabilities[101]["base_probability"], 0.01)
        self.assertAlmostEqual(probabilities[101]["probability"], 0.02)
        self.assertAlmostEqual(probabilities[102]["probability"], 0.02)
        self.assertTrue(probabilities[101]["is_personal_up"])

    def test_details_separate_current_hextech_and_hard_pity_probabilities(self):
        service, _repo, *_ = make_service()
        service.set_user_up("alice", 3, 101)
        service.hextech_service = SimpleNamespace(
            get_selected_card=lambda _user_id: {
                "balance_version": 3,
                "tier": "prismatic",
                "effects": [{"id": "P13", "params": {"chance": 0.5}}],
            }
        )
        details = service.get_pool_details(3, user_id="alice")
        rows = {row["gacha_pool_item_id"]: row for row in details["probabilities"]}
        self.assertEqual(details["current_hextech_effect_id"], "P13")
        current_top = rows[101]["current_hextech_probability"] + rows[102]["current_hextech_probability"]
        self.assertAlmostEqual(rows[101]["current_hextech_probability"], current_top * 0.5)
        self.assertAlmostEqual(rows[102]["current_hextech_probability"], current_top * 0.5)
        self.assertAlmostEqual(rows[101]["hard_pity_probability"], 0.5)
        self.assertAlmostEqual(rows[102]["hard_pity_probability"], 0.5)

    def test_setter_and_draw_share_bounded_account_lock_across_service_instances(self):
        service, repo, *_ = make_service()
        second_service = GachaService(
            repo,
            service.user_repo,
            service.inventory_repo,
            service.item_template_repo,
            service.log_repo,
            service.achievement_repo,
        )
        self.assertIs(service._account_lock("alice"), second_service._account_lock("alice"))
        entered = threading.Event()
        completed = threading.Event()

        def set_choice():
            entered.set()
            second_service.set_user_up("alice", 3, 101)
            completed.set()

        lock = service._account_lock("alice")
        with lock:
            worker = threading.Thread(target=set_choice)
            worker.start()
            self.assertTrue(entered.wait(1))
            self.assertFalse(completed.wait(0.05))
        worker.join(1)
        self.assertTrue(completed.is_set())

    def test_users_are_isolated_and_service_recreation_keeps_choices(self):
        service, repo, *_ = make_service()
        self.assertTrue(service.set_user_up("alice", 3, 101)["success"])
        self.assertTrue(service.set_user_up("bob", 3, 102)["success"])

        restarted_service = GachaService(
            repo,
            service.user_repo,
            service.inventory_repo,
            service.item_template_repo,
            service.log_repo,
            service.achievement_repo,
        )
        self.assertEqual(restarted_service.get_user_up("alice", 3)["up"]["entry_id"], 101)
        self.assertEqual(restarted_service.get_user_up("bob", 3)["up"]["entry_id"], 102)
        self.assertEqual(repo.get_user_up("alice", 3).up_pool_item_id, 101)

    def test_50_50_branches_exclude_duplicate_up_identity_from_miss_branch(self):
        pool = make_pool()
        duplicate = GachaPoolItem(104, 3, "rod", 1, 99, 1)
        pool.items.insert(1, duplicate)
        target, alternative = pool.items[0], pool.items[2]
        rarity = lambda item: 5 if item.item_type != "coins" and item.item_id != 3 else 1

        up, hit = apply_personal_up_to_draw(
            target, pool.items, rarity, target, random_value=lambda: 0.1
        )
        self.assertIs(up, target)
        self.assertTrue(hit)

        values = iter((0.9, 0.9))
        missed, hit = apply_personal_up_to_draw(
            target, pool.items, rarity, target, random_value=lambda: next(values)
        )
        self.assertIs(missed, alternative)
        self.assertFalse(hit)
        self.assertNotEqual((missed.item_type, missed.item_id), (target.item_type, target.item_id))

    def test_personal_probability_and_ev_include_up_mapping_and_hard_pity(self):
        pool = make_pool()
        target, alternative, low = pool.items
        rarity = lambda item: {101: 5, 102: 5, 103: 1}[item.gacha_pool_item_id]
        values = {101: 100.0, 102: 20.0, 103: 1.0}
        probs = expected_cycle_probabilities(pool.items, rarity, up_item=target)
        self.assertAlmostEqual(probs[id(target)], 0.02)
        self.assertAlmostEqual(probs[id(alternative)], 0.02)
        self.assertAlmostEqual(probs[id(low)], 0.96)
        self.assertAlmostEqual(
            expected_cycle_value(pool.items, rarity, lambda item: values[item.gacha_pool_item_id], up_item=target),
            3.36,
        )

        pity_probs = expected_cycle_probabilities(
            pool.items, rarity, pity_threshold=2, up_item=target
        )
        self.assertAlmostEqual(pity_probs[id(target)], 0.5 / 1.96)
        self.assertAlmostEqual(pity_probs[id(alternative)], 0.5 / 1.96)
        self.assertAlmostEqual(pity_probs[id(low)], 0.96 / 1.96)

    def test_c27_p13_g13_and_c28_budget_distributions_accept_personal_up(self):
        pool = make_pool()
        target, alternative, low = pool.items
        rarity = lambda item: {101: 5, 102: 5, 103: 1}[item.gacha_pool_item_id]
        values = {101: 100.0, 102: 20.0, 103: 1.0}
        for effect_id in ("C27", "P13"):
            distribution = expected_cycle_probabilities(
                pool.items,
                rarity,
                effect_id=effect_id,
                chance=0.5,
                up_item=target,
            )
            top_mass = distribution[id(target)] + distribution[id(alternative)]
            self.assertAlmostEqual(distribution[id(target)], top_mass * 0.5)
            self.assertAlmostEqual(distribution[id(alternative)], top_mass * 0.5)

        g13 = expected_cycle_probabilities(
            pool.items,
            rarity,
            effect_id="G13",
            weight_multiplier=1.5,
            up_item=target,
        )
        g13_top_mass = g13[id(target)] + g13[id(alternative)]
        self.assertAlmostEqual(g13[id(target)], g13_top_mass * 0.5)

        # The UP is an item stack; C28's modeled bonus must use the mapped mix.
        item_up = GachaPoolItem(102, 3, "item", 7, 3, 1)
        alternate_rod = GachaPoolItem(101, 3, "rod", 1, 1, 1)
        items = [alternate_rod, item_up, low]
        rarity_by_id = {101: 5, 102: 5, 103: 1}
        value_by_id = {101: 0.0, 102: 10.0, 103: 1.0}
        value_of = lambda item: value_by_id[item.gacha_pool_item_id]
        bonus_value = lambda item: 20.0 if item.item_type == "item" else 0.0
        chance = max_chance_for_budget(
            items,
            lambda item: rarity_by_id[item.gacha_pool_item_id],
            value_of,
            0.05,
            1.0,
            effect_id="P13",
            up_item=item_up,
        )
        self.assertGreaterEqual(chance, 0.0)
        self.assertLessEqual(chance, 1.0)
        c28_chance = max_bonus_chance_for_value_budget(
            items,
            lambda item: rarity_by_id[item.gacha_pool_item_id],
            value_of,
            bonus_value,
            0.05,
            1.0,
            up_item=item_up,
        )
        self.assertAlmostEqual(c28_chance, 0.145)
        baseline = expected_cycle_value(
            items,
            lambda item: rarity_by_id[item.gacha_pool_item_id],
            value_of,
            up_item=item_up,
        )
        bonus = expected_cycle_value(
            items,
            lambda item: rarity_by_id[item.gacha_pool_item_id],
            bonus_value,
            up_item=item_up,
        )
        self.assertAlmostEqual(baseline, 1.16)
        self.assertAlmostEqual(bonus, 0.4)

    def test_invalid_up_is_cleared_and_fails_before_deduction(self):
        service, repo, users, *_ = make_service()
        self.assertTrue(service.set_user_up("alice", 3, 101)["success"])
        repo.pool.items[0].weight = 0

        result = service.perform_draw("alice", 3)
        self.assertFalse(result["success"])
        self.assertIn("自动关闭", result["message"])
        self.assertEqual(users.get_by_id("alice").coins, 100000)
        self.assertIsNone(repo.get_user_up("alice", 3))

    def test_invalidated_choice_notice_is_delivered_before_first_charge(self):
        service, repo, users, *_ = make_service()
        self.assertTrue(service.set_user_up("alice", 3, 101)["success"])
        repo.invalidate_user_up("alice", 3, "所选奖品条目的物品身份已修改")

        first = service.perform_draw("alice", 3)
        self.assertFalse(first["success"])
        self.assertIn("物品身份已修改", first["message"])
        self.assertEqual(users.get_by_id("alice").coins, 100000)

        with patch(
            "core.services.gacha_service._perform_single_weighted_draw",
            return_value=repo.pool.items[2],
        ):
            second = service.perform_draw("alice", 3)
        self.assertTrue(second["success"])
        self.assertEqual(users.get_by_id("alice").coins, 99900)

    def test_template_reconciliation_preserves_valid_choices_then_invalidates_changed_rarity(self):
        service, repo, *_ = make_service()
        self.assertTrue(service.set_user_up("alice", 3, 101)["success"])
        item_service = ItemTemplateService(service.item_template_repo, repo)

        item_service._reconcile_gacha_ups()
        self.assertEqual(repo.get_user_up("alice", 3).up_pool_item_id, 101)

        service.item_template_repo.baits[5].rarity = 4
        item_service._reconcile_gacha_ups()
        self.assertIsNone(repo.get_user_up("alice", 3))
        query = service.get_user_up("alice", 3)
        self.assertTrue(query["warning"])

    def test_pool_entry_identity_edit_invalidates_saved_choice(self):
        service, repo, *_ = make_service()
        self.assertTrue(service.set_user_up("alice", 3, 101)["success"])
        item_service = ItemTemplateService(service.item_template_repo, repo)

        item_service.update_pool_item(101, {"item_full_id": "bait-5"})

        self.assertIsNone(repo.get_user_up("alice", 3))
        query = service.get_user_up("alice", 3)
        self.assertTrue(query["warning"])

    def test_hard_pity_draw_uses_up_after_pity_and_logs_actual_item(self):
        service, repo, users, inventory, logs, _ = make_service(pity=79, threshold=80)
        service.set_user_up("alice", 3, 101)
        with patch.object(service, "_pick_pity_item", return_value=repo.pool.items[0]), patch(
            "core.services.gacha_service.random.random", return_value=0.9
        ):
            result = service.perform_draw("alice", 3)
        self.assertTrue(result["success"])
        self.assertEqual(result["results"][0]["id"], 5)
        self.assertFalse(result["results"][0]["is_up"])
        self.assertEqual(result["up_hit_count"], 0)
        self.assertEqual(logs.records[-1].item_id, 5)
        self.assertEqual(repo.pity, 0)
        self.assertEqual(users.get_by_id("alice").coins, 99900)
        self.assertEqual(inventory.awards[-1][1:3], ("bait", 5))

    def test_free_draw_can_hit_up_without_advancing_hard_pity(self):
        service, repo, _users, _inventory, _logs, _ = make_service(free=True, pity=7, threshold=8)
        service.set_user_up("alice", 3, 101)
        with patch(
            "core.services.gacha_service._perform_single_weighted_draw",
            return_value=repo.pool.items[1],
        ), patch("core.services.gacha_service.random.random", return_value=0.1):
            result = service.perform_draw("alice", 3, is_daily_free=True)
        self.assertTrue(result["success"])
        self.assertTrue(result["results"][0]["is_up"])
        self.assertEqual(result["results"][0]["id"], 1)
        self.assertEqual(result["pity_threshold"], 0)
        self.assertEqual(repo.pity_writes, [])

    def test_batch_draw_returns_up_hit_count(self):
        service, repo, users, _inventory, logs, _ = make_service(threshold=0)
        service.set_user_up("alice", 3, 101)
        with patch(
            "core.services.gacha_service._perform_single_weighted_draw",
            return_value=repo.pool.items[0],
        ), patch("core.services.gacha_service.random.random", return_value=0.1):
            result = service.perform_draw("alice", 3, num_draws=2)
        self.assertTrue(result["success"])
        self.assertEqual(result["up_hit_count"], 2)
        self.assertEqual(sum(bool(row.get("is_up")) for row in result["results"]), 2)
        self.assertEqual(len(logs.records), 2)
        self.assertEqual(users.get_by_id("alice").coins, 99800)

    def test_premium_currency_pool_does_not_also_charge_coin_cost(self):
        pool = make_pool()
        pool.cost_premium_currency = 5
        service, _repo, users, *_ = make_service(pool=pool, coins=0, threshold=0)
        users.get_by_id("alice").premium_currency = 5

        with patch(
            "core.services.gacha_service._perform_single_weighted_draw",
            return_value=pool.items[2],
        ):
            result = service.perform_draw("alice", 3)

        self.assertTrue(result["success"])
        self.assertEqual(users.get_by_id("alice").coins, 0)
        self.assertEqual(users.get_by_id("alice").premium_currency, 0)

    def test_service_max_draws_is_enforced_before_any_charge(self):
        service, _repo, users, *_ = make_service(max_draws=2)
        result = service.perform_draw("alice", 3, num_draws=3)
        self.assertFalse(result["success"])
        self.assertIn("最多只能抽 2 张", result["message"])
        self.assertEqual(users.get_by_id("alice").coins, 100000)

    def test_migration_persists_choice_and_item_deletion_cascades(self):
        migration_path = os.path.join(
            os.path.dirname(__file__),
            "..",
            "core",
            "database",
            "migrations",
            "065_add_user_gacha_up.py",
        )
        spec = importlib.util.spec_from_file_location("migration_065", migration_path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)

        with tempfile.TemporaryDirectory(dir=os.path.dirname(__file__)) as directory:
            db_path = os.path.join(directory, "gacha.db")
            connection = sqlite3.connect(db_path)
            connection.execute("PRAGMA foreign_keys = ON")
            connection.executescript(
                """
                CREATE TABLE users (user_id TEXT PRIMARY KEY);
                CREATE TABLE gacha_pools (gacha_pool_id INTEGER PRIMARY KEY);
                CREATE TABLE gacha_pool_items (
                    gacha_pool_item_id INTEGER PRIMARY KEY,
                    gacha_pool_id INTEGER NOT NULL REFERENCES gacha_pools(gacha_pool_id) ON DELETE CASCADE,
                    item_type TEXT NOT NULL,
                    item_id INTEGER NOT NULL,
                    quantity INTEGER NOT NULL DEFAULT 1,
                    weight REAL NOT NULL DEFAULT 1
                );
                INSERT INTO users VALUES ('alice');
                INSERT INTO gacha_pools VALUES (3);
                INSERT INTO gacha_pool_items VALUES (101, 3, 'rod', 1, 1, 1);
                """
            )
            migration.up(connection.cursor())
            connection.commit()
            connection.close()

            first_repo = SqliteGachaRepository(db_path)
            first_repo.set_user_up("alice", 3, 101)
            second_repo = SqliteGachaRepository(db_path)
            saved = second_repo.get_user_up("alice", 3)
            self.assertEqual(saved.up_pool_item_id, 101)
            second_repo.update_pool_item(101, {"item_full_id": "bait-5"})
            self.assertIsNone(second_repo.get_user_up("alice", 3))
            self.assertIn(
                "物品身份已修改",
                second_repo.take_user_up_invalidation("alice", 3),
            )
            second_repo.set_user_up("alice", 3, 101)
            second_repo.delete_pool_item(101)
            self.assertIsNone(second_repo.get_user_up("alice", 3))
            self.assertEqual(
                second_repo.take_user_up_invalidation("alice", 3),
                "所选奖品条目已删除",
            )
            for repository in (first_repo, second_repo):
                connection = getattr(repository._local, "connection", None)
                if connection:
                    connection.close()


if __name__ == "__main__":
    unittest.main()
