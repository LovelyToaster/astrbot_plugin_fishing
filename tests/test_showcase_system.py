import sqlite3
import sys
import tempfile
import types
import unittest
from pathlib import Path
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

# InventoryService only needs the class annotation at import time for this
# focused test; avoid pulling the optional requests dependency into the test.
if "core.services.game_mechanics_service" not in sys.modules:
    game_mechanics = types.ModuleType("core.services.game_mechanics_service")
    game_mechanics.GameMechanicsService = object
    sys.modules["core.services.game_mechanics_service"] = game_mechanics


from core.repositories.sqlite_inventory_repo import SqliteInventoryRepository
from core.services.inventory_service import InventoryService
from core.services.showcase_service import ShowcaseService


class ShowcaseRepositoryTests(unittest.TestCase):
    def setUp(self):
        # SQLite WAL can keep the database handle alive briefly on Windows;
        # ignore cleanup races because the OS releases the temp file at exit.
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self.temp_dir.name) / "showcase.db")
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            conn.executescript(
                """
                CREATE TABLE user_showcase (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    item_type TEXT NOT NULL,
                    instance_id INTEGER NOT NULL,
                    slot_index INTEGER NOT NULL,
                    locked_before INTEGER NOT NULL DEFAULT 0,
                    theme TEXT NOT NULL DEFAULT 'ocean',
                    added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(user_id, item_type, instance_id),
                    UNIQUE(user_id, slot_index)
                );
                CREATE TABLE user_showcase_slot_settings (
                    user_id TEXT NOT NULL,
                    slot_index INTEGER NOT NULL,
                    theme TEXT NOT NULL DEFAULT 'ocean',
                    PRIMARY KEY (user_id, slot_index)
                );
                CREATE TABLE user_rods (
                    rod_instance_id INTEGER PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    rod_id INTEGER NOT NULL,
                    is_equipped INTEGER NOT NULL DEFAULT 0,
                    obtained_at TIMESTAMP,
                    refine_level INTEGER NOT NULL DEFAULT 1,
                    current_durability INTEGER,
                    is_locked INTEGER NOT NULL DEFAULT 0,
                    is_in_showcase INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE user_accessories (
                    accessory_instance_id INTEGER PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    accessory_id INTEGER NOT NULL,
                    is_equipped INTEGER NOT NULL DEFAULT 0,
                    obtained_at TIMESTAMP,
                    refine_level INTEGER NOT NULL DEFAULT 1,
                    is_locked INTEGER NOT NULL DEFAULT 0,
                    is_in_showcase INTEGER NOT NULL DEFAULT 0
                );
                INSERT INTO user_rods
                    (rod_instance_id, user_id, rod_id, obtained_at)
                VALUES (1, 'u1', 10, CURRENT_TIMESTAMP);
                INSERT INTO user_rods
                    (rod_instance_id, user_id, rod_id, is_locked, obtained_at)
                VALUES (2, 'u1', 10, 1, CURRENT_TIMESTAMP);
                """
            )
        self.repo = SqliteInventoryRepository(self.db_path)

    def tearDown(self):
        manager = self.repo._connection_manager
        connection = getattr(manager._local, "connection", None)
        if connection is not None:
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        manager.close_connection()
        self.temp_dir.cleanup()

    def test_showcase_round_trip_hides_then_restores_backpack_item(self):
        self.assertTrue(self.repo.add_to_showcase("u1", "rod", 1, 0))
        rod = self.repo.get_user_rod_instance_by_id("u1", 1)
        self.assertTrue(rod.is_in_showcase)
        self.assertTrue(rod.is_locked)

        self.assertTrue(self.repo.remove_from_showcase("u1", "rod", 1))
        rod = self.repo.get_user_rod_instance_by_id("u1", 1)
        self.assertFalse(rod.is_in_showcase)
        self.assertFalse(rod.is_locked)

    def test_showcase_round_trip_preserves_manual_lock(self):
        self.assertTrue(self.repo.add_to_showcase("u1", "rod", 2, 0))
        self.assertTrue(self.repo.remove_from_showcase("u1", "rod", 2))
        rod = self.repo.get_user_rod_instance_by_id("u1", 2)
        self.assertFalse(rod.is_in_showcase)
        self.assertTrue(rod.is_locked)

    def test_deleting_an_instance_removes_showcase_relation(self):
        self.assertTrue(self.repo.add_to_showcase("u1", "rod", 1, 0))
        self.repo.delete_rod_instance(1)
        self.assertEqual(self.repo.get_user_showcase("u1"), [])

    def test_each_showcase_slot_can_store_its_own_theme(self):
        self.assertTrue(self.repo.add_to_showcase("u1", "rod", 1, 0))
        self.assertTrue(self.repo.add_to_showcase("u1", "rod", 2, 1))
        self.assertTrue(self.repo.set_showcase_theme("u1", 0, "rose"))
        items = self.repo.get_user_showcase("u1")
        self.assertEqual([item.theme for item in items], ["rose", "ocean"])

    def test_slot_theme_survives_replacing_the_displayed_item(self):
        self.assertTrue(self.repo.set_showcase_theme("u1", 0, "midnight"))
        self.assertTrue(self.repo.add_to_showcase("u1", "rod", 1, 0))
        self.assertEqual(self.repo.get_user_showcase("u1")[0].theme, "midnight")
        self.assertTrue(self.repo.remove_from_showcase("u1", "rod", 1))
        self.assertTrue(self.repo.add_to_showcase("u1", "rod", 2, 0))
        self.assertEqual(self.repo.get_user_showcase("u1")[0].theme, "midnight")


