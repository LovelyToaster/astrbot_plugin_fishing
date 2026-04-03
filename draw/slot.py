"""
拉杆机(Slot Machine)图片生成模块
生成拉杆机游戏相关的各种图片消息
"""

import os
import time
import platform
from PIL import Image, ImageDraw, ImageFont
from typing import Dict, Any, List, Optional
from .gradient_utils import create_vertical_gradient
from .styles import (
    COLOR_SUCCESS, COLOR_WARNING, COLOR_ERROR, COLOR_GOLD,
    COLOR_TEXT_DARK, COLOR_TEXT_WHITE, COLOR_CARD_BG,
    load_font
)

# 拉杆机专用色板
COLOR_SLOT_BG_TOP = (25, 25, 50)       # 深蓝黑
COLOR_SLOT_BG_BOT = (15, 15, 35)       # 更深
COLOR_SLOT_REEL = (40, 40, 70)         # 转轮背景
COLOR_SLOT_BORDER = (255, 215, 0)      # 金色边框
COLOR_SLOT_WIN = (50, 205, 50)         # 中奖绿
COLOR_SLOT_LOSE = (200, 80, 80)        # 未中红
COLOR_JACKPOT = (255, 215, 0)          # Jackpot 金色
COLOR_MINI_JP = (192, 192, 255)        # Mini Jackpot 浅紫
COLOR_LUCKY = (255, 200, 100)          # 幸运时段暖色

# 拉杆机符号样式映射 (emoji -> (中文标签, 显示颜色))
SYMBOL_STYLE_MAP = {
    "🐟": ("小鱼", (100, 180, 255)),     # 浅蓝
    "🦀": ("螃蟹", (255, 130, 80)),      # 橙红
    "🐙": ("章鱼", (190, 130, 255)),     # 紫色
    "🦈": ("鲨鱼", (130, 160, 210)),     # 蓝灰
    "🐳": ("鲸鱼", (80, 170, 255)),      # 亮蓝
    "💎": ("宝石", (100, 240, 240)),     # 青色
    "🌟": ("海星", (255, 220, 80)),      # 金色
}

# ---------------------------------------------------------------------------
# Emoji 字体检测与缓存
# ---------------------------------------------------------------------------
_emoji_font_cache: Dict[int, Optional[ImageFont.FreeTypeFont]] = {}
_emoji_support_checked = False
_emoji_support_available = False


def _detect_emoji_font_paths() -> List[str]:
    """根据操作系统返回候选 emoji 字体路径，系统彩色字体优先，内置字体兜底"""
    paths: List[str] = []
    # 内置字体作为最终兜底（单色但跨平台可用）
    bundled = os.path.join(os.path.dirname(__file__), "resource", "NotoEmoji.ttf")

    system = platform.system()
    if system == "Windows":
        windir = os.environ.get("WINDIR", r"C:\Windows")
        paths.append(os.path.join(windir, "Fonts", "seguiemj.ttf"))       # Segoe UI Emoji (彩色)
    elif system == "Linux":
        paths.extend([
            "/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf",
            "/usr/share/fonts/noto-emoji/NotoColorEmoji.ttf",
            "/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf",
            "/usr/share/fonts/truetype/noto/NotoEmoji-Regular.ttf",
            "/usr/share/fonts/noto/NotoEmoji-Regular.ttf",
            "/usr/share/fonts/noto-emoji/NotoEmoji-Regular.ttf",
        ])
    elif system == "Darwin":
        paths.append("/System/Library/Fonts/Apple Color Emoji.ttc")

    # 内置字体始终作为最终兜底
    paths.append(bundled)
    return paths


def _test_emoji_render(font: ImageFont.FreeTypeFont) -> bool:
    """测试字体是否真的能渲染 emoji（非零尺寸且有像素输出）"""
    try:
        test_img = Image.new("RGBA", (120, 120), (0, 0, 0, 0))
        test_draw = ImageDraw.Draw(test_img)
        test_draw.text((10, 10), "🐟", font=font, fill=(255, 255, 255, 255))
        bbox = test_img.getbbox()
        if bbox and (bbox[2] - bbox[0]) > 8 and (bbox[3] - bbox[1]) > 8:
            return True
    except Exception:
        pass
    return False


