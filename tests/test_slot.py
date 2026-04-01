"""
拉杆机 (Slot Machine) 自测
覆盖：核心随机算法、赔付计算、保底机制、每日限额、奖池、幸运时段、连转、读博记录集成
"""
import sys, os, time
from unittest.mock import MagicMock
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
    TWO_SAME_PAYOUTS, DEFAULT_TIERS,
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
        "message_mode": "text",
        "initial_jackpot": overrides.get("initial_jackpot", 0),
    }}
    svc = SlotService(repo, log, config)
    return repo, svc


# ===== 测试 =====
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
            print(f"  ❌ {name}: {e}")
            failed += 1
    return decorator


print("🎰 拉杆机测试套件\n")

# ----- 1. 权重总和正确 -----
@test("权重总和 = 1000")
def _():
    assert sum(SYMBOL_WEIGHTS.values()) == 1000

# ----- 2. 赔率表完整 -----
@test("三同赔率表覆盖所有符号")
def _():
    for s in SlotSymbol:
        assert s in TRIPLE_PAYOUTS, f"缺少 {s.label}"
        assert s in TWO_SAME_PAYOUTS, f"缺少 {s.label}"

# ----- 3. 基本拉杆成功 -----
@test("铜桌拉杆成功并扣费")
def _():
    repo, svc = make_service()
    user = FakeUser("u1", coins=100_000)
    repo.add(user)
    result = svc.spin("u1", "铜")
    assert result["success"], result.get("message")
    assert result["cost"] == 10_000
    # 余额应该发生变化
    u = repo.get_by_id("u1")
    assert u.coins != 100_000 or result["payout"] == 10_000  # 如果恰好 payout==cost 则余额不变

# ----- 4. 余额不足 -----
@test("余额不足应失败")
def _():
    repo, svc = make_service()
    user = FakeUser("u2", coins=5000)
    repo.add(user)
    result = svc.spin("u2", "铜")  # 铜桌 10000
    assert not result["success"]
    assert "不足" in result["message"]

# ----- 5. 未注册用户 -----
@test("未注册用户应失败")
def _():
    repo, svc = make_service()
    result = svc.spin("nobody", "铜")
    assert not result["success"]
    assert "注册" in result["message"]

# ----- 6. 无效档位 -----
@test("无效档位应失败")
def _():
    repo, svc = make_service()
    user = FakeUser("u3", coins=10_000_000)
    repo.add(user)
    result = svc.spin("u3", "钻石")
    assert not result["success"]
    assert "未知" in result["message"]

# ----- 7. 每日限额 -----
@test("每日限额耗尽后应拒绝")
def _():
    repo, svc = make_service(daily_limit=3)
    user = FakeUser("u4", coins=10_000_000)
    repo.add(user)
    for i in range(3):
        r = svc.spin("u4", "铜")
        assert r["success"], f"第{i+1}次应成功"
    r = svc.spin("u4", "铜")
    assert not r["success"]
    assert "用完" in r["message"]

# ----- 8. 保底机制 -----
@test("保底机制：连续失败后保底触发")
def _():
    repo, svc = make_service(streak_protection=5)
    user = FakeUser("u5", coins=100_000_000)
    repo.add(user)
    # 强制连败计数到阈值
    svc._lose_streak["u5"] = 4  # 再失败一次就保底
    # 覆盖随机以产生三不同
    original_spin = svc._weighted_spin
    def fake_spin(lucky=False):
        return [SlotSymbol.FISH, SlotSymbol.CRAB, SlotSymbol.OCTOPUS]
    svc._weighted_spin = fake_spin
    r = svc.spin("u5", "铜")
    svc._weighted_spin = original_spin
    assert r["success"]
    rd = r["result"]
    # 保底应该是 double 类型
    assert rd["match_type"] == "double", f"保底应为 double，实际 {rd['match_type']}"
    assert "保底" in rd["match_desc"]

# ----- 9. 奖池累积 -----
@test("每次拉杆贡献金币到奖池")
def _():
    repo, svc = make_service(initial_jackpot=0)
    user = FakeUser("u6", coins=10_000_000)
    repo.add(user)
    before_pool = svc.jackpot_pool
    svc.spin("u6", "铜")
    # 铜桌贡献率 2%，cost 10000 → 贡献 200
    assert svc.jackpot_pool > before_pool

# ----- 10. 连转模式 -----
@test("连转模式正常执行")
def _():
    repo, svc = make_service(daily_limit=50)
    user = FakeUser("u7", coins=100_000_000)
    repo.add(user)
    r = svc.multi_spin("u7", "铜", 5)
    assert r["success"]
    assert r["count"] == 5
    assert len(r["results"]) == 5

# ----- 11. 连转超过限额 -----
@test("连转次数受每日限额约束")
def _():
    repo, svc = make_service(daily_limit=3)
    user = FakeUser("u8", coins=100_000_000)
    repo.add(user)
    r = svc.multi_spin("u8", "铜", 10)
    assert r["success"]
    assert r["count"] == 3  # 被限制到3次

