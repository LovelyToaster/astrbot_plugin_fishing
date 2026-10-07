import unittest
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import patch

from tests.test_hextech_expansion_games import make_service, make_user, GAME_SERVICE_MODULE
from tests.test_hextech_steal_cooldown import state_data
from astrbot_plugin_fishing.core.utils import format_remaining_time, get_now
from astrbot_plugin_fishing.core.domain.models import User


class PlayerTimeMessageTests(unittest.TestCase):
    def test_duration_boundaries(self):
        for seconds, expected in ((0, "0秒"), (0.2, "1秒"), (59, "59秒"),
                                  (59.2, "1分钟"), (61, "1分钟1秒"),
                                  (10000, "2小时46分钟40秒")):
            with self.subTest(seconds=seconds):
                self.assertEqual(format_remaining_time(seconds), expected)

    def test_actions_report_positive_subminute_remaining_time(self):
        now = get_now()
        for action, field, cooldown in (("steal_fish", "last_steal_time", 10800),
                                        ("electric_fish", "last_electric_fish_time", 7200)):
            for remaining in (59, 0.2):
                user = make_user("player", **{field: now - timedelta(seconds=cooldown-remaining)})
                service = make_service([user, make_user("victim")],
                                       config={"steal": {"cooldown_seconds": 10800},
                                               "electric_fish": {"cooldown_seconds": 7200}})
                with patch(GAME_SERVICE_MODULE + ".get_now", return_value=now):
                    result = getattr(service, action)("player", "victim")
                self.assertFalse(result["success"])
                self.assertIn("59秒" if remaining == 59 else "1秒", result["message"])

    def test_electric_status_rounds_up_until_expiry(self):
        now = get_now()
        user = User("player", now, "player")
        user.fishing_zone_id = None
        inventory = SimpleNamespace(get_user_equipped_rod=lambda _: None,
                                    get_user_equipped_accessory=lambda _: None,
                                    get_fish_inventory=lambda _: [])
        for remaining, expected in ((0.2, 1), (0, 0)):
            user.last_electric_fish_time = now - timedelta(seconds=7200-remaining)
            with patch("astrbot_plugin_fishing.core.utils.get_now", return_value=now):
                result = state_data(SimpleNamespace(get_by_id=lambda _: user), inventory,
                                    SimpleNamespace(), SimpleNamespace(has_checked_in=lambda *_: False),
                                    SimpleNamespace(get_active_by_user_and_type=lambda *_: None),
                                    {"electric_fish": {"cooldown_seconds": 7200}}, "player")
            self.assertEqual(result["electric_fish_cooldown_remaining"], expected)

    def test_protection_prompt_and_expiry_share_configured_timeout(self):
        now = get_now()
        for timeout in (15, 120):
            user = make_user("player", in_wheel_of_fate=True, wof_entry_fee=500,
                             wof_current_prize=500, wof_last_action_time=now)
            service = make_service([user])
            service.WHEEL_OF_FATE_CONFIG = dict(service.WHEEL_OF_FATE_CONFIG,
                                               timeout_seconds=timeout)
            service.item_template_repo.get_all_items = lambda: [
                SimpleNamespace(item_id=1, name="逆转天平", effect_type="WOF_PROTECTION")]
            service.inventory_repo.get_user_item_inventory = lambda _: {1: 1}
            with patch(GAME_SERVICE_MODULE + ".get_now", return_value=now), \
                    patch(GAME_SERVICE_MODULE + ".random.random", return_value=1):
                result = service.continue_wheel_of_fate("player")
            self.assertIn(f"请在{timeout}秒内选择", result["message"])
            self.assertTrue(service._wof_pending_protection["player"])
            with patch(GAME_SERVICE_MODULE + ".get_now", return_value=now + timedelta(seconds=timeout-1)):
                self.assertIsNone(service.handle_wof_timeout("player"))
            with patch(GAME_SERVICE_MODULE + ".get_now", return_value=now + timedelta(seconds=timeout+1)):
                self.assertEqual(service.handle_wof_timeout("player")["status"], "timed_out")
            self.assertFalse(user.in_wheel_of_fate)


if __name__ == "__main__":
    unittest.main()
