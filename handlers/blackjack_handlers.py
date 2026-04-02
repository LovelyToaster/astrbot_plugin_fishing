"""
21点（Blackjack）游戏处理器
处理所有21点相关的命令
"""

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from typing import TYPE_CHECKING
from ..utils import parse_amount

if TYPE_CHECKING:
    from ..main import FishingPlugin


async def _render_blackjack_response(plugin: "FishingPlugin", event: AstrMessageEvent, result: dict):
    """渲染21点响应 - 图片模式下对结算结果生成图片"""
    if plugin.blackjack_service.is_image_mode() and result.get("settled"):
        try:
            from ..draw.blackjack import draw_blackjack_result, save_image_to_temp
            image = draw_blackjack_result(
                result.get("dealer_cards", []),
                result.get("dealer_value", 0),
                result.get("results", []),
                result.get("banker_nickname"),
                result.get("banker_profit")
            )
            image_path = save_image_to_temp(image, "bj_settle", plugin.data_dir)
            yield event.image_result(image_path)
            return
        except Exception as e:
            logger.error(f"21点结算图片生成失败，回退到文本: {e}")
    yield event.plain_result(result["message"])


def _get_game_session_id(event: AstrMessageEvent) -> str:
    """获取21点游戏的会话ID"""
    group_id = event.get_group_id()
    if group_id:
        platform_name = getattr(event.platform_meta, 'platform_name', 'aiocqhttp')
        return f"{platform_name}:group:{group_id}"
    else:
        return event.unified_msg_origin


async def start_blackjack(plugin: "FishingPlugin", event: AstrMessageEvent):
    """开始21点游戏（系统庄家）"""
    if not plugin.is_game_enabled(event, "blackjack"):
        yield event.plain_result("❌ 21点功能已被管理员在本群关闭")
        return
    try:
        game_session_id = _get_game_session_id(event)
        user_id = plugin._get_effective_user_id(event)
        
        # 检查是否有逾期借款
        is_overdue, overdue_msg = plugin.loan_service.check_user_overdue_status(user_id)
        if is_overdue:
            yield event.plain_result(overdue_msg)
            return
        
        args = event.message_str.split()
        
        if len(args) < 2:
            yield event.plain_result(
                "🃏 21点游戏\n\n"
                "📋 用法：\n"
                "• /21点 [金额] - 系统庄家模式\n"
                "• /21点开庄 - 玩家当庄（其他人加入）\n"
                "• /21点加入 [金额] - 加入玩家开的局\n"
                "• /抽牌 - 要牌\n"
                "• /停牌 - 停止要牌\n"
                "• /加倍 - 加倍下注（初始2牌时）\n"
                "• /分牌 - 分牌（同点数时）\n"
                "• /买保险 - 庄家A时买保险\n"
                "• /读博记录 - 查看历史记录\n"
                "• /21点状态 - 查看当前游戏\n"
                "• /21点开始 - 提前开始（跳过等待）\n"
                "• /21点帮助 - 查看详细规则"
            )
            return
        
        amount_str = args[1]
        try:
            amount = parse_amount(amount_str)
        except Exception as e:
            yield event.plain_result(f"❌ 无法解析金额：{str(e)}")
            return
        
        session_info = {
            'platform': getattr(event.platform_meta, 'platform_name', 'aiocqhttp'),
            'session_id': event.session_id,
            'sender_id': event.get_sender_id(),
            'unified_msg_origin': event.unified_msg_origin,
        }
        group_id = event.get_group_id()
        if group_id:
            session_info['group_id'] = group_id
        
        result = plugin.blackjack_service.start_game(
            game_session_id, user_id, amount,
            session_info=session_info,
            is_player_banker=False
        )
        yield event.plain_result(result["message"])
    except Exception as e:
        yield event.plain_result(f"❌ 开始21点游戏失败：{str(e)}")


async def start_blackjack_banker(plugin: "FishingPlugin", event: AstrMessageEvent):
    """21点玩家开庄"""
    if not plugin.is_game_enabled(event, "blackjack"):
        yield event.plain_result("❌ 21点功能已被管理员在本群关闭")
        return
    try:
        game_session_id = _get_game_session_id(event)
        user_id = plugin._get_effective_user_id(event)
        
        # 检查是否有逾期借款
        is_overdue, overdue_msg = plugin.loan_service.check_user_overdue_status(user_id)
        if is_overdue:
            yield event.plain_result(overdue_msg)
            return
        
        session_info = {
            'platform': getattr(event.platform_meta, 'platform_name', 'aiocqhttp'),
            'session_id': event.session_id,
            'sender_id': event.get_sender_id(),
            'unified_msg_origin': event.unified_msg_origin,
        }
        group_id = event.get_group_id()
        if group_id:
            session_info['group_id'] = group_id
        
        result = plugin.blackjack_service.start_game(
            game_session_id, user_id, 0,
            session_info=session_info,
            is_player_banker=True
        )
        yield event.plain_result(result["message"])
    except Exception as e:
        yield event.plain_result(f"❌ 21点开庄失败：{str(e)}")


