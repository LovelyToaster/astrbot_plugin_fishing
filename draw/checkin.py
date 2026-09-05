import os
import calendar
from typing import Dict, Any, List
from PIL import Image, ImageDraw
from .gradient_utils import create_vertical_gradient
from .styles import (
    COLOR_TEXT_DARK, COLOR_TEXT_GRAY,
    COLOR_TEXT_WHITE, COLOR_GOLD,
    load_font
)
from .text_utils import load_font_with_cjk_fallback, draw_text_smart

FONT_BOLD_PATH = os.path.join(os.path.dirname(__file__), "resource", "DouyinSansBold.otf")

WIDTH = 620
HEIGHT = 580  # 默认高度（实际根据日历行数及内容动态计算）
CELL_W = 80
CELL_H = 48
CELL_GAP = 5

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

BG_TOP = (30, 80, 162)
BG_BOT = (240, 248, 255)

CARD_COLOR = (255, 255, 255)
CARD_BORDER = (220, 228, 238)
HEADER_BG = (41, 98, 186)
HEADER_BORDER = (65, 125, 215)

SIGNED_BG = (225, 245, 230)
SIGNED_BORDER = (180, 225, 190)
SIGNED_TEXT = (46, 125, 50)

TODAY_NOT_SIGNED_BG = (255, 246, 232)
TODAY_NOT_SIGNED_BORDER = (255, 150, 20)
TODAY_NOT_SIGNED_TEXT = (230, 105, 0)

TODAY_SIGNED_BG = (215, 245, 225)
TODAY_SIGNED_BORDER = (56, 170, 80)

FUTURE_TEXT = (175, 185, 198)
DEFAULT_BORDER = (225, 232, 240)


def _get_fonts():
    return {
        "title": load_font_with_cjk_fallback(FONT_BOLD_PATH, 24),
        "subtitle": load_font(15),
        "day": load_font(17),
        "tag": load_font_with_cjk_fallback(FONT_BOLD_PATH, 11),
        "weekday": load_font_with_cjk_fallback(FONT_BOLD_PATH, 13),
        "body_cjk": load_font_with_cjk_fallback(FONT_BOLD_PATH, 14),
        "body_bold": load_font_with_cjk_fallback(FONT_BOLD_PATH, 15),
        "label_cjk": load_font_with_cjk_fallback(FONT_BOLD_PATH, 18),
        "badge_cjk": load_font_with_cjk_fallback(FONT_BOLD_PATH, 12),
    }


