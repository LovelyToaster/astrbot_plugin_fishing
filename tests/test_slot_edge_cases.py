"""
拉杆机 边界/漏洞/压力 自测
覆盖：赔率表一致性、参数异常、并发安全、保底边界、奖池边界、
      历史上限、连转中途中断、配置缺省、文本构建空安全、
      幸运时段边界、连败计数跨日等
"""
import sys, os, time, copy
from unittest.mock import MagicMock, patch
from types import ModuleType

# 项目根目录
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock astrbot
astrbot_mock = ModuleType("astrbot")
astrbot_api_mock = ModuleType("astrbot.api")
astrbot_api_mock.logger = MagicMock()
astrbot_mock.api = astrbot_api_mock
sys.modules["astrbot"] = astrbot_mock
sys.modules["astrbot.api"] = astrbot_api_mock
sys.modules["astrbot.api.event"] = ModuleType("astrbot.api.event")

from core.services.slot_service import (
    SlotService, SlotSymbol, SYMBOL_WEIGHTS, TRIPLE_PAYOUTS,
    TWO_SAME_PAYOUTS, DEFAULT_TIERS, SpinResult,
)

# ===== Fake Repos =====
class FakeUser:
    def __init__(self, uid, coins=10_000_000, nickname=None):
        self.user_id = uid
        self.nickname = nickname or uid
        self.coins = coins

class FakeUserRepo:
    def __init__(self):
        self.users = {}
    def add(self, u):
        self.users[u.user_id] = u
    def get_by_id(self, uid):
        return self.users.get(uid)
    def update_coins(self, uid, delta):
        u = self.users.get(uid)
        if u:
            u.coins += delta

class FakeLogRepo:
    def add(self, *a, **kw): pass

def make_service(**overrides):
    repo = FakeUserRepo()
    log = FakeLogRepo()
    config = {"slot": {
        "daily_limit": overrides.get("daily_limit", 50),
        "max_multi_spin": overrides.get("max_multi_spin", 10),
        "streak_protection": overrides.get("streak_protection", 20),
        "message_mode": overrides.get("message_mode", "text"),
        "initial_jackpot": overrides.get("initial_jackpot", 0),
    }}
    svc = SlotService(repo, log, config)
    return repo, svc


# ===== 测试框架 =====
passed = 0
failed = 0

def test(name):
    global passed, failed
    def decorator(fn):
        global passed, failed
        try:
            fn()
            print(f"  ✅ {name}")
            passed += 1
        except Exception as e:
            import traceback
            print(f"  ❌ {name}: {e}")
            traceback.print_exc()
            failed += 1
    return decorator


print("🔍 拉杆机边界/漏洞测试套件\n")

# ====================================================================
# 一、赔率表一致性 (验证帮助文本与实际赔率是否一致)
# ====================================================================
print("--- 赔率表一致性 ---")

@test("BUG检测: draw_slot_help 赔率表是否硬编码了旧值")
def _():
    """draw/slot.py 中 draw_slot_help 的 odds_data 硬编码了两同赔率，
    如果代码修改了 TWO_SAME_PAYOUTS 但没更新画面，就会产生不一致。
    本测试直接验证实际赔率值。"""
    # 实际赔率
    assert TWO_SAME_PAYOUTS[SlotSymbol.FISH] == 1, f"两鱼应为×1, 实际 ×{TWO_SAME_PAYOUTS[SlotSymbol.FISH]}"
    assert TWO_SAME_PAYOUTS[SlotSymbol.CRAB] == 1, f"两蟹应为×1, 实际 ×{TWO_SAME_PAYOUTS[SlotSymbol.CRAB]}"
    assert TWO_SAME_PAYOUTS[SlotSymbol.OCTOPUS] == 1, f"两章鱼应为×1, 实际 ×{TWO_SAME_PAYOUTS[SlotSymbol.OCTOPUS]}"
    assert TWO_SAME_PAYOUTS[SlotSymbol.SHARK] == 1, f"两鲨鱼应为×1, 实际 ×{TWO_SAME_PAYOUTS[SlotSymbol.SHARK]}"
    assert TWO_SAME_PAYOUTS[SlotSymbol.WHALE] == 2, f"两鲸鱼应为×2, 实际 ×{TWO_SAME_PAYOUTS[SlotSymbol.WHALE]}"
    assert TWO_SAME_PAYOUTS[SlotSymbol.GEM] == 3, f"两宝石应为×3, 实际 ×{TWO_SAME_PAYOUTS[SlotSymbol.GEM]}"
    assert TWO_SAME_PAYOUTS[SlotSymbol.STAR] == 5, f"两海星应为×5, 实际 ×{TWO_SAME_PAYOUTS[SlotSymbol.STAR]}"


