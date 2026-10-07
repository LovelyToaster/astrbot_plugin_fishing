import ast
import math
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Optional
import unittest
from unittest.mock import patch

from tests.test_hextech_expansion_games import card, make_service, make_user
from astrbot_plugin_fishing.core.domain.models import User
from astrbot_plugin_fishing.core.services.hextech_game_balance import steal_cooldown


# Load the actual data builder without image/HTTP dependencies; image rendering
# only consumes this dictionary and does not change its cooldown value.
source = ast.parse((Path(__file__).parents[1] / "draw/state.py").read_text(encoding="utf-8"))
namespace = {"__package__": "astrbot_plugin_fishing.draw", "Optional": Optional,
             "Dict": Dict, "Any": Any, "json": json, "math": math}
exec(compile(ast.Module(body=[node for node in source.body
                             if isinstance(node, ast.FunctionDef)
                             and node.name == "get_user_state_data"], type_ignores=[]),
             "draw/state.py", "exec"), namespace)
state_data = namespace["get_user_state_data"]


class StealCooldownTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 10, 1, 10, 20, tzinfo=timezone(timedelta(hours=8)))
        self.effect_card = card("C23", tier="prismatic", ev_budget=0.08,
                                cooldown_reduction=0.2405)

    def status(self, selected_card, elapsed):
        user = User("player", self.now, "player")
        user.fishing_zone_id = None
        user.last_steal_time = (self.now - timedelta(seconds=elapsed)).replace(tzinfo=None)
        inventory = SimpleNamespace(get_user_equipped_rod=lambda _: None,
                                    get_user_equipped_accessory=lambda _: None,
                                    get_fish_inventory=lambda _: [])
        with patch("astrbot_plugin_fishing.core.utils.get_now", return_value=self.now):
            return state_data(SimpleNamespace(get_by_id=lambda _: user), inventory,
                              SimpleNamespace(), SimpleNamespace(has_checked_in=lambda *_: False),
                              SimpleNamespace(get_active_by_user_and_type=lambda *_: None),
                              {"steal": {"cooldown_seconds": 10800}}, "player",
                              hextech_service=SimpleNamespace(get_selected_card=lambda _: selected_card))

    def test_status_and_action_use_the_real_user_effective_cooldown(self):
        self.assertEqual(steal_cooldown(10800, self.effect_card)[0], 10000)
        self.assertEqual(self.status(self.effect_card, 60)["steal_cooldown_remaining"], 9940)
        for elapsed, blocked in ((9999, True), (9999.8, True), (10000, False)):
            thief = make_user("player", last_steal_time=self.now - timedelta(seconds=elapsed))
            service = make_service([thief, make_user("victim")], card=self.effect_card,
                                   config={"steal": {"cooldown_seconds": 10800}})
            with patch("astrbot_plugin_fishing.core.services.game_mechanics_service.get_now",
                       return_value=self.now):
                result = service.steal_fish("player", "victim")
            self.assertEqual("偷鱼冷却中" in result["message"], blocked)
            self.assertEqual(self.status(self.effect_card, elapsed)["steal_cooldown_remaining"],
                             1 if blocked else 0)

    def test_no_effect_expired_card_and_legacy_card_keep_base_cooldown(self):
        legacy = dict(self.effect_card, balance_version=2)
        for selected in (None, legacy, card("C21")):
            with self.subTest(selected=selected):
                self.assertEqual(self.status(selected, 60)["steal_cooldown_remaining"], 10740)
        self.assertEqual(self.status(self.effect_card, 12000)["steal_cooldown_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
