import asyncio
import os
import sys
import tempfile
import types
import unittest
from dataclasses import fields
from datetime import datetime
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


from core.repositories.sqlite_statistics_repo import SqliteStatisticsRepository
from core.repositories.sqlite_user_repo import SqliteUserRepository
from core.domain.models import User
from core.services.statistics_service import get_period_range
from draw.statistics import draw_period_report_image, draw_period_report_image_async


class PeriodStatisticsTests(unittest.TestCase):
    def setUp(self):
        self.repo = SqliteStatisticsRepository(":memory:")
        conn = self.repo._get_connection()
        conn.executescript(
            """
            CREATE TABLE users (
                user_id TEXT PRIMARY KEY,
                nickname TEXT,
                is_system INTEGER DEFAULT 0
            );
            CREATE TABLE statistics_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT NOT NULL,
                target_id TEXT,
                action_type TEXT NOT NULL,
                success INTEGER NOT NULL DEFAULT 1,
                fish_count INTEGER NOT NULL DEFAULT 0,
                coin_amount INTEGER NOT NULL DEFAULT 0,
                details TEXT,
                created_at TIMESTAMP NOT NULL
            );
            """
        )
        conn.executemany(
            "INSERT INTO users(user_id, nickname, is_system) VALUES (?, ?, ?)",
            [("u1", "甲", 0), ("u2", "乙", 0), ("SYSTEM", "系统", 1)],
        )

    def test_report_aggregates_each_requested_leader(self):
        self.repo.add_log("u1", "coin_earn", coin_amount=1000)
        self.repo.add_log("u2", "coin_earn", coin_amount=2000)
        self.repo.add_log("u1", "coin_spend", coin_amount=-300)
        self.repo.add_log("u2", "coin_spend", coin_amount=-500)
        self.repo.add_log("u1", "fish", fish_count=4, coin_amount=400)
        self.repo.add_log("u2", "fish", fish_count=2, coin_amount=1000)
        self.repo.add_log("u1", "steal", fish_count=4, coin_amount=80)
        self.repo.add_log("u2", "steal", fish_count=1, coin_amount=20)
        self.repo.add_log("u2", "electric_fish", fish_count=3, coin_amount=120)

        start, end = get_period_range("today")
        report = self.repo.get_period_report(start, end)

        self.assertEqual(report["coins_earned"]["nickname"], "乙")
        self.assertEqual(report["coins_spent"]["amount"], 500)
        self.assertEqual(report["coins_net"]["nickname"], "乙")
        self.assertEqual(report["coins_net"]["earned"], 2000)
        self.assertEqual(report["coins_net"]["spent"], 500)
        self.assertEqual(report["coins_net"]["amount"], 1500)
        self.assertEqual(report["fishing"]["nickname"], "甲")
        self.assertEqual(report["fishing"]["count"], 4)
        self.assertEqual(report["steal"]["nickname"], "甲")
        self.assertEqual(report["steal"]["count"], 4)
        self.assertEqual(report["electric_fish"]["nickname"], "乙")
        self.assertEqual(report["electric_fish"]["count"], 3)
        self.assertEqual(report["totals"]["fish_count"], 6)
        self.assertEqual(report["totals"]["steal_count"], 5)
        self.assertEqual(report["totals"]["electric_fish_count"], 3)

    def test_report_image_is_written(self):
        data = {
            "period_label": "今天",
            "coins_net": {
                "nickname": "甲",
                "earned": 1000,
                "spent": 300,
                "amount": 700,
            },
            "fishing": {"nickname": "甲", "count": 4, "value": 400},
            "steal": None,
            "electric_fish": None,
            "totals": {
                "coins_earned": 1000,
                "coins_spent": 0,
                "fish_count": 4,
                "steal_count": 0,
                "electric_fish_count": 0,
            },
        }
        fd, output_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        os.remove(output_path)
        try:
            draw_period_report_image(data, output_path)
            from PIL import Image

            with Image.open(output_path) as image:
                self.assertEqual(image.width, 800)
                self.assertGreater(image.height, 380)
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_async_report_fetches_avatar_before_drawing(self):
        data = {
            "period_label": "今天",
            "coins_earned": {"user_id": "u1", "nickname": "甲", "amount": 100},
            "coins_spent": None,
            "fishing": {"user_id": "u1", "nickname": "甲", "count": 2, "value": 50},
            "steal": None,
            "electric_fish": None,
        }
        fd, output_path = tempfile.mkstemp(suffix=".png")
        os.close(fd)
        os.remove(output_path)
        calls = []

        async def fake_get_user_avatar(user_id, data_dir, avatar_size, avatar_config):
            calls.append((user_id, data_dir, avatar_size, avatar_config))
            from PIL import Image

            return Image.new("RGBA", (avatar_size, avatar_size), (80, 140, 220, 255))

        try:
            with patch("draw.statistics.get_user_avatar", side_effect=fake_get_user_avatar):
                asyncio.run(
                    draw_period_report_image_async(
                        data, output_path, "avatar-data", {"source": "qq"}
                    )
                )
            self.assertEqual(len(calls), 1)
            self.assertEqual(calls[0][0], "u1")
            self.assertEqual(calls[0][1], "avatar-data")
            self.assertEqual(calls[0][2], 46)
            self.assertEqual(calls[0][3], {"source": "qq"})
        finally:
            if os.path.exists(output_path):
                os.remove(output_path)

    def test_user_repository_records_balance_delta(self):
        class StatsRecorder:
            def __init__(self):
                self.logs = []

            def add_log(self, **kwargs):
                self.logs.append(kwargs)

        stats = StatsRecorder()
        repo = SqliteUserRepository(":memory:", statistics_repo=stats)
        columns = [field.name for field in fields(User)]
        definition = ", ".join(
            ["user_id TEXT PRIMARY KEY"]
            + [f"{column} TEXT" for column in columns if column != "user_id"]
        )
        repo._get_connection().execute(f"CREATE TABLE users ({definition})")
        user = User(user_id="u1", created_at=datetime.now(), nickname="甲", coins=10)
        repo.add(user)
        user.coins = 42
        repo.update(user)

        self.assertEqual(len(stats.logs), 1)
        self.assertEqual(stats.logs[0]["action_type"], "coin_earn")
        self.assertEqual(stats.logs[0]["coin_amount"], 32)


if __name__ == "__main__":
    unittest.main()
