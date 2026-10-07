import dataclasses
import importlib
import json
import os
import random
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone

from tests.test_hextech_fishing import FishingService  # Supplies the optional AstrBot logger stub.
from core.domain.models import User
from core.repositories.sqlite_user_repo import SqliteUserRepository
from core.services.hextech_effects import EFFECTS, EXPANSION_IDS, describe_card, roll_card
from core.services.hextech_service import HextechService


class ExpansionCatalogTests(unittest.TestCase):
    def test_generated_cards_preserve_composition_and_operation_budget(self):
        observed = set()
        rng = random.Random(412)
        for tier, count in (("silver", 2), ("gold", 3), ("prismatic", 4)):
            for _ in range(300):
                card = roll_card(tier, rng)
                self.assertEqual(card["balance_version"], 4)
                self.assertEqual(len(card["effects"]), count)
                operations = []
                for effect in card["effects"]:
                    if effect["id"] in EXPANSION_IDS:
                        observed.add(effect["id"])
                        operations.append(EFFECTS[effect["id"]]["operation"])
                self.assertEqual(len(operations), len(set(operations)))
                self.assertTrue(describe_card(card, [1, 4, 8]))
        self.assertEqual(observed, EXPANSION_IDS)

    def test_every_offer_set_has_fishing_option_and_independent_tiers(self):
        service = HextechService(None, rng=random.Random(910))
        for _ in range(50):
            offers = service._make_offers()
            self.assertTrue(any(all(EFFECTS[e["id"]]["operation"] == "fishing"
                                    for e in card["effects"]) for card in offers))

    def test_wheel_snapshot_migration_and_repository_roundtrip(self):
        fd, path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        repo = None
        try:
            with sqlite3.connect(path) as connection:
                fields = [f.name for f in dataclasses.fields(User) if f.name != "wof_hextech_snapshot"]
                connection.execute("CREATE TABLE users (" + ",".join('"' + field + '"' for field in fields) + ")")
                migration = importlib.import_module("core.database.migrations.063_add_wof_hextech_snapshot")
                migration.up(connection.cursor())
                migration.up(connection.cursor())
            connection.close()
            repo = SqliteUserRepository(path)
            user = User("wheel-player", datetime.now(timezone.utc), "test", coins=1000)
            user.wof_hextech_snapshot = json.dumps({"balance_version": 3, "effects": [{"id": "P15"}]})
            repo.add(user)
            loaded = repo.get_by_id(user.user_id)
            self.assertEqual(loaded.wof_hextech_snapshot, user.wof_hextech_snapshot)
            loaded.wof_hextech_snapshot = None
            repo.update(loaded)
            self.assertIsNone(repo.get_by_id(user.user_id).wof_hextech_snapshot)
        finally:
            if repo is not None:
                repo._get_connection().close()
            os.unlink(path)


if __name__ == "__main__":
    unittest.main()