# ----- 12. 幸运时段信息 -----
@test("幸运时段信息可获取")
def _():
    repo, svc = make_service()
    info = svc.get_lucky_hour_info()
    assert ":" in info  # 格式如 "14:00 - 16:00"

# ----- 13. 历史记录存储 -----
@test("拉杆记录被正确存储")
def _():
    repo, svc = make_service()
    user = FakeUser("u9", coins=10_000_000)
    repo.add(user)
    svc.spin("u9", "铜")
    svc.spin("u9", "铜")
    records = svc.get_user_history("u9")
    assert len(records) == 2

# ----- 14. 读博记录回调 -----
@test("读博记录回调被触发")
def _():
    repo, svc = make_service()
    user = FakeUser("u10", coins=10_000_000, nickname="测试玩家")
    repo.add(user)
    callback_calls = []
    def fake_callback(*args):
        callback_calls.append(args)
    svc.set_gambling_record_callback(fake_callback)
    svc.spin("u10", "铜")
    assert len(callback_calls) == 1
    # 检查回调参数
    call = callback_calls[0]
    assert call[0] == "拉杆机"  # game_type
    assert call[2] == "u10"  # user_id

# ----- 15. 消息模式切换 -----
@test("消息模式切换")
def _():
    repo, svc = make_service()
    assert svc.get_message_mode() == "text"  # 测试用 text
    r = svc.set_message_mode("image")
    assert r["success"]
    assert svc.is_image_mode()
    r = svc.set_message_mode("text")
    assert r["success"]
    assert not svc.is_image_mode()
    r = svc.set_message_mode("invalid")
    assert not r["success"]

# ----- 16. 至尊桌价格正确 -----
@test("至尊桌价格为500万")
def _():
    assert DEFAULT_TIERS["至尊"].cost == 5_000_000

# ----- 17. 三同赔付正确 -----
@test("三同赔付计算正确")
def _():
    repo, svc = make_service()
    user = FakeUser("u11", coins=100_000_000)
    repo.add(user)
    # 覆盖随机以产生三海星
    original_spin = svc._weighted_spin
    def fake_triple(lucky=False):
        return [SlotSymbol.STAR, SlotSymbol.STAR, SlotSymbol.STAR]
    svc._weighted_spin = fake_triple
    r = svc.spin("u11", "铜")
    svc._weighted_spin = original_spin
    assert r["success"]
    rd = r["result"]
    assert rd["match_type"] == "triple"
    assert rd["payout_multiplier"] == 250
    assert r["payout"] == 10_000 * 250  # 2,500,000

# ----- 18. Jackpot 触发 -----
@test("Jackpot 触发时清空奖池")
def _():
    repo, svc = make_service(initial_jackpot=10_000_000)
    user = FakeUser("u12", coins=100_000_000)
    repo.add(user)
    # 强制 jackpot 触发
    original_check = svc._check_jackpot
    svc._check_jackpot = lambda tier: (True, False)
    r = svc.spin("u12", "至尊")
    svc._check_jackpot = original_check
    assert r["success"]
    rd = r["result"]
    assert rd["match_type"] == "jackpot"
    assert rd["jackpot_win"] > 0
    # 奖池应被清空（但本次拉杆又贡献了一些）
    # jackpot_pool 在 spin 中先加 contribution 再检查，所以清空后只剩 contribution
    assert svc.jackpot_pool < 10_000_000

# ----- 19. 两同赔付 -----
@test("两海星赔付 ×5")
def _():
    repo, svc = make_service()
    user = FakeUser("u13", coins=100_000_000)
    repo.add(user)
    original_spin = svc._weighted_spin
    def fake_double(lucky=False):
        return [SlotSymbol.STAR, SlotSymbol.STAR, SlotSymbol.FISH]
    svc._weighted_spin = fake_double
    r = svc.spin("u13", "铜")
    svc._weighted_spin = original_spin
    assert r["success"]
    rd = r["result"]
    assert rd["match_type"] == "double"
    assert rd["payout_multiplier"] == 5

# ----- 20. 统计学验证(小概率) -----
@test("1000次拉杆系统回收率在预期范围")
def _():
    repo, svc = make_service(daily_limit=2000, streak_protection=100)
    user = FakeUser("u14", coins=999_999_999)
    repo.add(user)
    initial = user.coins
    for _ in range(1000):
        svc.spin("u14", "铜")
    u = repo.get_by_id("u14")
    total_spent = 10_000 * 1000  # 1000万
    final = u.coins
    return_rate = (final - initial + total_spent) / total_spent
    # 理论期望回报率约 96%（三同贡献~45% + 两同贡献~51%），含保底和方差
    assert 0.6 < return_rate < 1.3, f"回报率 {return_rate:.2%} 超出预期范围"


# ===== 汇总 =====
print(f"\n{'='*40}")
print(f"✅ 通过: {passed}  ❌ 失败: {failed}  总计: {passed + failed}")
if failed > 0:
    sys.exit(1)
else:
    print("🎉 所有测试通过！")
