"""
自跑测试 - 骰宝玩家开庄 & 21点游戏
验证核心逻辑的正确性
"""

import asyncio
import sys
import os
import types
from unittest.mock import MagicMock
from datetime import datetime, timezone, timedelta

# 插件根目录
PLUGIN_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PLUGIN_ROOT)

# ========== 模拟外部依赖 ==========
# 创建一个假的 astrbot 包层次结构以满足 import
astrbot_mock = types.ModuleType("astrbot")
astrbot_api_mock = types.ModuleType("astrbot.api")
astrbot_api_mock.logger = MagicMock()  # logger 作为模块属性
sys.modules["astrbot"] = astrbot_mock
sys.modules["astrbot.api"] = astrbot_api_mock

# 创建假的 User dataclass 供 domain models 使用（但我们用真正的 core 模块）
# 我们用真实的 core 模块，只需要 mock astrbot


# ========== 模拟用户仓储 ==========
from core.domain.models import User
from core.utils import get_now


def make_user(user_id, nickname, coins=10000):
    """快速创建测试用户"""
    return User(
        user_id=user_id,
        created_at=get_now(),
        nickname=nickname,
        coins=coins,
    )


class MockUserRepo:
    """模拟用户仓储"""
    def __init__(self):
        self.users = {}
    
    def get_by_id(self, user_id):
        return self.users.get(user_id)
    
    def update(self, user):
        self.users[user.user_id] = user
    
    def add(self, user):
        self.users[user.user_id] = user
    
    def check_exists(self, user_id):
        return user_id in self.users
    
    def add_user(self, user_id, nickname, coins):
        user = make_user(user_id, nickname, coins)
        self.users[user_id] = user
        return user


class MockLogRepo:
    """模拟日志仓储"""
    def add_log(self, *args, **kwargs):
        pass


# ========== 测试骰宝玩家开庄 ==========
async def test_sicbo_player_banker():
    """测试骰宝玩家开庄功能"""
    print("\n" + "=" * 60)
    print("🎲 测试骰宝玩家开庄功能")
    print("=" * 60)
    
    from core.services.sicbo_service import SicboService
    
    user_repo = MockUserRepo()
    log_repo = MockLogRepo()
    
    config = {
        "sicbo": {
            "countdown_seconds": 3,  # 测试用短倒计时
            "min_bet": 100,
            "max_bet": 1000000,
            "min_banker_coins": 1000000,
            "message_mode": "text"
        }
    }
    
    service = SicboService(user_repo, log_repo, config)
    
    # 创建测试用户
    banker = user_repo.add_user("banker_001", "大庄家", 2000000)
    player1 = user_repo.add_user("player_001", "玩家A", 500000)
    player2 = user_repo.add_user("player_002", "玩家B", 300000)
    poor_banker = user_repo.add_user("poor_001", "穷庄家", 500000)
    
    # 测试1: 余额不足的玩家不能开庄
    print("\n--- 测试1: 余额不足开庄 ---")
    result = service.start_new_game("session_1", {}, banker_user_id="poor_001")
    assert not result["success"], "穷庄家不应该能开庄"
    print(f"✅ 穷庄家余额 50万 < 最低要求 100万，被拒绝: {result['message']}")
    
    # 测试2: 余额充足的玩家可以开庄
    print("\n--- 测试2: 正常开庄 ---")
    result = service.start_new_game("session_2", {}, banker_user_id="banker_001")
    assert result["success"], "大庄家应该能开庄"
    print(f"✅ 大庄家余额 200万 >= 100万，成功开庄")
    
    # 测试3: 庄家不能给自己下注
    print("\n--- 测试3: 庄家自己下注 ---")
    result = service.place_bet("banker_001", "大", 10000, "session_2")
    assert not result["success"], "庄家不应该能给自己下注"
    print(f"✅ 庄家不能自己下注: {result['message']}")
    
    # 测试4: 玩家正常下注
    print("\n--- 测试4: 玩家下注 ---")
    player1_before = player1.coins
    result = service.place_bet("player_001", "大", 50000, "session_2")
    assert result["success"], "玩家A应该能下注"
    print(f"✅ 玩家A下注 50000 金币, 余额 {player1_before} -> {player1.coins}")
    
    result = service.place_bet("player_002", "小", 30000, "session_2")
    assert result["success"], "玩家B应该能下注"
    print(f"✅ 玩家B下注 30000 金币")
    
    # 测试5: 系统开庄模式
    print("\n--- 测试5: 系统开庄 ---")
    result = service.start_new_game("session_3", {})  # 不传 banker_user_id
    assert result["success"], "系统开庄应该成功"
    game = service.games.get("session_3")
    assert game.banker_user_id is None, "系统开庄不应有庄家用户ID"
    print(f"✅ 系统开庄成功，庄家ID为None")
    
    print("\n✅ 骰宝玩家开庄基础测试通过！")