class BackpackShowcaseFilteringTests(unittest.TestCase):
    def test_backpack_does_not_return_showcase_items(self):
        service = InventoryService.__new__(InventoryService)
        service.inventory_repo = SimpleNamespace(
            get_user_rod_instances=lambda user_id: [
                SimpleNamespace(
                    rod_instance_id=1, user_id=user_id, rod_id=10,
                    is_equipped=False, is_locked=True, is_in_showcase=True,
                    refine_level=1, current_durability=100,
                ),
                SimpleNamespace(
                    rod_instance_id=2, user_id=user_id, rod_id=10,
                    is_equipped=False, is_locked=False, is_in_showcase=False,
                    refine_level=1, current_durability=100,
                ),
            ],
            get_user_accessory_instances=lambda user_id: [
                SimpleNamespace(
                    accessory_instance_id=3, user_id=user_id, accessory_id=20,
                    is_equipped=False, is_locked=True, is_in_showcase=True,
                    refine_level=1,
                ),
                SimpleNamespace(
                    accessory_instance_id=4, user_id=user_id, accessory_id=20,
                    is_equipped=False, is_locked=False, is_in_showcase=False,
                    refine_level=1,
                ),
            ],
        )
        service.item_template_repo = SimpleNamespace(
            get_rod_by_id=lambda item_id: SimpleNamespace(
                name="测试鱼竿", rarity=3, description="", durability=100,
                bonus_fish_quality_modifier=1.1,
                bonus_fish_quantity_modifier=1.0,
                bonus_rare_fish_chance=0.0,
            ),
            get_accessory_by_id=lambda item_id: SimpleNamespace(
                name="测试饰品", rarity=3, description="",
                bonus_fish_quality_modifier=1.1,
                bonus_fish_quantity_modifier=1.0,
                bonus_rare_fish_chance=0.0,
                bonus_coin_modifier=1.0,
            ),
        )

        rods = service.get_user_rod_inventory("u1")["rods"]
        accessories = service.get_user_accessory_inventory("u1")["accessories"]
        self.assertEqual([item["instance_id"] for item in rods], [2])
        self.assertEqual([item["instance_id"] for item in accessories], [4])


class ShowcaseThemeServiceTests(unittest.TestCase):
    def test_theme_can_target_position_or_equipment_code(self):
        updated = []
        inventory_repo = SimpleNamespace(
            get_user_showcase=lambda user_id: [
                SimpleNamespace(item_type="rod", instance_id=9, slot_index=1)
            ],
            set_showcase_theme=lambda user_id, slot_index, theme: updated.append(
                (slot_index, theme)
            ) or True,
        )
        user_repo = SimpleNamespace(
            get_by_id=lambda user_id: SimpleNamespace(
                user_id=user_id, showcase_capacity=3
            )
        )
        service = ShowcaseService(inventory_repo, user_repo, SimpleNamespace())

        result = service.set_theme("u1", "1", "樱粉")
        self.assertTrue(result["success"])
        self.assertEqual(updated[-1], (0, "rose"))

        result = service.set_theme("u1", "R9", "黑金")
        self.assertTrue(result["success"])
        self.assertEqual(updated[-1], (1, "midnight"))


if __name__ == "__main__":
    unittest.main()