def _get_emoji_font(size: int) -> Optional[ImageFont.FreeTypeFont]:
    """尝试加载 emoji 字体并缓存，若不可用返回 None"""
    global _emoji_support_checked, _emoji_support_available

    # 已确认不支持则快速返回
    if _emoji_support_checked and not _emoji_support_available:
        return None
    if size in _emoji_font_cache:
        return _emoji_font_cache[size]

    for path in _detect_emoji_font_paths():
        if os.path.exists(path):
            try:
                font = ImageFont.truetype(path, size)
                if _test_emoji_render(font):
                    _emoji_font_cache[size] = font
                    _emoji_support_checked = True
                    _emoji_support_available = True
                    return font
            except Exception:
                continue

    _emoji_font_cache[size] = None
    _emoji_support_checked = True
    _emoji_support_available = False
    return None


def _render_symbol_cell(draw: ImageDraw.Draw, sym_emoji: str,
                        cx: int, cy: int, cell_w: int, cell_h: int,
                        label_font, emoji_font_size: int = 40):
    """渲染单个拉杆机符号单元格 —— emoji 优先，文字兜底
    
    cx, cy: 单元格左上角坐标
    cell_w, cell_h: 单元格尺寸
    """
    _, sym_color = SYMBOL_STYLE_MAP.get(sym_emoji, (sym_emoji, COLOR_TEXT_WHITE))
    emoji_font = _get_emoji_font(emoji_font_size)
    if emoji_font:
        # emoji 模式：居中绘制 emoji
        # 对于单色字体使用符号主题色，彩色字体 embedded_color 会自动覆盖
        eb = draw.textbbox((0, 0), sym_emoji, font=emoji_font)
        ew = eb[2] - eb[0]
        eh = eb[3] - eb[1]
        ex = cx + cell_w // 2 - ew // 2
        ey = cy + cell_h // 2 - eh // 2
        draw.text((ex, ey), sym_emoji, font=emoji_font, fill=sym_color,
                  embedded_color=True)
    else:
        # 文字标签模式：彩色背景 + 居中中文
        label, sym_color = SYMBOL_STYLE_MAP.get(sym_emoji, (sym_emoji, COLOR_TEXT_WHITE))
        pad = 6
        cell_rect = [cx + pad, cy + pad, cx + cell_w - pad, cy + cell_h - pad]
        bg_color = tuple(max(0, c - 80) for c in sym_color)
        draw.rounded_rectangle(cell_rect, radius=8, fill=bg_color)
        lb = draw.textbbox((0, 0), label, font=label_font)
        lw = lb[2] - lb[0]
        lh = lb[3] - lb[1]
        lx = cx + cell_w // 2 - lw // 2
        ly = cy + cell_h // 2 - lh // 2
        draw.text((lx, ly), label, fill=sym_color, font=label_font)


def _symbol_display_text(sym_emoji: str) -> str:
    """将一个 emoji 符号转换为适合 PIL 绘制的显示文本（emoji 优先）"""
    if _get_emoji_font(18):
        return sym_emoji
    label, _ = SYMBOL_STYLE_MAP.get(sym_emoji, (sym_emoji, None))
    return label


