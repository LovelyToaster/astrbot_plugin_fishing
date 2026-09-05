import asyncio
import os
import sqlite3
import sys
import tempfile
import time
import types
import unittest
from datetime import date, timedelta
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

from core.domain.models import Fish, Rod, Bait, Accessory, Title, Item, User
from core.repositories.sqlite_item_template_repo import SqliteItemTemplateRepository
from core.services.user_service import UserService
from core.services.achievement_service import AchievementService
from draw.utils import run_in_thread, async_save_image
from PIL import Image


class PerformanceOptimizationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = str(Path(self.temp_dir.name) / "perf_test.db")
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript("""
                CREATE TABLE fish (
                    fish_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    rarity INTEGER NOT NULL,
                    base_value INTEGER NOT NULL,
                    min_weight REAL NOT NULL,
                    max_weight REAL NOT NULL,
                    icon_url TEXT
                );
                CREATE TABLE rods (
                    rod_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    rarity INTEGER NOT NULL,
                    source TEXT,
                    purchase_cost INTEGER,
                    bonus_fish_quality_modifier REAL,
                    bonus_fish_quantity_modifier REAL,
                    bonus_rare_fish_chance REAL,
                    durability INTEGER,
                    icon_url TEXT
                );
                CREATE TABLE baits (
                    bait_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    rarity INTEGER NOT NULL,
                    effect_description TEXT,
                    duration_minutes INTEGER,
                    cost INTEGER,
                    required_rod_rarity INTEGER,
                    success_rate_modifier REAL,
                    rare_chance_modifier REAL,
                    garbage_reduction_modifier REAL,
                    value_modifier REAL,
                    quantity_modifier REAL,
                    is_consumable INTEGER
                );
                CREATE TABLE accessories (
                    accessory_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    rarity INTEGER NOT NULL,
                    slot_type TEXT,
                    bonus_fish_quality_modifier REAL,
                    bonus_fish_quantity_modifier REAL,
                    bonus_rare_fish_chance REAL,
                    bonus_coin_modifier REAL,
                    other_bonus_description TEXT,
                    icon_url TEXT
                );
                CREATE TABLE titles (
                    title_id INTEGER PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    display_format TEXT
                );
                CREATE TABLE items (
                    item_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT,
                    rarity INTEGER NOT NULL,
                    effect_description TEXT,
                    cost INTEGER NOT NULL,
                    is_consumable INTEGER NOT NULL,
                    icon_url TEXT,
                    effect_type TEXT,
                    effect_payload TEXT
                );
                CREATE TABLE check_ins (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id TEXT NOT NULL,
                    check_in_date DATE NOT NULL,
                    UNIQUE(user_id, check_in_date)
                );
                CREATE TABLE users (
                    user_id TEXT PRIMARY KEY,
                    nickname TEXT,
                    coins INTEGER DEFAULT 0,
                    diamonds INTEGER DEFAULT 0,
                    premium_currency INTEGER DEFAULT 0,
                    consecutive_login_days INTEGER DEFAULT 0,
                    last_login_time TIMESTAMP,
                    is_ai INTEGER DEFAULT 0
                );
            """)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_item_template_caching(self):
        """测试模板仓储的内存缓存与失效"""
        repo = SqliteItemTemplateRepository(self.db_path)

        # 插入测试鱼
        repo.add_fish_template({
            "name": "金枪鱼",
            "description": "美味的海鱼",
            "rarity": 4,
            "base_value": 500,
            "min_weight": 1000.0,
            "max_weight": 50000.0,
            "icon_url": None
        })

        # 第一次查询（查库回填缓存）
        fish1 = repo.get_fish_by_id(1)
        self.assertIsNotNone(fish1)
        self.assertEqual(fish1.name, "金枪鱼")
        self.assertIn(1, repo._fish_cache)

        # 第二次查询：10000次查询应极速完成（全走内存字典）
        t0 = time.perf_counter()
        for _ in range(10000):
            f = repo.get_fish_by_id(1)
            self.assertEqual(f.name, "金枪鱼")
        t_elapsed = time.perf_counter() - t0
        self.assertLess(t_elapsed, 0.1, f"10000 次查询耗时过长: {t_elapsed:.4f}s")

        # 测试更新后缓存自动失效
        repo.update_fish_template(1, {
            "name": "超级金枪鱼",
            "description": "传说中的海鱼",
            "rarity": 5,
            "base_value": 2000,
            "min_weight": 2000.0,
            "max_weight": 80000.0,
            "icon_url": None
        })
        self.assertEqual(len(repo._fish_cache), 0)
        fish_updated = repo.get_fish_by_id(1)
        self.assertEqual(fish_updated.name, "超级金枪鱼")

    def test_recalculate_consecutive_days_single_query(self):
        """测试优化后的连续天数计算"""
        from core.repositories.sqlite_log_repo import SqliteLogRepository
        log_repo = SqliteLogRepository(self.db_path)
        
        today = date.today()
        user_id = "test_user_consecutive"

        # 模拟签到过去连续 5 天（包含昨天、前天等）
        with sqlite3.connect(self.db_path) as conn:
            for i in range(1, 6):
                d = today - timedelta(days=i)
                if d.month == today.month:
                    conn.execute("INSERT INTO check_ins (user_id, check_in_date) VALUES (?, ?)", (user_id, d))

        user_service = UserService(
            user_repo=None,
            log_repo=log_repo,
            inventory_repo=None,
            item_template_repo=None,
            gacha_service=None,
            config={},
            achievement_repo=None
        )

        consecutive = user_service._recalculate_consecutive_days(user_id)
        # 连续天数应正确计算
        expected_days = min(5, today.day - 1)
        self.assertEqual(consecutive, expected_days)

    def test_achievement_service_startup_delay_and_stop(self):
        """测试成就系统后台线程的延时与优雅停止"""
        ach_service = AchievementService(
            achievement_repo=None,
            user_repo=None,
            inventory_repo=None,
            item_template_repo=None,
            log_repo=None
        )

        ach_service.start_achievement_check_task()
        self.assertTrue(ach_service.achievement_check_running)
        self.assertTrue(ach_service.achievement_check_thread.is_alive())

        # 测试毫秒级优雅退出（不阻塞120秒延时或600秒轮询）
        t0 = time.perf_counter()
        ach_service.stop_achievement_check_task()
        t_stop = time.perf_counter() - t0
        self.assertFalse(ach_service.achievement_check_running)
        self.assertLess(t_stop, 0.5, f"线程停止耗时过长: {t_stop:.4f}s")

    def test_async_save_image_non_blocking(self):
        """测试异步图片保存 helper"""
        async def _test():
            img = Image.new("RGB", (100, 100), color=(255, 0, 0))
            out_file = os.path.join(self.temp_dir.name, "test_async_save.png")
            res = await async_save_image(img, out_file, compress_level=1)
            self.assertEqual(res, out_file)
            self.assertTrue(os.path.exists(out_file))

        asyncio.run(_test())


if __name__ == "__main__":
    unittest.main()