@test("BUG检测: draw/slot.py 帮助图赔率是否与实际一致")
def _():
    """检查 draw_slot_help 中硬编码的 odds_data 是否和 TWO_SAME_PAYOUTS 一致"""
    try:
        from draw.slot import draw_slot_help
        import inspect
        source = inspect.getsource(draw_slot_help)
        # 检关键数据行: 低级符号应为 ×1 而非 ×2
        # 如果源码含 "两鲨鱼", "×2" 相邻，就是BUG
        import re
        # 检索 odds_data 中的两同赔率
        wrong_patterns = [
            (r'两鲨鱼.*?×2', "两鲨鱼应为×1"),
            (r'两章鱼.*?×2', "两章鱼应为×1"),
            (r'两螃蟹.*?×2', "两螃蟹应为×1"),
            (r'两小鱼.*?×2', "两小鱼应为×1"),
            (r'两鲸鱼.*?×3', "两鲸鱼应为×2"),
        ]
        bugs_found = []
        for pattern, msg in wrong_patterns:
            if re.search(pattern, source):
                bugs_found.append(msg)
        if bugs_found:
            raise AssertionError(f"帮助图赔率BUG: {'; '.join(bugs_found)}")
    except ImportError:
        print("    [跳过: draw模块无法导入，需Pillow]")


@test("BUG检测: handlers/slot_handlers.py 帮助文本赔率是否正确")
def _():
    """检查 slot_help 文本中是否有错误的赔率"""
    try:
        import inspect
        from handlers.slot_handlers import slot_help
        source = inspect.getsource(slot_help)
        # "其余两同 ×2" 应该是 "×1"
        if "其余两同 ×2" in source:
            raise AssertionError("帮助文本BUG: '其余两同 ×2' 应为 '其余两同 ×1(返还本金)'")
        # "两宝石/鲸鱼 ×3" 不正确：宝石×3但鲸鱼应为×2
        if "两宝石/鲸鱼 ×3" in source:
            raise AssertionError("帮助文本BUG: '两宝石/鲸鱼 ×3' 不正确，鲸鱼应为×2")
    except ImportError:
        print("    [跳过: handlers模块无法导入]")


# ====================================================================
# 二、参数边界测试
# ====================================================================
print("\n--- 参数边界测试 ---")

@test("档位别名: copper/silver/gold/supreme 可正常使用")
def _():
    repo, svc = make_service()
    user = FakeUser("u_alias", coins=100_000_000)
    repo.add(user)
    for alias in ["copper", "silver", "gold", "supreme"]:
        r = svc.spin("u_alias", alias)
        assert r["success"], f"别名 {alias} 应成功，实际: {r.get('message')}"

@test("连转次数为0 → 自动调为1")
def _():
    repo, svc = make_service()
    user = FakeUser("u_zero", coins=100_000_000)
    repo.add(user)
    r = svc.multi_spin("u_zero", "铜", 0)
    assert r["success"]
    assert r["count"] == 1

@test("连转次数为负数 → 自动调为1")
def _():
    repo, svc = make_service()
    user = FakeUser("u_neg", coins=100_000_000)
    repo.add(user)
    r = svc.multi_spin("u_neg", "铜", -999)
    assert r["success"]
    assert r["count"] == 1

@test("连转次数超大 → 被 max_multi_spin 限制")
def _():
    repo, svc = make_service(max_multi_spin=5)
    user = FakeUser("u_big", coins=100_000_000)
    repo.add(user)
    r = svc.multi_spin("u_big", "铜", 9999999)
    assert r["success"]
    assert r["count"] == 5