def draw_slot_result(symbols: List[str], tier_name: str, cost: int, payout: int,
                     net: int, match_type: str, match_desc: str,
                     balance: int, remaining: int, daily_limit: int,
                     jackpot_pool: int, jackpot_win: int = 0,
                     is_lucky_hour: bool = False) -> Image.Image:
    """绘制单次拉杆结果图片"""
    width = 600
    height = 520 if jackpot_win > 0 else 480
    if is_lucky_hour:
        height += 30

    # 深色渐变背景，营造拉杆机氛围
    image = create_vertical_gradient(width, height, COLOR_SLOT_BG_TOP, COLOR_SLOT_BG_BOT)
    draw = ImageDraw.Draw(image)

    title_font = load_font(30)
    info_font = load_font(20)
    small_font = load_font(16)
    big_font = load_font(36)

    y = 20

    # ===== 标题 =====
    title = f"拉杆机 · {tier_name}"
    _draw_centered(draw, title, width, y, title_font, COLOR_JACKPOT)
    y += 50

    # ===== 转轮区域 =====
    reel_h = 100
    reel_margin = 40
    reel_rect = [reel_margin, y, width - reel_margin, y + reel_h]

    # 转轮背景 + 金色边框
    draw.rounded_rectangle(reel_rect, radius=15, fill=COLOR_SLOT_REEL,
                           outline=COLOR_SLOT_BORDER, width=3)

    # 三个符号 —— emoji 优先，文字标签兜底
    sym_w = (width - 2 * reel_margin) // 3
    label_font = load_font(28)
    for i, sym in enumerate(symbols):
        sx = reel_margin + sym_w * i
        _render_symbol_cell(draw, sym, sx, y, sym_w, reel_h,
                            label_font, emoji_font_size=40)

        # 分隔线（前两个后面画竖线）
        if i < 2:
            lx = reel_margin + sym_w * (i + 1)
            draw.line([(lx, y + 10), (lx, y + reel_h - 10)],
                      fill=(100, 100, 140), width=2)

    y += reel_h + 20

    # ===== 结果描述 =====
    if match_type == "jackpot":
        _draw_centered(draw, "🎉🎉🎉 JACKPOT！！！ 🎉🎉🎉", width, y, info_font, COLOR_JACKPOT)
        y += 30
        _draw_centered(draw, f"🏆 独得累积奖池：{jackpot_win:,} 金币", width, y, info_font, COLOR_JACKPOT)
        y += 30
    elif match_type == "mini_jackpot":
        _draw_centered(draw, f"🎊 {match_desc}", width, y, info_font, COLOR_MINI_JP)
        y += 30
    elif match_type in ("triple", "double"):
        _draw_centered(draw, f"🏆 {match_desc}", width, y, info_font, COLOR_SLOT_WIN)
        y += 30
    else:
        _draw_centered(draw, f"💨 {match_desc}", width, y, info_font, (150, 150, 170))
        y += 30

    # ===== 盈亏 =====
    if net > 0:
        net_text = f"💰 赢得：+{net:,} 金币"
        net_color = COLOR_SLOT_WIN
    elif net < 0:
        net_text = f"💸 花费：{net:,} 金币"
        net_color = COLOR_SLOT_LOSE
    else:
        net_text = "⚖️ 持平"
        net_color = COLOR_WARNING
    _draw_centered(draw, net_text, width, y, info_font, net_color)
    y += 35

    # ===== 分隔线 =====
    draw.line([(40, y), (width - 40, y)], fill=(80, 80, 120), width=1)
    y += 15

    # ===== 底部信息 =====
    info_items = [
        (f"💳 余额：{balance:,}", COLOR_TEXT_WHITE),
        (f"🎰 今日剩余：{remaining}/{daily_limit}", COLOR_TEXT_WHITE),
        (f"🏆 累积奖池：{jackpot_pool:,}", COLOR_JACKPOT),
    ]
    for text, color in info_items:
        _draw_centered(draw, text, width, y, small_font, color)
        y += 24

    if is_lucky_hour:
        y += 5
        _draw_centered(draw, "🍀 当前处于幸运时段！高级符号概率UP！", width, y, small_font, COLOR_LUCKY)

    return image