async def join_blackjack(plugin: "FishingPlugin", event: AstrMessageEvent):
    """加入21点游戏"""
    if not plugin.is_game_enabled(event, "blackjack"):
        yield event.plain_result("❌ 21点功能已被管理员在本群关闭")
        return
    try:
        game_session_id = _get_game_session_id(event)
        user_id = plugin._get_effective_user_id(event)
        
        # 检查是否有逾期借款
        is_overdue, overdue_msg = plugin.loan_service.check_user_overdue_status(user_id)
        if is_overdue:
            yield event.plain_result(overdue_msg)
            return
        
        args = event.message_str.split()
        
        if len(args) < 2:
            yield event.plain_result("❌ 请指定下注金额，例如：/21点加入 1000")
            return
        
        amount_str = args[1]
        try:
            amount = parse_amount(amount_str)
        except Exception as e:
            yield event.plain_result(f"❌ 无法解析金额：{str(e)}")
            return
        
        result = plugin.blackjack_service.join_game(game_session_id, user_id, amount)
        yield event.plain_result(result["message"])
    except Exception as e:
        yield event.plain_result(f"❌ 加入21点失败：{str(e)}")


async def blackjack_hit(plugin: "FishingPlugin", event: AstrMessageEvent):
    """抽牌/要牌"""
    if not plugin.is_game_enabled(event, "blackjack"):
        yield event.plain_result("❌ 21点功能已被管理员在本群关闭")
        return
    try:
        game_session_id = _get_game_session_id(event)
        user_id = plugin._get_effective_user_id(event)
        
        result = await plugin.blackjack_service.hit(game_session_id, user_id)
        async for r in _render_blackjack_response(plugin, event, result):
            yield r
    except Exception as e:
        yield event.plain_result(f"❌ 抽牌失败：{str(e)}")


async def blackjack_stand(plugin: "FishingPlugin", event: AstrMessageEvent):
    """停牌"""
    if not plugin.is_game_enabled(event, "blackjack"):
        yield event.plain_result("❌ 21点功能已被管理员在本群关闭")
        return
    try:
        game_session_id = _get_game_session_id(event)
        user_id = plugin._get_effective_user_id(event)
        
        result = await plugin.blackjack_service.stand(game_session_id, user_id)
        async for r in _render_blackjack_response(plugin, event, result):
            yield r
    except Exception as e:
        yield event.plain_result(f"❌ 停牌失败：{str(e)}")


async def blackjack_status(plugin: "FishingPlugin", event: AstrMessageEvent):
    """查看21点状态"""
    try:
        game_session_id = _get_game_session_id(event)
        result = plugin.blackjack_service.get_game_status(game_session_id)
        yield event.plain_result(result["message"])
    except Exception as e:
        yield event.plain_result(f"❌ 查看状态失败：{str(e)}")


async def blackjack_force_start(plugin: "FishingPlugin", event: AstrMessageEvent):
    """提前开始21点游戏"""
    if not plugin.is_game_enabled(event, "blackjack"):
        yield event.plain_result("❌ 21点功能已被管理员在本群关闭")
        return
    try:
        game_session_id = _get_game_session_id(event)
        result = await plugin.blackjack_service.force_start(game_session_id)
        async for r in _render_blackjack_response(plugin, event, result):
            yield r
    except Exception as e:
        yield event.plain_result(f"❌ 开始失败：{str(e)}")


async def blackjack_help(plugin: "FishingPlugin", event: AstrMessageEvent):
    """21点帮助"""
    min_banker = plugin.blackjack_service.min_banker_coins
    min_bet = plugin.blackjack_service.min_bet
    join_timeout = plugin.blackjack_service.join_timeout
    action_timeout = plugin.blackjack_service.action_timeout
    streak_win = plugin.blackjack_service.streak_win_bonus_threshold
    streak_lose = plugin.blackjack_service.streak_lose_consolation_threshold
    
    help_msg = f"""🃏 21点（Blackjack）游戏帮助

【游戏规则】
• 目标：手牌点数尽量接近21点但不超过
• A = 1 或 11（自动最优计算）
• J/Q/K = 10，其他按面值
• 天牌Blackjack（开牌即21点）赔率 1.5 倍
• 庄家必须在16点以下继续要牌
• 点数相同则平局，退还本金

【游戏模式】
🎮 系统庄家：/21点 [金额]
   • 与系统对战，可多人同时参与
🏦 玩家开庄：/21点开庄
   • 发起者当庄，最多6人加入
   • 庄家最低余额要求 {min_banker:,} 金币
   • 庄家资金不足时按比例派彩

【基础命令】
• /21点 [金额] - 开局（系统庄家）
• /21点开庄 - 玩家当庄
• /21点加入 [金额] - 加入游戏
• /21点开始 - 跳过等待期直接开始
• /抽牌 - 要一张牌
• /停牌 - 停止要牌
• /21点状态 - 查看当前牌局

【进阶操作】
• /加倍 - 加倍下注（仅限初始2张牌时），再抽一张后自动停牌
• /分牌 - 分牌（两张同点数牌时可用），拆成两手各自操作
• /买保险 - 购买保险（庄家明牌为A时可用），花费下注额一半
  ↳ 庄家Blackjack时保险赔2:1

【查询命令】
• /读博记录 - 查看最近的读博历史记录
• /21点帮助 - 查看本帮助

【连胜/连败奖励】
🔥 连胜 {streak_win} 局以上：额外奖励当局利润的10%
💫 连败 {streak_lose} 局以上：获得安慰金

【游戏流程】
1. 发起者开局 → 等待{join_timeout}秒供其他人加入
2. 发牌（每人2张，庄家1明1暗）
3. 若庄家明牌为A → 可购买保险
4. 按顺序操作：抽牌/停牌/加倍/分牌（{action_timeout}秒超时智能自动操作）
5. 所有人操作完 → 庄家自动操作 → 结算

【下注限额】
💰 最低下注：{min_bet:,} 金币
💰 支持中文数字：1万、10万 等

祝您好运！🍀"""
    yield event.plain_result(help_msg)


