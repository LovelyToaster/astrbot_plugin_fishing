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

# 全局布局常量
CARD_WIDTH = 50
CARD_HEIGHT = 70
CARD_SPACING = 60
IMAGE_WIDTH = 650
PADDING_X = 40


def _draw_centered_text(draw: ImageDraw.Draw, y: int, text: str, fill, font,
                         width: int = IMAGE_WIDTH) -> int:
    """绘制居中文本，返回文本高度"""
    bbox = draw.textbbox((0, 0), text, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = max(10, (width - text_w) // 2)
    draw.text((x, y), text, fill=fill, font=font)
    return text_h


def _get_cards_center_x(num_cards: int, width: int = IMAGE_WIDTH,
                         spacing: int = CARD_SPACING) -> int:
    """计算居中显示扑克牌组的起始x坐标"""
    if num_cards <= 0:
        return width // 2
    total_w = (num_cards - 1) * spacing + CARD_WIDTH
    return max(PADDING_X, (width - total_w) // 2)


def _draw_card(draw: ImageDraw.Draw, x: int, y: int, rank: str, suit: str,
               card_width: int = CARD_WIDTH, card_height: int = CARD_HEIGHT, font_size: int = 18):
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
                    card_width: int = CARD_WIDTH, card_height: int = CARD_HEIGHT):
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


def _draw_cards_centered(draw: ImageDraw.Draw, y: int, cards: list,
                          width: int = IMAGE_WIDTH, hide_indices: set = None) -> int:
    """居中绘制一组扑克牌，返回牌组右边缘的x坐标。牌数较多时自动缩小间距防溢出"""
    num_cards = len(cards)
    if num_cards == 0:
        return width // 2
    # 动态间距：牌数较多时自动缩小防止溢出
    max_total = width - 2 * PADDING_X
    if num_cards > 1:
        spacing = min(CARD_SPACING, (max_total - CARD_WIDTH) // (num_cards - 1))
    else:
        spacing = CARD_SPACING
    spacing = max(spacing, CARD_WIDTH + 5)  # 最小间距避免牌面完全重叠
    start_x = _get_cards_center_x(num_cards, width, spacing)
    for i, card in enumerate(cards):
        cx = start_x + i * spacing
        if hide_indices and i in hide_indices:
            _draw_card_back(draw, cx, y)
        else:
            _draw_card(draw, cx, y, card["rank"], card["suit"])
    return start_x + (num_cards - 1) * spacing + CARD_WIDTH


def draw_blackjack_game(dealer_cards: List[dict], players: List[dict],
                        hide_dealer_second: bool = True,
                        banker_nickname: str = None,
                        current_player: str = None,
                        action_hint: str = None) -> Image.Image:
    """
    绘制21点游戏状态图片（居中布局）
    
    Args:
        dealer_cards: 庄家手牌列表 [{"rank": "A", "suit": "♠"}, ...]
        players: 玩家列表
        hide_dealer_second: 是否隐藏庄家第二张牌
        banker_nickname: 庄家昵称
        current_player: 当前操作玩家昵称（嵌入图片底部提示）
        action_hint: 当前可用操作提示文本
    """
    # 计算每个玩家需要的高度
    player_heights = []
    for p in players:
        h = 105
        if p.get("split_cards"):
            h += 85
        player_heights.append(h)
    
    hint_height = 65 if current_player else 0
    width = IMAGE_WIDTH
    height = 260 + sum(player_heights) + hint_height
    
    # 牌桌绿色渐变背景
    image = create_vertical_gradient(width, height, (34, 100, 34), (20, 70, 20))
    draw = ImageDraw.Draw(image)
    
    title_font = load_font(28)
    name_font = load_font(20)
    info_font = load_font(16)
    tag_font = load_font(14)
    
    # ── 标题居中 ──
    _draw_centered_text(draw, 15, "🃏 21点", COLOR_TEXT_WHITE, title_font, width)
    
    # ── 庄家区域 ──
    y = 60
    banker_label = "庄家" + (f"（{banker_nickname}）" if banker_nickname else "")
    _draw_centered_text(draw, y, banker_label, COLOR_GOLD, name_font, width)
    
    # 庄家手牌居中
    hide_set = {1} if hide_dealer_second and len(dealer_cards) > 1 else None
    _draw_cards_centered(draw, y + 30, dealer_cards, width, hide_set)
    
    # 分隔线
    sep_y = 170
    draw.line([(30, sep_y), (width - 30, sep_y)], fill=(100, 200, 100), width=1)
    
    # ── 玩家区域 ──
    y = sep_y + 15
    status_icons = {
        "waiting": "⏳", "playing": "🎯", "stood": "✋",
        "busted": "💥", "blackjack": "🎉", "doubled": "⬆️"
    }
    
    for player in players:
        icon = status_icons.get(player.get("status", ""), "")
        bet_text = f"下注{player.get('bet', 0):,}"
        
        tags = []
        if player.get("is_doubled"):
            tags.append("[加倍]")
        if player.get("has_insurance"):
            tags.append("[保险]")
        tag_str = " ".join(tags)
        
        # 玩家信息行居中
        name_line = f"{icon} {player['nickname']}  {bet_text}"
        if tag_str:
            name_line += f"  {tag_str}"
        _draw_centered_text(draw, y, name_line, COLOR_TEXT_WHITE, name_font, width)
        
        # 主手标签（有分牌时显示）
        has_split = bool(player.get("split_cards"))
        if has_split:
            _draw_centered_text(draw, y + 24, "[主手]", (200, 200, 200), tag_font, width)
        
        # 主手牌居中
        cards = player.get("cards", [])
        card_end_x = _draw_cards_centered(draw, y + 28, cards, width)
        
        # 点数（在牌组右侧，防溢出）
        value = player.get("value", 0)
        value_color = COLOR_ERROR if value > 21 else (COLOR_GOLD if value == 21 else COLOR_TEXT_WHITE)
        value_text = f"{value}点"
        value_x = card_end_x + 15
        vbbox = draw.textbbox((0, 0), value_text, font=info_font)
        if value_x + (vbbox[2] - vbbox[0]) > width - 10:
            value_x = width - (vbbox[2] - vbbox[0]) - 15
        draw.text((value_x, y + 50), value_text, fill=value_color, font=info_font)
        
        y += 105
        
        # 绘制分牌手
        if has_split:
            sp_status = player.get("split_status", "")
            sp_icon = status_icons.get(sp_status, "")
            sp_info = f"↳ {sp_icon} 分牌手 (下注{player.get('split_bet', 0):,})"
            _draw_centered_text(draw, y - 18, sp_info, (180, 200, 255), tag_font, width)
            
            split_cards = player.get("split_cards", [])
            sp_end_x = _draw_cards_centered(draw, y, split_cards, width)
            
            sp_value = player.get("split_value", 0)
            sp_color = COLOR_ERROR if sp_value > 21 else (COLOR_GOLD if sp_value == 21 else COLOR_TEXT_WHITE)
            sp_val_text = f"{sp_value}点"
            sp_val_x = sp_end_x + 15
            sp_bbox = draw.textbbox((0, 0), sp_val_text, font=info_font)
            if sp_val_x + (sp_bbox[2] - sp_bbox[0]) > width - 10:
                sp_val_x = width - (sp_bbox[2] - sp_bbox[0]) - 15
            draw.text((sp_val_x, y + 17), sp_val_text, fill=sp_color, font=info_font)
            y += 85
    
    # ── 操作提示区域（嵌入图片底部） ──
    if current_player:
        hint_y = height - hint_height
        draw.rectangle([(0, hint_y), (width, height)], fill=(15, 40, 15))
        draw.line([(30, hint_y + 2), (width - 30, hint_y + 2)], fill=(80, 160, 80), width=1)
        _draw_centered_text(draw, hint_y + 10, f"🎯 轮到 {current_player} 操作",
                           COLOR_GOLD, info_font, width)
        if action_hint:
            _draw_centered_text(draw, hint_y + 35, action_hint,
                               (180, 220, 180), tag_font, width)
    
    return image


def draw_blackjack_result(dealer_cards: List[dict], dealer_value: int,
                          results: List[dict], banker_nickname: str = None,
                          banker_profit: int = None) -> Image.Image:
    """
    绘制21点结算结果图片（居中布局）
    
    Args:
        dealer_cards: 庄家手牌
        dealer_value: 庄家点数
        results: 结算结果列表
        banker_nickname: 庄家昵称
        banker_profit: 庄家盈亏
    """
    num_results = len(results)
    width = IMAGE_WIDTH
    height = 300 + num_results * 90 + (60 if banker_profit is not None else 0)
    
    image = create_vertical_gradient(width, height, (30, 30, 60), (20, 20, 40))
    draw = ImageDraw.Draw(image)
    
    title_font = load_font(30)
    name_font = load_font(20)
    info_font = load_font(16)
    tag_font = load_font(14)
    profit_font = load_font(22)
    
    # 标题居中
    _draw_centered_text(draw, 15, "21点结算", COLOR_TEXT_WHITE, title_font, width)
    
    # ── 庄家结果 ──
    y = 65
    banker_label = "庄家" + (f"（{banker_nickname}）" if banker_nickname else "")
    _draw_centered_text(draw, y, banker_label, COLOR_GOLD, name_font, width)
    
    # 庄家手牌居中
    card_end_x = _draw_cards_centered(draw, y + 30, dealer_cards, width)
    
    value_color = COLOR_ERROR if dealer_value > 21 else COLOR_GOLD
    value_text = f"{dealer_value}点" + (" 💥爆牌" if dealer_value > 21 else "")
    value_x = card_end_x + 15
    vbbox = draw.textbbox((0, 0), value_text, font=info_font)
    if value_x + (vbbox[2] - vbbox[0]) > width - 10:
        value_x = width - (vbbox[2] - vbbox[0]) - 15
    draw.text((value_x, y + 50), value_text, fill=value_color, font=info_font)
    
    # 分隔线
    y = 175
    draw.line([(30, y), (width - 30, y)], fill=(100, 100, 150), width=1)
    
    y += 15
    _draw_centered_text(draw, y, "结算结果", COLOR_TEXT_WHITE, name_font, width)
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
        
        name_display = f"{nickname}"
        if tag_str:
            name_display += f"  {tag_str}"
        _draw_centered_text(draw, y, name_display, COLOR_TEXT_WHITE, name_font, width)
        _draw_centered_text(draw, y + 25, result_text, color, info_font, width)
        _draw_centered_text(draw, y + 48, f"{profit_str} 金币", color, info_font, width)
        y += 85
    
    # 庄家盈亏
    if banker_profit is not None:
        draw.line([(30, y), (width - 30, y)], fill=(100, 100, 150), width=1)
        y += 15
        if banker_profit > 0:
            text = f"庄家盈利：+{banker_profit:,} 金币"
            color = COLOR_SUCCESS
        elif banker_profit < 0:
            text = f"庄家亏损：{banker_profit:,} 金币"
            color = COLOR_ERROR
        else:
            text = f"庄家持平"
            color = COLOR_WARNING
        _draw_centered_text(draw, y, text, color, profit_font, width)
    
    return image


def draw_blackjack_notification(message: str) -> Image.Image:
    """
    将文本消息渲染为风格化通知图片
    用于游戏开桌、加入、保险等文本提示在图片模式下的渲染
    """
    lines = message.strip().split('\n')
    
    # 预处理行数据: (text, color, font_size)
    line_data = []
    first_content = True
    for line in lines:
        stripped = line.strip()
        if not stripped:
            line_data.append(("", None, 0))
            continue
        
        # 第一个非空行作为标题
        if first_content and ('🃏' in stripped or '📊' in stripped or '✅' in stripped):
            line_data.append((stripped, COLOR_GOLD, 24))
            first_content = False
            continue
        first_content = False
        
        # 根据内容决定颜色和字号
        if stripped.startswith('❌'):
            line_data.append((stripped, COLOR_ERROR, 16))
        elif stripped.startswith('✅') or stripped.startswith('🎉'):
            line_data.append((stripped, COLOR_SUCCESS, 16))
        elif stripped.startswith('🏦') or stripped.startswith('💰') or stripped.startswith('👤'):
            line_data.append((stripped, COLOR_TEXT_WHITE, 17))
        elif stripped.startswith('📋') or stripped.startswith('⏩') or stripped.startswith('💡'):
            line_data.append((stripped, (170, 190, 210), 14))
        elif stripped.startswith('⏰') or stripped.startswith('👥'):
            line_data.append((stripped, (200, 210, 220), 16))
        elif stripped.startswith('🛡️'):
            line_data.append((stripped, (100, 200, 255), 16))
        else:
            line_data.append((stripped, COLOR_TEXT_WHITE, 16))
    
    # 计算图片高度
    padding_y = 30
    total_height = padding_y * 2
    for text, _, size in line_data:
        if not text:
            total_height += 12
        elif size >= 24:
            total_height += 40
        elif size <= 14:
            total_height += 24
        else:
            total_height += 30
    
    width = IMAGE_WIDTH
    height = max(120, total_height)
    
    image = create_vertical_gradient(width, height, (30, 30, 60), (20, 20, 40))
    draw = ImageDraw.Draw(image)
    
    y = padding_y
    for text, color, size in line_data:
        if not text:
            y += 12
            continue
        
        font = load_font(size)
        _draw_centered_text(draw, y, text, color, font, width)
        
        if size >= 24:
            y += 40
        elif size <= 14:
            y += 24
        else:
            y += 30
    
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
