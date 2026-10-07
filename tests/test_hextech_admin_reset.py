import ast
import importlib
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from core.repositories.sqlite_hextech_repo import SqliteHextechRepository
from core.services.hextech_service import HextechService


# Execute the real command method without importing AstrBot's full runtime.
source = ast.parse((Path(__file__).parents[1] / "main.py").read_text(encoding="utf-8"))
plugin = next(node for node in source.body if isinstance(node, ast.ClassDef) and node.name == "FishingPlugin")
handler_node = next(node for node in plugin.body if isinstance(node, ast.AsyncFunctionDef) and node.name == "hextech")
handler_node.decorator_list = []
namespace = {"AstrMessageEvent": object, "logger": SimpleNamespace(info=Mock(), error=Mock())}
exec(compile(ast.Module(body=[handler_node], type_ignores=[]), "main.py", "exec"), namespace)
handler = namespace["hextech"]


class ResetRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.path = str(Path(self.directory.name) / "fish.db")
        with sqlite3.connect(self.path) as connection:
            importlib.import_module("core.database.migrations.062_add_hextech_daily").up(connection.cursor())
            connection.execute("CREATE TABLE users(user_id TEXT PRIMARY KEY, coins INTEGER, in_wheel_of_fate INTEGER, wof_hextech_snapshot TEXT)")
            connection.execute("INSERT INTO users VALUES ('a',10000,1,'{\"balance_version\":3}')")
            connection.execute("INSERT INTO users VALUES ('b',5000,0,NULL)")
        connection.close()
        self.repo = SqliteHextechRepository(self.path)
        self.now = datetime(2026, 10, 1, 12, tzinfo=timezone(timedelta(hours=8)))
        self.service = HextechService(self.repo, clock=lambda: self.now)
        self.service.ensure_daily_state("a")
        self.service.choose("a", 1)
        self.now += timedelta(days=1)
        self.service.ensure_daily_state("a")
        self.service.ensure_daily_state("b")
        self.service.reroll("b")
        self.service.reroll("b")

    def tearDown(self):
        self.repo._get_connection().close()
        self.directory.cleanup()

    def test_reset_clears_history_refreshes_and_wheel_effect_only(self):
        result = self.service.reset_all_users()
        self.assertEqual(result, {"users": 2, "records": 3, "wheel_snapshots": 1})
        for actor in ("a", "b"):
            self.assertIsNone(self.service.get_selected_card(actor))
            self.assertIsNone(self.service.get_daily_state(actor))
        user = self.repo._get_connection().execute("SELECT coins,in_wheel_of_fate,wof_hextech_snapshot FROM users WHERE user_id='a'").fetchone()
        self.assertEqual(tuple(user), (10000, 1, None))
        state, created = self.service.ensure_daily_state("b")
        self.assertTrue(created)
        self.assertEqual(state["reroll_count"], 0)
        self.assertIsNone(state["selected_index"])
        self.assertTrue(all(card["balance_version"] == 4 for card in state["offers"]))
        self.assertEqual(self.service.reroll("b")[1], "rerolled")
        self.assertEqual(self.service.reroll("b")[1], "rerolled")
        self.assertEqual(self.service.reroll("b")[1], "limit_reached")

    def test_failed_reset_rolls_back_deleted_cards(self):
        connection = self.repo._get_connection()
        with connection:
            connection.execute("CREATE TRIGGER deny_reset BEFORE UPDATE ON users BEGIN SELECT RAISE(ABORT,'blocked'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.service.reset_all_users()
        self.assertEqual(connection.execute("SELECT count(*) FROM hextech_daily_choices").fetchone()[0], 3)
        self.assertIsNotNone(connection.execute("SELECT wof_hextech_snapshot FROM users WHERE user_id='a'").fetchone()[0])


class ResetCommandTests(unittest.IsolatedAsyncioTestCase):
    async def invoke(self, admin, text="/海克斯 重置"):
        service = SimpleNamespace(reset_all_users=Mock(return_value={"users": 2}))
        plugin = SimpleNamespace(hextech_service=service, _get_effective_user_id=Mock(return_value="proxy"))
        event = SimpleNamespace(message_str=text, is_admin=lambda: admin,
                                get_sender_id=lambda: "real-sender", plain_result=lambda text: text)
        replies = [reply async for reply in handler(plugin, event)]
        return service, plugin, replies

    async def test_nonadmin_cannot_reset_even_with_proxy(self):
        service, plugin, replies = await self.invoke(False)
        service.reset_all_users.assert_not_called()
        plugin._get_effective_user_id.assert_not_called()
        self.assertIn("只有管理员", replies[0])

    async def test_admin_resets_once_without_creating_own_offer(self):
        service, plugin, replies = await self.invoke(True)
        service.reset_all_users.assert_called_once_with()
        plugin._get_effective_user_id.assert_not_called()
        self.assertIn("涉及 2 位用户", replies[0])
        self.assertIn("免费刷新恢复为2次", replies[0])

    async def test_extra_arguments_do_not_reset(self):
        service, _, replies = await self.invoke(True, "/海克斯 重置 extra")
        service.reset_all_users.assert_not_called()
        self.assertIn("用法", replies[0])

    async def test_reset_failure_reports_failure(self):
        service = SimpleNamespace(reset_all_users=Mock(side_effect=RuntimeError("failure")))
        plugin = SimpleNamespace(hextech_service=service)
        event = SimpleNamespace(message_str="/海克斯 重置", is_admin=lambda: True,
                                get_sender_id=lambda: "admin", plain_result=lambda text: text)
        replies = [reply async for reply in handler(plugin, event)]
        self.assertIn("重置失败", replies[0])


if __name__ == "__main__":
    unittest.main()