async def blackjack_double_down(plugin: "FishingPlugin", event: AstrMessageEvent):
    """加倍下注"""
    if not plugin.is_game_enabled(event, "blackjack"):
        yield event.plain_result("❌ 21点功能已被管理员在本群关闭")
        return
    try:
        game_session_id = _get_game_session_id(event)
        user_id = plugin._get_effective_user_id(event)
        
        result = await plugin.blackjack_service.double_down(game_session_id, user_id)
        async for r in _render_blackjack_response(plugin, event, result):
            yield r
    except Exception as e:
        yield event.plain_result(f"❌ 加倍失败：{str(e)}")


async def blackjack_split(plugin: "FishingPlugin", event: AstrMessageEvent):
    """分牌"""
    if not plugin.is_game_enabled(event, "blackjack"):
        yield event.plain_result("❌ 21点功能已被管理员在本群关闭")
        return
    try:
        game_session_id = _get_game_session_id(event)
        user_id = plugin._get_effective_user_id(event)
        
        result = await plugin.blackjack_service.split(game_session_id, user_id)
        async for r in _render_blackjack_response(plugin, event, result):
            yield r
    except Exception as e:
        yield event.plain_result(f"❌ 分牌失败：{str(e)}")


async def blackjack_buy_insurance(plugin: "FishingPlugin", event: AstrMessageEvent):
    """购买保险"""
    if not plugin.is_game_enabled(event, "blackjack"):
        yield event.plain_result("❌ 21点功能已被管理员在本群关闭")
        return
    try:
        game_session_id = _get_game_session_id(event)
        user_id = plugin._get_effective_user_id(event)
        
        result = await plugin.blackjack_service.buy_insurance(game_session_id, user_id)
        yield event.plain_result(result["message"])
    except Exception as e:
        yield event.plain_result(f"❌ 购买保险失败：{str(e)}")


async def blackjack_gambling_records(plugin: "FishingPlugin", event: AstrMessageEvent):
    """查看读博记录"""
    try:
        user_id = plugin._get_effective_user_id(event)
        
        args = event.message_str.split()
        limit = 5
        if len(args) > 1:
            try:
                limit = int(args[1])
                limit = max(1, min(limit, 50))
            except ValueError:
                pass
        
        records = plugin.blackjack_service.get_user_gambling_records(user_id, limit)
        
        if not records:
            yield event.plain_result("📋 暂无读博记录")
            return
        
        message = f"📋 最近 {len(records)} 条读博记录\n\n"
        for i, r in enumerate(reversed(records), 1):
            profit_str = f"+{r['profit']:,}" if r['profit'] >= 0 else f"{r['profit']:,}"
            profit_icon = "💰" if r['profit'] > 0 else ("💸" if r['profit'] < 0 else "⚖️")
            message += (f"{i}. [{r['game_type']}] {r['time']}\n"
                       f"   下注 {r['bet']:,} | {profit_icon} {profit_str}\n"
                       f"   {r['detail']}\n\n")
        
        yield event.plain_result(message)
    except Exception as e:
        yield event.plain_result(f"❌ 查询记录失败：{str(e)}")


async def set_blackjack_mode(plugin: "FishingPlugin", event: AstrMessageEvent):
    """[管理员] 设置21点消息模式"""
    args = event.message_str.split()
    
    if len(args) < 2:
        current_mode = plugin.blackjack_service.get_message_mode()
        mode_name = "图片模式" if current_mode == "image" else "文本模式"
        yield event.plain_result(f"📱 当前21点消息模式：{mode_name}\n用法：/21点模式 <image|text>")
        return
    
    try:
        mode = args[1].lower()
        
        # 支持中文输入
        if mode in ["图片", "图片模式", "img"]:
            mode = "image"
        elif mode in ["文本", "文字", "文本模式", "txt"]:
            mode = "text"
        
        result = plugin.blackjack_service.set_message_mode(mode)
        
        if result["success"]:
            yield event.plain_result(result["message"])
        else:
            yield event.plain_result(result["message"])
    except Exception as e:
        yield event.plain_result(f"❌ 设置失败：{str(e)}")