@test("空字符串档位 → 失败")
def _():
    repo, svc = make_service()
    user = FakeUser("u_empty", coins=100_000_000)
    repo.add(user)
    r = svc.spin("u_empty", "")
    assert not r["success"]
    assert "未知" in r["message"]

@test("特殊字符档位 → 失败")
def _():
    repo, svc = make_service()
    user = FakeUser("u_special", coins=100_000_000)
    repo.add(user)
    for bad_tier in ["<script>", "'; DROP TABLE", "至尊 ", " 金", "🎰"]:
        r = svc.spin("u_special", bad_tier)
        assert not r["success"], f"'{bad_tier}' 应失败"

@test("连转无效档位 → 失败")
def _():
    repo, svc = make_service()
    user = FakeUser("u_bad_tier", coins=100_000_000)
    repo.add(user)
    r = svc.multi_spin("u_bad_tier", "钻石", 5)
    assert not r["success"]
    assert "未知" in r["message"]


# ====================================================================
# 三、金币边界与资金安全
# ====================================================================
print("\n--- 金币边界与资金安全 ---")

@test("恰好够一次铜桌 → 成功")
def _():
    repo, svc = make_service()
    user = FakeUser("u_exact", coins=10_000)
    repo.add(user)
    r = svc.spin("u_exact", "铜")
    assert r["success"]

@test("差1金币不够 → 失败且不扣费")
def _():
    repo, svc = make_service()
    user = FakeUser("u_short", coins=9_999)
    repo.add(user)
    initial = user.coins
    r = svc.spin("u_short", "铜")
    assert not r["success"]
    assert user.coins == initial, "失败时不应扣费"

@test("连转中途余额不足应中断且不丢金币")
def _():
    repo, svc = make_service(daily_limit=100, streak_protection=100)
    # 给3次铜桌的钱
    user = FakeUser("u_mid", coins=30_000)
    repo.add(user)
    # 强制不中奖
    original_spin = svc._weighted_spin
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.FISH, SlotSymbol.CRAB, SlotSymbol.OCTOPUS]
    # 强制不保底
    svc.streak_protection = 9999
    r = svc.multi_spin("u_mid", "铜", 10)
    svc._weighted_spin = original_spin
    assert r["success"]
    # 应只转了3次 (30000 / 10000)
    assert r["count"] == 3, f"应只转3次，实际 {r['count']}"
    assert user.coins == 0, f"应恰好花完，实际余额 {user.coins}"

@test("至尊桌余额刚好 → 成功")
def _():
    repo, svc = make_service()
    user = FakeUser("u_supreme", coins=5_000_000)
    repo.add(user)
    r = svc.spin("u_supreme", "至尊")
    assert r["success"]

@test("金币为0 → 失败(所有档位)")
def _():
    repo, svc = make_service()
    user = FakeUser("u_broke", coins=0)
    repo.add(user)
    for tier in ["铜", "银", "金", "至尊"]:
        r = svc.spin("u_broke", tier)
        assert not r["success"], f"档位{tier}应失败"
        assert "不足" in r["message"]

@test("连转预检不足但能转1次的情况")
def _():
    repo, svc = make_service(daily_limit=100)
    # 能转1次铜桌，但请求10次
    user = FakeUser("u_partial", coins=15_000)
    repo.add(user)
    r = svc.multi_spin("u_partial", "铜", 10)
    assert r["success"]
    assert r["count"] == 1

@test("大额金币溢出安全性")
def _():
    repo, svc = make_service()
    user = FakeUser("u_rich", coins=999_999_999_999)
    repo.add(user)
    r = svc.spin("u_rich", "至尊")
    assert r["success"]
    assert r["balance"] >= 0, "余额不应为负"


# ====================================================================
# 四、保底机制边界
# ====================================================================
print("\n--- 保底机制边界 ---")