def draw_slot_multi_result(results: List[Dict[str, Any]], tier_name: str,
                           total_cost: int, total_payout: int, total_net: int,
                           balance: int, remaining: int, daily_limit: int,
                           jackpot_pool: int) -> Image.Image:
    """绘制连转结果图片"""
    count = len(results)
    row_h = 32
    width = 650
    height = 200 + count * row_h + 80

    image = create_vertical_gradient(width, height, COLOR_SLOT_BG_TOP, COLOR_SLOT_BG_BOT)
    draw = ImageDraw.Draw(image)

    title_font = load_font(28)
    row_font = load_font(18)
    info_font = load_font(18)
    small_font = load_font(16)

    y = 20

    # 标题
    _draw_centered(draw, f"拉杆机连转 ×{count}  ·  {tier_name}", width, y, title_font, COLOR_JACKPOT)
    y += 50

    # 表头
    draw.text((30, y), "#", fill=(150, 150, 180), font=row_font)
    draw.text((60, y), "结果", fill=(150, 150, 180), font=row_font)
    draw.text((210, y), "描述", fill=(150, 150, 180), font=row_font)
    draw.text((480, y), "盈亏", fill=(150, 150, 180), font=row_font)
    y += 28
    draw.line([(25, y), (width - 25, y)], fill=(80, 80, 120), width=1)
    y += 8

    # 用于行内显示的 emoji 字体（可能为 None）
    row_emoji_font = _get_emoji_font(18)

    # 每行结果
    for i, r in enumerate(results, 1):
        rd = r["result"]
        # emoji 优先，不可用则文字标签
        sym_list = rd["symbols"]
        display_syms = [_symbol_display_text(s) for s in sym_list]
        syms = " ".join(display_syms)
        net = rd["net"]
        desc = rd["match_desc"]
        # 截短描述
        if len(desc) > 12:
            desc = desc[:12] + "…"

        net_str = f"+{net:,}" if net > 0 else f"{net:,}"
        net_color = COLOR_SLOT_WIN if net > 0 else (COLOR_SLOT_LOSE if net < 0 else COLOR_WARNING)

        draw.text((30, y), f"{i:>2}", fill=(150, 150, 180), font=row_font)
        # 符号列：如果能渲染 emoji，用 emoji 字体绘制
        if row_emoji_font:
            draw.text((60, y), syms, fill=COLOR_TEXT_WHITE, font=row_emoji_font,
                      embedded_color=True)
        else:
            draw.text((60, y), syms, fill=COLOR_TEXT_WHITE, font=row_font)
        draw.text((210, y), desc, fill=COLOR_TEXT_WHITE, font=row_font)
        draw.text((480, y), net_str, fill=net_color, font=row_font)
        y += row_h

    y += 10
    draw.line([(25, y), (width - 25, y)], fill=(80, 80, 120), width=1)
    y += 15

    # 合计
    net_str = f"+{total_net:,}" if total_net > 0 else f"{total_net:,}"
    net_color = COLOR_SLOT_WIN if total_net > 0 else (COLOR_SLOT_LOSE if total_net < 0 else COLOR_WARNING)
    _draw_centered(draw, f"📊 合计盈亏：{net_str} 金币", width, y, info_font, net_color)
    y += 28
    _draw_centered(draw, f"💳 余额：{balance:,}  |  🎰 剩余：{remaining}/{daily_limit}  |  🏆 奖池：{jackpot_pool:,}",
                   width, y, small_font, COLOR_TEXT_WHITE)

    return image


def draw_slot_jackpot_info(jackpot_pool: int, lucky_hour_info: str,
                           is_lucky_hour: bool,
                           tiers: Dict[str, Dict]) -> Image.Image:
    """绘制奖池信息图片"""
    width, height = 600, 500

    bg_top = (20, 20, 60)
    bg_bot = (10, 10, 30)
    image = create_vertical_gradient(width, height, bg_top, bg_bot)
    draw = ImageDraw.Draw(image)

    title_font = load_font(32)
    big_font = load_font(42)
    section_font = load_font(22)
    info_font = load_font(18)
    small_font = load_font(16)

    y = 25

    # 标题
    _draw_centered(draw, "🏆 拉杆机累积奖池", width, y, title_font, COLOR_JACKPOT)
    y += 55

    # 奖池金额（大号）
    pool_text = f"{jackpot_pool:,} 金币"
    _draw_centered(draw, pool_text, width, y, big_font, COLOR_JACKPOT)
    y += 60

    # 幸运时段
    if is_lucky_hour:
        _draw_centered(draw, f"🍀 幸运时段进行中！({lucky_hour_info})", width, y, info_font, COLOR_LUCKY)
    else:
        _draw_centered(draw, f"⏰ 今日幸运时段：{lucky_hour_info}", width, y, info_font, (180, 180, 200))
    y += 40

    # 分隔线
    draw.line([(40, y), (width - 40, y)], fill=(80, 80, 120), width=1)
    y += 20

    # 档位表
    _draw_centered(draw, "📋 档位一览", width, y, section_font, COLOR_TEXT_WHITE)
    y += 35

    # 表头
    draw.text((50, y), "档位", fill=(150, 150, 180), font=info_font)
    draw.text((150, y), "花费/次", fill=(150, 150, 180), font=info_font)
    draw.text((310, y), "Jackpot", fill=(150, 150, 180), font=info_font)
    draw.text((440, y), "Mini JP", fill=(150, 150, 180), font=info_font)
    y += 28
    draw.line([(45, y), (width - 45, y)], fill=(80, 80, 120), width=1)
    y += 10

    for tier_key, t in tiers.items():
        draw.text((50, y), t.get("name", tier_key), fill=COLOR_TEXT_WHITE, font=info_font)
        draw.text((150, y), f"{t['cost']:,}", fill=COLOR_GOLD, font=info_font)
        draw.text((310, y), t.get("jackpot_chance", "0%"), fill=COLOR_JACKPOT, font=info_font)
        draw.text((440, y), t.get("mini_chance", "0%"), fill=COLOR_MINI_JP, font=info_font)
        y += 28

    return image


