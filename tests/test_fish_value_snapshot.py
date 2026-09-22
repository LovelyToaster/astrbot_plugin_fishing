import os
import importlib
import sqlite3
import sys
import tempfile
import types
import unittest
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

from core.repositories.sqlite_inventory_repo import SqliteInventoryRepository


fish_value_migration = importlib.import_module(
    "core.database.migrations.061_add_fish_unit_value_snapshot"
)


class FishValueSnapshotTests(unittest.TestCase):
    def setUp(self):
        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.executescript(
            """
            CREATE TABLE users (user_id TEXT PRIMARY KEY);
            CREATE TABLE fish (fish_id INTEGER PRIMARY KEY, base_value INTEGER NOT NULL);
            CREATE TABLE user_fish_inventory (
                user_id TEXT NOT NULL,
                fish_id INTEGER NOT NULL,
                quality_level INTEGER DEFAULT 0,
                quantity INTEGER DEFAULT 0,
                no_sell_until DATETIME,
                PRIMARY KEY (user_id, fish_id, quality_level)
            );
            CREATE TABLE user_aquarium (
                user_id TEXT NOT NULL,
                fish_id INTEGER NOT NULL,
                quality_level INTEGER DEFAULT 0,
                quantity INTEGER DEFAULT 0,
                added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, fish_id, quality_level)
            );
            CREATE TABLE market (
                market_id INTEGER PRIMARY KEY AUTOINCREMENT,
                item_type TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                quality_level INTEGER DEFAULT 0
            );
            """
        )
        conn.execute("INSERT INTO users (user_id) VALUES ('u1')")
        conn.execute("INSERT INTO fish (fish_id, base_value) VALUES (1, 100)")
        conn.execute(
            "INSERT INTO user_fish_inventory (user_id, fish_id, quality_level, quantity) VALUES ('u1', 1, 0, 2)"
        )
        conn.execute(
            "INSERT INTO user_aquarium (user_id, fish_id, quality_level, quantity) VALUES ('u1', 1, 0, 1)"
        )
        conn.execute(
            "INSERT INTO market (item_type, item_id, quality_level) VALUES ('fish', 1, 0)"
        )
        fish_value_migration.up(conn.cursor())
        conn.commit()
        conn.close()
        self.repo = SqliteInventoryRepository(self.db_path)

    def tearDown(self):
        self.repo._connection_manager.close_connection()
        os.unlink(self.db_path)

    def test_migration_backfills_legacy_values_and_preserves_aquarium(self):
        pond = self.repo.get_fish_inventory("u1")
        aquarium = self.repo.get_aquarium_inventory("u1")

        self.assertEqual([(item.quantity, item.unit_value) for item in pond], [(2, 100)])
        self.assertEqual([(item.quantity, item.unit_value) for item in aquarium], [(1, 100)])
        self.assertEqual(self.repo.get_fish_inventory_value("u1"), 200)
        self.assertEqual(self.repo.get_aquarium_inventory_value("u1"), 100)

    def test_different_prices_do_not_merge_and_aquarium_round_trip_preserves_value(self):
        self.repo.add_fish_to_inventory("u1", 1, quantity=2, unit_value=150)
        pond = self.repo.get_fish_inventory("u1")
        self.assertEqual(
            sorted((item.quantity, item.unit_value) for item in pond),
            [(2, 100), (2, 150)],
        )

        self.repo.update_fish_quantity("u1", 1, -1, unit_value=150)
        self.repo.add_fish_to_aquarium("u1", 1, quantity=1, unit_value=150)
        aquarium = self.repo.get_aquarium_inventory("u1")
        self.assertEqual(sorted((item.quantity, item.unit_value) for item in aquarium), [(1, 100), (1, 150)])

        aquarium_lot = next(item for item in aquarium if item.unit_value == 150)
        self.repo.remove_fish_from_aquarium("u1", 1, 1, unit_value=aquarium_lot.unit_value)
        self.repo.add_fish_to_inventory("u1", 1, 1, unit_value=aquarium_lot.unit_value)
        pond = self.repo.get_fish_inventory("u1")
        self.assertIn((2, 150), [(item.quantity, item.unit_value) for item in pond])

if __name__ == "__main__":
    unittest.main()
