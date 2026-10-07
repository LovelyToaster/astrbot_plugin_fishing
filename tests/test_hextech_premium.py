import ast
import math
import random
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# AST 解析 handlers/fishing_handlers.py 提取真实 _build_fish_message 函数节点，避免导入 AstrBot 运行环境
_handlers_file = Path(__file__).resolve().parents[1] / "handlers" / "fishing_handlers.py"
_tree = ast.parse(_handlers_file.read_text(encoding="utf-8"))
_func_node = next(
    node for node in _tree.body
    if isinstance(node, ast.FunctionDef) and node.name == "_build_fish_message"
)
_ns = {}
exec(compile(ast.Module(body=[_func_node], type_ignores=[]), "fishing_handlers.py", "exec"), _ns)
_build_fish_message = _ns["_build_fish_message"]

from tests.test_hextech_fishing import Fish, FakeUser, make_service, FishingService
from core.services.hextech_effects import (
    EFFECTS,
    PREMIUM_EFFECT_IDS,
    PREMIUM_BASE_CHANCES,
    PREMIUM_CONDITIONS,
    describe_card,
    effective_card,
    roll_card,
    _roll_params,
    _v4_params,
)


class FakeAccessory:
    def __init__(self, accessory_id, name, rarity=1):
        self.accessory_id = accessory_id
        self.name = name
        self.rarity = rarity
        self.bonus_fish_quality_modifier = 1.0
        self.bonus_fish_quantity_modifier = 1.0
        self.bonus_rare_fish_chance = 0.0
        self.bonus_coin_modifier = 1.0


