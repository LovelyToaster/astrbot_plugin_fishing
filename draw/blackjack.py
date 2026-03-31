"""
21点（Blackjack）游戏图片生成模块
用于生成21点游戏相关的图片消息
"""

import os
from PIL import Image, ImageDraw, ImageFont
from typing import Dict, Any, List, Optional
from .gradient_utils import create_vertical_gradient
from .styles import (
    COLOR_SUCCESS, COLOR_WARNING, COLOR_ERROR, COLOR_GOLD,
    COLOR_TEXT_DARK, COLOR_TEXT_WHITE, COLOR_CARD_BG,
    load_font
)


# 扑克牌花色颜色
COLOR_RED_SUIT = (220, 20, 60)    # 红心/方块
COLOR_BLACK_SUIT = (30, 30, 30)    # 黑桃/梅花
COLOR_CARD_FACE = (255, 255, 255)  # 牌面白色
COLOR_CARD_BACK = (25, 80, 150)    # 牌背蓝色
COLOR_TABLE_GREEN = (34, 139, 34)  # 牌桌绿色


def _draw_card(draw: ImageDraw.Draw, x: int, y: int, rank: str, suit: str, 
               card_width: int = 50, card_height: int = 70, font_size: int = 18):
    """在图片上绘制一张扑克牌"""
    font = load_font(font_size)
    small_font = load_font(12)
    
    # 牌面背景
    draw.rounded_rectangle(
        [(x, y), (x + card_width, y + card_height)],
        radius=5, fill=COLOR_CARD_FACE, outline=(180, 180, 180), width=1
    )
    
    # 花色颜色
    is_red = suit in ['♥', '♦', '♥️', '♦️']
    color = COLOR_RED_SUIT if is_red else COLOR_BLACK_SUIT
    
    # 绘制牌面文字
    draw.text((x + 5, y + 3), rank, fill=color, font=font)
    draw.text((x + 5, y + card_height - 20), suit, fill=color, font=small_font)


def _draw_card_back(draw: ImageDraw.Draw, x: int, y: int,
                    card_width: int = 50, card_height: int = 70):
    """绘制牌背面"""
    draw.rounded_rectangle(
        [(x, y), (x + card_width, y + card_height)],
        radius=5, fill=COLOR_CARD_BACK, outline=(20, 60, 120), width=1
    )
    # 内框装饰
    draw.rounded_rectangle(
        [(x + 5, y + 5), (x + card_width - 5, y + card_height - 5)],
        radius=3, fill=None, outline=(255, 255, 255, 100), width=1
    )