def draw_slot_history(records: List[Dict], username: str) -> Image.Image:
    """绘制用户拉杆历史图片"""
    count = len(records) if records else 0
    row_h = 28
    width, height = 600, max(300, 160 + count * row_h)

    image = create_vertical_gradient(width, height, COLOR_SLOT_BG_TOP, COLOR_SLOT_BG_BOT)
    draw = ImageDraw.Draw(image)

    title_font = load_font(26)
    row_font = load_font(16)

    y = 20
    _draw_centered(draw, f"📋 {username} 的拉杆记录", width, y, title_font, COLOR_JACKPOT)
    y += 45

    if not records:
        _draw_centered(draw, "💭 暂无拉杆记录", width, y, row_font, (150, 150, 180))
        return image

    # 表头
    draw.text((25, y), "时间", fill=(150, 150, 180), font=row_font)
    draw.text((100, y), "档位", fill=(150, 150, 180), font=row_font)
    draw.text((165, y), "结果", fill=(150, 150, 180), font=row_font)
    draw.text((300, y), "描述", fill=(150, 150, 180), font=row_font)
    draw.text((490, y), "盈亏", fill=(150, 150, 180), font=row_font)
    y += 24
    draw.line([(20, y), (width - 20, y)], fill=(80, 80, 120), width=1)
    y += 6

    for rec in reversed(records):  # 最新的在前
        t = rec.get("time", "")
        tier = rec.get("tier", "")
        # emoji 优先，不可用则文字标签
        raw_syms = rec.get("symbols", [])
        display_syms = [_symbol_display_text(s) for s in raw_syms]
        syms = " ".join(display_syms)
        desc = rec.get("match_desc", "")
        net = rec.get("net", 0)

        if len(desc) > 8:
            desc = desc[:8] + "…"

        net_str = f"+{net:,}" if net > 0 else f"{net:,}"
        net_color = COLOR_SLOT_WIN if net > 0 else (COLOR_SLOT_LOSE if net < 0 else COLOR_WARNING)

        row_emoji_font = _get_emoji_font(16)
        draw.text((25, y), t, fill=(180, 180, 200), font=row_font)
        draw.text((100, y), tier, fill=COLOR_TEXT_WHITE, font=row_font)
        if row_emoji_font:
            draw.text((165, y), syms, fill=COLOR_TEXT_WHITE, font=row_emoji_font,
                      embedded_color=True)
        else:
            draw.text((165, y), syms, fill=COLOR_TEXT_WHITE, font=row_font)
        draw.text((300, y), desc, fill=COLOR_TEXT_WHITE, font=row_font)
        draw.text((490, y), net_str, fill=net_color, font=row_font)
        y += row_h

    return image