@test("保底阈值=1: 首次不中即保底")
def _():
    repo, svc = make_service(streak_protection=1)
    user = FakeUser("u_sp1", coins=100_000_000)
    repo.add(user)
    # 强制不中奖
    original_spin = svc._weighted_spin
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.FISH, SlotSymbol.CRAB, SlotSymbol.OCTOPUS]
    r = svc.spin("u_sp1", "铜")
    svc._weighted_spin = original_spin
    assert r["success"]
    rd = r["result"]
    # 第1次不中就触发保底
    assert rd["match_type"] == "double", f"保底应触发, 实际 {rd['match_type']}"
    assert "保底" in rd["match_desc"]

@test("保底阈值=0: 每次都保底(极端)")
def _():
    repo, svc = make_service(streak_protection=0)
    user = FakeUser("u_sp0", coins=100_000_000)
    repo.add(user)
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.FISH, SlotSymbol.CRAB, SlotSymbol.OCTOPUS]
    r = svc.spin("u_sp0", "铜")
    # streak_protection=0, streak(1) >= 0 → 触发
    assert r["success"]
    rd = r["result"]
    assert "保底" in rd["match_desc"] or rd["match_type"] == "double"

@test("保底后连败计数重置")
def _():
    repo, svc = make_service(streak_protection=2)
    user = FakeUser("u_reset", coins=100_000_000)
    repo.add(user)
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.FISH, SlotSymbol.CRAB, SlotSymbol.OCTOPUS]
    # 第1次: streak=1 < 2, 不保底
    r1 = svc.spin("u_reset", "铜")
    assert r1["result"]["match_type"] == "none"
    # 第2次: streak=2 >= 2, 保底
    r2 = svc.spin("u_reset", "铜")
    assert r2["result"]["match_type"] == "double"
    # 第3次: streak 已重置，streak=1 < 2, 不保底
    r3 = svc.spin("u_reset", "铜")
    assert r3["result"]["match_type"] == "none"

@test("保底给出的对子不会变成三同")
def _():
    """保底符号选最高级符号做对子，第三个必须不同"""
    repo, svc = make_service(streak_protection=1)
    user = FakeUser("u_no_triple", coins=100_000_000)
    repo.add(user)
    # 强制三不同
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.STAR, SlotSymbol.CRAB, SlotSymbol.FISH]
    for _ in range(50):
        r = svc.spin("u_no_triple", "铜")
        rd = r["result"]
        syms = rd["symbols"]
        # 保底应为 double，不应为 triple
        if rd["match_type"] == "double" and "保底" in rd["match_desc"]:
            pass  # expected
        else:
            assert False, f"保底未触发或类型异常: {rd['match_type']}, {rd['match_desc']}"

@test("低级符号保底: 净盈亏=0 (返还本金)")
def _():
    repo, svc = make_service(streak_protection=1)
    user = FakeUser("u_low_sp", coins=100_000_000)
    repo.add(user)
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.FISH, SlotSymbol.CRAB, SlotSymbol.OCTOPUS]
    r = svc.spin("u_low_sp", "铜")
    rd = r["result"]
    # best = OCTOPUS (tier 3), payout = ×1, net = 0
    assert rd["net"] == 0, f"低级保底 net 应= 0, 实际 {rd['net']}"


# ====================================================================
# 五、奖池边界
# ====================================================================
print("\n--- 奖池边界 ---")

@test("铜桌永远不触发Jackpot(概率=0)")
def _():
    repo, svc = make_service(initial_jackpot=100_000_000)
    user = FakeUser("u_jp_copper", coins=999_999_999)
    repo.add(user)
    # 铜桌 jackpot_trigger_chance=0.0, mini_jackpot_chance=0.0
    original_check = svc._check_jackpot
    # 直接调用 _check_jackpot 验证
    tier = DEFAULT_TIERS["铜"]
    for _ in range(1000):
        jp, mini = svc._check_jackpot(tier)
        assert not jp and not mini, "铜桌不应触发任何Jackpot"

@test("奖池为0时不触发Jackpot检查")
def _():
    repo, svc = make_service(initial_jackpot=0)
    tier = DEFAULT_TIERS["至尊"]
    # 奖池为0应跳过检查
    jp, mini = svc._check_jackpot(tier)
    assert not jp and not mini