def draw_blackjack_game(dealer_cards: List[dict], players: List[dict], 
                        hide_dealer_second: bool = True,
                        banker_nickname: str = None) -> Image.Image:
    """
    绘制21点游戏状态图片
    
    Args:
        dealer_cards: 庄家手牌列表 [{"rank": "A", "suit": "♠"}, ...]
        players: 玩家列表 [{"nickname": "...", "cards": [...], "value": 21, "status": "...", 
                  "bet": 1000, "is_doubled": False, "has_insurance": False,
                  "split_cards": [...], "split_value": 0, "split_status": ""}, ...]
        hide_dealer_second: 是否隐藏庄家第二张牌
        banker_nickname: 庄家昵称
    """
    # 计算每个玩家需要的高度
    player_heights = []
    for p in players:
        h = 100
        if p.get("split_cards"):
            h += 80  # 分牌手额外高度
        player_heights.append(h)
    
    num_players = len(players)
    width = 650
    height = 280 + sum(player_heights)
    
    # 牌桌绿色渐变背景
    bg_top = (34, 100, 34)
    bg_bot = (20, 70, 20)
    image = create_vertical_gradient(width, height, bg_top, bg_bot)
    draw = ImageDraw.Draw(image)
    
    title_font = load_font(28)
    name_font = load_font(20)
    info_font = load_font(16)
    tag_font = load_font(14)
    
    # 标题
    title = "🃏 21点"
    draw.text((width // 2 - 60, 15), title, fill=COLOR_TEXT_WHITE, font=title_font)
    
    # 庄家区域
    y = 60
    banker_label = f"🏦 庄家" + (f"({banker_nickname})" if banker_nickname else "")
    draw.text((30, y), banker_label, fill=COLOR_GOLD, font=name_font)
    
    card_x = 30
    for i, card in enumerate(dealer_cards):
        if i == 1 and hide_dealer_second:
            _draw_card_back(draw, card_x, y + 30)
        else:
            _draw_card(draw, card_x, y + 30, card["rank"], card["suit"])
        card_x += 60
    
    if not hide_dealer_second and dealer_cards:
        # 显示庄家点数
        draw.text((card_x + 20, y + 50), f"", fill=COLOR_TEXT_WHITE, font=info_font)
    
    # 分隔线
    y = 170
    draw.line([(20, y), (width - 20, y)], fill=(100, 200, 100), width=1)
    
    # 玩家区域
    y += 15
    for player in players:
        # 状态图标
        status_icons = {
            "waiting": "⏳",
            "playing": "🎯",
            "stood": "✋",
            "busted": "💥",
            "blackjack": "🎉",
            "doubled": "⬆️"
        }
        icon = status_icons.get(player.get("status", ""), "")
        
        # 构建名字行
        bet_text = f"下注 {player.get('bet', 0):,}"
        tags = []
        if player.get("is_doubled"):
            tags.append("[加倍]")
        if player.get("has_insurance"):
            tags.append("[保险]")
        tag_str = " ".join(tags)
        
        name_text = f"{icon} {player['nickname']} ({bet_text})"
        draw.text((30, y), name_text, fill=COLOR_TEXT_WHITE, font=name_font)
        if tag_str:
            draw.text((30 + len(name_text) * 11, y + 3), tag_str, fill=COLOR_GOLD, font=tag_font)
        
        # 绘制主手牌
        card_x = 30
        hand_label = "[主手] " if player.get("split_cards") else ""
        if hand_label:
            draw.text((30, y + 25), hand_label, fill=(200, 200, 200), font=tag_font)
            card_x = 75
        
        for card in player.get("cards", []):
            _draw_card(draw, card_x, y + 28, card["rank"], card["suit"])
            card_x += 60
        
        # 点数
        value = player.get("value", 0)
        value_color = COLOR_ERROR if value > 21 else (COLOR_GOLD if value == 21 else COLOR_TEXT_WHITE)
        draw.text((card_x + 20, y + 45), f"{value}点", fill=value_color, font=info_font)
        
        y += 100
        
        # 绘制分牌手
        if player.get("split_cards"):
            sp_status = player.get("split_status", "")
            sp_icon = status_icons.get(sp_status, "")
            draw.text((30, y - 15), f"  ↳ {sp_icon} 分牌手 (下注 {player.get('split_bet', 0):,})",
                      fill=(180, 200, 255), font=tag_font)
            
            card_x = 75
            for card in player.get("split_cards", []):
                _draw_card(draw, card_x, y + 3, card["rank"], card["suit"])
                card_x += 60
            
            sp_value = player.get("split_value", 0)
            sp_color = COLOR_ERROR if sp_value > 21 else (COLOR_GOLD if sp_value == 21 else COLOR_TEXT_WHITE)
            draw.text((card_x + 20, y + 20), f"{sp_value}点", fill=sp_color, font=info_font)
            y += 80
    
    return image


def draw_blackjack_result(dealer_cards: List[dict], dealer_value: int,
                          results: List[dict], banker_nickname: str = None,
                          banker_profit: int = None) -> Image.Image:
    """
    绘制21点结算结果图片
    
    Args:
        dealer_cards: 庄家手牌
        dealer_value: 庄家点数
        results: 结算结果列表 [{"nickname", "profit", "result_text", "is_doubled", "is_split_hand"}, ...]
        banker_nickname: 庄家昵称
        banker_profit: 庄家盈亏
    """
    num_results = len(results)
    width = 650
    height = 300 + num_results * 90 + (60 if banker_profit is not None else 0)
    
    bg_top = (30, 30, 60)
    bg_bot = (20, 20, 40)
    image = create_vertical_gradient(width, height, bg_top, bg_bot)
    draw = ImageDraw.Draw(image)
    
    title_font = load_font(30)
    name_font = load_font(20)
    info_font = load_font(16)
    tag_font = load_font(14)
    profit_font = load_font(22)
    
    # 标题
    draw.text((width // 2 - 100, 15), "🃏 21点结算", fill=COLOR_TEXT_WHITE, font=title_font)
    
    # 庄家结果
    y = 65
    banker_label = f"🏦 庄家" + (f"({banker_nickname})" if banker_nickname else "")
    draw.text((30, y), banker_label, fill=COLOR_GOLD, font=name_font)
    
    card_x = 30
    for card in dealer_cards:
        _draw_card(draw, card_x, y + 30, card["rank"], card["suit"])
        card_x += 60
    
    value_color = COLOR_ERROR if dealer_value > 21 else COLOR_GOLD
    value_text = f"{dealer_value}点" + (" 💥爆牌" if dealer_value > 21 else "")
    draw.text((card_x + 20, y + 45), value_text, fill=value_color, font=info_font)
    
    # 分隔线
    y = 175
    draw.line([(20, y), (width - 20, y)], fill=(100, 100, 150), width=1)
    
    y += 15
    draw.text((30, y), "📊 结算结果", fill=COLOR_TEXT_WHITE, font=name_font)
    y += 35
    
    for r in results:
        nickname = r.get("nickname", "未知")
        profit = r.get("profit", 0)
        result_text = r.get("result_text", "")
        
        color = COLOR_SUCCESS if profit > 0 else (COLOR_ERROR if profit < 0 else COLOR_WARNING)
        profit_str = f"+{profit:,}" if profit > 0 else f"{profit:,}"
        
        # 构建标签
        tags = []
        if r.get("is_doubled"):
            tags.append("[加倍]")
        if r.get("is_split_hand"):
            tags.append("[分牌]")
        tag_str = " ".join(tags)
        
        name_display = f"👤 {nickname}"
        draw.text((30, y), name_display, fill=COLOR_TEXT_WHITE, font=name_font)
        if tag_str:
            draw.text((30 + len(name_display) * 11, y + 3), tag_str, fill=COLOR_GOLD, font=tag_font)
        
        draw.text((30, y + 25), f"   {result_text}", fill=color, font=info_font)
        draw.text((30, y + 48), f"   💰 {profit_str} 金币", fill=color, font=info_font)
        y += 85
    
    # 庄家盈亏
    if banker_profit is not None:
        draw.line([(20, y), (width - 20, y)], fill=(100, 100, 150), width=1)
        y += 10
        if banker_profit > 0:
            text = f"🏦 庄家盈利：+{banker_profit:,} 金币 💰"
            color = COLOR_SUCCESS
        elif banker_profit < 0:
            text = f"🏦 庄家亏损：{banker_profit:,} 金币 💸"
            color = COLOR_ERROR
        else:
            text = f"🏦 庄家持平 ⚖️"
            color = COLOR_WARNING
        draw.text((30, y), text, fill=color, font=profit_font)
    
    return image


def save_image_to_temp(image: Image.Image, prefix: str, data_dir: str) -> str:
    """保存图片到临时目录"""
    import time
    tmp_dir = os.path.join(data_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    filename = f"{prefix}_{int(time.time() * 1000)}.png"
    filepath = os.path.join(tmp_dir, filename)
    image.save(filepath, "PNG")
    return filepath
