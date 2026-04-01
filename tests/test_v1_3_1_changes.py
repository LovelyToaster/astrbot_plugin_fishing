"""
v1.3.1 改动自测
覆盖：赌博→读博重命名、默认图片模式、提前开始提示、智能超时、统一读博记录、骰宝开奖记录
"""
import sys, os, asyncio, random
from unittest.mock import MagicMock
from types import ModuleType

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock astrbot 模块
astrbot_mock = ModuleType("astrbot")
astrbot_api_mock = ModuleType("astrbot.api")
astrbot_api_mock.logger = MagicMock()
astrbot_mock.api = astrbot_api_mock
sys.modules["astrbot"] = astrbot_mock
sys.modules["astrbot.api"] = astrbot_api_mock
sys.modules["astrbot.api.event"] = ModuleType("astrbot.api.event")

from core.services.blackjack_service import BlackjackService, BlackjackGame, BlackjackGameState, PlayerState, Card, CardSuit
from core.services.sicbo_service import SicboService


# ===== 公共工厂 =====
class FakeUser:
    def __init__(self, uid, coins=100000, nickname=None):
        self.user_id = uid
        self.nickname = nickname or uid
        self.coins = coins
    def can_afford(self, amount):
        return self.coins >= amount

class FakeUserRepo:
    def __init__(self):
        self.users = {}
    def add(self, u):
        self.users[u.user_id] = u
    def get_by_id(self, uid):
        return self.users.get(uid)
    def update(self, u):
        self.users[u.user_id] = u

class FakeLogRepo:
    def add(self, *a, **kw): pass

def make_services():
    repo = FakeUserRepo()
    log = FakeLogRepo()
    config = {
        "blackjack": {"min_bet": 100, "max_bet": 1000000, "join_timeout": 5,
                       "action_timeout": 2, "min_banker_coins": 1000000},
        "sicbo": {"countdown_seconds": 5, "min_bet": 100, "max_bet": 1000000}
    }
    bj = BlackjackService(repo, log, config)
    sb = SicboService(repo, log, config)
    # 接入统一读博记录
    sb.set_gambling_record_callback(bj._add_gambling_record)
    return repo, bj, sb

def run_async(coro):
    """辅助：在新事件循环中运行协程"""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

async def _start_game_async(bj, *args, **kwargs):
    """在事件循环内调用start_game，避免asyncio.create_task报错"""
    r = bj.start_game(*args, **kwargs)
    # 取消自动创建的倒计时task
    for sid, task in list(bj.countdown_tasks.items()):
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
    return r


# ===== 测试 =====

def test_default_image_mode():
    """21点和骰宝默认都是图片模式"""
    _, bj, sb = make_services()
    assert bj.is_image_mode(), "blackjack should default to image mode"
    assert sb.is_image_mode(), "sicbo should default to image mode"
    print("  ✅ test_default_image_mode")

def test_blackjack_set_message_mode():
    """21点模式切换"""
    _, bj, _ = make_services()
    r = bj.set_message_mode("text")
    assert r["success"]
    assert not bj.is_image_mode()
    r = bj.set_message_mode("image")
    assert r["success"]
    assert bj.is_image_mode()
    r = bj.set_message_mode("invalid")
    assert not r["success"]
    print("  ✅ test_blackjack_set_message_mode")

def test_start_game_has_early_start_hint():
    """开局消息包含 /21点开始 提示"""
    repo, bj, _ = make_services()
    u = FakeUser("p1", 100000, "玩家1")
    repo.add(u)
    r = run_async(_start_game_async(bj, "s1", "p1", 1000, session_info={"unified_msg_origin": "s1"}))
    assert r["success"]
    assert "/21点开始" in r["message"], f"Missing early start hint in: {r['message']}"
    print("  ✅ test_start_game_has_early_start_hint")