# ========== 测试骰宝结算逻辑 ==========
async def test_sicbo_settlement():
    """测试骰宝结算逻辑（含庄家资金不足情况）"""
    print("\n" + "=" * 60)
    print("🎲 测试骰宝结算逻辑")
    print("=" * 60)
    
    from core.services.sicbo_service import SicboService
    
    user_repo = MockUserRepo()
    log_repo = MockLogRepo()
    
    config = {
        "sicbo": {
            "countdown_seconds": 10000,
            "min_bet": 100,
            "max_bet": 1000000,
            "min_banker_coins": 100000,
            "message_mode": "text"
        }
    }
    
    service = SicboService(user_repo, log_repo, config)
    
    # 场景1: 庄家资金充足
    print("\n--- 场景1: 庄家资金充足 ---")
    banker = user_repo.add_user("banker_a", "庄家A", 5000000)
    p1 = user_repo.add_user("p1", "选手1", 1000000)
    
    result = service.start_new_game("settle_test_1", {}, banker_user_id="banker_a")
    assert result["success"]
    
    # 选手1赌大 100000
    service.place_bet("p1", "大", 100000, "settle_test_1")
    
    # 手动结算
    game = service.games["settle_test_1"]
    # 取消自动计时（测试中不启动事件循环）
    task = service.countdown_tasks.get("settle_test_1")
    if task:
        task.cancel()
    
    # 强制设置骰子结果并结算
    import random
    random.seed(42)  # 固定随机种子
    
    result = await service._settle_game("settle_test_1")
    print(f"✅ 结算完成:")
    print(f"   庄家余额: {banker.coins:,}")
    print(f"   选手1余额: {p1.coins:,}")
    print(f"   庄家净变化: {result.get('banker_net_change', 'N/A')}")
    
    # 场景2: 庄家资金不足（模拟大额赔付）
    print("\n--- 场景2: 庄家资金不足 ---")
    small_banker = user_repo.add_user("banker_small", "小庄家", 200000)
    big_player = user_repo.add_user("big_p", "大玩家", 5000000)
    
    result = service.start_new_game("settle_test_2", {}, banker_user_id="banker_small")
    assert result["success"]
    
    # 大玩家赌豹子 100000
    service.place_bet("big_p", "豹子", 100000, "settle_test_2")
    
    task = service.countdown_tasks.get("settle_test_2")
    if task:
        task.cancel()
    
    # 通过 monkey-patch random.randint 强制三个相同骰子(豹子)
    original_randint = random.randint
    random.randint = lambda a, b: 3  # 强制所有骰子为3
    
    result2 = await service._settle_game("settle_test_2")
    
    random.randint = original_randint  # 恢复
    
    print(f"   小庄家初始余额: 200,000")
    print(f"   大玩家下注: 100,000 (豹子, 赔率1:24)")
    print(f"   理论赔付: 100,000 × 25 = 2,500,000")
    print(f"   庄家可用: 200,000 + 100,000 = 300,000")
    print(f"   缩减比例: {result2.get('payout_ratio', 'N/A')}")
    print(f"   小庄家最终余额: {small_banker.coins:,}")
    print(f"   大玩家最终余额: {big_player.coins:,}")
    
    # 验证庄家没有变成负数
    assert small_banker.coins >= 0, f"庄家余额不应为负数: {small_banker.coins}"
    print(f"✅ 庄家余额未变负: {small_banker.coins:,}")
    
    print("\n✅ 骰宝结算逻辑测试通过！")