def draw_slot_help(daily_limit: int, tiers_info: Dict,
                   max_multi_spin: int = 10) -> Image.Image:
    """绘制拉杆机帮助图片"""
    width, height = 650, 800

    bg_top = (20, 25, 55)
    bg_bot = (10, 12, 30)
    image = create_vertical_gradient(width, height, bg_top, bg_bot)
    draw = ImageDraw.Draw(image)

    title_font = load_font(32)
    section_font = load_font(22)
    content_font = load_font(17)
    small_font = load_font(15)

    y = 25
    _draw_centered(draw, "🎰 拉杆机帮助", width, y, title_font, COLOR_JACKPOT)
    y += 55

    # 游戏说明卡片
    card_h = 110
    _draw_card(draw, 30, y, width - 60, card_h, "📋 游戏说明")
    inner_y = y + 35
    rules = [
        "• 投入金币拉杆，3个转轮随机停止",
        "• 三同 → 高倍奖金 | 两同 → 小倍奖金",
        f"• 每日限 {daily_limit} 次，支持连转模式",
        "• 幸运时段：每日随机2h，高级符号概率提升",
    ]
    for rule in rules:
        draw.text((55, inner_y), rule, fill=COLOR_TEXT_WHITE, font=content_font)
        inner_y += 20
    y += card_h + 15

    # 赔率卡片
    card_h = 220
    _draw_card(draw, 30, y, width - 60, card_h, "💰 赔率表")
    inner_y = y + 35
    odds_data = [
        ("海星 ×250", "×250", "两海星", "×5"),
        ("宝石 ×120", "×120", "两宝石", "×3"),
        ("鲸鱼 ×60", "×60", "两鲸鱼", "×2"),
        ("鲨鱼 ×30", "×30", "两鲨鱼", "×1"),
        ("章鱼 ×15", "×15", "两章鱼", "×1"),
        ("螃蟹 ×8", "×8", "两螃蟹", "×1"),
        ("小鱼 ×5", "×5", "两小鱼", "×1"),
    ]
    # 表头
    draw.text((55, inner_y), "三同", fill=(150, 150, 180), font=small_font)
    draw.text((200, inner_y), "赔率", fill=(150, 150, 180), font=small_font)
    draw.text((330, inner_y), "两同", fill=(150, 150, 180), font=small_font)
    draw.text((500, inner_y), "赔率", fill=(150, 150, 180), font=small_font)
    inner_y += 22
    for triple, t_odds, double, d_odds in odds_data:
        draw.text((55, inner_y), triple, fill=COLOR_TEXT_WHITE, font=small_font)
        draw.text((200, inner_y), t_odds, fill=COLOR_JACKPOT, font=small_font)
        draw.text((330, inner_y), double, fill=COLOR_TEXT_WHITE, font=small_font)
        draw.text((500, inner_y), d_odds, fill=COLOR_GOLD, font=small_font)
        inner_y += 24
    y += card_h + 15

    # 档位卡片
    card_h = 130
    _draw_card(draw, 30, y, width - 60, card_h, "🏷️ 档位")
    inner_y = y + 35
    tier_list = [
        ("铜桌 1万/次", "银桌 10万/次"),
        ("金桌 100万/次", "至尊桌 500万/次"),
        ("金桌/至尊桌 可触发 Jackpot 累积奖池", ""),
    ]
    for left, right in tier_list:
        draw.text((55, inner_y), left, fill=COLOR_TEXT_WHITE, font=content_font)
        if right:
            draw.text((330, inner_y), right, fill=COLOR_TEXT_WHITE, font=content_font)
        inner_y += 24
    y += card_h + 15

    # 命令卡片
    card_h = 130
    _draw_card(draw, 30, y, width - 60, card_h, "⌨️ 命令")
    inner_y = y + 35
    cmds = [
        "/拉杆 [档位]     - 单次拉杆（默认铜桌）",
        f"/连转 [档位] [次数] - 连续拉杆（最多{max_multi_spin}次）",
        "/奖池          - 查看累积奖池与档位",
        "/拉杆记录       - 查看最近拉杆历史",
        "/拉杆帮助       - 查看本帮助",
    ]
    for cmd in cmds:
        draw.text((55, inner_y), cmd, fill=COLOR_TEXT_WHITE, font=small_font)
        inner_y += 20

    return image


# ---------------------------------------------------------------------------
# 辅助函数
# ---------------------------------------------------------------------------

def _draw_centered(draw: ImageDraw.Draw, text: str, width: int, y: int,
                   font, color):
    """居中绘制文字"""
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    draw.text(((width - tw) // 2, y), text, fill=color, font=font)


def _draw_card(draw: ImageDraw.Draw, x: int, y: int, w: int, h: int, title: str):
    """绘制暗色圆角卡片"""
    draw.rounded_rectangle(
        [(x, y), (x + w, y + h)],
        radius=10, fill=(35, 35, 65), outline=(60, 60, 100), width=1
    )
    section_font = load_font(20)
    draw.text((x + 20, y + 8), title, fill=COLOR_JACKPOT, font=section_font)


def save_image_to_temp(image: Image.Image, prefix: str, data_dir: str) -> str:
    """保存图片到临时目录"""
    tmp_dir = os.path.join(data_dir, "tmp")
    os.makedirs(tmp_dir, exist_ok=True)
    filename = f"{prefix}_{int(time.time() * 1000)}.png"
    filepath = os.path.join(tmp_dir, filename)
    image.save(filepath, "PNG")
    return filepath