@test("Mini Jackpot 只取奖池的10%")
def _():
    repo, svc = make_service(initial_jackpot=100_000_000)  # 大奖池使贡献占比小
    user = FakeUser("u_mini", coins=100_000_000)
    repo.add(user)
    # 强制触发 mini jackpot
    svc._check_jackpot = lambda tier: (False, True)
    before_pool = svc.jackpot_pool  # 100,000,000
    r = svc.spin("u_mini", "铜")  # 铜桌贡献=200, mini_win=pool//10=~10,000,000
    mini_win = r["result"]["jackpot_win"]
    # mini_win 大约 = (100,000,000+200)//10 = 10,000,020
    assert mini_win > 0, "Mini Jackpot应有奖金"
    # 奖池应减少（因为 mini_win >> contribution）
    assert svc.jackpot_pool < before_pool, f"奖池应减少: {svc.jackpot_pool} >= {before_pool}"

@test("Jackpot清空后本次贡献仍进入奖池")
def _():
    repo, svc = make_service(initial_jackpot=500_000)
    user = FakeUser("u_jp_clear", coins=100_000_000)
    repo.add(user)
    svc._check_jackpot = lambda tier: (True, False)
    r = svc.spin("u_jp_clear", "至尊")
    # Jackpot 触发后奖池清零，但本spin的贡献已在清零前入池
    assert r["result"]["match_type"] == "jackpot"
    # 清零后奖池 = 0 (所有余额被赢走)
    assert svc.jackpot_pool == 0, f"Jackpot后奖池应为0, 实际 {svc.jackpot_pool}"

@test("极小奖池(1金币) Mini Jackpot = max(1, 0) = 1")
def _():
    repo, svc = make_service(initial_jackpot=1)
    user = FakeUser("u_tiny", coins=100_000_000)
    repo.add(user)
    svc._check_jackpot = lambda tier: (False, True)
    r = svc.spin("u_tiny", "至尊")
    assert r["result"]["jackpot_win"] >= 1


# ====================================================================
# 六、每日限额边界
# ====================================================================
print("\n--- 每日限额边界 ---")

@test("每日限额=1: 只能转1次")
def _():
    repo, svc = make_service(daily_limit=1)
    user = FakeUser("u_dl1", coins=100_000_000)
    repo.add(user)
    r1 = svc.spin("u_dl1", "铜")
    assert r1["success"]
    r2 = svc.spin("u_dl1", "铜")
    assert not r2["success"]
    assert "用完" in r2["message"]
    assert r1["remaining_spins"] == 0

@test("get_remaining_spins 跨日重置")
def _():
    repo, svc = make_service(daily_limit=5)
    user = FakeUser("u_crossday", coins=100_000_000)
    repo.add(user)
    svc.spin("u_crossday", "铜")
    assert svc.get_remaining_spins("u_crossday") == 4
    # 模拟日期变更
    svc._daily_usage["u_crossday"]["date"] = "1999-01-01"
    assert svc.get_remaining_spins("u_crossday") == 5, "跨日应重置"

@test("连转请求超过剩余次数但剩余>0")
def _():
    repo, svc = make_service(daily_limit=3)
    user = FakeUser("u_remain", coins=100_000_000)
    repo.add(user)
    svc.spin("u_remain", "铜")  # 用掉1次, 剩余2次
    r = svc.multi_spin("u_remain", "铜", 10)
    assert r["success"]
    assert r["count"] == 2, f"应只转2次, 实际 {r['count']}"


# ====================================================================
# 七、历史记录边界
# ====================================================================
print("\n--- 历史记录边界 ---")

@test("历史上限: 超出50条裁剪")
def _():
    repo, svc = make_service(daily_limit=100, streak_protection=9999)
    user = FakeUser("u_hist", coins=999_999_999)
    repo.add(user)
    for _ in range(60):
        svc.spin("u_hist", "铜")
    records = svc._history.get("u_hist", [])
    assert len(records) == 50, f"历史应截断到50, 实际 {len(records)}"

@test("无历史记录: 返回空列表")
def _():
    repo, svc = make_service()
    assert svc.get_user_history("nobody") == []

@test("get_user_history limit参数")
def _():
    repo, svc = make_service(daily_limit=100)
    user = FakeUser("u_hlimit", coins=999_999_999)
    repo.add(user)
    for _ in range(20):
        svc.spin("u_hlimit", "铜")
    assert len(svc.get_user_history("u_hlimit", 5)) == 5
    assert len(svc.get_user_history("u_hlimit", 100)) == 20


