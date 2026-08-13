import sys
import types
import unittest
from types import SimpleNamespace


# 本插件运行时由 AstrBot 提供 logger；策略纯逻辑测试不需要完整运行时。
if "astrbot" not in sys.modules:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    api.logger = types.SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        info=lambda *args, **kwargs: None,
        warning=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )
    astrbot.api = api
    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api

from core.services.ai.gacha_strategy import GachaStrategy
from core.services.ai.item_strategy import AIItemStrategy
from core.services.ai.target_strategy import SocialTargetScorer


class StatsStub:
    def get_user_action_counts_in_window(self, action_type, hours):
        return {"revenge": 5, "other": 1}

    def get_victim_counts_in_window(self, action_type, hours):
        return {"other": 6}

    def get_actor_target_counts_in_window(self, actor_id, action_type, hours):
        return {"revenge": 2}

    def get_incoming_attacker_counts(self, victim_id, action_type, hours):
        return {"revenge": 2}

    def get_top_attacker_of(self, target_id, action_type, hours):
        return "revenge"

    def get_target_success_rates(self, action_type, hours):
        return {"revenge": (5, 4), "other": (5, 2)}


class ItemStrategyStub:
    def estimate_social_item_cost(self, operation, features):
        return 0

    def can_handle_protection(self, operation, features):
        return False


class ContextStub:
    def __init__(self, candidates):
        self.ai_user_id = "AI"
        self.ai_user = SimpleNamespace(coins=100000)
        self.global_config = {"electric_fish": {"base_success_rate": 0.6}}
        self.statistics_repo = StatsStub()
        self.item_strategy = ItemStrategyStub()
        self._candidates = candidates

    def get_candidates(self):
        return self._candidates


class GachaContextStub:
    def __init__(self):
        self.ai_user_id = "AI"
        self.inventory_repo = SimpleNamespace(
            get_user_item_inventory=lambda user_id: {},
            get_user_bait_inventory=lambda user_id: {},
        )
        self.inventory_service = SimpleNamespace(
            get_user_rod_inventory=lambda user_id: {"rods": []},
            get_user_accessory_inventory=lambda user_id: {"accessories": []},
        )
        self.item_template_repo = SimpleNamespace()
        self.gacha_service = SimpleNamespace(
            pity_threshold=80,
            gacha_repo=SimpleNamespace(
                get_user_pity=lambda user_id, pool_id: None
            ),
        )


class AIStrategyTests(unittest.TestCase):
    def test_revenge_pressure_is_present_and_protected_targets_are_filtered(self):
        ctx = ContextStub(
            [
                (
                    "revenge",
                    {
                        "target_fish_count": 200,
                        "target_fish_value": 100000,
                        "target_actor_count": 5,
                        "target_ai_action_count": 0,
                        "target_protection_layers": 0,
                    },
                ),
                (
                    "protected",
                    {
                        "target_fish_count": 200,
                        "target_fish_value": 200000,
                        "target_protection_layers": 1,
                    },
                ),
            ]
        )
        scores = SocialTargetScorer(ctx).score("electric_fish", 100)
        self.assertEqual([score.target_id for score in scores], ["revenge"])
        self.assertGreater(scores[0].revenge_pressure, 0.5)
        self.assertGreater(scores[0].expected_net_value, 0)

    def test_dynamic_coin_reserve_respects_refine_floor(self):
        ctx = SimpleNamespace(
            ai_user_id="AI",
            ai_user=SimpleNamespace(coins=100000),
            inventory_repo=SimpleNamespace(
                get_zone_by_id=lambda zone_id: SimpleNamespace(fishing_cost=30),
                get_user_item_inventory=lambda user_id: {},
                get_fish_inventory=lambda user_id: [],
            ),
            item_template_repo=SimpleNamespace(get_all_items=lambda: []),
            global_config={"fishing": {"cooldown_seconds": 180}},
            ai_config={"refine_reserve_coins": 200000},
        )
        self.assertEqual(AIItemStrategy(ctx).coin_reserve(), 200000)

    def test_gacha_uses_real_coin_value_instead_of_rarity_only(self):
        ctx = GachaContextStub()
        strategy = GachaStrategy(ctx)
        cheap = SimpleNamespace(
            gacha_pool_id=1,
            cost_coins=5000,
            cost_premium_currency=0,
            items=[SimpleNamespace(item_type="coins", item_id=0, quantity=10000, weight=1)],
        )
        expensive = SimpleNamespace(
            gacha_pool_id=2,
            cost_coins=30000,
            cost_premium_currency=0,
            items=[SimpleNamespace(item_type="coins", item_id=0, quantity=100000, weight=1)],
        )
        selected = strategy.choose([cheap, expensive])
        self.assertIsNotNone(selected)
        self.assertEqual(selected[0].gacha_pool_id, 2)
        self.assertGreater(selected[1]["expected_value"], selected[1]["cost"])


if __name__ == "__main__":
    unittest.main()