# ========== 测试21点游戏 ==========
async def test_blackjack_basic():
    """测试21点基础功能"""
    print("\n" + "=" * 60)
    print("🃏 测试21点游戏基础功能")
    print("=" * 60)
    
    from core.services.blackjack_service import BlackjackService, Card, CardSuit
    
    user_repo = MockUserRepo()
    log_repo = MockLogRepo()
    
    config = {
        "blackjack": {
            "min_bet": 100,
            "max_bet": 1000000,
            "min_banker_coins": 1000000,
            "join_timeout": 3,
            "action_timeout": 300,
            "message_mode": "text"
        }
    }
    
    service = BlackjackService(user_repo, log_repo, config)
    
    # 创建测试用户
    user_repo.add_user("sys_player", "系统玩家", 500000)
    user_repo.add_user("banker_bj", "21点庄家", 3000000)
    user_repo.add_user("joiner1", "参与者1", 200000)
    user_repo.add_user("joiner2", "参与者2", 200000)
    user_repo.add_user("poor_bj", "穷玩家BJ", 500000)
    
    # 测试1: 系统庄家开局
    print("\n--- 测试1: 系统庄家开局 ---")
    result = service.start_game("bj_session_1", "sys_player", 10000)
    assert result["success"], f"系统庄家开局失败: {result['message']}"
    print(f"✅ 系统庄家开局成功")
    
    # 测试2: 余额不足不能开局
    print("\n--- 测试2: 金币不足 ---")
    result = service.start_game("bj_session_2", "sys_player", 999999999)
    assert not result["success"]
    print(f"✅ 金币不足被拒绝: {result['message']}")
    
    # 测试3: 玩家开庄
    print("\n--- 测试3: 玩家开庄 ---")
    result = service.start_game("bj_session_3", "banker_bj", 0,
                                 is_player_banker=True)
    assert result["success"], f"玩家开庄失败: {result['message']}"
    print(f"✅ 玩家开庄成功: 庄家={result.get('is_player_banker')}")
    
    # 测试4: 余额不足不能当庄
    print("\n--- 测试4: 余额不足当庄 ---")
    result = service.start_game("bj_session_4", "poor_bj", 0,
                                 is_player_banker=True)
    assert not result["success"]
    print(f"✅ 穷玩家被拒绝当庄: {result['message']}")
    
    # 测试5: 加入游戏
    print("\n--- 测试5: 加入游戏 ---")
    result = service.join_game("bj_session_3", "joiner1", 5000)
    assert result["success"], f"加入失败: {result['message']}"
    print(f"✅ 参与者1加入成功")
    
    result = service.join_game("bj_session_3", "joiner2", 10000)
    assert result["success"]
    print(f"✅ 参与者2加入成功")
    
    # 测试6: 庄家不能加入自己的游戏
    print("\n--- 测试6: 庄家自我加入 ---")
    result = service.join_game("bj_session_3", "banker_bj", 5000)
    assert not result["success"]
    print(f"✅ 庄家不能自我加入: {result['message']}")
    
    # 测试7: 重复加入
    print("\n--- 测试7: 重复加入 ---")
    result = service.join_game("bj_session_3", "joiner1", 5000)
    assert not result["success"]
    print(f"✅ 不能重复加入: {result['message']}")
    
    print("\n✅ 21点基础功能测试通过！")


async def test_blackjack_gameplay():
    """测试21点游戏流程"""
    print("\n" + "=" * 60)
    print("🃏 测试21点游戏流程")
    print("=" * 60)
    
    from core.services.blackjack_service import BlackjackService, Card, CardSuit, BlackjackGameState
    
    user_repo = MockUserRepo()
    log_repo = MockLogRepo()
    
    config = {
        "blackjack": {
            "min_bet": 100,
            "max_bet": 1000000,
            "min_banker_coins": 100000,
            "join_timeout": 10000,
            "action_timeout": 10000,
            "message_mode": "text"
        }
    }
    
    service = BlackjackService(user_repo, log_repo, config)
    
    user_repo.add_user("gp_player", "游戏玩家", 500000)
    
    # 开局（系统庄家）
    result = service.start_game("gp_session", "gp_player", 10000)
    assert result["success"]
    
    # 取消加入倒计时
    task = service.countdown_tasks.get("gp_session")
    if task:
        task.cancel()
    
    # 强制开始
    result = await service.force_start("gp_session")
    assert result["success"]
    print(f"✅ 游戏开始发牌")
    print(f"   {result['message']}")
    
    game = service.games["gp_session"]
    player = game.players[0]
    
    # 模拟抽牌
    print(f"\n--- 玩家操作 ---")
    print(f"   当前手牌: {player.hand_display()}")
    
    # 抽一张牌
    if player.hand_value() < 17:
        # 取消超时
        old_task = service.action_tasks.get("gp_session")
        if old_task:
            old_task.cancel()
        
        result = await service.hit("gp_session", "gp_player")
        print(f"   抽牌后: {result['message']}")
    
    # 停牌
    if game.state == BlackjackGameState.IN_PROGRESS:
        old_task = service.action_tasks.get("gp_session")
        if old_task:
            old_task.cancel()
        
        result = await service.stand("gp_session", "gp_player")
        print(f"   停牌结果: {result['message']}")
    
    # 检查游戏已结算
    assert game.state == BlackjackGameState.SETTLED, f"游戏应已结算, 实际状态: {game.state}"
    
    final_coins = user_repo.get_by_id("gp_player").coins
    print(f"\n   玩家最终余额: {final_coins:,} (初始 500,000)")
    
    print("\n✅ 21点游戏流程测试通过！")


