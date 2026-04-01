"""
拉杆机(Slot Machine)图片生成模块
生成拉杆机游戏相关的各种图片消息
"""

import os
import time
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
    emoji_font = load_font(48)
    info_font = load_font(20)
    small_font = load_font(16)
    big_font = load_font(36)

    y = 20

    # ===== 标题 =====
    title = f"🎰 拉杆机 · {tier_name}"
    _draw_centered(draw, title, width, y, title_font, COLOR_JACKPOT)
    y += 50

    # ===== 转轮区域 =====
    reel_h = 100
    reel_margin = 40
    reel_rect = [reel_margin, y, width - reel_margin, y + reel_h]

    # 转轮背景 + 金色边框
    draw.rounded_rectangle(reel_rect, radius=15, fill=COLOR_SLOT_REEL,
                           outline=COLOR_SLOT_BORDER, width=3)

    # 三个符号
    sym_w = (width - 2 * reel_margin) // 3
    for i, sym in enumerate(symbols):
        sx = reel_margin + sym_w * i + sym_w // 2
        sy = y + reel_h // 2
        # 符号用大字体居中
        sym_bbox = draw.textbbox((0, 0), sym, font=emoji_font)
        sw = sym_bbox[2] - sym_bbox[0]
        sh = sym_bbox[3] - sym_bbox[1]
        draw.text((sx - sw // 2, sy - sh // 2 - 5), sym, fill=COLOR_TEXT_WHITE, font=emoji_font)

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
    _draw_centered(draw, f"🎰 拉杆机连转 ×{count}  ·  {tier_name}", width, y, title_font, COLOR_JACKPOT)
    y += 50

    # 表头
    draw.text((30, y), "#", fill=(150, 150, 180), font=row_font)
    draw.text((60, y), "结果", fill=(150, 150, 180), font=row_font)
    draw.text((210, y), "描述", fill=(150, 150, 180), font=row_font)
    draw.text((480, y), "盈亏", fill=(150, 150, 180), font=row_font)
    y += 28
    draw.line([(25, y), (width - 25, y)], fill=(80, 80, 120), width=1)
    y += 8

    # 每行结果
    for i, r in enumerate(results, 1):
        rd = r["result"]
        syms = " ".join(rd["symbols"])
        net = rd["net"]
        desc = rd["match_desc"]
        # 截短描述
        if len(desc) > 12:
            desc = desc[:12] + "…"

        net_str = f"+{net:,}" if net > 0 else f"{net:,}"
        net_color = COLOR_SLOT_WIN if net > 0 else (COLOR_SLOT_LOSE if net < 0 else COLOR_WARNING)

        draw.text((30, y), f"{i:>2}", fill=(150, 150, 180), font=row_font)
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
        syms = " ".join(rec.get("symbols", []))
        desc = rec.get("match_desc", "")
        net = rec.get("net", 0)

        if len(desc) > 8:
            desc = desc[:8] + "…"

        net_str = f"+{net:,}" if net > 0 else f"{net:,}"
        net_color = COLOR_SLOT_WIN if net > 0 else (COLOR_SLOT_LOSE if net < 0 else COLOR_WARNING)

        draw.text((25, y), t, fill=(180, 180, 200), font=row_font)
        draw.text((100, y), tier, fill=COLOR_TEXT_WHITE, font=row_font)
        draw.text((165, y), syms, fill=COLOR_TEXT_WHITE, font=row_font)
        draw.text((300, y), desc, fill=COLOR_TEXT_WHITE, font=row_font)
        draw.text((490, y), net_str, fill=net_color, font=row_font)
        y += row_h

    return image


def draw_slot_help(daily_limit: int, tiers_info: Dict) -> Image.Image:
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
        ("🌟 三海星", "×250", "🌟🌟 两海星", "×5"),
        ("💎 三宝石", "×120", "💎 两宝石", "×3"),
        ("🐳 三鲸鱼", "×60", "🐳 两鲸鱼", "×3"),
        ("🦈 三鲨鱼", "×30", "🦈 两鲨鱼", "×2"),
        ("🐙 三章鱼", "×15", "🐙 两章鱼", "×2"),
        ("🦀 三螃蟹", "×8", "🦀 两螃蟹", "×2"),
        ("🐟 三小鱼", "×5", "🐟 两小鱼", "×2"),
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
        "/连转 [档位] [次数] - 连续拉杆（最多10次）",
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
