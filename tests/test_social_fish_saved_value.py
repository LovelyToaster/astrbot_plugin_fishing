import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_hextech_expansion_games import make_service, make_user, card, GAME_SERVICE_MODULE
from astrbot_plugin_fishing.core.repositories.sqlite_inventory_repo import SqliteInventoryRepository


class SocialSavedValueTests(unittest.TestCase):
    def make_game(self, rows, selected=None):
        return make_service([make_user("actor"), make_user("target")], {"target": rows},
                            [SimpleNamespace(fish_id=1, name="鱼", base_value=100, rarity=2)], selected)

    def test_steal_preserves_saved_hextech_price_despite_equipment_change(self):
        row = SimpleNamespace(fish_id=1, quality_level=0, quantity=1, unit_value=160)
        game = self.make_game([row])
        lookups = []
        game.hextech_service = SimpleNamespace(get_selected_card=lambda user: lookups.append(user) or None)
        with patch(GAME_SERVICE_MODULE + ".random.choice", return_value=row), \
                patch(GAME_SERVICE_MODULE + ".get_user_coins_chance_by_repo", return_value=9):
            result = game.steal_fish("actor", "target")
        self.assertTrue(result["success"])
        self.assertIn("价值 160 金币", result["message"])
        self.assertEqual(game.inventory_repo.added[0][-1], 160)
        self.assertEqual(game.inventory_repo.removed[0][-1], 160)
        self.assertEqual(result["victim_notification"]["value"], 160)
        self.assertEqual(lookups, ["actor"])

    def test_quality_upgrade_doubles_saved_price_but_reports_original_victim_loss(self):
        row = SimpleNamespace(fish_id=1, quality_level=0, quantity=1, unit_value=160)
        game = self.make_game([row], card("C22", chance=1, ev_budget=.05))
        with patch(GAME_SERVICE_MODULE + ".random.choice", return_value=row), \
                patch(GAME_SERVICE_MODULE + ".random.random", return_value=0):
            result = game.steal_fish("actor", "target")
        self.assertEqual(game.inventory_repo.added[0][3:], (1, 320))
        self.assertEqual(game.inventory_repo.removed[0][3:], (0, 160))
        self.assertEqual(result["hextech_bonus_value"], 160)
        self.assertEqual(result["victim_notification"]["value"], 160)

    def test_legacy_without_saved_price_keeps_fallback(self):
        row = SimpleNamespace(fish_id=1, quality_level=0, quantity=1, unit_value=0)
        game = self.make_game([row])
        with patch(GAME_SERVICE_MODULE + ".random.choice", return_value=row), \
                patch(GAME_SERVICE_MODULE + ".get_user_coins_chance_by_repo", return_value=.5):
            result = game.steal_fish("actor", "target")
        self.assertEqual(game.inventory_repo.added[0][-1], 150)
        self.assertIn("价值 150 金币", result["message"])

    def test_electric_transfers_the_selected_price_batch_in_real_sqlite(self):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "fish.db")
            con = sqlite3.connect(path)
            with con:
                con.execute("CREATE TABLE user_fish_inventory(user_id TEXT,fish_id INTEGER,quality_level INTEGER,unit_value INTEGER,quantity INTEGER,PRIMARY KEY(user_id,fish_id,quality_level,unit_value))")
                con.executemany("INSERT INTO user_fish_inventory VALUES ('target',1,0,?,60)", [(100,), (160,)])
            con.close()
            repo = SqliteInventoryRepository(path)
            try:
                game = self.make_game([])
                for method in ("get_fish_inventory", "update_fish_quantity", "add_fish_to_inventory"):
                    setattr(game.inventory_repo, method, getattr(repo, method))
                with patch(GAME_SERVICE_MODULE + ".random.random", return_value=0), \
                        patch(GAME_SERVICE_MODULE + ".random.randint", return_value=20), \
                        patch(GAME_SERVICE_MODULE + ".random.sample", side_effect=lambda population, n: sorted(population, key=lambda row: row[2], reverse=True)[:n]), \
                        patch(GAME_SERVICE_MODULE + ".get_user_coins_chance_by_repo", return_value=9):
                    result = game.electric_fish("actor", "target")
                self.assertTrue(result["success"])
                self.assertIn("总价值 3200 金币", result["message"])
                target = {row.unit_value: row.quantity for row in repo.get_fish_inventory("target")}
                received = [(row.unit_value, row.quantity) for row in repo.get_fish_inventory("actor")]
                self.assertEqual(target, {100: 60, 160: 40})
                self.assertEqual(received, [(160, 20)])
                self.assertEqual(result["victim_notification"]["total_value"], 3200)
            finally:
                repo._connection_manager.close_connection()

    def test_g12_distinguishes_prices_of_same_species_and_quality(self):
        rows = [SimpleNamespace(fish_id=1, quality_level=0, quantity=60, unit_value=value) for value in (100, 160)]
        game = self.make_game(rows, card("G12", tier="gold", chance=1, ev_budget=.065))
        with patch(GAME_SERVICE_MODULE + ".random.random", return_value=0), \
                patch(GAME_SERVICE_MODULE + ".random.randint", return_value=20), \
                patch(GAME_SERVICE_MODULE + ".random.sample", side_effect=lambda population, n: population[:n]), \
                patch(GAME_SERVICE_MODULE + ".random.choice", side_effect=lambda population: population[-1]):
            result = game.electric_fish("actor", "target")
        self.assertTrue(result["success"])
        self.assertEqual(result["hextech_value_gain"], 60)
        self.assertEqual({row[-1]: row[2] for row in game.inventory_repo.added}, {100: 19, 160: 1})
        self.assertEqual({row[-1]: -row[2] for row in game.inventory_repo.removed}, {100: 19, 160: 1})
        self.assertEqual(result["victim_notification"]["total_value"], 2060)


if __name__ == "__main__":
    unittest.main()