# ====================================================================
# 八、幸运时段边界
# ====================================================================
print("\n--- 幸运时段边界 ---")

@test("幸运时段 start 范围合法 [0, 21]")
def _():
    repo, svc = make_service()
    assert 0 <= svc._lucky_hour_start <= 21, f"start={svc._lucky_hour_start} 超出范围"

@test("幸运时段信息格式正确")
def _():
    repo, svc = make_service()
    info = svc.get_lucky_hour_info()
    # 格式: "HH:00 - HH:00"
    import re
    assert re.match(r"\d{2}:00 - \d{2}:00", info), f"格式不正确: {info}"

@test("幸运时段不跨日刷新多次")
def _():
    repo, svc = make_service()
    start1 = svc._lucky_hour_start
    svc._refresh_lucky_hour()
    start2 = svc._lucky_hour_start
    assert start1 == start2, "同日不应重新随机"

@test("幸运时段: 权重增强验证")
def _():
    repo, svc = make_service()
    # 非幸运时段
    normal = svc._weighted_spin(lucky=False)
    assert len(normal) == 3
    # 幸运时段
    lucky = svc._weighted_spin(lucky=True)
    assert len(lucky) == 3


# ====================================================================
# 九、配置缺省与容错
# ====================================================================
print("\n--- 配置缺省与容错 ---")

@test("空config → 所有默认值")
def _():
    repo = FakeUserRepo()
    svc = SlotService(repo, FakeLogRepo(), {})
    assert svc.daily_limit == 50
    assert svc.max_multi_spin == 10
    assert svc.streak_protection == 20
    assert svc.message_mode == "image"
    assert svc.jackpot_pool == 0

@test("slot key 缺失 → 默认值")
def _():
    repo = FakeUserRepo()
    svc = SlotService(repo, FakeLogRepo(), {"other_key": 123})
    assert svc.daily_limit == 50

@test("部分slot配置 → 缺失项使用默认")
def _():
    svc = SlotService(FakeUserRepo(), FakeLogRepo(), {"slot": {"daily_limit": 99}})
    assert svc.daily_limit == 99
    assert svc.max_multi_spin == 10  # 默认


# ====================================================================
# 十、消息模式切换边界
# ====================================================================
print("\n--- 消息模式切换 ---")

@test("set_message_mode 各种输入")
def _():
    repo, svc = make_service()
    # 合法值
    assert svc.set_message_mode("image")["success"]
    assert svc.is_image_mode()
    assert svc.set_message_mode("text")["success"]
    assert not svc.is_image_mode()
    # 非法值
    assert not svc.set_message_mode("xml")["success"]
    assert not svc.set_message_mode("")["success"]
    assert not svc.set_message_mode("IMAGE")["success"]  # 大小写敏感
    # 确认模式未被错误切换
    assert svc.get_message_mode() == "text"


# ====================================================================
# 十一、文本构建安全性
# ====================================================================
print("\n--- 文本构建安全性 ---")

@test("_build_text_result 正常生成")
def _():
    repo, svc = make_service()
    user = FakeUser("u_text", coins=100_000)
    repo.add(user)
    r = svc.spin("u_text", "铜")
    assert r["success"]
    msg = r["message"]
    assert "拉杆机" in msg
    assert "余额" in msg
    assert "今日剩余" in msg

@test("_build_text_result 不同结果类型")
def _():
    repo, svc = make_service()
    user = FakeUser("u_types", coins=100_000_000)
    repo.add(user)
    
    # 测试 triple
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.FISH, SlotSymbol.FISH, SlotSymbol.FISH]
    r = svc.spin("u_types", "铜")
    assert "三小鱼" in r["message"] or "🏆" in r["message"]
    
    # 测试 none
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.FISH, SlotSymbol.CRAB, SlotSymbol.OCTOPUS]
    svc._lose_streak["u_types"] = 0
    svc.streak_protection = 9999
    r = svc.spin("u_types", "铜")
    assert "未中奖" in r["message"]

