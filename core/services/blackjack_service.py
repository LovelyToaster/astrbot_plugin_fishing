"""
21点（Blackjack）游戏服务
支持系统庄家和玩家庄家，支持多人对战（最多6人）
"""

import asyncio
import random
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Tuple
from dataclasses import dataclass, field
from enum import Enum

from ..utils import get_now
from ..repositories.abstract_repository import AbstractUserRepository, AbstractLogRepository
from astrbot.api import logger


class CardSuit(Enum):
    """花色"""
    SPADE = "♠"
    HEART = "♥"
    DIAMOND = "♦"
    CLUB = "♣"


class PlayerState(Enum):
    """玩家状态"""
    WAITING = "waiting"        # 等待操作
    PLAYING = "playing"        # 正在操作（当前轮到的玩家）
    STOOD = "stood"            # 已停牌
    BUSTED = "busted"          # 爆牌
    BLACKJACK = "blackjack"    # 天牌21点
    DOUBLED = "doubled"        # 已加倍（只能再抽一张）


@dataclass
class Card:
    """一张牌"""
    suit: CardSuit
    rank: str  # A, 2-10, J, Q, K
    
    @property
    def value(self) -> int:
        """获取牌面值（A按1算，后续手牌计算中处理11的情况）"""
        if self.rank in ['J', 'Q', 'K']:
            return 10
        elif self.rank == 'A':
            return 11  # 默认按11，在hand_value中处理
        else:
            return int(self.rank)
    
    def display(self) -> str:
        """显示牌面"""
        return f"{self.suit.value}{self.rank}"
    
    def emoji(self) -> str:
        """显示带花色的emoji版"""
        suit_colors = {
            CardSuit.SPADE: "♠️",
            CardSuit.HEART: "♥️",
            CardSuit.DIAMOND: "♦️",
            CardSuit.CLUB: "♣️"
        }
        return f"{suit_colors[self.suit]}{self.rank}"


@dataclass
class BlackjackPlayer:
    """21点玩家"""
    user_id: str
    nickname: str
    bet_amount: int
    hand: List[Card] = field(default_factory=list)
    state: PlayerState = PlayerState.WAITING
    is_banker: bool = False
    # 加倍 (Double Down)
    is_doubled: bool = False
    # 分牌 (Split)
    split_hand: Optional[List[Card]] = None  # 分牌后的第二手牌
    split_bet: int = 0  # 分牌的额外下注
    is_split: bool = False  # 是否已经分牌
    playing_split_hand: bool = False  # 当前是否在操作分牌手
    split_state: PlayerState = PlayerState.WAITING  # 分牌手的状态
    # 保险 (Insurance)
    insurance_bet: int = 0  # 保险下注金额
    has_insurance: bool = False
    
    def _calc_hand_value(self, cards: List[Card]) -> int:
        """计算指定手牌的点数"""
        total = 0
        aces = 0
        for card in cards:
            if card.rank == 'A':
                aces += 1
                total += 11
            else:
                total += card.value
        while total > 21 and aces > 0:
            total -= 10
            aces -= 1
        return total
    
    def hand_value(self) -> int:
        """计算主手牌点数，A可以是1或11"""
        return self._calc_hand_value(self.hand)
    
    def split_hand_value(self) -> int:
        """计算分牌手的点数"""
        if self.split_hand:
            return self._calc_hand_value(self.split_hand)
        return 0
    
    def is_busted(self) -> bool:
        return self.hand_value() > 21
    
    def is_split_busted(self) -> bool:
        if self.split_hand:
            return self.split_hand_value() > 21
        return False
    
    def is_blackjack(self) -> bool:
        """判断是否天牌21点（两张牌恰好21点，分牌后不算天牌）"""
        return len(self.hand) == 2 and self.hand_value() == 21 and not self.is_split
    
    def can_split(self) -> bool:
        """判断是否可以分牌（两张同点数，且未分过牌）"""
        if self.is_split or len(self.hand) != 2:
            return False
        return self.hand[0].value == self.hand[1].value
    
    def can_double_down(self) -> bool:
        """判断是否可以加倍（只有两张牌且未分牌操作中）"""
        if self.is_doubled:
            return False
        if self.playing_split_hand:
            return self.split_hand is not None and len(self.split_hand) == 2
        return len(self.hand) == 2
    
    def hand_display(self) -> str:
        """显示手牌"""
        cards = " ".join([c.emoji() for c in self.hand])
        display = f"{cards} ({self.hand_value()}点)"
        if self.is_doubled:
            display += " [加倍]"
        return display
    
    def split_hand_display(self) -> str:
        """显示分牌手"""
        if self.split_hand:
            cards = " ".join([c.emoji() for c in self.split_hand])
            return f"{cards} ({self.split_hand_value()}点)"
        return ""

    def is_active(self) -> bool:
        """判断玩家是否处于可操作状态（主手或分牌手正在操作中）"""
        if self.playing_split_hand:
            return self.split_state == PlayerState.PLAYING
        return self.state == PlayerState.PLAYING


class BlackjackGameState(Enum):
    """游戏状态"""
    WAITING_PLAYERS = "waiting"   # 等待玩家加入
    IN_PROGRESS = "in_progress"   # 游戏进行中
    SETTLED = "settled"           # 已结算


@dataclass
class BlackjackGame:
    """21点游戏房间"""
    game_id: str
    session_id: str
    start_time: datetime
    join_deadline: datetime        # 加入截止时间
    state: BlackjackGameState = BlackjackGameState.WAITING_PLAYERS
    deck: List[Card] = field(default_factory=list)
    players: List[BlackjackPlayer] = field(default_factory=list)
    dealer: Optional[BlackjackPlayer] = None  # 庄家（系统或玩家）
    current_player_index: int = 0
    is_system_dealer: bool = True  # 是否系统庄家
    banker_user_id: Optional[str] = None
    banker_nickname: Optional[str] = None
    session_info: Optional[Dict[str, Any]] = None
    max_players: int = 7  # 最多7人（含庄家）
    min_bet: int = 100
    settled: bool = False
    action_timeout_task: Optional[asyncio.Task] = None
    insurance_offered: bool = False  # 是否已提供过保险选项


