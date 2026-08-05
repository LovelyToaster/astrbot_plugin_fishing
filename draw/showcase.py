import os
from datetime import datetime
from typing import Dict, Any, List, Optional
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from .utils import get_user_avatar
from .styles import (
    IMG_WIDTH, PADDING, CORNER_RADIUS,
    COLOR_BACKGROUND, COLOR_HEADER_BG, COLOR_TEXT_WHITE, COLOR_TEXT_DARK,
    COLOR_TEXT_GRAY, COLOR_CARD_BG, COLOR_CARD_BORDER, COLOR_ACCENT,
    COLOR_SUCCESS, COLOR_WARNING, COLOR_GOLD, COLOR_REFINE_RED, COLOR_REFINE_ORANGE,
    COLOR_CORNER, load_font
)

def format_rarity_display(rarity: int) -> str:
    """格式化稀有度显示"""
    if rarity <= 10:
        return '★' * rarity
    return '★★★★★★★★★★+'

def draw_showcase_image(data: Dict[str, Any], avatar_img: Optional[Image.Image] = None) -> Image.Image:
    """
    绘制极具质感且排版严谨对齐的典藏展示柜图片
    """
    user_id = data.get("user_id", "")
    nickname = data.get("nickname", "未知钓客")
    signature = data.get("signature", "快来参观我的展示柜吧！")
    capacity = data.get("capacity", 6)
    count = data.get("count", 0)
    slots = data.get("slots", [])

    # 布局参数
    header_height = 140
    footer_height = 50
    grid_cols = 2
    grid_rows = (capacity + grid_cols - 1) // grid_cols
    slot_width = (IMG_WIDTH - PADDING * 3) // grid_cols
    slot_height = 180
    
    total_height = header_height + grid_rows * slot_height + (grid_rows + 1) * PADDING + footer_height

    # 主体暗色配色调整（高质感暗调黑金风格）
    bg_color = (20, 24, 33, 255)
    header_bg = (30, 36, 50, 255)
    header_outline = (212, 175, 55, 200) # 烫金边框

    # 创建画布
    image = Image.new("RGBA", (IMG_WIDTH, total_height), bg_color)
    draw = ImageDraw.Draw(image)

    # 字体加载
    font_title = load_font(22)
    font_name = load_font(16)
    font_subtitle = load_font(13)
    font_body = load_font(13)
    font_small = load_font(11)
    font_badge = load_font(12)

    # 1. 绘制 Header 卡片
    header_x1 = PADDING
    header_y1 = PADDING
    header_x2 = IMG_WIDTH - PADDING
    header_y2 = PADDING + header_height
    header_rect = [header_x1, header_y1, header_x2, header_y2]

    draw.rounded_rectangle(header_rect, radius=CORNER_RADIUS, fill=header_bg, outline=header_outline, width=1)

    # 绘制头像
    avatar_size = 80
    avatar_x = header_x1 + 25
    avatar_y = header_y1 + (header_height - avatar_size) // 2
    
    if avatar_img:
        try:
            avatar_resized = avatar_img.resize((avatar_size, avatar_size), Image.Resampling.LANCZOS)
            mask = Image.new('L', (avatar_size, avatar_size), 0)
            mask_draw = ImageDraw.Draw(mask)
            mask_draw.ellipse((0, 0, avatar_size, avatar_size), fill=255)
            image.paste(avatar_resized, (avatar_x, avatar_y), mask)
            # 头像金框
            draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], outline=header_outline, width=2)
        except Exception:
            avatar_img = None

    if not avatar_img:
        draw.ellipse([avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size], fill=(45, 52, 70, 255), outline=header_outline, width=2)
        initial_char = nickname[0] if nickname else "钓"
        draw.text((avatar_x + avatar_size // 2, avatar_y + avatar_size // 2), initial_char, font=font_title, fill=COLOR_TEXT_WHITE, anchor="mm")

    # 右上角展示位容量胶囊（精准居中）
    pill_w = 130
    pill_h = 32
    pill_x2 = header_x2 - 20
    pill_x1 = pill_x2 - pill_w
    pill_y1 = header_y1 + 20
    pill_y2 = pill_y1 + pill_h

    # 胶囊背景框
    draw.rounded_rectangle([pill_x1, pill_y1, pill_x2, pill_y2], radius=pill_h // 2, fill=(18, 22, 30, 200), outline=COLOR_GOLD, width=1)
    
    # 胶囊文字精准居中（使用 anchor="mm"）
    counter_str = f"已展示: {count} / {capacity}"
    pill_center_x = (pill_x1 + pill_x2) / 2
    pill_center_y = (pill_y1 + pill_y2) / 2
    draw.text((pill_center_x, pill_center_y), counter_str, font=font_badge, fill=COLOR_GOLD, anchor="mm")

    # 左侧标题与描述信息文本块（严格对齐排版）
    text_x = avatar_x + avatar_size + 20

    # 3行文字绝对对齐
    line1_y = header_y1 + 28
    line2_y = header_y1 + 58
    line3_y = header_y1 + 88

    clean_sig = (signature or "").strip()
    draw.text((text_x, line1_y), "典藏展示柜", font=font_title, fill=COLOR_GOLD)
    draw.text((text_x, line2_y), f"钓手：{nickname}", font=font_name, fill=COLOR_TEXT_WHITE)
    draw.text((text_x, line3_y), clean_sig, font=font_subtitle, fill=(160, 175, 200, 255))

    # 2. 绘制 Grid 槽位
    start_y = PADDING + header_height + PADDING

    for idx in range(capacity):
        row = idx // grid_cols
        col = idx % grid_cols
        
        x1 = PADDING + col * (slot_width + PADDING)
        y1 = start_y + row * (slot_height + PADDING)
        x2 = x1 + slot_width
        y2 = y1 + slot_height

        slot_item = slots[idx] if idx < len(slots) else None

        if slot_item:
            # === 有装备的槽位 ===
            card_bg = (32, 38, 52, 255)
            draw.rounded_rectangle([x1, y1, x2, y2], radius=CORNER_RADIUS, fill=card_bg, outline=COLOR_GOLD, width=1)
            
            # 短码徽章 (例如 R1)
            code_str = slot_item.get("display_code", "EQ")
            badge_w, badge_h = 55, 22
            badge_x1, badge_y1 = x1 + 14, y1 + 14
            badge_x2, badge_y2 = badge_x1 + badge_w, badge_y1 + badge_h
            draw.rounded_rectangle([badge_x1, badge_y1, badge_x2, badge_y2], radius=6, fill=COLOR_ACCENT)
            draw.text(((badge_x1 + badge_x2) / 2, (badge_y1 + badge_y2) / 2), code_str, font=font_badge, fill=COLOR_TEXT_DARK, anchor="mm")

            # 类型标签
            item_type_label = "🎣 鱼竿" if slot_item.get("item_type") == "rod" else "💍 饰品"
            draw.text((badge_x2 + 10, badge_y1 + 2), item_type_label, font=font_small, fill=COLOR_TEXT_GRAY)

            # 精炼徽章 (右上角对齐居中)
            refine_lvl = slot_item.get("refine_level", 1)
            if refine_lvl > 1:
                refine_str = f"+{refine_lvl - 1}"
                badge_bg_color = COLOR_REFINE_RED if refine_lvl >= 5 else COLOR_REFINE_ORANGE
                rb_w, rb_h = 42, 22
                rb_x2, rb_y1 = x2 - 14, y1 + 14
                rb_x1, rb_y2 = rb_x2 - rb_w, rb_y1 + rb_h
                draw.rounded_rectangle([rb_x1, rb_y1, rb_x2, rb_y2], radius=10, fill=badge_bg_color)
                draw.text(((rb_x1 + rb_x2) / 2, (rb_y1 + rb_y2) / 2), refine_str, font=font_badge, fill=COLOR_TEXT_WHITE, anchor="mm")

            # 装备名称
            name_str = slot_item.get("name", "未命名装备")
            draw.text((x1 + 14, y1 + 44), name_str, font=font_name, fill=COLOR_TEXT_WHITE)

            # 稀有度
            rarity = slot_item.get("rarity", 1)
            rarity_str = format_rarity_display(rarity)
            draw.text((x1 + 14, y1 + 68), rarity_str, font=font_body, fill=COLOR_GOLD)

            # 属性加成渲染
            bonus_y = y1 + 96
            attr_lines = []
            if slot_item.get("bonus_quality", 1.0) > 1.0:
                attr_lines.append(f"品质提升: +{(slot_item['bonus_quality']-1)*100:.1f}%")
            if slot_item.get("bonus_quantity", 1.0) > 1.0:
                attr_lines.append(f"渔获数量: +{(slot_item['bonus_quantity']-1)*100:.1f}%")
            if slot_item.get("bonus_rare", 0.0) > 0:
                attr_lines.append(f"稀有概率: +{slot_item['bonus_rare']*100:.1f}%")
            if slot_item.get("bonus_coin", 1.0) > 1.0:
                attr_lines.append(f"金币产出: +{(slot_item['bonus_coin']-1)*100:.1f}%")

            if not attr_lines:
                attr_lines.append("基础强化属性提升中")

            for line in attr_lines[:3]:
                draw.text((x1 + 14, bonus_y), f"• {line}", font=font_small, fill=COLOR_SUCCESS)
                bonus_y += 18

            # 锁定安全提示
            draw.text((x1 + 14, y2 - 20), "🔒 展示保护中", font=font_small, fill=COLOR_WARNING)

        else:
            # === 空置槽位 ===
            empty_bg = (26, 32, 44, 180)
            draw.rounded_rectangle([x1, y1, x2, y2], radius=CORNER_RADIUS, fill=empty_bg, outline=(55, 65, 80, 255), width=1)
            
            slot_center_x = (x1 + x2) / 2
            draw.text((slot_center_x, y1 + slot_height // 2 - 14), "📦 槽位空置", font=font_body, fill=COLOR_TEXT_GRAY, anchor="mm")
            draw.text((slot_center_x, y1 + slot_height // 2 + 14), "指令: /放入展示柜 短码", font=font_small, fill=(100, 115, 135, 255), anchor="mm")

    # 3. 绘制 Footer
    footer_y = total_height - footer_height
    draw.line([PADDING, footer_y, IMG_WIDTH - PADDING, footer_y], fill=(45, 55, 70, 255), width=1)
    footer_tip = "💡 提示: 展示柜中的装备已自动获得锁定防护 | 输入 /取出展示柜 <短码> 可移回背包"
    draw.text((PADDING, footer_y + 16), footer_tip, font=font_small, fill=COLOR_TEXT_GRAY)

    return image