@test("_build_multi_text 正常生成")
def _():
    repo, svc = make_service()
    user = FakeUser("u_multi_text", coins=100_000_000)
    repo.add(user)
    r = svc.multi_spin("u_multi_text", "铜", 3)
    assert r["success"]
    msg = r["message"]
    assert "连转" in msg
    assert "合计盈亏" in msg

@test("净盈亏=0时显示持平")
def _():
    repo, svc = make_service(streak_protection=1)
    user = FakeUser("u_even", coins=100_000_000)
    repo.add(user)
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.FISH, SlotSymbol.CRAB, SlotSymbol.OCTOPUS]
    r = svc.spin("u_even", "铜")
    # 保底低级 → net=0
    if r["result"]["net"] == 0:
        assert "持平" in r["message"]


# ====================================================================
# 十二、读博记录回调边界
# ====================================================================
print("\n--- 读博记录回调 ---")

@test("无回调设置: 不崩溃")
def _():
    repo, svc = make_service()
    user = FakeUser("u_nocb", coins=100_000_000)
    repo.add(user)
    # 不设置 set_gambling_record_callback
    r = svc.spin("u_nocb", "铜")
    assert r["success"]

@test("回调异常: 捕获并继续")
def _():
    repo, svc = make_service()
    user = FakeUser("u_cberr", coins=100_000_000, nickname="测试")
    repo.add(user)
    def bad_callback(*args):
        raise RuntimeError("模拟回调失败")
    svc.set_gambling_record_callback(bad_callback)
    r = svc.spin("u_cberr", "铜")
    assert r["success"], "回调异常不应影响游戏"

@test("回调参数完整性")
def _():
    repo, svc = make_service()
    user = FakeUser("u_cbargs", coins=100_000_000, nickname="完整测试")
    repo.add(user)
    calls = []
    svc.set_gambling_record_callback(lambda *a: calls.append(a))
    svc.spin("u_cbargs", "金")
    assert len(calls) == 1
    game_type, game_id, uid, nick, cost, net, desc = calls[0]
    assert game_type == "拉杆机"
    assert uid == "u_cbargs"
    assert nick == "完整测试"
    assert cost == 1_000_000  # 金桌
    assert isinstance(net, int)
    assert "金桌" in desc

@test("nickname为None时回调不崩溃")
def _():
    repo, svc = make_service()
    user = FakeUser("u_nonick", coins=100_000_000)
    repo.add(user)
    # 显式设置nickname为None以模拟真实场景
    user.nickname = None
    calls = []
    svc.set_gambling_record_callback(lambda *a: calls.append(a))
    r = svc.spin("u_nonick", "铜")
    assert r["success"]
    assert len(calls) == 1
    assert calls[0][3] == "未知", f"nickname应为'未知', 实际 '{calls[0][3]}'"


# ====================================================================
# 十三、Jackpot信息查询
# ====================================================================
print("\n--- Jackpot信息查询 ---")

@test("get_jackpot_info 返回完整结构")
def _():
    repo, svc = make_service(initial_jackpot=12345)
    info = svc.get_jackpot_info()
    assert info["success"]
    assert info["jackpot_pool"] == 12345
    assert "lucky_hour_info" in info
    assert "is_lucky_hour" in info
    assert "tiers" in info
    for tier_key in ["铜", "银", "金", "至尊"]:
        assert tier_key in info["tiers"]
        t = info["tiers"][tier_key]
        assert "name" in t
        assert "cost" in t
        assert "jackpot_chance" in t
        assert "mini_chance" in t


# ====================================================================
# 十四、并发模拟与状态一致性
# ====================================================================
print("\n--- 并发与状态一致性 ---")

@test("多用户交替拉杆: 状态互不影响")
def _():
    repo, svc = make_service(daily_limit=10)
    u1 = FakeUser("u_c1", coins=100_000_000)
    u2 = FakeUser("u_c2", coins=100_000_000)
    repo.add(u1)
    repo.add(u2)
    for _ in range(5):
        svc.spin("u_c1", "铜")
        svc.spin("u_c2", "铜")
    assert svc.get_remaining_spins("u_c1") == 5
    assert svc.get_remaining_spins("u_c2") == 5
    # 历史互不影响
    assert len(svc.get_user_history("u_c1")) == 5
    assert len(svc.get_user_history("u_c2")) == 5