def draw_sign_in_image(data: Dict[str, Any], data_dir: str) -> Image.Image:
    fonts = _get_fonts()

    year = data["year"]
    month = data["month"]
    days_in_month = data["days_in_month"]
    signed_dates: List[int] = data.get("signed_dates", [])
    consecutive = data.get("consecutive_days", 0)
    today = data.get("today", 0)
    reward = data.get("reward", {})

    first_weekday, _ = calendar.monthrange(year, month)
    first_col = first_weekday
    total_rows = (first_col + days_in_month + 6) // 7

    # 布局参数：统一左右边距 15px，标题栏、星期栏、日历网格及奖励卡片宽度完全一致 (590px)
    margin_x = 15
    card_w = WIDTH - 2 * margin_x  # 590
    header_y = 10
    header_h = 80

    weekday_y = 100
    weekday_h = 24
    row_y = weekday_y + weekday_h + 5

    grid_bottom = row_y + total_rows * (CELL_H + CELL_GAP) - CELL_GAP
    reward_y = grid_bottom + 16
    reward_h = 156 if reward else 112
    bottom_padding = 16
    canvas_height = reward_y + reward_h + bottom_padding

    image = create_vertical_gradient(WIDTH, canvas_height, BG_TOP, BG_BOT)
    draw = ImageDraw.Draw(image)

    # --- Header Bar ---
    draw.rounded_rectangle(
        [margin_x, header_y, margin_x + card_w, header_y + header_h],
        radius=10,
        fill=HEADER_BG,
        outline=HEADER_BORDER,
        width=1
    )

    month_names = ["一月", "二月", "三月", "四月", "五月", "六月",
                   "七月", "八月", "九月", "十月", "十一月", "十二月"]
    header_text = f"{year}年{month_names[month - 1]} 签到日历"
    draw_text_smart(draw, (margin_x + 16, header_y + 12), header_text, fonts["title"], COLOR_TEXT_WHITE)

    # 统计信息胶囊
    total_signed = len(signed_dates)
    badge1_text = f"本月已签 {total_signed}/{days_in_month} 天"
    badge2_text = f"连续签到 {consecutive} 天"

    b1_w = int(draw.textlength(badge1_text, font=fonts["badge_cjk"].primary_font)) + 16
    b2_w = int(draw.textlength(badge2_text, font=fonts["badge_cjk"].primary_font)) + 16
    badge_h = 24
    badge_y = header_y + 44

    b1_x = margin_x + 16
    draw.rounded_rectangle([b1_x, badge_y, b1_x + b1_w, badge_y + badge_h], radius=5, fill=(55, 115, 205), outline=(85, 145, 230), width=1)
    draw_text_smart(draw, (b1_x + 8, badge_y + 4), badge1_text, fonts["badge_cjk"], (235, 245, 255))

    b2_x = b1_x + b1_w + 10
    draw.rounded_rectangle([b2_x, badge_y, b2_x + b2_w, badge_y + badge_h], radius=5, fill=(65, 125, 215), outline=(95, 155, 235), width=1)
    draw_text_smart(draw, (b2_x + 8, badge_y + 4), badge2_text, fonts["badge_cjk"], (255, 225, 135))

    # --- Weekday Bar ---
    # 横条宽度与顶部卡片、日历网格完全对齐 (590px)
    draw.rounded_rectangle(
        [margin_x, weekday_y, margin_x + card_w, weekday_y + weekday_h],
        radius=5,
        fill=(46, 105, 195),
        outline=(75, 135, 220),
        width=1
    )

    grid_x = margin_x

    for col in range(7):
        cx = grid_x + col * (CELL_W + CELL_GAP)
        wd = WEEKDAYS[col]
        tw = draw.textlength(wd, font=fonts["weekday"].primary_font)
        wd_color = (255, 215, 145) if col >= 5 else (225, 238, 255)
        draw_text_smart(draw, (cx + (CELL_W - tw) // 2, weekday_y + 4), wd, fonts["weekday"], wd_color)

    # --- Calendar Grid ---
    for day in range(1, days_in_month + 1):
        cell_idx = first_col + day - 1
        col = cell_idx % 7
        row = cell_idx // 7
        cx = grid_x + col * (CELL_W + CELL_GAP)
        cy = row_y + row * (CELL_H + CELL_GAP)

        is_today = (day == today)
        is_signed = day in signed_dates
        is_future = (day > today) if today > 0 else False

        if is_today and is_signed:
            cell_bg = TODAY_SIGNED_BG
            cell_border = TODAY_SIGNED_BORDER
            border_w = 2
            day_color = SIGNED_TEXT
        elif is_today and not is_signed:
            cell_bg = TODAY_NOT_SIGNED_BG
            cell_border = TODAY_NOT_SIGNED_BORDER
            border_w = 2
            day_color = TODAY_NOT_SIGNED_TEXT
        elif is_signed:
            cell_bg = SIGNED_BG
            cell_border = SIGNED_BORDER
            border_w = 1
            day_color = SIGNED_TEXT
        else:
            cell_bg = CARD_COLOR
            cell_border = DEFAULT_BORDER
            border_w = 1
            day_color = FUTURE_TEXT if is_future else COLOR_TEXT_DARK

        draw.rounded_rectangle(
            [cx, cy, cx + CELL_W, cy + CELL_H],
            radius=7,
            fill=cell_bg,
            outline=cell_border,
            width=border_w
        )

        day_str = str(day)
        tw = draw.textlength(day_str, font=fonts["day"])

        if is_signed:
            draw.text((cx + (CELL_W - tw) // 2, cy + 5), day_str, font=fonts["day"], fill=day_color)
            check_str = "✓"
            cw = draw.textlength(check_str, font=fonts["subtitle"])
            draw.text((cx + (CELL_W - cw) // 2, cy + 24), check_str, font=fonts["subtitle"], fill=day_color)
        elif is_today and not is_signed:
            draw.text((cx + (CELL_W - tw) // 2, cy + 4), day_str, font=fonts["day"], fill=day_color)
            tag_str = "今日"
            tag_w = draw.textlength(tag_str, font=fonts["tag"].primary_font)
            draw_text_smart(draw, (cx + (CELL_W - tag_w) // 2, cy + 26), tag_str, fonts["tag"], TODAY_NOT_SIGNED_TEXT)
        else:
            draw.text((cx + (CELL_W - tw) // 2, cy + 13), day_str, font=fonts["day"], fill=day_color)

    # --- Reward Section Card ---
    card_x0 = margin_x
    card_x1 = margin_x + card_w  # 605
    card_y0 = reward_y
    card_y1 = reward_y + reward_h

    draw.rounded_rectangle(
        [card_x0, card_y0, card_x1, card_y1],
        radius=10,
        fill=CARD_COLOR,
        outline=CARD_BORDER,
        width=1
    )

    header_title = "今日签到奖励"
    draw_text_smart(draw, (card_x0 + 16, card_y0 + 12), header_title, fonts["label_cjk"], COLOR_TEXT_DARK)

    if consecutive > 0:
        streak_badge = f"已连签 {consecutive} 天"
        sb_w = draw.textlength(streak_badge, font=fonts["badge_cjk"].primary_font)
        draw_text_smart(draw, (card_x1 - 16 - sb_w, card_y0 + 15), streak_badge, fonts["badge_cjk"], COLOR_TEXT_GRAY)

    line_y = card_y0 + 40
    draw.line([(card_x0 + 16, line_y), (card_x1 - 16, line_y)], fill=(230, 236, 244), width=1)

    if reward:
        r = reward
        coins_parts = []
        if r.get("coins_base", 0) > 0:
            coins_parts.append(f"保底 +{r['coins_base']}")
        if r.get("coins_linear", 0) > 0:
            coins_parts.append(f"连续 +{r['coins_linear']}")
        if r.get("coins_milestone", 0) > 0:
            coins_parts.append(f"里程碑 +{r['coins_milestone']}")

        prem_parts = []
        if r.get("prem_base", 0) > 0:
            prem_parts.append(f"保底 +{r['prem_base']}")
        if r.get("prem_linear", 0) > 0:
            prem_parts.append(f"连续 +{r['prem_linear']}")
        if r.get("prem_milestone", 0) > 0:
            prem_parts.append(f"里程碑 +{r['prem_milestone']}")

        coins_line = f"金币: {'  +  '.join(coins_parts)}" if coins_parts else ""
        prem_line = f"高级货币: {'  +  '.join(prem_parts)}" if prem_parts else ""

        curr_y = card_y0 + 49
        if coins_line:
            draw_text_smart(draw, (card_x0 + 18, curr_y), coins_line, fonts["body_cjk"], COLOR_TEXT_DARK)
            curr_y += 26
        if prem_line:
            draw_text_smart(draw, (card_x0 + 18, curr_y), prem_line, fonts["body_cjk"], COLOR_TEXT_DARK)
            curr_y += 26

        banner_y = card_y1 - 38
        banner_h = 28
        draw.rounded_rectangle(
            [card_x0 + 16, banner_y, card_x1 - 16, banner_y + banner_h],
            radius=6,
            fill=(255, 250, 238),
            outline=(245, 222, 168),
            width=1
        )

        total_coins = r.get("total_coins", 0)
        total_prem = r.get("total_premium", 0)
        total_str = f"本日合计:  +{total_coins} 金币"
        if total_prem > 0:
            total_str += f"    +{total_prem} 高级货币"

        draw_text_smart(draw, (card_x0 + 26, banner_y + 5), total_str, fonts["body_bold"], (195, 115, 15))

    elif today in signed_dates:
        draw_text_smart(
            draw,
            (card_x0 + 18, card_y0 + 54),
            "今天已签到，明天记得再来签到哦！",
            fonts["body_bold"],
            SIGNED_TEXT
        )
        draw_text_smart(
            draw,
            (card_x0 + 18, card_y0 + 78),
            "持续每日签到可解锁更丰厚的连续奖励与里程碑大礼~",
            fonts["body_cjk"],
            COLOR_TEXT_GRAY
        )
    else:
        draw_text_smart(
            draw,
            (card_x0 + 18, card_y0 + 54),
            "今天还没有签到哦，快来签到吧！",
            fonts["body_bold"],
            TODAY_NOT_SIGNED_TEXT
        )
        draw_text_smart(
            draw,
            (card_x0 + 18, card_y0 + 78),
            "每日坚持签到，可领取金币、高级货币及免费抽卡机会！",
            fonts["body_cjk"],
            COLOR_TEXT_GRAY
        )

    return image