def test_start_game_banker_has_early_start_hint():
    """玩家开庄消息包含 /21点开始 提示"""
    repo, bj, _ = make_services()
    u = FakeUser("b1", 2000000, "庄家1")
    repo.add(u)
    r = run_async(_start_game_async(bj, "s2", "b1", 0, session_info={"unified_msg_origin": "s2"}, is_player_banker=True))
    assert r["success"]
    assert "/21点开始" in r["message"], f"Missing early start hint in: {r['message']}"
    print("  ✅ test_start_game_banker_has_early_start_hint")

def test_join_game_has_early_start_hint():
    """加入游戏消息包含 /21点开始 提示"""
    async def _test():
        repo, bj, _ = make_services()
        u1 = FakeUser("b2", 2000000, "庄家2")
        u2 = FakeUser("p2", 100000, "玩家2")
        repo.add(u1)
        repo.add(u2)
        await _start_game_async(bj, "s3", "b2", 0, session_info={"unified_msg_origin": "s3"}, is_player_banker=True)
        r = bj.join_game("s3", "p2", 1000)
        assert r["success"]
        assert "/21点开始" in r["message"], f"Missing early start hint in join message: {r['message']}"
    run_async(_test())
    print("  ✅ test_join_game_has_early_start_hint")

def test_smart_auto_play_low_hand():
    """智能超时：手牌<=11时应自动要牌"""
    async def _test():
        repo, bj, _ = make_services()
        u = FakeUser("p3", 100000, "玩家3")
        repo.add(u)
        await _start_game_async(bj, "s4", "p3", 1000, session_info={"unified_msg_origin": "s4"})
        game = bj.games["s4"]

        game.state = BlackjackGameState.IN_PROGRESS
        player = game.players[0]
        # 设置玩家手牌为3+2=5（<=11, 应自动要牌）
        player.hand = [Card(CardSuit.SPADE, '3'), Card(CardSuit.HEART, '2')]
        player.state = PlayerState.PLAYING
        game.current_player_index = 0
        game.dealer.hand = [Card(CardSuit.DIAMOND, '7'), Card(CardSuit.CLUB, '10')]

        messages = []
        async def mock_cb(session_info, result):
            messages.append(result.get("message", ""))

        bj.message_callback = mock_cb
        await bj._smart_auto_play("s4", game, player)

        combined = "".join(messages) if messages else ""
        assert "自动要牌" in combined or player.state in [PlayerState.STOOD, PlayerState.BUSTED, PlayerState.DOUBLED], \
            f"Smart play should auto-hit with hand value 5, messages: {combined}"
    run_async(_test())
    print("  ✅ test_smart_auto_play_low_hand")

def test_smart_auto_play_high_hand():
    """智能超时：手牌>=17时应自动停牌"""
    async def _test():
        repo, bj, _ = make_services()
        u = FakeUser("p4", 100000, "玩家4")
        repo.add(u)
        await _start_game_async(bj, "s5", "p4", 1000, session_info={"unified_msg_origin": "s5"})
        game = bj.games["s5"]

        game.state = BlackjackGameState.IN_PROGRESS
        player = game.players[0]
        # 设置玩家手牌为10+8=18（>=17, 应自动停牌）
        player.hand = [Card(CardSuit.SPADE, '10'), Card(CardSuit.HEART, '8')]
        player.state = PlayerState.PLAYING
        game.current_player_index = 0
        game.dealer.hand = [Card(CardSuit.DIAMOND, '7'), Card(CardSuit.CLUB, '10')]

        messages = []
        async def mock_cb(session_info, result):
            messages.append(result.get("message", ""))

        bj.message_callback = mock_cb
        await bj._smart_auto_play("s5", game, player)

        combined = "".join(messages) if messages else ""
        assert "自动停牌" in combined, f"Should auto-stand with hand 18, got: {combined}"
        assert len(player.hand) == 2, "Should not draw any cards with hand value 18"
    run_async(_test())
    print("  ✅ test_smart_auto_play_high_hand")