class HextechPremiumTests(unittest.TestCase):
    def setUp(self):
        self.fish_pool = [
            Fish(fish_id=1, name="小鲫鱼", rarity=1, min_weight=50, max_weight=150, base_value=10),
            Fish(fish_id=2, name="鲤鱼", rarity=2, min_weight=100, max_weight=300, base_value=25),
            Fish(fish_id=3, name="草鱼", rarity=3, min_weight=200, max_weight=500, base_value=50),
            Fish(fish_id=4, name="七彩神仙鱼", rarity=4, min_weight=300, max_weight=800, base_value=200),
            Fish(fish_id=5, name="巨型金枪鱼", rarity=5, min_weight=1000, max_weight=3000, base_value=800),
        ]
        self.distribution = [0.4, 0.3, 0.15, 0.1, 0.05]

    def _make_card(self, effect_id, tier="silver", chance=None, is_gift=False):
        ch = chance if chance is not None else PREMIUM_BASE_CHANCES[effect_id]
        return {
            "tier": tier,
            "balance_version": 4,
            "effects": [
                {
                    "id": effect_id,
                    "tier": tier,
                    "params": {
                        "premium_chance": ch,
                        "premium_condition": PREMIUM_CONDITIONS[effect_id],
                        "is_gift": is_gift,
                    },
                }
            ],
        }

    # ==========================================
    # 1. 四种条件的真假判定测试
    # ==========================================
    def test_c34_condition_truth_values(self):
        """C34 瓶中微光：仅当最终钓到四星及以上稀有鱼时为真，空竿或1-3星为假"""
        card = self._make_card("C34", tier="common", chance=1.0)
        service, user, zone, _ = make_service(card, self.fish_pool, self.distribution)
        user.premium_currency = 0

        # 空竿：条件为假，不发奖
        with patch("random.random", side_effect=[0.99]):  # did_catch 失败
            res = service.go_fish("u1")
            self.assertFalse(res["success"])
            self.assertNotIn("hextech_premium_reward", res)
            self.assertEqual(user.premium_currency, 0)

        # 钓到2星鱼：条件为假，不发奖
        with patch("random.random", side_effect=[0.1, 0.99]), \
             patch("random.choices", return_value=[1]):  # index 1 => rarity 2
            res = service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertEqual(res["fish"]["rarity"], 2)
            self.assertNotIn("hextech_premium_reward", res)
            self.assertEqual(user.premium_currency, 0)

        # 钓到4星鱼：条件为真，发奖
        with patch("random.random", side_effect=[0.1, 0.99, 0.01]), \
             patch("random.choices", return_value=[3]):  # index 3 => rarity 4
            res = service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertEqual(res["fish"]["rarity"], 4)
            self.assertEqual(res["hextech_premium_reward"], 1)
            self.assertEqual(res["hextech_premium_effect_id"], "C34")
            self.assertEqual(res["hextech_premium_message"], "💎 海克斯惊喜：获得1点高级货币！")
            self.assertEqual(user.premium_currency, 1)

    def test_s17_condition_truth_values(self):
        """S17 空钩奇遇：实际付费钓鱼最终空竿时为真，成功钓到鱼为假"""
        card = self._make_card("S17", tier="silver", chance=1.0)
        service, user, zone, _ = make_service(card, self.fish_pool, self.distribution)
        user.premium_currency = 0

        # 付费空竿：条件为真，发奖
        with patch("random.random", side_effect=[0.99, 0.01]):
            res = service.go_fish("u1")
            self.assertFalse(res["success"])
            self.assertEqual(res["hextech_premium_reward"], 1)
            self.assertEqual(res["hextech_premium_effect_id"], "S17")
            self.assertEqual(res["hextech_premium_message"], "💎 海克斯惊喜：获得1点高级货币！")
            self.assertIn("💎 海克斯惊喜：获得1点高级货币！", res["message"])
            self.assertEqual(user.premium_currency, 1)

        # 成功钓到鱼：条件为假，不发奖
        with patch("random.random", side_effect=[0.1, 0.99]), \
             patch("random.choices", return_value=[0]):
            res = service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertNotIn("hextech_premium_reward", res)
            self.assertEqual(user.premium_currency, 1)

    def test_s17_zero_cost_fishing_no_reward(self):
        """S17 审查项1：只有实际付费 > 0 才触发，零成本钓鱼最终空竿不得奖励"""
        card = self._make_card("S17", tier="silver", chance=1.0)
        
        # 1. 区域原成本为 0
        service, user, zone, _ = make_service(card, self.fish_pool, self.distribution, cost=0)
        user.premium_currency = 0
        with patch("random.random", side_effect=[0.99]):  # 仅空竿判断，不应调用高级货币判定
            res = service.go_fish("u1")
            self.assertFalse(res["success"])
            self.assertNotIn("hextech_premium_reward", res)
            self.assertNotIn("hextech_premium_message", res)
            self.assertEqual(user.premium_currency, 0)

        # 2. 海克斯减费使实际支付 paid = 0
        free_card = {
            "tier": "silver",
            "balance_version": 1,
            "effects": [
                {"id": "C01", "params": {"cost_discount": 1.0}},
                {"id": "S17", "params": {"premium_chance": 1.0, "premium_condition": "empty"}},
            ],
        }
        service_free, user_free, _, _ = make_service(free_card, self.fish_pool, self.distribution, cost=100)
        user_free.premium_currency = 0
        with patch("random.random", side_effect=[0.99]):
            res_free = service_free.go_fish("u1")
            self.assertFalse(res_free["success"])
            self.assertNotIn("hextech_premium_reward", res_free)
            self.assertEqual(user_free.premium_currency, 0)

    def test_g17_condition_truth_values(self):
        """G17 闪光结晶：仅最终为高品质且四星及以上稀有鱼时为真"""
        card = self._make_card("G17", tier="gold", chance=1.0)
        service, user, zone, _ = make_service(card, self.fish_pool, self.distribution)
        user.premium_currency = 0

        # 配置一把提供品质加成的鱼竿使 quality_modifier > 1.0
        service.inventory_repo.get_user_equipped_rod = lambda uid: SimpleNamespace(rod_id=1, refine_level=0, current_durability=100)
        service.item_template_repo.get_rod_by_id = lambda rid: SimpleNamespace(
            bonus_fish_quality_modifier=2.0, bonus_fish_quantity_modifier=1.0, bonus_rare_fish_chance=0.0, rarity=1
        )

        # 4星鱼但普通品质 (quality_level=0)：条件为假，不发奖
        with patch("random.random", side_effect=[0.1, 0.99]), \
             patch("random.choices", return_value=[3]):
            res = service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertEqual(res["fish"]["rarity"], 4)
            self.assertEqual(res["fish"]["quality_level"], 0)
            self.assertNotIn("hextech_premium_reward", res)
            self.assertEqual(user.premium_currency, 0)

        # 2星鱼高品质 (quality_level=1)：条件为假，不发奖
        with patch("random.random", side_effect=[0.1, 0.001]), \
             patch("random.choices", return_value=[1]):
            res = service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertEqual(res["fish"]["rarity"], 2)
            self.assertEqual(res["fish"]["quality_level"], 1)
            self.assertNotIn("hextech_premium_reward", res)
            self.assertEqual(user.premium_currency, 0)

        # 4星鱼高品质 (quality_level=1)：条件为真，发奖
        with patch("random.random", side_effect=[0.1, 0.001, 0.01]), \
             patch("random.choices", return_value=[3]):
            res = service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertEqual(res["fish"]["rarity"], 4)
            self.assertEqual(res["fish"]["quality_level"], 1)
            self.assertEqual(res["hextech_premium_reward"], 1)
            self.assertEqual(res["hextech_premium_effect_id"], "G17")
            self.assertEqual(user.premium_currency, 1)

    def test_p17_condition_truth_values(self):
        """P17 鱼王秘藏：最终鱼星级等于当前鱼区最高可抽星级且最高>=4为真"""
        card = self._make_card("P17", tier="prismatic", chance=1.0)
        service, user, zone, _ = make_service(card, self.fish_pool, self.distribution)
        user.premium_currency = 0

        # 当前鱼区最高星级为5。钓到4星：低于最高，条件为假
        with patch("random.random", side_effect=[0.1, 0.99]), \
             patch("random.choices", return_value=[3]):  # 4星
            res = service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertEqual(res["fish"]["rarity"], 4)
            self.assertNotIn("hextech_premium_reward", res)
            self.assertEqual(user.premium_currency, 0)

        # 钓到5星：等于最高星级5且>=4，条件为真，发奖
        with patch("random.random", side_effect=[0.1, 0.99, 0.01]), \
             patch("random.choices", return_value=[4]):  # 5星
            res = service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertEqual(res["fish"]["rarity"], 5)
            self.assertEqual(res["hextech_premium_reward"], 1)
            self.assertEqual(res["hextech_premium_effect_id"], "P17")
            self.assertEqual(user.premium_currency, 1)

        # 若当前鱼区最高星级不足4星（如最高3星），即使钓到3星也不发奖
        low_pool = self.fish_pool[:3]
        low_dist = [0.5, 0.3, 0.2]
        low_service, low_user, _, _ = make_service(card, low_pool, low_dist)
        low_user.premium_currency = 0
        with patch("random.random", side_effect=[0.1, 0.99]), \
             patch("random.choices", return_value=[2]):  # 3星
            res = low_service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertEqual(res["fish"]["rarity"], 3)
            self.assertNotIn("hextech_premium_reward", res)
            self.assertEqual(low_user.premium_currency, 0)

    # ==========================================
    # 2. 概率边界与非法概率拒绝
    # ==========================================
    def test_chance_bounds_and_invalid_inputs(self):
        """测试概率边界截断与非法/非有限数值的拒绝处理"""
        calc = FishingService._calculate_effective_premium_chance

        # 正常计算 (以120s为基准)
        self.assertAlmostEqual(calc(0.032, 120), 0.032)
        self.assertAlmostEqual(calc(0.10, 120), 0.10)
        self.assertAlmostEqual(calc(0.16, 60), 0.08)

        # 超过 1.0 截断
        self.assertEqual(calc(0.80, 240), 1.0)
        self.assertEqual(calc(1.5, 120), 1.0)

        # <= 0
        self.assertEqual(calc(0.0, 120), 0.0)
        self.assertEqual(calc(-0.05, 120), 0.0)

        # 非有限值
        self.assertEqual(calc(float("nan"), 120), 0.0)
        self.assertEqual(calc(float("inf"), 120), 0.0)
        self.assertEqual(calc(float("-inf"), 120), 0.0)

        # 非法类型
        self.assertEqual(calc("0.1", 120), 0.1)
        self.assertEqual(calc("invalid", 120), 0.0)
        self.assertEqual(calc(None, 120), 0.0)

        # 冷却时间非法
        self.assertEqual(calc(0.10, 0), 0.0)
        self.assertEqual(calc(0.10, -60), 0.0)
        self.assertEqual(calc(0.10, float("nan")), 0.0)
        self.assertEqual(calc(0.10, float("inf")), 0.0)

    # ==========================================
    # 3. 冷却默认 180 与海洋之心减半测试（审查项2）
    # ==========================================
    def test_cooldown_defaults_and_ocean_heart(self):
        """审查项2：默认冷却为 180s（与自动钓鱼一致）；配置 120s 时按 120s；海洋之心减半，不认海灵之心"""
        card = self._make_card("C34", tier="common", chance=0.032)
        service, user, _, inventory = make_service(card, self.fish_pool, self.distribution)

        # 1. 默认未配置冷却：base_cd 为 180.0
        self.assertAlmostEqual(service._get_effective_fishing_cooldown("u1"), 180.0)
        # 180s 冷却时概率缩放为 0.032 * 180 / 120 = 0.048
        self.assertAlmostEqual(service._calculate_effective_premium_chance(0.032, 180.0), 0.048)

        # 2. 默认未配置且装备“海洋之心”：冷却减半为 90.0
        inventory.get_user_equipped_accessory = lambda uid: SimpleNamespace(accessory_id=101, refine_level=0)
        service.item_template_repo.get_accessory_by_id = lambda aid: FakeAccessory(101, "海洋之心")
        self.assertAlmostEqual(service._get_effective_fishing_cooldown("u1"), 90.0)
        self.assertAlmostEqual(service._calculate_effective_premium_chance(0.032, 90.0), 0.024)

        # 3. 配置为 120s：base_cd 为 120.0
        service.config = {"fishing": {"cooldown_seconds": 120}}
        inventory.get_user_equipped_accessory = lambda uid: None
        self.assertAlmostEqual(service._get_effective_fishing_cooldown("u1"), 120.0)
        self.assertAlmostEqual(service._calculate_effective_premium_chance(0.032, 120.0), 0.032)

        # 4. 配置为 120s 且装备“海洋之心”：冷却减半为 60.0
        inventory.get_user_equipped_accessory = lambda uid: SimpleNamespace(accessory_id=101, refine_level=0)
        self.assertAlmostEqual(service._get_effective_fishing_cooldown("u1"), 60.0)
        self.assertAlmostEqual(service._calculate_effective_premium_chance(0.032, 60.0), 0.016)

        # 5. 不存在别名“海灵之心”，装备“海灵之心”不会减半
        service.item_template_repo.get_accessory_by_id = lambda aid: FakeAccessory(101, "海灵之心")
        self.assertAlmostEqual(service._get_effective_fishing_cooldown("u1"), 120.0)

    # ==========================================
    # 4. 赠卡 25% 缩减与普通卡独立参数
    # ==========================================
    def test_gift_card_quarter_reduction_and_v4_independence(self):
        """新卡不被钓鱼通用系数二次削弱；赠卡仅乘一次0.25；普通卡各品质相同"""
        rng = random.Random(42)

        # 普通卡在不同品质抽取 C34，均为 0.032
        for tier in ("silver", "gold", "prismatic"):
            params = _v4_params("C34", tier, rng, gift=False)
            self.assertEqual(params["premium_chance"], 0.032)
            self.assertFalse(params.get("is_gift"))

        # 各品质固有效果基础概率
        self.assertEqual(_v4_params("S17", "silver", rng, gift=False)["premium_chance"], 0.10)
        self.assertEqual(_v4_params("G17", "gold", rng, gift=False)["premium_chance"], 0.16)
        self.assertEqual(_v4_params("P17", "prismatic", rng, gift=False)["premium_chance"], 0.10)

        # 赠卡只乘一次 0.25
        self.assertEqual(_v4_params("C34", "silver", rng, gift=True)["premium_chance"], 0.008)
        self.assertEqual(_v4_params("S17", "silver", rng, gift=True)["premium_chance"], 0.025)
        self.assertEqual(_v4_params("G17", "gold", rng, gift=True)["premium_chance"], 0.040)
        self.assertEqual(_v4_params("P17", "prismatic", rng, gift=True)["premium_chance"], 0.025)

    # ==========================================
    # 5. 一次多鱼与免费重试仅单次判定
    # ==========================================
    def test_multi_catch_and_empty_retry_single_evaluation(self):
        """一次多鱼与免费重试仅根据最终结果判定一次，奖励固定1点"""
        # 1. 一次多鱼
        card = self._make_card("C34", tier="common", chance=1.0)
        service, user, _, _ = make_service(card, self.fish_pool, self.distribution)
        user.premium_currency = 0

        # mock 鱼竿提供 3 条鱼的数量加成
        service.inventory_repo.get_user_equipped_rod = lambda uid: SimpleNamespace(rod_id=1, refine_level=0, current_durability=100)
        service.item_template_repo.get_rod_by_id = lambda rid: SimpleNamespace(
            bonus_fish_quality_modifier=1.0, bonus_fish_quantity_modifier=3.0, bonus_rare_fish_chance=0.0, rarity=1
        )

        with patch("random.random", side_effect=[0.1, 0.99, 0.5, 0.01]), \
             patch("random.choices", return_value=[3]):  # 4星鱼
            res = service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertGreaterEqual(res["fish"]["catches"], 2)
            self.assertEqual(res["hextech_premium_reward"], 1)
            self.assertEqual(user.premium_currency, 1)  # 仅增加 1

        # 2. 免费重试成功钓到鱼：按最终渔获判定，非空竿不触发 S17
        s17_card = self._make_card("S17", tier="silver", chance=1.0)
        s17_card["effects"].append({"id": "C17", "tier": "silver", "params": {"empty_retry_chance": 1.0}})
        s17_service, s17_user, _, _ = make_service(s17_card, self.fish_pool, self.distribution)
        s17_user.premium_currency = 0

        # 第1次 catch 失败(0.99) -> 重试判定(0.01) -> 第2次 catch 成功(0.1) -> 品质(0.99)
        with patch("random.random", side_effect=[0.99, 0.01, 0.1, 0.99]), \
             patch("random.choices", return_value=[0]):
            res = s17_service.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertNotIn("hextech_premium_reward", res)
            self.assertEqual(s17_user.premium_currency, 0)

        # 3. 免费重试仍然失败：仅判定一次 S17
        with patch("random.random", side_effect=[0.99, 0.01, 0.99, 0.01]):
            # 第1次失败(0.99) -> 重试成功判定(0.01) -> 第2次失败(0.99) -> S17 触发(0.01)
            res = s17_service.go_fish("u1")
            self.assertFalse(res["success"])
            self.assertEqual(res["hextech_premium_reward"], 1)
            self.assertEqual(s17_user.premium_currency, 1)

    # ==========================================
    # 6. 无效操作/退款不发奖
    # ==========================================
    def test_invalid_operations_do_not_grant_reward(self):
        """金币不足、区域关闭、无鱼退款时不发奖"""
        card = self._make_card("S17", tier="silver", chance=1.0)
        service, user, zone, _ = make_service(card, self.fish_pool, self.distribution)
        user.premium_currency = 0

        # 金币不足
        user.coins = 5
        res = service.go_fish("u1")
        self.assertFalse(res["success"])
        self.assertIn("金币不足", res["message"])
        self.assertNotIn("hextech_premium_reward", res)
        self.assertEqual(user.premium_currency, 0)

        # 区域未激活
        user.coins = 1000
        zone.is_active = False
        res = service.go_fish("u1")
        self.assertFalse(res["success"])
        self.assertNotIn("hextech_premium_reward", res)
        self.assertEqual(user.premium_currency, 0)

    # ==========================================
    # 7. 旧卡无额外随机调用（随机流一致性）
    # ==========================================
    def test_random_call_count_identical_when_condition_unmet(self):
        """无效果或条件不满足时，完全不额外调用 random.random"""
        old_card = {"tier": "silver", "effects": [{"id": "C01", "params": {"cost_discount": 0.1}}]}
        service_old, user_old, _, _ = make_service(old_card, self.fish_pool, self.distribution)

        c34_card = self._make_card("C34", tier="common", chance=0.5)
        service_c34, user_c34, _, _ = make_service(c34_card, self.fish_pool, self.distribution)

        # 场景A：空竿。C34 不满足条件，调用 random 次数应与旧卡完全一致
        calls_old = []
        with patch("random.random", side_effect=lambda: calls_old.append(1) or 0.99):
            service_old.go_fish("u1")

        calls_c34 = []
        with patch("random.random", side_effect=lambda: calls_c34.append(1) or 0.99):
            service_c34.go_fish("u1")

        self.assertEqual(len(calls_old), len(calls_c34))

        # 场景B：钓到2星鱼（不满足C34条件）。调用次数完全一致
        calls_old_fish = []
        with patch("random.random", side_effect=lambda: calls_old_fish.append(1) or 0.1), \
             patch("random.choices", return_value=[1]):
            service_old.go_fish("u1")

        calls_c34_fish = []
        with patch("random.random", side_effect=lambda: calls_c34_fish.append(1) or 0.1), \
             patch("random.choices", return_value=[1]):
            service_c34.go_fish("u1")

        self.assertEqual(len(calls_old_fish), len(calls_c34_fish))

    # ==========================================
    # 8. 目录与双向全互斥（整套至多一个）
    # ==========================================
    def test_premium_effects_mutual_exclusion(self):
        """C34, S17, G17, P17 两两互斥；整套卡（含福袋赠卡）至多出现一个"""
        # 两两双向互斥
        for eid in PREMIUM_EFFECT_IDS:
            expected_conflicts = set(PREMIUM_EFFECT_IDS) - {eid}
            self.assertEqual(set(EFFECTS[eid]["conflicts"]), expected_conflicts)

        # 随机抽取的大量卡片中，整套最多只有 1 个高级货币效果
        rng = random.Random(12345)
        for tier in ("silver", "gold", "prismatic"):
            for _ in range(50):
                card = roll_card(tier, rng=rng, fishing_only=False)
                flattened = effective_card(card)
                premium_count = sum(1 for e in flattened["effects"] if e["id"] in PREMIUM_EFFECT_IDS)
                self.assertLessEqual(premium_count, 1)

    # ==========================================
    # 9. 卡面描述与说明展示
    # ==========================================
    def test_card_descriptions(self):
        """测试四张新卡的面额描述包含条件、概率与冷却缩放说明"""
        for eid in PREMIUM_EFFECT_IDS:
            card = self._make_card(eid, tier="silver")
            desc = describe_card(card, [1, 2, 3, 4, 5])
            self.assertIn(EFFECTS[eid]["name"], desc)
            self.assertIn("高级货币", desc)
            self.assertIn("120秒", desc)

    # ==========================================
    # 10. 持久化存储
    # ==========================================
    def test_saved_premium_currency_in_user_repo_both_branches(self):
        """无论空竿还是成功捕获，触发奖励后 user_repo.user.premium_currency 均被持久化更新"""
        # 成功分支
        c34_card = self._make_card("C34", tier="common", chance=1.0)
        s, u, _, _ = make_service(c34_card, self.fish_pool, self.distribution)
        u.premium_currency = 5
        with patch("random.random", side_effect=[0.1, 0.99, 0.01]), patch("random.choices", return_value=[3]):
            res = s.go_fish("u1")
            self.assertTrue(res["success"])
            self.assertEqual(s.user_repo.user.premium_currency, 6)

        # 空竿分支
        s17_card = self._make_card("S17", tier="silver", chance=1.0)
        s2, u2, _, _ = make_service(s17_card, self.fish_pool, self.distribution)
        u2.premium_currency = 10
        with patch("random.random", side_effect=[0.99, 0.01]):
            res2 = s2.go_fish("u1")
            self.assertFalse(res2["success"])
            self.assertEqual(s2.user_repo.user.premium_currency, 11)

    # ==========================================
    # 11. 真实 _build_fish_message 与装备损坏解耦（审查项3）
    # ==========================================
    def test_build_fish_message_displays_once_and_no_broken_equipment(self):
        """审查项3：中奖提示通过独立 hextech_premium_message 进入消息，装备损坏消息保持仅损坏"""
        # 1. 成功且中奖（无装备损坏）
        success_reward_result = {
            "success": True,
            "fish": {
                "name": "七彩神仙鱼",
                "rarity": 4,
                "weight": 500,
                "value": 1200,
                "unit_value": 1200,
                "catches": 1,
                "quality_level": 0,
                "quality_label": "普通",
            },
            "hextech_premium_reward": 1,
            "hextech_premium_effect_id": "C34",
            "hextech_premium_message": "💎 海克斯惊喜：获得1点高级货币！",
        }
        # 验证返回结构中不含 equipment_broken_messages
        self.assertNotIn("equipment_broken_messages", success_reward_result)
        msg = _build_fish_message(success_reward_result, fishing_cost=100)
        self.assertIn("💎 海克斯惊喜：获得1点高级货币！", msg)
        self.assertNotIn("损坏", msg)
        self.assertEqual(msg.count("💎 海克斯惊喜：获得1点高级货币！"), 1)

        # 2. 成功且未中奖
        success_no_reward = {
            "success": True,
            "fish": {
                "name": "小鲫鱼",
                "rarity": 1,
                "weight": 100,
                "value": 10,
                "unit_value": 10,
                "catches": 1,
                "quality_level": 0,
                "quality_label": "普通",
            },
        }
        msg_no = _build_fish_message(success_no_reward, fishing_cost=100)
        self.assertNotIn("💎 海克斯惊喜：获得1点高级货币！", msg_no)

        # 3. 失败且中奖（空竿）
        fail_reward_result = {
            "success": False,
            "message": "💨 什么都没钓到...\n💎 海克斯惊喜：获得1点高级货币！",
            "hextech_premium_reward": 1,
            "hextech_premium_effect_id": "S17",
            "hextech_premium_message": "💎 海克斯惊喜：获得1点高级货币！",
        }
        msg_fail = _build_fish_message(fail_reward_result, fishing_cost=100)
        self.assertIn("💎 海克斯惊喜：获得1点高级货币！", msg_fail)
        # 确保不会重复出现两次
        self.assertEqual(msg_fail.count("💎 海克斯惊喜：获得1点高级货币！"), 1)

        # 4. 真实 go_fish 返回结构中，中奖且无装备损坏时不存在 equipment_broken_messages
        card = self._make_card("C34", tier="common", chance=1.0)
        service, user, _, _ = make_service(card, self.fish_pool, self.distribution)
        user.premium_currency = 0
        with patch("random.random", side_effect=[0.1, 0.99, 0.01]), patch("random.choices", return_value=[3]):
            real_res = service.go_fish("u1")
            self.assertTrue(real_res["success"])
            self.assertEqual(real_res.get("hextech_premium_reward"), 1)
            self.assertNotIn("equipment_broken_messages", real_res)
            msg_real = _build_fish_message(real_res, fishing_cost=100)
            self.assertIn("💎 海克斯惊喜：获得1点高级货币！", msg_real)
            self.assertEqual(msg_real.count("💎 海克斯惊喜：获得1点高级货币！"), 1)

    # ==========================================
    # 12. 自动钓鱼真实循环通知路径验证
    # ==========================================
    def _setup_auto_fishing_service(self, card, coins=1000):
        service, user, zone, _ = make_service(card, self.fish_pool, self.distribution, cost=100)
        user.coins = coins
        user.premium_currency = 0
        user.auto_fishing_enabled = True
        user.fishing_zone_id = 1
        user.last_fishing_time = datetime(2020, 1, 1, tzinfo=timezone.utc)

        service.user_repo.get_all_user_ids = MagicMock(return_value=["u1"])
        service._reset_rare_fish_pool_quota = MagicMock(return_value=False)
        service.config = {"fishing": {"cooldown_seconds": 180, "cost": 100}}
        service.auto_fishing_running = True

        notifications = []
        notifier_mock = MagicMock(side_effect=lambda uid, text: notifications.append((uid, text)))
        service.register_notifier(notifier_mock)
        return service, user, notifications, notifier_mock

    def test_auto_fishing_loop_catch_success_notifies_premium(self):
        """真实 _auto_fishing_loop：捕获4星稀有鱼中奖后通知并入账，断言真实 go_fish 调用一次"""
        card = self._make_card("C34", tier="common", chance=1.0)
        service, user, notifications, notifier_mock = self._setup_auto_fishing_service(card)

        def stop_loop(_duration):
            service.auto_fishing_running = False

        with patch("core.services.fishing_service.time.sleep", side_effect=stop_loop), \
             patch("random.random", side_effect=[0.1, 0.99, 0.01]), \
             patch("random.choices", return_value=[3]), \
             patch.object(service, "go_fish", wraps=service.go_fish) as spy:
            service._auto_fishing_loop()

        spy.assert_called_once_with("u1")
        self.assertEqual(user.premium_currency, 1)
        notifier_mock.assert_called_once_with("u1", "💎 海克斯惊喜：获得1点高级货币！")
        self.assertEqual(notifications, [("u1", "💎 海克斯惊喜：获得1点高级货币！")])

    def test_auto_fishing_loop_paid_empty_hook_notifies_premium(self):
        """真实 _auto_fishing_loop：S17 付费空竿中奖后通知并入账，断言真实 go_fish 调用一次"""
        card = self._make_card("S17", tier="silver", chance=1.0)
        service, user, notifications, notifier_mock = self._setup_auto_fishing_service(card, coins=1000)

        def stop_loop(_duration):
            service.auto_fishing_running = False

        with patch("core.services.fishing_service.time.sleep", side_effect=stop_loop), \
             patch("random.random", side_effect=[0.99, 0.01]), \
             patch.object(service, "go_fish", wraps=service.go_fish) as spy:
            service._auto_fishing_loop()

        spy.assert_called_once_with("u1")
        self.assertEqual(user.premium_currency, 1)
        notifier_mock.assert_called_once_with("u1", "💎 海克斯惊喜：获得1点高级货币！")
        self.assertEqual(notifications, [("u1", "💎 海克斯惊喜：获得1点高级货币！")])

    def test_auto_fishing_loop_no_win_does_not_notify(self):
        """真实 _auto_fishing_loop：未触发高级货币时不调用通知，断言真实 go_fish 调用一次"""
        card = self._make_card("C34", tier="common", chance=0.032)
        service, user, notifications, notifier_mock = self._setup_auto_fishing_service(card)

        def stop_loop(_duration):
            service.auto_fishing_running = False

        with patch("core.services.fishing_service.time.sleep", side_effect=stop_loop), \
             patch("random.random", side_effect=[0.1, 0.99, 0.99]), \
             patch("random.choices", return_value=[3]), \
             patch.object(service, "go_fish", wraps=service.go_fish) as spy:
            service._auto_fishing_loop()

        spy.assert_called_once_with("u1")
        self.assertEqual(user.premium_currency, 0)
        notifier_mock.assert_not_called()
        self.assertEqual(len(notifications), 0)

    def test_auto_fishing_loop_notifier_exception_does_not_rollback_or_regrant(self):
        """真实 _auto_fishing_loop：notifier 抛出异常不会撤销已入账奖励或二次发奖，断言真实 go_fish 调用一次"""
        card = self._make_card("C34", tier="common", chance=1.0)
        service, user, notifications, _ = self._setup_auto_fishing_service(card)
        failing_notifier = MagicMock(side_effect=RuntimeError("connection dropped"))
        service.register_notifier(failing_notifier)

        def stop_loop(_duration):
            service.auto_fishing_running = False

        with patch("core.services.fishing_service.time.sleep", side_effect=stop_loop), \
             patch("random.random", side_effect=[0.1, 0.99, 0.01]), \
             patch("random.choices", return_value=[3]), \
             patch.object(service, "go_fish", wraps=service.go_fish) as spy:
            service._auto_fishing_loop()

        spy.assert_called_once_with("u1")
        failing_notifier.assert_called_once_with("u1", "💎 海克斯惊喜：获得1点高级货币！")
        self.assertEqual(user.premium_currency, 1)
        self.assertEqual(len(notifications), 0)

    def test_auto_fishing_loop_notifies_premium_reward(self):
        """综合验证：调用真实 _auto_fishing_loop 覆盖中奖通知全流程"""
        self.test_auto_fishing_loop_catch_success_notifies_premium()
        self.test_auto_fishing_loop_paid_empty_hook_notifies_premium()
        self.test_auto_fishing_loop_no_win_does_not_notify()
        self.test_auto_fishing_loop_notifier_exception_does_not_rollback_or_regrant()


if __name__ == "__main__":
    unittest.main()
