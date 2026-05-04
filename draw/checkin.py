import os
import calendar
from typing import Dict, Any, List
from PIL import Image, ImageDraw
from .gradient_utils import create_vertical_gradient
from .styles import (
    COLOR_TEXT_DARK, COLOR_TEXT_GRAY, COLOR_CARD_BG,
    COLOR_ACCENT, COLOR_TEXT_WHITE, COLOR_GOLD,
    load_font
)
from .text_utils import load_font_with_cjk_fallback, draw_text_smart

FONT_BOLD_PATH = os.path.join(os.path.dirname(__file__), "resource", "DouyinSansBold.otf")

WIDTH, HEIGHT = 620, 560
GRID_TOP = 115
CELL_W = 78
CELL_H = 48
CELL_GAP = 4

WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"]

BG_TOP = (30, 80, 162)
BG_BOT = (245, 251, 255)
CARD_COLOR = (255, 255, 255)
HEADER_BG = (41, 98, 186)
SIGNED_BG = (200, 230, 201)
SIGNED_MARK = (76, 175, 80)
WEEKDAY_COLOR = (200, 215, 240)
GRID_LINE = (220, 220, 220)


def _get_fonts():
    return {
        "title": load_font(26),
        "title_cjk": load_font_with_cjk_fallback(FONT_BOLD_PATH, 26),
        "subtitle": load_font(16),
        "subtitle_cjk": load_font_with_cjk_fallback(FONT_BOLD_PATH, 16),
        "day": load_font(16),
        "weekday": load_font_with_cjk_fallback(FONT_BOLD_PATH, 13),
        "body_cjk": load_font_with_cjk_fallback(FONT_BOLD_PATH, 15),
        "label_cjk": load_font_with_cjk_fallback(FONT_BOLD_PATH, 22),
    }


def _draw_rounded_rect(draw, x, y, w, h, r, fill):
    draw.rounded_rectangle([x, y, x + w, y + h], radius=r, fill=fill)


def draw_sign_in_image(data: Dict[str, Any], data_dir: str) -> Image.Image:
    fonts = _get_fonts()
    image = create_vertical_gradient(WIDTH, HEIGHT, BG_TOP, BG_BOT)
    draw = ImageDraw.Draw(image)

    year = data["year"]
    month = data["month"]
    days_in_month = data["days_in_month"]
    signed_dates: List[int] = data.get("signed_dates", [])
    consecutive = data.get("consecutive_days", 0)
    today = data.get("today", 0)

    reward = data.get("reward", {})

    # --- Header bar ---
    _draw_rounded_rect(draw, 10, 8, WIDTH - 20, 82, 10, fill=HEADER_BG)

    month_names = ["一月", "二月", "三月", "四月", "五月", "六月",
                   "七月", "八月", "九月", "十月", "十一月", "十二月"]
    header_text = f"{year}年{month_names[month - 1]} 签到日历"
    draw_text_smart(draw, (20, 14), header_text, fonts["title_cjk"], COLOR_TEXT_WHITE)

    total_signed = len(signed_dates)
    stats_text = f"本月已签 {total_signed}/{days_in_month} 天  当前连续 {consecutive} 天"
    draw_text_smart(draw, (20, 48), stats_text, fonts["body_cjk"], (220, 235, 255))

    # --- Calendar grid (Monday first) ---
    first_weekday, _ = calendar.monthrange(year, month)
    first_col = first_weekday

    grid_w = 7 * CELL_W + 6 * CELL_GAP
    grid_x = (WIDTH - grid_w) // 2
    grid_y = GRID_TOP

    # weekday header
    for col in range(7):
        cx = grid_x + col * (CELL_W + CELL_GAP)
        wd = WEEKDAYS[col]
        tw = draw.textlength(wd, font=fonts["weekday"].primary_font)
        draw_text_smart(draw, (cx + (CELL_W - tw) // 2, grid_y), wd, fonts["weekday"], WEEKDAY_COLOR)

    header_h = 22
    row_y = grid_y + header_h + 4

    total_rows = (first_col + days_in_month + 6) // 7
    grid_bottom = row_y + total_rows * (CELL_H + CELL_GAP) - CELL_GAP

    for day in range(1, days_in_month + 1):
        cell_idx = first_col + day - 1
        col = cell_idx % 7
        row = cell_idx // 7
        cx = grid_x + col * (CELL_W + CELL_GAP)
        cy = row_y + row * (CELL_H + CELL_GAP)

        is_today = (day == today)
        is_signed = day in signed_dates

        if is_today and not is_signed:
            _draw_rounded_rect(draw, cx, cy, CELL_W, CELL_H, 6, fill=(255, 243, 224))
        elif is_signed:
            _draw_rounded_rect(draw, cx, cy, CELL_W, CELL_H, 6, fill=SIGNED_BG)
        else:
            _draw_rounded_rect(draw, cx, cy, CELL_W, CELL_H, 6, fill=CARD_COLOR)

        draw.rounded_rectangle([cx, cy, cx + CELL_W, cy + CELL_H], radius=6, outline=GRID_LINE, width=1)

        day_color = COLOR_TEXT_DARK
        if is_signed:
            day_color = SIGNED_MARK
        elif is_today:
            day_color = COLOR_ACCENT

        day_str = str(day)
        tw = draw.textlength(day_str, font=fonts["day"])
        draw.text((cx + (CELL_W - tw) // 2, cy + 5), day_str, font=fonts["day"], fill=day_color)

        if is_signed:
            check_str = "✓"
            cw = draw.textlength(check_str, font=fonts["subtitle"])
            draw.text((cx + (CELL_W - cw) // 2, cy + 24), check_str, font=fonts["subtitle"], fill=SIGNED_MARK)

    # --- Reward section ---
    reward_y = grid_bottom + 20
    _draw_rounded_rect(draw, 15, reward_y, WIDTH - 30, 150, 10, fill=CARD_COLOR)
    draw.rounded_rectangle([15, reward_y, WIDTH - 30, reward_y + 150], radius=10, outline=GRID_LINE, width=1)

    draw_text_smart(draw, (30, reward_y + 10), "今日签到奖励", fonts["label_cjk"], COLOR_TEXT_DARK)

    line_y = reward_y + 38
    draw.line([(30, line_y), (WIDTH - 30, line_y)], fill=GRID_LINE, width=1)

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

        coins_line = f"金币: {' + '.join(coins_parts)}"
        prem_line = f"高级货币: {' + '.join(prem_parts)}" if prem_parts else ""

        draw_text_smart(draw, (30, reward_y + 50), coins_line, fonts["body_cjk"], COLOR_TEXT_DARK)
        if prem_line:
            draw_text_smart(draw, (30, reward_y + 78), prem_line, fonts["body_cjk"], COLOR_TEXT_DARK)

        total_line = f"本日合计: +{r.get('total_coins', 0)} 金币"
        if r.get("total_premium", 0) > 0:
            total_line += f"  +{r['total_premium']} 高级货币"
        draw_text_smart(draw, (30, reward_y + 110), total_line, fonts["body_cjk"], COLOR_GOLD)
    elif today in signed_dates:
        draw_text_smart(draw, (30, reward_y + 55), "今天已签到，明天再来吧！",
                       fonts["label_cjk"], SIGNED_MARK)
    else:
        draw_text_smart(draw, (30, reward_y + 55), "今天还没有签到哦，快来签到吧！",
                       fonts["body_cjk"], COLOR_TEXT_GRAY)

    return image
