import json
import sqlite3
import sys
import types
import unittest
from datetime import datetime
from types import SimpleNamespace


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


from core.domain.models import UserBuff
from core.repositories.sqlite_user_buff_repo import SqliteUserBuffRepository
from core.services.item_effects.electric_fish_success_boost_effect import (
    ElectricFishSuccessBoostEffect,
)


class MemoryBuffRepository:
    def __init__(self):
        self.buff = None
        self.next_id = 1

    def get_active_by_user_and_type(self, user_id, buff_type):
        return self.buff

    def add(self, buff):
        buff.id = self.next_id
        self.next_id += 1
        self.buff = buff

    def update(self, buff):
        self.buff = buff


class ElectricFishBoostTests(unittest.TestCase):
    def test_effect_does_not_stack(self):
        repo = MemoryBuffRepository()
        effect = ElectricFishSuccessBoostEffect(buff_repo=repo)
        user = SimpleNamespace(user_id="user-1")
        item = SimpleNamespace(name="雷鸣护符")

        first = effect.apply(user, item, {"bonus_rate": 0.2, "max_rate": 1.0})
        second = effect.apply(
            user,
            item,
            {"bonus_rate": 0.2, "max_rate": 1.0},
        )

        self.assertTrue(first["success"])
        self.assertFalse(second["success"])
        self.assertNotIn("charges", json.loads(repo.buff.payload))

    def test_effect_rejects_batch_use_and_stores_fish_multiplier(self):
        repo = MemoryBuffRepository()
        effect = ElectricFishSuccessBoostEffect(buff_repo=repo)
        user = SimpleNamespace(user_id="user-1")
        item = SimpleNamespace(name="雷鸣护符")

        result = effect.apply(
            user,
            item,
            {
                "bonus_rate": 0.2,
                "max_rate": 1.0,
                "fish_count_multiplier": 1.1,
            },
            quantity=2,
        )

        self.assertFalse(result["success"])
        self.assertIsNone(repo.buff)

        result = effect.apply(
            user,
            item,
            {
                "bonus_rate": 0.2,
                "max_rate": 1.0,
                "fish_count_multiplier": 1.1,
            },
        )
        self.assertTrue(result["success"])
        self.assertEqual(
            json.loads(repo.buff.payload)["fish_count_multiplier"], 1.1
        )

    def test_sqlite_consume_is_compare_and_delete_on_last_charge(self):
        repo = SqliteUserBuffRepository(":memory:")
        connection = repo._get_connection()
        connection.execute(
            "CREATE TABLE user_buffs (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, buff_type TEXT NOT NULL, payload TEXT, started_at TIMESTAMP, expires_at TIMESTAMP)"
        )
        connection.execute("CREATE INDEX idx_user_buffs_user_id ON user_buffs(user_id)")
        connection.commit()

        buff = UserBuff(
            id=0,
            user_id="user-1",
            buff_type="ELECTRIC_FISH_SUCCESS_BOOST",
            payload=json.dumps(
                {
                    "bonus_rate": 0.2,
                    "max_rate": 1.0,
                    "fish_count_multiplier": 1.1,
                }
            ),
            started_at=datetime.now(),
            expires_at=None,
        )
        repo.add(buff)

        stored_buff = repo.get_active_by_user_and_type(
            "user-1", "ELECTRIC_FISH_SUCCESS_BOOST"
        )
        self.assertIsNotNone(stored_buff)
        self.assertTrue(
            repo.consume_charge_if_match(stored_buff.id, stored_buff.payload, None)
        )
        self.assertFalse(
            repo.consume_charge_if_match(stored_buff.id, stored_buff.payload, None)
        )
        self.assertIsNone(
            repo.get_active_by_user_and_type(
                "user-1", "ELECTRIC_FISH_SUCCESS_BOOST"
            )
        )
        connection.close()


if __name__ == "__main__":
    unittest.main()