async def test_blackjack_hand_value():
    """测试21点手牌点数计算"""
    print("\n" + "=" * 60)
    print("🃏 测试21点手牌点数计算")
    print("=" * 60)
    
    from core.services.blackjack_service import BlackjackPlayer, Card, CardSuit
    
    # 测试1: A + K = 21 (Blackjack)
    p1 = BlackjackPlayer("test", "测试", 0)
    p1.hand = [Card(CardSuit.SPADE, 'A'), Card(CardSuit.HEART, 'K')]
    assert p1.hand_value() == 21, f"A+K应为21, 实际{p1.hand_value()}"
    assert p1.is_blackjack(), "A+K应为Blackjack"
    print(f"✅ A + K = {p1.hand_value()} (Blackjack: {p1.is_blackjack()})")
    
    # 测试2: A + A = 12 (一个A为11，一个为1)
    p2 = BlackjackPlayer("test", "测试", 0)
    p2.hand = [Card(CardSuit.SPADE, 'A'), Card(CardSuit.HEART, 'A')]
    assert p2.hand_value() == 12, f"A+A应为12, 实际{p2.hand_value()}"
    print(f"✅ A + A = {p2.hand_value()}")
    
    # 测试3: A + 5 + 6 = 12 (A为1)
    p3 = BlackjackPlayer("test", "测试", 0)
    p3.hand = [Card(CardSuit.SPADE, 'A'), Card(CardSuit.HEART, '5'), Card(CardSuit.DIAMOND, '6')]
    assert p3.hand_value() == 12, f"A+5+6应为12, 实际{p3.hand_value()}"
    print(f"✅ A + 5 + 6 = {p3.hand_value()}")
    
    # 测试4: K + Q = 20
    p4 = BlackjackPlayer("test", "测试", 0)
    p4.hand = [Card(CardSuit.SPADE, 'K'), Card(CardSuit.HEART, 'Q')]
    assert p4.hand_value() == 20, f"K+Q应为20, 实际{p4.hand_value()}"
    print(f"✅ K + Q = {p4.hand_value()}")
    
    # 测试5: 8 + 7 + 9 = 24 (爆牌)
    p5 = BlackjackPlayer("test", "测试", 0)
    p5.hand = [Card(CardSuit.SPADE, '8'), Card(CardSuit.HEART, '7'), Card(CardSuit.DIAMOND, '9')]
    assert p5.hand_value() == 24, f"8+7+9应为24, 实际{p5.hand_value()}"
    assert p5.is_busted(), "8+7+9应爆牌"
    print(f"✅ 8 + 7 + 9 = {p5.hand_value()} (爆牌: {p5.is_busted()})")
    
    # 测试6: A + 5 = 16 (A为11)
    p6 = BlackjackPlayer("test", "测试", 0)
    p6.hand = [Card(CardSuit.SPADE, 'A'), Card(CardSuit.HEART, '5')]
    assert p6.hand_value() == 16, f"A+5应为16, 实际{p6.hand_value()}"
    print(f"✅ A + 5 = {p6.hand_value()} (A作为11)")
    
    # 测试7: A + 5 + K = 16 (A被迫变为1)
    p7 = BlackjackPlayer("test", "测试", 0)
    p7.hand = [Card(CardSuit.SPADE, 'A'), Card(CardSuit.HEART, '5'), Card(CardSuit.DIAMOND, 'K')]
    assert p7.hand_value() == 16, f"A+5+K应为16, 实际{p7.hand_value()}"
    print(f"✅ A + 5 + K = {p7.hand_value()} (A被迫变成1)")
    
    print("\n✅ 手牌点数计算测试全部通过！")


# ========== 主测试入口 ==========
async def main():
    print("=" * 60)
    print("🔰 钓鱼插件 - 新功能自跑测试")
    print("=" * 60)
    
    passed = 0
    failed = 0
    
    tests = [
        ("骰宝玩家开庄基础", test_sicbo_player_banker),
        ("骰宝结算逻辑", test_sicbo_settlement),
        ("21点手牌计算", test_blackjack_hand_value),
        ("21点基础功能", test_blackjack_basic),
        ("21点游戏流程", test_blackjack_gameplay),
    ]
    
    for name, test_func in tests:
        try:
            result = test_func()
            if asyncio.iscoroutine(result):
                await result
            passed += 1
        except Exception as e:
            failed += 1
            import traceback
            print(f"\n❌ 测试 [{name}] 失败:")
            traceback.print_exc()
    
    print("\n" + "=" * 60)
    print(f"📊 测试结果: {passed} 通过, {failed} 失败, 共 {len(tests)} 个")
    print("=" * 60)
    
    return failed == 0


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