class BlackjackService:
    """21点游戏服务"""
    
    def __init__(self, user_repo: AbstractUserRepository, log_repo: AbstractLogRepository, config: Dict[str, Any]):
        self.user_repo = user_repo
        self.log_repo = log_repo
        self.config = config
        
        blackjack_config = config.get("blackjack", {})
        self.min_bet = blackjack_config.get("min_bet", 100)
        self.max_bet = blackjack_config.get("max_bet", 1000000)
        self.join_timeout = blackjack_config.get("join_timeout", 60)  # 加入等待时间
        self.action_timeout = blackjack_config.get("action_timeout", 30)  # 操作超时时间
        self.min_banker_coins = blackjack_config.get("min_banker_coins", 1000000)
        self.message_mode = blackjack_config.get("message_mode", "image")
        
        # 连胜/连败配置
        self.streak_win_bonus_threshold = blackjack_config.get("streak_win_bonus_threshold", 3)
        self.streak_win_bonus_rate = blackjack_config.get("streak_win_bonus_rate", 0.1)
        self.streak_lose_consolation_threshold = blackjack_config.get("streak_lose_consolation_threshold", 3)
        self.streak_lose_consolation = blackjack_config.get("streak_lose_consolation", 500)
        
        # 游戏存储
        self.games: Dict[str, BlackjackGame] = {}
        self.countdown_tasks: Dict[str, asyncio.Task] = {}
        self.action_tasks: Dict[str, asyncio.Task] = {}
        
        # 连胜/连败追踪  {user_id: {"wins": int, "losses": int}}
        self.streaks: Dict[str, Dict[str, int]] = {}
        
        # 读博历史记录  [{time, game_type, game_id, user_id, nickname, bet, profit, detail}, ...]
        self.gambling_records: List[Dict[str, Any]] = []
        self.max_records = 500  # 最多保留500条
        
        # 消息回调
        self.message_callback = None
    
    def is_image_mode(self) -> bool:
        """是否使用图片模式"""
        return self.message_mode == "image"
    
    def set_message_mode(self, mode: str) -> Dict[str, Any]:
        """设置消息模式"""
        if mode not in ["image", "text"]:
            return {"success": False, "message": "❌ 无效的消息模式，请使用 'image' 或 'text'"}
        
        self.message_mode = mode
        mode_name = "图片模式" if mode == "image" else "文本模式"
        return {
            "success": True,
            "message": f"✅ 21点消息模式已设置为 {mode_name}"
        }
    
    def get_message_mode(self) -> str:
        """获取当前消息模式"""
        return self.message_mode
    
    def set_message_callback(self, callback):
        """设置消息发送回调函数"""
        self.message_callback = callback
    
    def _update_streak(self, user_id: str, won: bool):
        """更新连胜/连败记录"""
        if user_id not in self.streaks:
            self.streaks[user_id] = {"wins": 0, "losses": 0}
        
        if won:
            self.streaks[user_id]["wins"] += 1
            self.streaks[user_id]["losses"] = 0
        else:
            self.streaks[user_id]["losses"] += 1
            self.streaks[user_id]["wins"] = 0
    
    def _get_streak_bonus(self, user_id: str, profit: int) -> Tuple[int, str]:
        """计算连胜/连败奖励，返回 (奖励金额, 描述文本)"""
        streak = self.streaks.get(user_id, {"wins": 0, "losses": 0})
        
        if profit > 0 and streak["wins"] >= self.streak_win_bonus_threshold:
            bonus = int(profit * self.streak_win_bonus_rate)
            return bonus, f"🔥 连胜{streak['wins']}局！额外奖励 +{bonus:,} 金币"
        elif profit < 0 and streak["losses"] >= self.streak_lose_consolation_threshold:
            consolation = self.streak_lose_consolation
            return consolation, f"💫 连败{streak['losses']}局，安慰奖 +{consolation:,} 金币"
        
        return 0, ""
    
    def _add_gambling_record(self, game_type: str, game_id: str, user_id: str,
                             nickname: str, bet: int, profit: int, detail: str):
        """添加读博历史记录"""
        record = {
            "time": get_now().strftime("%Y-%m-%d %H:%M:%S"),
            "game_type": game_type,
            "game_id": game_id,
            "user_id": user_id,
            "nickname": nickname,
            "bet": bet,
            "profit": profit,
            "detail": detail
        }
        self.gambling_records.append(record)
        # 超出上限则移除最旧的
        if len(self.gambling_records) > self.max_records:
            self.gambling_records = self.gambling_records[-self.max_records:]
    
    def get_user_gambling_records(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """获取用户的读博历史记录"""
        user_records = [r for r in self.gambling_records if r["user_id"] == user_id]
        return user_records[-limit:]  # 取最近N条
    
    def _create_deck(self, num_decks: int = 2) -> List[Card]:
        """创建并洗牌"""
        deck = []
        for _ in range(num_decks):
            for suit in CardSuit:
                for rank in ['A', '2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K']:
                    deck.append(Card(suit=suit, rank=rank))
        random.shuffle(deck)
        return deck
    
    def _draw_card(self, game: BlackjackGame) -> Card:
        """从牌堆抽一张牌"""
        if not game.deck:
            game.deck = self._create_deck()
        return game.deck.pop()
    
    def start_game(self, session_id: str, user_id: str, bet_amount: int,
                   session_info: Dict[str, Any] = None,
                   is_player_banker: bool = False) -> Dict[str, Any]:
        """
        开始21点游戏
        
        Args:
            session_id: 会话ID
            user_id: 发起者用户ID
            bet_amount: 下注金额
            session_info: 会话信息
            is_player_banker: 是否玩家开庄
        """
        # 检查是否有进行中的游戏
        current_game = self.games.get(session_id)
        if current_game and current_game.state != BlackjackGameState.SETTLED:
            return {"success": False, "message": "❌ 当前会话已有21点游戏进行中"}
        
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "❌ 用户不存在，请先注册"}
        
        if is_player_banker:
            # 玩家开庄模式
            if user.coins < self.min_banker_coins:
                return {
                    "success": False,
                    "message": f"❌ 玩家开庄需要至少 {self.min_banker_coins:,} 金币\n"
                              f"💰 你当前余额：{user.coins:,} 金币"
                }
            
            now = get_now()
            game_id = f"bj_{session_id}_{now.strftime('%Y%m%d_%H%M%S')}"
            
            game = BlackjackGame(
                game_id=game_id,
                session_id=session_id,
                start_time=now,
                join_deadline=now + timedelta(seconds=self.join_timeout),
                deck=self._create_deck(),
                is_system_dealer=False,
                banker_user_id=user_id,
                banker_nickname=user.nickname or user_id,
                session_info=session_info,
                min_bet=self.min_bet
            )
            
            # 庄家作为dealer
            game.dealer = BlackjackPlayer(
                user_id=user_id,
                nickname=user.nickname or user_id,
                bet_amount=0,
                is_banker=True
            )
            
            self.games[session_id] = game
            
            # 启动加入倒计时
            self.countdown_tasks[session_id] = asyncio.create_task(
                self._join_countdown(session_id)
            )
            
            return {
                "success": True,
                "message": f"🃏 21点游戏开桌！\n"
                          f"🏦 庄家：{user.nickname or user_id}\n"
                          f"⏰ {self.join_timeout}秒内可加入\n"
                          f"💰 最低下注：{self.min_bet:,} 金币\n"
                          f"👥 最多可加入 6 名玩家\n\n"
                          f"📋 输入 /21点加入 [金额] 加入游戏\n"
                          f"⏩ 输入 /21点开始 可跳过等待提前开始\n"
                          f"🃏 加入后输入 /抽牌 要牌，/停牌 停止要牌\n"
                          f"💡 输入 /21点帮助 查看完整规则（含加倍/分牌/保险等）",
                "game_id": game_id,
                "is_player_banker": True
            }
        else:
            # 系统庄家模式 - 单人游戏或等待玩家加入
            if bet_amount < self.min_bet:
                return {"success": False, "message": f"❌ 最低下注 {self.min_bet:,} 金币"}
            
            if bet_amount > self.max_bet:
                return {"success": False, "message": f"❌ 最高下注 {self.max_bet:,} 金币"}
            
            if not user.can_afford(bet_amount):
                return {"success": False, "message": f"❌ 金币不足！当前 {user.coins:,} 金币"}
            
            now = get_now()
            game_id = f"bj_{session_id}_{now.strftime('%Y%m%d_%H%M%S')}"
            
            game = BlackjackGame(
                game_id=game_id,
                session_id=session_id,
                start_time=now,
                join_deadline=now + timedelta(seconds=self.join_timeout),
                deck=self._create_deck(),
                is_system_dealer=True,
                session_info=session_info,
                min_bet=self.min_bet
            )
            
            # 系统庄家
            game.dealer = BlackjackPlayer(
                user_id="SYSTEM",
                nickname="庄家",
                bet_amount=0,
                is_banker=True
            )
            
            # 扣除发起者的金币并加入
            user.coins -= bet_amount
            self.user_repo.update(user)
            
            player = BlackjackPlayer(
                user_id=user_id,
                nickname=user.nickname or user_id,
                bet_amount=bet_amount
            )
            game.players.append(player)
            
            self.games[session_id] = game
            
            # 启动加入倒计时
            self.countdown_tasks[session_id] = asyncio.create_task(
                self._join_countdown(session_id)
            )
            
            return {
                "success": True,
                "message": f"🃏 21点游戏开桌！\n"
                          f"🏦 庄家：系统\n"
                          f"👤 {user.nickname or user_id} 下注 {bet_amount:,} 金币加入\n"
                          f"⏰ {self.join_timeout}秒内其他玩家可加入\n"
                          f"💰 最低下注：{self.min_bet:,} 金币\n"
                          f"👥 最多可加入 6 名玩家\n\n"
                          f"📋 输入 /21点加入 [金额] 加入游戏\n"
                          f"⏩ 输入 /21点开始 可跳过等待提前开始\n"
                          f"💡 无人加入则自动开始单人游戏\n"
                          f"💡 输入 /21点帮助 查看完整规则（含加倍/分牌/保险等）",
                "game_id": game_id,
                "is_player_banker": False
            }
    
    def join_game(self, session_id: str, user_id: str, bet_amount: int) -> Dict[str, Any]:
        """加入21点游戏"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": "❌ 当前没有21点游戏等待加入"}
        
        if game.state != BlackjackGameState.WAITING_PLAYERS:
            return {"success": False, "message": "❌ 游戏已开始，无法加入"}
        
        # 检查截止时间
        if get_now() > game.join_deadline:
            return {"success": False, "message": "❌ 加入时间已过"}
        
        # 检查庄家不能自己加入
        if game.banker_user_id and user_id == game.banker_user_id:
            return {"success": False, "message": "❌ 庄家不能作为玩家加入"}
        
        # 检查是否已加入
        for p in game.players:
            if p.user_id == user_id:
                return {"success": False, "message": "❌ 你已经在游戏中了"}
        
        # 检查人数上限（不含庄家）
        if len(game.players) >= 6:
            return {"success": False, "message": "❌ 游戏人数已满（最多6名玩家）"}
        
        # 检查下注金额
        if bet_amount < game.min_bet:
            return {"success": False, "message": f"❌ 最低下注 {game.min_bet:,} 金币"}
        
        if bet_amount > self.max_bet:
            return {"success": False, "message": f"❌ 最高下注 {self.max_bet:,} 金币"}
        
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "❌ 用户不存在，请先注册"}
        
        if not user.can_afford(bet_amount):
            return {"success": False, "message": f"❌ 金币不足！当前 {user.coins:,} 金币"}
        
        # 扣除金币
        user.coins -= bet_amount
        self.user_repo.update(user)
        
        player = BlackjackPlayer(
            user_id=user_id,
            nickname=user.nickname or user_id,
            bet_amount=bet_amount
        )
        game.players.append(player)
        
        return {
            "success": True,
            "message": f"✅ {user.nickname or user_id} 加入游戏！\n"
                      f"💰 下注：{bet_amount:,} 金币\n"
                      f"👥 当前 {len(game.players)}/6 名玩家\n"
                      f"⏩ 输入 /21点开始 可跳过等待提前开始\n"
                      f"⏰ 等待其他玩家加入..."
        }
    
    async def _join_countdown(self, session_id: str):
        """加入等待倒计时"""
        try:
            await asyncio.sleep(self.join_timeout)
            game = self.games.get(session_id)
            if game and game.state == BlackjackGameState.WAITING_PLAYERS:
                if not game.players:
                    # 无人加入，取消游戏
                    game.state = BlackjackGameState.SETTLED
                    game.settled = True
                    if self.message_callback and game.session_info:
                        await self.message_callback(
                            game.session_info,
                            {"success": True, "message": "🃏 21点游戏因无人参与已自动取消"}
                        )
                    return
                
                # 开始游戏
                result = await self._start_dealing(session_id)
                if self.message_callback and game.session_info:
                    await self.message_callback(game.session_info, result)
        except asyncio.CancelledError:
            logger.info(f"21点加入倒计时被取消 (会话: {session_id})")
        except Exception as e:
            logger.error(f"21点加入倒计时错误: {e}")
    
    async def force_start(self, session_id: str) -> Dict[str, Any]:
        """强制开始游戏（跳过等待）"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": "❌ 没有等待中的游戏"}
        
        if game.state != BlackjackGameState.WAITING_PLAYERS:
            return {"success": False, "message": "❌ 游戏已经开始"}
        
        if not game.players:
            return {"success": False, "message": "❌ 还没有玩家加入"}
        
        # 取消倒计时
        task = self.countdown_tasks.get(session_id)
        if task:
            task.cancel()
        
        result = await self._start_dealing(session_id)
        return result
    
    async def _start_dealing(self, session_id: str) -> Dict[str, Any]:
        """开始发牌"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": "游戏不存在"}
        
        game.state = BlackjackGameState.IN_PROGRESS
        
        # 给每个玩家发两张牌
        for player in game.players:
            player.hand.append(self._draw_card(game))
            player.hand.append(self._draw_card(game))
            
            # 检查是否天牌21点
            if player.is_blackjack():
                player.state = PlayerState.BLACKJACK
            else:
                player.state = PlayerState.WAITING
        
        # 给庄家发两张牌
        game.dealer.hand.append(self._draw_card(game))
        game.dealer.hand.append(self._draw_card(game))
        
        # 生成发牌信息
        message = "🃏 21点游戏开始发牌！\n\n"
        
        # 庄家信息（只显示第一张牌）
        dealer_first = game.dealer.hand[0].emoji()
        message += f"🏦 庄家：{dealer_first} 🂠\n\n"
        
        # 检测庄家明牌是否为A（提供保险选项）
        dealer_shows_ace = game.dealer.hand[0].rank == 'A'
        if dealer_shows_ace:
            game.insurance_offered = True
            message += "⚠️ 庄家明牌为A，可以购买保险！\n"
            message += "📋 输入 /买保险 购买保险（花费下注额的一半，庄家BJ则赔2:1）\n\n"
        
        # 玩家信息
        for i, player in enumerate(game.players):
            cards = " ".join([c.emoji() for c in player.hand])
            status = ""
            if player.state == PlayerState.BLACKJACK:
                status = " 🎉 Blackjack!"
            else:
                # 提示可用操作
                actions = []
                if player.can_double_down():
                    actions.append("加倍")
                if player.can_split():
                    actions.append("分牌")
                if actions:
                    status = f"  💡可{'/'.join(actions)}"
            message += f"👤 {player.nickname}：{cards} ({player.hand_value()}点){status}\n"
        
        # 找到第一个需要操作的玩家
        first_active = self._find_next_active_player(game, -1)
        if first_active is not None:
            game.current_player_index = first_active
            game.players[first_active].state = PlayerState.PLAYING
            p = game.players[first_active]
            message += f"\n🎯 轮到 {p.nickname} 操作\n"
            ops = "/抽牌 - 要牌 | /停牌 - 停止要牌"
            if p.can_double_down():
                ops += " | /加倍 - 加倍下注"
            if p.can_split():
                ops += " | /分牌 - 拆分同点牌"
            message += f"📋 {ops}"
            
            # 启动操作超时
            self._start_action_timeout(session_id)
        else:
            # 所有玩家都是blackjack，直接结算
            result = await self._settle_game(session_id)
            return result
        
        gs = self._build_game_state_data(session_id)
        r = {
            "success": True,
            "message": message,
            "game_started": True
        }
        if gs:
            r["game_state"] = gs
        return r
    
    def _find_next_active_player(self, game: BlackjackGame, current_index: int) -> Optional[int]:
        """找到下一个需要操作的玩家"""
        for i in range(current_index + 1, len(game.players)):
            if game.players[i].state in [PlayerState.WAITING, PlayerState.PLAYING]:
                return i
        return None
    
    def _start_action_timeout(self, session_id: str):
        """启动操作超时任务"""
        # 取消旧的超时任务（但不取消当前正在执行的任务，避免自我取消）
        old_task = self.action_tasks.get(session_id)
        if old_task and old_task is not asyncio.current_task():
            old_task.cancel()
        
        self.action_tasks[session_id] = asyncio.create_task(
            self._action_timeout_task(session_id)
        )
    
    async def _action_timeout_task(self, session_id: str):
        """操作超时处理 - 智能自动操作"""
        try:
            await asyncio.sleep(self.action_timeout)
            game = self.games.get(session_id)
            if game and game.state == BlackjackGameState.IN_PROGRESS:
                current = game.players[game.current_player_index]
                if current.state == PlayerState.PLAYING:
                    try:
                        # 如果在分牌手中，先处理分牌手超时
                        if current.playing_split_hand:
                            # 分牌手智能自动操作
                            await self._smart_auto_play(session_id, game, current, is_split=True)
                            return
                        else:
                            if current.is_split and current.split_state == PlayerState.WAITING:
                                # 主手超时：智能自动操作主手
                                await self._smart_auto_play(session_id, game, current, is_split=False, has_pending_split=True)
                                return
                            else:
                                # 普通超时：智能自动操作
                                await self._smart_auto_play(session_id, game, current, is_split=False)
                                return
                    except Exception as e:
                        logger.error(f"21点智能自动操作失败: {e}")
                        # 强制停牌并推进结算
                        try:
                            current.state = PlayerState.STOOD
                            if current.playing_split_hand:
                                current.split_state = PlayerState.STOOD
                                current.playing_split_hand = False
                            error_msg = f"⏰ {current.nickname} 操作超时（自动停牌）\n"
                            # 先发送超时通知
                            if self.message_callback and game.session_info:
                                await self.message_callback(game.session_info,
                                    {"success": True, "message": error_msg})
                            # 再推进结算（settlement 可能生成图片）
                            result = await self._advance_turn(session_id)
                            if self.message_callback and game.session_info:
                                await self.message_callback(game.session_info, result)
                        except Exception as e2:
                            logger.error(f"21点超时强制结算也失败: {e2}")
                            if self.message_callback and game.session_info:
                                await self.message_callback(game.session_info,
                                    {"success": True, "message": f"⏰ 操作超时，游戏异常结束"})
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"21点操作超时处理错误: {e}")
    
    async def _smart_auto_play(self, session_id: str, game: BlackjackGame, 
                                player: BlackjackPlayer, is_split: bool = False,
                                has_pending_split: bool = False):
        """智能自动操作：根据手牌和庄家明牌决定要牌或停牌
        
        基本策略：
        - 手牌 ≤ 11：自动要牌（不可能爆牌）
        - 手牌 12-16 且庄家明牌 ≥ 7：自动要牌
        - 手牌 ≥ 17 或庄家明牌 ≤ 6 且手牌 ≥ 12：自动停牌
        """
        timeout_msg = f"⏰ {player.nickname} 操作超时，执行智能自动操作\n"
        
        try:
            # 获取庄家明牌点数
            dealer_up_card = game.dealer.hand[0]
            dealer_up_value = dealer_up_card.value  # property, J/Q/K=10, A=11
            
            # 循环自动操作直到停牌或爆牌
            while True:
                if is_split:
                    hand = player.split_hand
                    hand_value = player.split_hand_value()
                else:
                    hand = player.hand
                    hand_value = player.hand_value()
                
                # 决策：是否要牌
                should_hit = False
                if hand_value <= 11:
                    should_hit = True
                elif hand_value <= 16 and dealer_up_value >= 7:
                    should_hit = True
                # 手牌 >= 17 或 (12-16 且庄家明牌 <= 6) → 停牌
                
                if should_hit:
                    card = self._draw_card(game)
                    hand.append(card)
                    new_value = player.split_hand_value() if is_split else player.hand_value()
                    timeout_msg += f"🤖 自动要牌：{card.emoji()}（当前 {new_value} 点）\n"
                    
                    if new_value > 21:
                        if is_split:
                            player.split_state = PlayerState.BUSTED
                            timeout_msg += f"💥 分牌手爆牌！\n"
                            player.playing_split_hand = False
                        else:
                            player.state = PlayerState.BUSTED
                            timeout_msg += f"💥 爆牌！\n"
                            # 如果有待处理的分牌手
                            if has_pending_split:
                                player.playing_split_hand = True
                                player.split_state = PlayerState.PLAYING
                                timeout_msg += f"\n📋 转到分牌手：{player.split_hand_display()}\n"
                                self._start_action_timeout(session_id)
                                if self.message_callback and game.session_info:
                                    await self.message_callback(game.session_info,
                                        {"success": True, "message": timeout_msg})
                                return
                        break
                    elif new_value == 21:
                        if is_split:
                            player.split_state = PlayerState.STOOD
                            timeout_msg += f"🎯 分牌手 21 点！自动停牌\n"
                            player.playing_split_hand = False
                        else:
                            player.state = PlayerState.STOOD
                            timeout_msg += f"🎯 21 点！自动停牌\n"
                            if has_pending_split:
                                player.playing_split_hand = True
                                player.split_state = PlayerState.PLAYING
                                timeout_msg += f"\n📋 转到分牌手：{player.split_hand_display()}\n"
                                self._start_action_timeout(session_id)
                                if self.message_callback and game.session_info:
                                    await self.message_callback(game.session_info,
                                        {"success": True, "message": timeout_msg})
                                return
                        break
                    # 继续循环判断是否还需要要牌
                else:
                    # 停牌
                    if is_split:
                        player.split_state = PlayerState.STOOD
                        player.playing_split_hand = False
                        timeout_msg += f"🤖 分牌手自动停牌（{hand_value} 点）\n"
                    else:
                        player.state = PlayerState.STOOD
                        timeout_msg += f"🤖 自动停牌（{hand_value} 点）\n"
                        if has_pending_split:
                            player.playing_split_hand = True
                            player.split_state = PlayerState.PLAYING
                            timeout_msg += f"\n📋 转到分牌手：{player.split_hand_display()}\n"
                            self._start_action_timeout(session_id)
                            if self.message_callback and game.session_info:
                                await self.message_callback(game.session_info,
                                    {"success": True, "message": timeout_msg})
                            return
                    break
            
            # 先发送自动操作过程文本（确保用户能看到系统做了什么）
            if timeout_msg and self.message_callback and game.session_info:
                await self.message_callback(game.session_info,
                    {"success": True, "message": timeout_msg})
            
            # 推进到下一个玩家或结算（settled 结果将单独发送，图片模式可正确渲染）
            result = await self._advance_turn(session_id)
            
            if self.message_callback and game.session_info:
                await self.message_callback(game.session_info, result)
        
        except Exception as e:
            logger.error(f"21点智能自动操作异常: {e}")
            # 确保即使出错也发送超时通知
            if self.message_callback and game.session_info:
                await self.message_callback(game.session_info,
                    {"success": True, "message": timeout_msg + f"⚠️ 自动操作异常，请手动继续操作"})
    
    def _get_current_hand(self, player: BlackjackPlayer) -> List[Card]:
        """获取当前操作中的手牌"""
        if player.playing_split_hand and player.split_hand is not None:
            return player.split_hand
        return player.hand
    
    def _get_current_hand_value(self, player: BlackjackPlayer) -> int:
        """获取当前操作中的手牌点数"""
        if player.playing_split_hand:
            return player.split_hand_value()
        return player.hand_value()
    
    def _get_current_hand_display(self, player: BlackjackPlayer) -> str:
        """获取当前操作中的手牌显示"""
        if player.playing_split_hand:
            return f"[分牌手] {player.split_hand_display()}"
        label = "[主手] " if player.is_split else ""
        return f"{label}{player.hand_display()}"
    
    def _build_game_state_data(self, session_id: str) -> Optional[Dict[str, Any]]:
        """构建当前游戏状态的序列化数据，用于图片模式渲染游戏过程"""
        game = self.games.get(session_id)
        if not game or game.state != BlackjackGameState.IN_PROGRESS:
            return None
        
        dealer_cards = [{"rank": c.rank, "suit": c.suit.value} for c in game.dealer.hand]
        
        players_data = []
        for p in game.players:
            pd = {
                "nickname": p.nickname,
                "cards": [{"rank": c.rank, "suit": c.suit.value} for c in p.hand],
                "value": p.hand_value(),
                "status": p.state.value,
                "bet": p.bet_amount,
                "is_doubled": p.is_doubled,
                "has_insurance": p.has_insurance,
            }
            if p.is_split and p.split_hand:
                pd["split_cards"] = [{"rank": c.rank, "suit": c.suit.value} for c in p.split_hand]
                pd["split_value"] = p.split_hand_value()
                pd["split_status"] = p.split_state.value if p.split_state else ""
                pd["split_bet"] = p.split_bet
            players_data.append(pd)
        
        return {
            "dealer_cards": dealer_cards,
            "players": players_data,
            "hide_dealer_second": True,
            "banker_nickname": game.banker_nickname,
        }

    def _build_result(self, message: str, advance_result: Dict[str, Any] = None,
                      session_id: str = None) -> Dict[str, Any]:
        """构建结果字典，转发来自 _advance_turn 的结算数据（用于图片模式渲染）"""
        if advance_result:
            message += advance_result.get("message", "")
        result = {"success": True, "message": message}
        if advance_result and advance_result.get("settled"):
            for key in ["settled", "results", "dealer_cards", "dealer_value", "banker_profit", "banker_nickname"]:
                if key in advance_result:
                    result[key] = advance_result[key]
        elif session_id:
            # 非结算结果：附加游戏状态数据用于图片模式
            game_state = self._build_game_state_data(session_id)
            if game_state:
                result["game_state"] = game_state
        return result
    
    async def hit(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """抽牌/要牌"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": "❌ 没有进行中的21点游戏"}
        
        if game.state != BlackjackGameState.IN_PROGRESS:
            return {"success": False, "message": "❌ 游戏不在进行状态"}
        
        current = game.players[game.current_player_index]
        if current.user_id != user_id:
            return {"success": False, "message": f"❌ 现在轮到 {current.nickname} 操作"}
        
        if not current.is_active():
            return {"success": False, "message": "❌ 你不在操作状态"}
        
        # 取消超时任务
        old_task = self.action_tasks.get(session_id)
        if old_task:
            old_task.cancel()
        
        # 获取当前操作的手牌
        hand = self._get_current_hand(current)
        card = self._draw_card(game)
        hand.append(card)
        
        hand_label = "[分牌手]" if current.playing_split_hand else ("[主手]" if current.is_split else "")
        value = self._get_current_hand_value(current)
        display = self._get_current_hand_display(current)
        
        message = f"🃏 {current.nickname} {hand_label}抽到了 {card.emoji()}\n"
        message += f"📋 当前手牌：{display}\n"
        
        if value > 21:
            if current.playing_split_hand:
                current.split_state = PlayerState.BUSTED
                message += f"💥 分牌手爆牌！\n"
                # 分牌手爆了，结束该玩家操作
                current.playing_split_hand = False
                current.state = PlayerState.STOOD if current.state == PlayerState.STOOD else current.state
                # 如果主手也已经结束了
                if current.state in [PlayerState.STOOD, PlayerState.BUSTED, PlayerState.DOUBLED]:
                    result = await self._advance_turn(session_id)
                    return self._build_result(message, result, session_id=session_id)
            else:
                current.state = PlayerState.BUSTED
                message += f"💥 爆牌！超过21点\n"
                # 如果有分牌且分牌手未操作，转到分牌手
                if current.is_split and current.split_state == PlayerState.WAITING:
                    current.playing_split_hand = True
                    current.split_state = PlayerState.PLAYING
                    message += f"\n📋 转到分牌手：{current.split_hand_display()}\n"
                    sp_ops = "/抽牌 继续要牌 | /停牌 停止"
                    if current.can_double_down():
                        sp_ops += " | /加倍"
                    message += f"📋 {sp_ops}\n"
                    self._start_action_timeout(session_id)
                    gs = self._build_game_state_data(session_id)
                    r = {"success": True, "message": message}
                    if gs:
                        r["game_state"] = gs
                    return r
                else:
                    result = await self._advance_turn(session_id)
                    return self._build_result(message, result, session_id=session_id)
        elif value == 21:
            if current.playing_split_hand:
                current.split_state = PlayerState.STOOD
                message += f"🎯 分牌手 21点！自动停牌\n"
                current.playing_split_hand = False
            else:
                current.state = PlayerState.STOOD
                message += f"🎯 21点！自动停牌\n"
                if current.is_split and current.split_state == PlayerState.WAITING:
                    current.playing_split_hand = True
                    current.split_state = PlayerState.PLAYING
                    message += f"\n📋 转到分牌手：{current.split_hand_display()}\n"
                    sp_ops = "/抽牌 继续要牌 | /停牌 停止"
                    if current.can_double_down():
                        sp_ops += " | /加倍"
                    message += f"📋 {sp_ops}\n"
                    self._start_action_timeout(session_id)
                    gs = self._build_game_state_data(session_id)
                    r = {"success": True, "message": message}
                    if gs:
                        r["game_state"] = gs
                    return r
            
            result = await self._advance_turn(session_id)
            return self._build_result(message, result, session_id=session_id)
        else:
            message += f"📋 /抽牌 继续要牌 | /停牌 停止"
            self._start_action_timeout(session_id)
            gs = self._build_game_state_data(session_id)
            r = {"success": True, "message": message}
            if gs:
                r["game_state"] = gs
            return r
    
    async def stand(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """停牌"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": "❌ 没有进行中的21点游戏"}
        
        if game.state != BlackjackGameState.IN_PROGRESS:
            return {"success": False, "message": "❌ 游戏不在进行状态"}
        
        current = game.players[game.current_player_index]
        if current.user_id != user_id:
            return {"success": False, "message": f"❌ 现在轮到 {current.nickname} 操作"}
        
        if not current.is_active():
            return {"success": False, "message": "❌ 你不在操作状态"}
        
        old_task = self.action_tasks.get(session_id)
        if old_task:
            old_task.cancel()
        
        if current.playing_split_hand:
            current.split_state = PlayerState.STOOD
            current.playing_split_hand = False
            message = f"✋ {current.nickname} 分牌手停牌 ({current.split_hand_value()}点)\n"
        else:
            current.state = PlayerState.STOOD
            hand_label = "[主手]" if current.is_split else ""
            message = f"✋ {current.nickname} {hand_label}选择停牌 ({current.hand_value()}点)\n"
            
            # 如果有分牌且分牌手未操作
            if current.is_split and current.split_state == PlayerState.WAITING:
                current.playing_split_hand = True
                current.split_state = PlayerState.PLAYING
                message += f"\n📋 转到分牌手：{current.split_hand_display()}\n"
                sp_ops = "/抽牌 继续要牌 | /停牌 停止"
                if current.can_double_down():
                    sp_ops += " | /加倍"
                message += f"📋 {sp_ops}\n"
                self._start_action_timeout(session_id)
                gs = self._build_game_state_data(session_id)
                r = {"success": True, "message": message}
                if gs:
                    r["game_state"] = gs
                return r
        
        result = await self._advance_turn(session_id)
        return self._build_result(message, result, session_id=session_id)
    
    async def double_down(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """加倍下注 - 加倍后只能再抽一张牌"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": "❌ 没有进行中的21点游戏"}
        
        if game.state != BlackjackGameState.IN_PROGRESS:
            return {"success": False, "message": "❌ 游戏不在进行状态"}
        
        current = game.players[game.current_player_index]
        if current.user_id != user_id:
            return {"success": False, "message": f"❌ 现在轮到 {current.nickname} 操作"}
        
        if not current.is_active():
            return {"success": False, "message": "❌ 你不在操作状态"}
        
        if not current.can_double_down():
            return {"success": False, "message": "❌ 只有拿到初始两张牌时才能加倍"}
        
        # 检查余额
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "❌ 用户不存在"}
        
        double_cost = current.bet_amount
        if not user.can_afford(double_cost):
            return {"success": False, "message": f"❌ 加倍需要额外 {double_cost:,} 金币，余额不足"}
        
        old_task = self.action_tasks.get(session_id)
        if old_task:
            old_task.cancel()
        
        # 区分主手/分牌手的加倍
        if current.playing_split_hand:
            # 分牌手加倍
            user.coins -= double_cost
            self.user_repo.update(user)
            current.split_bet *= 2
            # 注意: is_doubled 标志仅标记主手加倍状态，分牌手通过 split_state 判断
        else:
            # 主手加倍
            user.coins -= double_cost
            self.user_repo.update(user)
            current.bet_amount *= 2
            current.is_doubled = True
        
        # 只抽一张牌
        hand = self._get_current_hand(current)
        card = self._draw_card(game)
        hand.append(card)
        
        value = self._get_current_hand_value(current)
        display = self._get_current_hand_display(current)
        
        actual_bet = current.split_bet if current.playing_split_hand else current.bet_amount
        message = f"⬆️ {current.nickname} 选择加倍！下注翻倍至 {actual_bet:,} 金币\n"
        message += f"🃏 抽到 {card.emoji()}\n"
        message += f"📋 最终手牌：{display}\n"
        
        if current.playing_split_hand:
            # 分牌手加倍后的结果
            if value > 21:
                current.split_state = PlayerState.BUSTED
                message += f"💥 分牌手爆牌！\n"
            else:
                current.split_state = PlayerState.DOUBLED
                message += f"✋ 分牌手加倍后自动停牌\n"
            current.playing_split_hand = False
        else:
            # 主手加倍后的结果
            if value > 21:
                current.state = PlayerState.BUSTED
                message += f"💥 爆牌！\n"
            else:
                current.state = PlayerState.DOUBLED
                message += f"✋ 加倍后自动停牌\n"
        
        # 如果有分牌手待操作
        if current.is_split and current.split_state == PlayerState.WAITING and not current.playing_split_hand:
            current.playing_split_hand = True
            current.split_state = PlayerState.PLAYING
            message += f"\n📋 转到分牌手：{current.split_hand_display()}\n"
            sp_ops = "/抽牌 继续要牌 | /停牌 停止"
            if current.can_double_down():
                sp_ops += " | /加倍"
            message += f"📋 {sp_ops}\n"
            self._start_action_timeout(session_id)
            gs = self._build_game_state_data(session_id)
            r = {"success": True, "message": message}
            if gs:
                r["game_state"] = gs
            return r
        
        result = await self._advance_turn(session_id)
        return self._build_result(message, result, session_id=session_id)
    
    async def split(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """分牌 - 两张相同点数的牌拆成两手"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": "❌ 没有进行中的21点游戏"}
        
        if game.state != BlackjackGameState.IN_PROGRESS:
            return {"success": False, "message": "❌ 游戏不在进行状态"}
        
        current = game.players[game.current_player_index]
        if current.user_id != user_id:
            return {"success": False, "message": f"❌ 现在轮到 {current.nickname} 操作"}
        
        if current.state != PlayerState.PLAYING:
            return {"success": False, "message": "❌ 你不在操作状态"}
        
        if not current.can_split():
            return {"success": False, "message": "❌ 只有两张相同点数的牌才能分牌，且只能分一次"}
        
        # 检查余额
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "❌ 用户不存在"}
        
        split_cost = current.bet_amount
        if not user.can_afford(split_cost):
            return {"success": False, "message": f"❌ 分牌需要额外 {split_cost:,} 金币，余额不足"}
        
        old_task = self.action_tasks.get(session_id)
        if old_task:
            old_task.cancel()
        
        # 扣除额外金币
        user.coins -= split_cost
        self.user_repo.update(user)
        current.split_bet = current.bet_amount
        current.is_split = True
        
        # 拆分手牌
        second_card = current.hand.pop()
        current.split_hand = [second_card]
        
        # 给两手各补一张牌
        current.hand.append(self._draw_card(game))
        current.split_hand.append(self._draw_card(game))
        
        message = f"✂️ {current.nickname} 选择分牌！额外下注 {split_cost:,} 金币\n"
        message += f"📋 主手：{current.hand_display()}\n"
        message += f"📋 分牌手：{current.split_hand_display()}\n"
        message += f"\n🎯 先操作主手\n"
        
        # 检查主手是否21点
        if current.hand_value() == 21:
            current.state = PlayerState.STOOD
            message += f"🎯 主手21点！自动停牌\n"
            # 转到分牌手
            current.playing_split_hand = True
            current.split_state = PlayerState.PLAYING
            if current.split_hand_value() == 21:
                current.split_state = PlayerState.STOOD
                current.playing_split_hand = False
                message += f"🎯 分牌手也21点！自动停牌\n"
                result = await self._advance_turn(session_id)
                return self._build_result(message, result, session_id=session_id)
            message += f"📋 转到分牌手：{current.split_hand_display()}\n"
            sp_ops = "/抽牌 继续要牌 | /停牌 停止"
            if current.can_double_down():
                sp_ops += " | /加倍"
            message += f"📋 {sp_ops}\n"
        else:
            ops = "/抽牌 - 要牌 | /停牌 - 停止"
            if current.can_double_down():
                ops += " | /加倍"
            message += f"📋 {ops}"
        
        self._start_action_timeout(session_id)
        gs = self._build_game_state_data(session_id)
        r = {"success": True, "message": message}
        if gs:
            r["game_state"] = gs
        return r
    
    async def buy_insurance(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """购买保险 - 庄家明牌为A时可购买，花费下注额一半"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": "❌ 没有进行中的21点游戏"}
        
        if game.state != BlackjackGameState.IN_PROGRESS:
            return {"success": False, "message": "❌ 游戏不在进行状态"}
        
        if not game.insurance_offered:
            return {"success": False, "message": "❌ 庄家明牌不是A，不能购买保险"}
        
        # 找到该玩家
        player = None
        for p in game.players:
            if p.user_id == user_id:
                player = p
                break
        
        if not player:
            return {"success": False, "message": "❌ 你不在游戏中"}
        
        if player.has_insurance:
            return {"success": False, "message": "❌ 你已经购买过保险了"}
        
        insurance_cost = player.bet_amount // 2
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "❌ 用户不存在"}
        
        if not user.can_afford(insurance_cost):
            return {"success": False, "message": f"❌ 保险费用 {insurance_cost:,} 金币，余额不足"}
        
        # 扣除保险费用
        user.coins -= insurance_cost
        self.user_repo.update(user)
        player.insurance_bet = insurance_cost
        player.has_insurance = True
        
        return {
            "success": True,
            "message": f"🛡️ {player.nickname} 购买保险！花费 {insurance_cost:,} 金币\n"
                      f"📋 如果庄家是Blackjack，保险赔 2:1（获得 {insurance_cost * 2:,} 金币）"
        }
    
    async def _advance_turn(self, session_id: str) -> Dict[str, Any]:
        """推进到下一个玩家或进入庄家阶段"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": ""}
        
        next_idx = self._find_next_active_player(game, game.current_player_index)
        
        if next_idx is not None:
            game.current_player_index = next_idx
            game.players[next_idx].state = PlayerState.PLAYING
            p = game.players[next_idx]
            
            self._start_action_timeout(session_id)
            
            ops = "/抽牌 - 要牌 | /停牌 - 停止要牌"
            if p.can_double_down():
                ops += " | /加倍 - 加倍下注"
            if p.can_split():
                ops += " | /分牌 - 拆分同点牌"
            
            gs = self._build_game_state_data(session_id)
            r = {
                "success": True,
                "message": f"\n🎯 轮到 {p.nickname} 操作\n"
                          f"📋 手牌：{p.hand_display()}\n"
                          f"📋 {ops}"
            }
            if gs:
                r["game_state"] = gs
            return r
        else:
            return await self._dealer_play_and_settle(session_id)
    
    def _settle_single_hand(self, hand_value: int, hand_busted: bool, hand_blackjack: bool,
                            bet_amount: int, is_doubled: bool,
                            dealer_value: int, dealer_busted: bool, dealer_blackjack: bool) -> Tuple[int, str, int]:
        """结算单手牌，返回 (payout, result_text, profit)"""
        if hand_busted:
            return 0, "💥 爆牌", -bet_amount
        elif dealer_busted:
            if hand_blackjack:
                payout = int(bet_amount * 2.5)
                return payout, "🎉 Blackjack！庄家爆牌", payout - bet_amount
            else:
                payout = bet_amount * 2
                return payout, "🎉 胜利！庄家爆牌", payout - bet_amount
        elif hand_blackjack and not dealer_blackjack:
            payout = int(bet_amount * 2.5)
            return payout, "🎉 Blackjack！", payout - bet_amount
        elif dealer_blackjack and not hand_blackjack:
            return 0, "💸 庄家Blackjack", -bet_amount
        elif hand_blackjack and dealer_blackjack:
            return bet_amount, "⚖️ 双方Blackjack", 0
        elif hand_value > dealer_value:
            payout = bet_amount * 2
            return payout, f"🎉 胜利！{hand_value} > {dealer_value}", payout - bet_amount
        elif hand_value < dealer_value:
            return 0, f"💸 输了 {hand_value} < {dealer_value}", -bet_amount
        else:
            return bet_amount, f"⚖️ 平局 {hand_value} = {dealer_value}", 0
    
    async def _dealer_play_and_settle(self, session_id: str) -> Dict[str, Any]:
        """庄家自动操作并结算"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": ""}
        
        message = "\n" + "=" * 30 + "\n"
        message += "🏦 庄家翻牌\n"
        
        dealer = game.dealer
        message += f"📋 庄家手牌：{dealer.hand_display()}\n"
        
        dealer_blackjack = dealer.is_blackjack()
        
        # 先处理保险
        if game.insurance_offered:
            insurance_msg = ""
            for player in game.players:
                if player.has_insurance:
                    if dealer_blackjack:
                        # 庄家BJ，保险赔2:1
                        insurance_payout = player.insurance_bet * 3  # 返还本金+2倍
                        user = self.user_repo.get_by_id(player.user_id)
                        if user:
                            user.coins += insurance_payout
                            self.user_repo.update(user)
                        insurance_msg += f"🛡️ {player.nickname} 保险赢了 +{player.insurance_bet * 2:,} 金币\n"
                    else:
                        insurance_msg += f"🛡️ {player.nickname} 保险输了 -{player.insurance_bet:,} 金币\n"
            if insurance_msg:
                message += insurance_msg
        
        # 检查是否所有玩家都爆牌了（含分牌手）
        all_busted = True
        for p in game.players:
            if p.state != PlayerState.BUSTED:
                all_busted = False
                break
            if p.is_split and p.split_state != PlayerState.BUSTED:
                all_busted = False
                break
        
        if not all_busted and not dealer_blackjack:
            while dealer.hand_value() < 17:
                card = self._draw_card(game)
                dealer.hand.append(card)
                message += f"🃏 庄家抽到 {card.emoji()}\n"
            
            message += f"📊 庄家最终：{dealer.hand_display()}\n"
            
            if dealer.is_busted():
                message += f"💥 庄家爆牌！\n"
        elif all_busted:
            message += f"💀 所有玩家都爆牌了，庄家无需抽牌\n"
        elif dealer_blackjack:
            message += f"🎉 庄家 Blackjack！\n"
        
        # 结算
        message += "\n" + "=" * 30 + "\n"
        message += "📊 结算结果\n\n"
        
        dealer_value = dealer.hand_value()
        dealer_busted = dealer.is_busted()
        
        total_banker_change = 0
        results = []
        
        for player in game.players:
            # 主手结算
            main_busted = player.state in [PlayerState.BUSTED]
            main_bj = player.state == PlayerState.BLACKJACK
            
            payout, result_text, profit = self._settle_single_hand(
                player.hand_value(), main_busted, main_bj,
                player.bet_amount, player.is_doubled,
                dealer_value, dealer_busted, dealer_blackjack
            )
            
            result_entry = {
                "user_id": player.user_id,
                "nickname": player.nickname,
                "bet_amount": player.bet_amount,
                "payout": payout,
                "profit": profit,
                "result_text": result_text,
                "hand": player.hand_display(),
                "is_doubled": player.is_doubled,
            }
            results.append(result_entry)
            
            # 分牌手结算
            if player.is_split and player.split_hand:
                split_busted = player.split_state == PlayerState.BUSTED
                sp_val = player.split_hand_value()
                # 分牌后不算天牌BJ
                sp_payout, sp_text, sp_profit = self._settle_single_hand(
                    sp_val, split_busted, False,
                    player.split_bet, False,
                    dealer_value, dealer_busted, dealer_blackjack
                )
                
                results.append({
                    "user_id": player.user_id,
                    "nickname": f"{player.nickname}(分牌)",
                    "bet_amount": player.split_bet,
                    "payout": sp_payout,
                    "profit": sp_profit,
                    "result_text": sp_text,
                    "hand": player.split_hand_display(),
                    "is_split_hand": True
                })
        
        # 玩家庄家模式：按比例缩减
        if not game.is_system_dealer:
            banker = self.user_repo.get_by_id(game.banker_user_id)
            if banker:
                total_bets = sum(r["bet_amount"] for r in results)
                total_payouts = sum(r["payout"] for r in results)
                banker_pool = banker.coins + total_bets
                
                payout_ratio = 1.0
                if total_payouts > banker_pool:
                    payout_ratio = banker_pool / total_payouts if total_payouts > 0 else 0
                    message += f"⚠️ 庄家资金不足，派彩按 {payout_ratio:.1%} 比例发放\n\n"
                    for r in results:
                        r["payout"] = int(r["payout"] * payout_ratio)
                        r["profit"] = r["payout"] - r["bet_amount"]
                
                total_payouts = sum(r["payout"] for r in results)
                total_banker_change = total_bets - total_payouts
                banker.coins += total_banker_change
                self.user_repo.update(banker)
        
        # 按玩家聚合结果（用于连胜统计）
        player_total_profits = {}
        for r in results:
            uid = r["user_id"]
            if uid not in player_total_profits:
                player_total_profits[uid] = {"profit": 0, "nickname": r["nickname"].replace("(分牌)", "")}
            player_total_profits[uid]["profit"] += r["profit"]
        
        # 给玩家结算 + 连胜/连败 + 记录
        streak_messages = []
        for r in results:
            if r["payout"] > 0:
                user = self.user_repo.get_by_id(r["user_id"])
                if user:
                    user.coins += r["payout"]
                    self.user_repo.update(user)
            
            doubled_tag = " [加倍]" if r.get("is_doubled") else ""
            split_tag = " [分牌]" if r.get("is_split_hand") else ""
            profit_str = f"+{r['profit']:,}" if r['profit'] >= 0 else f"{r['profit']:,}"
            message += (f"👤 {r['nickname']}：{r['hand']}{doubled_tag}{split_tag}\n"
                       f"   {r['result_text']}\n"
                       f"   💰 {profit_str} 金币\n\n")
            
            # 记录读博历史
            self._add_gambling_record(
                "21点", game.game_id, r["user_id"],
                r["nickname"], r["bet_amount"], r["profit"], r["result_text"]
            )
        
        # 连胜/连败处理
        for uid, info in player_total_profits.items():
            won = info["profit"] > 0
            if info["profit"] != 0:  # 平局不影响连胜
                self._update_streak(uid, won)
            
            bonus, bonus_msg = self._get_streak_bonus(uid, info["profit"])
            if bonus > 0:
                user = self.user_repo.get_by_id(uid)
                if user:
                    user.coins += bonus
                    self.user_repo.update(user)
                streak_messages.append(bonus_msg)
        
        if streak_messages:
            message += "\n".join(streak_messages) + "\n"
        
        # 显示庄家信息
        if not game.is_system_dealer:
            message += f"\n{'='*20}\n"
            if total_banker_change > 0:
                message += f"🏦 庄家 {game.banker_nickname} 盈利：+{total_banker_change:,} 金币 💰"
            elif total_banker_change < 0:
                message += f"🏦 庄家 {game.banker_nickname} 亏损：{total_banker_change:,} 金币 💸"
            else:
                message += f"🏦 庄家 {game.banker_nickname} 持平 ⚖️"
        
        game.state = BlackjackGameState.SETTLED
        game.settled = True
        
        # 清理超时任务（不取消当前正在执行的任务，避免自我取消导致结算消息丢失）
        task = self.action_tasks.pop(session_id, None)
        if task and task is not asyncio.current_task():
            task.cancel()
        
        return {
            "success": True,
            "message": message,
            "settled": True,
            "results": results,
            "dealer_cards": [{"rank": c.rank, "suit": c.suit.value} for c in dealer.hand],
            "dealer_value": dealer_value,
            "banker_profit": total_banker_change if not game.is_system_dealer else None,
            "banker_nickname": game.banker_nickname
        }
    
    def get_game_status(self, session_id: str) -> Dict[str, Any]:
        """获取游戏状态"""
        game = self.games.get(session_id)
        if not game:
            return {"success": False, "message": "❌ 当前没有21点游戏"}
        
        if game.state == BlackjackGameState.SETTLED:
            return {"success": False, "message": "❌ 上一局已结束，输入 /21点 开始新游戏"}
        
        message = "🃏 21点游戏状态\n\n"
        
        if game.state == BlackjackGameState.WAITING_PLAYERS:
            remaining = max(0, int((game.join_deadline - get_now()).total_seconds()))
            banker_info = game.banker_nickname or "系统"
            message += f"🏦 庄家：{banker_info}\n"
            message += f"⏰ 还剩 {remaining} 秒可加入\n"
            message += f"👥 已加入：{len(game.players)} 人\n"
            for p in game.players:
                message += f"  • {p.nickname} (下注 {p.bet_amount:,})\n"
        else:
            dealer = game.dealer
            if game.state == BlackjackGameState.IN_PROGRESS:
                message += f"🏦 庄家：{dealer.hand[0].emoji()} 🂠\n\n"
            else:
                message += f"🏦 庄家：{dealer.hand_display()}\n\n"
            
            for i, p in enumerate(game.players):
                status_icon = {
                    PlayerState.WAITING: "⏳",
                    PlayerState.PLAYING: "🎯",
                    PlayerState.STOOD: "✋",
                    PlayerState.BUSTED: "💥",
                    PlayerState.BLACKJACK: "🎉",
                    PlayerState.DOUBLED: "⬆️"
                }.get(p.state, "")
                
                bet_info = f"下注 {p.bet_amount:,}"
                if p.is_doubled:
                    bet_info += " [加倍]"
                message += f"{status_icon} {p.nickname}：{p.hand_display()} ({bet_info})\n"
                
                if p.is_split and p.split_hand:
                    sp_icon = {
                        PlayerState.WAITING: "⏳",
                        PlayerState.PLAYING: "🎯", 
                        PlayerState.STOOD: "✋",
                        PlayerState.BUSTED: "💥",
                    }.get(p.split_state, "")
                    message += f"  ↳ {sp_icon} 分牌手：{p.split_hand_display()} (下注 {p.split_bet:,})\n"
        
        return {"success": True, "message": message}
    
    async def _settle_game(self, session_id: str) -> Dict[str, Any]:
        """直接结算（所有玩家已完成）"""
        return await self._dealer_play_and_settle(session_id)