def test_gambling_records_include_sicbo():
    """读博记录应包含骰宝和21点"""
    repo, bj, sb = make_services()
    
    # 直接写入21点记录
    bj._add_gambling_record("21点", "bj_test", "u1", "测试者", 1000, 500, "胜利")
    
    # 通过回调写入骰宝记录
    sb._gambling_record_callback("骰宝", "sb_test", "u1", "测试者", 500, -500, "骰子[1,2,3]=6点 输")
    
    records = bj.get_user_gambling_records("u1", 5)
    assert len(records) == 2, f"Should have 2 records, got {len(records)}"
    types = {r["game_type"] for r in records}
    assert "21点" in types, "Should have 21点 record"
    assert "骰宝" in types, "Should have 骰宝 record"
    print("  ✅ test_gambling_records_include_sicbo")

def test_gambling_records_top5():
    """读博记录默认只返回Top5"""
    repo, bj, _ = make_services()
    for i in range(10):
        bj._add_gambling_record("21点", f"bj_{i}", "u2", "测试者2", 100, i * 100, f"第{i}局")
    records = bj.get_user_gambling_records("u2", 5)
    assert len(records) == 5, f"Should return 5 records, got {len(records)}"
    # 应该是最近5条
    assert records[-1]["detail"] == "第9局"
    print("  ✅ test_gambling_records_top5")

def test_sicbo_draw_history():
    """骰宝开奖记录应按session存储"""
    repo, bj, sb = make_services()
    u = FakeUser("p5", 100000, "玩家5")
    repo.add(u)
    
    # 手动写入draw_history
    from datetime import datetime
    for i in range(7):
        dice = [random.randint(1, 6) for _ in range(3)]
        total = sum(dice)
        dice_emojis = {1: '⚀', 2: '⚁', 3: '⚂', 4: '⚃', 5: '⚄', 6: '⚅'}
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dice": dice,
            "dice_display": " ".join(dice_emojis[d] for d in dice),
            "total": total,
            "big_small": "大" if total >= 11 else "小",
            "odd_even": "双" if total % 2 == 0 else "单",
            "is_triple": dice[0] == dice[1] == dice[2],
            "game_id": f"sb_{i}",
            "participants": 2,
        }
        if "group1" not in sb.draw_history:
            sb.draw_history["group1"] = []
        sb.draw_history["group1"].append(record)
    
    # 默认取5条
    history = sb.get_draw_history("group1", 5)
    assert len(history) == 5, f"Should return 5, got {len(history)}"
    
    # 另一个群没有记录
    history2 = sb.get_draw_history("group2", 5)
    assert len(history2) == 0, "Different group should have no records"
    print("  ✅ test_sicbo_draw_history")

def test_no_gambling_text_in_user_facing():
    """确认用户可见文本中不再包含 '赌博'"""
    files_to_check = [
        os.path.join(os.path.dirname(__file__), "..", "handlers", "blackjack_handlers.py"),
        os.path.join(os.path.dirname(__file__), "..", "main.py"),
    ]
    for fpath in files_to_check:
        with open(fpath, encoding="utf-8") as f:
            content = f.read()
        # 检查用户可见字符串中的赌博
        # 忽略变量名如 gambling_records（英文）
        import re
        # 找到所有中文 "赌博" 
        matches = re.findall(r'赌博', content)
        assert len(matches) == 0, f"Found '赌博' in {os.path.basename(fpath)}: {len(matches)} occurrences"
    print("  ✅ test_no_gambling_text_in_user_facing")


if __name__ == "__main__":
    print("🧪 v1.3.1 改动自测开始...\n")
    test_default_image_mode()
    test_blackjack_set_message_mode()
    test_start_game_has_early_start_hint()
    test_start_game_banker_has_early_start_hint()
    test_join_game_has_early_start_hint()
    test_smart_auto_play_low_hand()
    test_smart_auto_play_high_hand()
    test_gambling_records_include_sicbo()
    test_gambling_records_top5()
    test_sicbo_draw_history()
    test_no_gambling_text_in_user_facing()
    print(f"\n🎉 全部 11 项测试通过！")