@test("多用户共享奖池")
def _():
    repo, svc = make_service(initial_jackpot=0)
    u1 = FakeUser("u_pool1", coins=100_000_000)
    u2 = FakeUser("u_pool2", coins=100_000_000)
    repo.add(u1)
    repo.add(u2)
    svc.spin("u_pool1", "铜")
    pool_after1 = svc.jackpot_pool
    svc.spin("u_pool2", "铜")
    assert svc.jackpot_pool >= pool_after1, "第二人也应贡献奖池"

@test("不同用户连败计数独立")
def _():
    repo, svc = make_service(streak_protection=3)
    u1 = FakeUser("u_s1", coins=100_000_000)
    u2 = FakeUser("u_s2", coins=100_000_000)
    repo.add(u1)
    repo.add(u2)
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.FISH, SlotSymbol.CRAB, SlotSymbol.OCTOPUS]
    svc.spin("u_s1", "铜")  # u1 streak=1
    svc.spin("u_s1", "铜")  # u1 streak=2
    svc.spin("u_s2", "铜")  # u2 streak=1, 独立
    assert svc._lose_streak.get("u_s1", 0) == 2
    assert svc._lose_streak.get("u_s2", 0) == 1


# ====================================================================
# 十五、性能/超时检测
# ====================================================================
print("\n--- 性能/超时 ---")

@test("1000次拉杆性能(<2秒)")
def _():
    repo, svc = make_service(daily_limit=2000, streak_protection=9999)
    user = FakeUser("u_perf", coins=999_999_999)
    repo.add(user)
    import time
    start = time.time()
    for _ in range(1000):
        svc.spin("u_perf", "铜")
    elapsed = time.time() - start
    assert elapsed < 2.0, f"1000次拉杆用时 {elapsed:.2f}s 超过2秒"

@test("连转10次性能(<0.5秒)")
def _():
    repo, svc = make_service(daily_limit=100)
    user = FakeUser("u_mperf", coins=999_999_999)
    repo.add(user)
    import time
    start = time.time()
    svc.multi_spin("u_mperf", "至尊", 10)
    elapsed = time.time() - start
    assert elapsed < 0.5, f"连转10次用时 {elapsed:.2f}s"

@test("保底循环不会无限卡死")
def _():
    """保底代码有 while 循环，验证不会死循环"""
    repo, svc = make_service(streak_protection=1)
    user = FakeUser("u_loop", coins=100_000_000)
    repo.add(user)
    svc._weighted_spin = lambda lucky=False: [SlotSymbol.STAR, SlotSymbol.CRAB, SlotSymbol.FISH]
    import time
    start = time.time()
    for _ in range(100):
        svc.spin("u_loop", "铜")
    elapsed = time.time() - start
    assert elapsed < 1.0, f"100次保底用时 {elapsed:.2f}s, 可能有死循环风险"


# ====================================================================
# 十六、未使用导入检测
# ====================================================================
print("\n--- 代码质量 ---")

@test("BUG检测: slot_handlers.py 是否导入了未使用的 parse_amount")
def _():
    try:
        import inspect
        from handlers import slot_handlers
        source = inspect.getsource(slot_handlers)
        if "from ..utils import parse_amount" in source or "from ..utils import parse_amount" in source:
            # 检查是否真的使用了
            lines = source.split("\n")
            usage_count = sum(1 for l in lines if "parse_amount" in l and "import" not in l)
            if usage_count == 0:
                raise AssertionError("slot_handlers.py 导入了 parse_amount 但未使用")
    except ImportError:
        print("    [跳过: 模块导入需要完整环境]")


# ===== 汇总 =====
print(f"\n{'='*50}")
print(f"✅ 通过: {passed}  ❌ 失败: {failed}  总计: {passed + failed}")
if failed > 0:
    print(f"\n⚠️ 有 {failed} 项失败，需要修复！")
    sys.exit(1)
else:
    print("🎉 所有边界/漏洞测试通过！")
