from typing import Any, Dict, List, Optional, Sequence

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .styles import (
    COLOR_CARD_BORDER,
    COLOR_GOLD,
    COLOR_RARITY_MAP,
    IMG_WIDTH,
    load_font,
)

try:
    from ..core.showcase_themes import get_showcase_theme
except ImportError:
    from core.showcase_themes import get_showcase_theme


def format_rarity_display(rarity: int) -> str:
    """将稀有度转成紧凑且不会撑爆卡片的文本。"""
    try:
        value = max(1, int(rarity))
    except (TypeError, ValueError):
        value = 1
    return "★" * min(value, 10) + ("+" if value > 10 else "")


def _text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont):
    bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> str:
    """按像素宽度截断文字，避免中文名或签名溢出卡片。"""
    value = str(text or "").strip()
    if not value or _text_size(draw, value, font)[0] <= max_width:
        return value
    suffix = "…"
    while value and _text_size(draw, value + suffix, font)[0] > max_width:
        value = value[:-1]
    return value + suffix if value else suffix


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
    max_lines: int,
) -> List[str]:
    """以像素宽度换行，并限制行数。"""
    value = str(text or "").strip()
    if not value:
        return []

    lines: List[str] = []
    current = ""
    for char in value:
        candidate = current + char
        if current and _text_size(draw, candidate, font)[0] > max_width:
            lines.append(current)
            current = char
        else:
            current = candidate
    if current:
        lines.append(current)

    if len(lines) <= max_lines:
        return lines
    lines = lines[:max_lines]
    lines[-1] = _fit_text(draw, lines[-1] + "…", font, max_width)
    return lines


def _draw_shadow_card(
    image: Image.Image,
    draw: ImageDraw.ImageDraw,
    bbox: Sequence[int],
    radius: int,
    fill,
    outline,
    outline_width: int = 1,
):
    """绘制轻阴影卡片，让信息层次更清楚但不压暗背景。"""
    x1, y1, x2, y2 = bbox
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (x1, y1 + 4, x2, y2 + 4),
        radius=radius,
        fill=(54, 76, 98, 32),
    )
    image.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(6)))
    draw.rounded_rectangle(
        bbox,
        radius=radius,
        fill=fill,
        outline=outline,
        width=outline_width,
    )


def _gradient_background(width: int, height: int, top, bottom) -> Image.Image:
    image = Image.new("RGBA", (width, height), top + (255,))
    pixels = image.load()
    denominator = max(1, height - 1)
    for y in range(height):
        ratio = y / denominator
        color = tuple(
            int(top[index] + (bottom[index] - top[index]) * ratio)
            for index in range(3)
        ) + (255,)
        for x in range(width):
            pixels[x, y] = color
    return image


def _rarity_color(rarity: Any):
    try:
        value = int(rarity)
    except (TypeError, ValueError):
        value = 1
    return COLOR_RARITY_MAP.get(value, COLOR_GOLD if value > 10 else COLOR_CARD_BORDER)


def _format_bonus(label: str, value: Any) -> Optional[str]:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    threshold = 1.0 if label != "稀有" else 0.0
    if numeric <= threshold:
        return None
    amount = (numeric - 1) * 100 if label != "稀有" else numeric * 100
    return f"{label} +{amount:.1f}%"


def _attribute_lines(slot_item: Dict[str, Any]) -> List[str]:
    lines = []
    for label, key in (
        ("品质", "bonus_quality"),
        ("渔获", "bonus_quantity"),
        ("稀有", "bonus_rare"),
        ("金币", "bonus_coin"),
    ):
        value = _format_bonus(label, slot_item.get(key))
        if value:
            lines.append(value)
    return lines[:2]


def draw_showcase_image(
    data: Dict[str, Any], avatar_img: Optional[Image.Image] = None
) -> Image.Image:
    """渲染展示柜图片，布局固定、文字可控，适合聊天窗口查看。"""
    nickname = str(data.get("nickname") or "未知钓客")
    signature = str(data.get("signature") or "快来参观我的展示柜吧！")
    try:
        capacity = max(1, int(data.get("capacity", 6) or 6))
    except (TypeError, ValueError):
        capacity = 6
    slots = list(data.get("slots") or [])
    slot_themes = list(data.get("slot_themes") or [])
    count = sum(slot is not None for slot in slots[:capacity])
    theme = get_showcase_theme(data.get("theme", "ocean"))
    colors = theme["colors"]

    outer = 30
    gap = 16
    header_height = 132
    section_height = 42
    card_height = 172
    footer_height = 54
    grid_cols = 2
    grid_rows = (capacity + grid_cols - 1) // grid_cols
    card_width = (IMG_WIDTH - outer * 2 - gap) // grid_cols
    grid_height = grid_rows * card_height + max(0, grid_rows - 1) * gap
    total_height = (
        outer + header_height + 18 + section_height + 14 + grid_height + 20 + footer_height + outer
    )

    image = _gradient_background(
        IMG_WIDTH, total_height, colors["bg_top"], colors["bg_bottom"]
    )
    draw = ImageDraw.Draw(image)

    title_font = load_font(25)
    name_font = load_font(17)
    body_font = load_font(14)
    small_font = load_font(12)
    tiny_font = load_font(11)
    stat_font = load_font(23)

    text_primary = colors["text_primary"]
    text_secondary = colors["text_secondary"]
    text_muted = colors["text_muted"]
    panel_fill = colors["panel_fill"]

    # 用户头部
    header = (outer, outer, IMG_WIDTH - outer, outer + header_height)
    _draw_shadow_card(image, draw, header, 18, panel_fill, colors["panel_border"])
    draw.rounded_rectangle((outer, outer, outer + 7, outer + header_height), radius=4, fill=colors["accent"])

    avatar_size = 76
    avatar_x = outer + 24
    avatar_y = outer + (header_height - avatar_size) // 2
    if avatar_img is not None:
        try:
            resampling = getattr(Image, "Resampling", Image)
            avatar = avatar_img.convert("RGBA").resize(
                (avatar_size, avatar_size), resampling.LANCZOS
            )
            mask = Image.new("L", (avatar_size, avatar_size), 0)
            ImageDraw.Draw(mask).ellipse((0, 0, avatar_size, avatar_size), fill=255)
            image.paste(avatar, (avatar_x, avatar_y), mask)
        except Exception:
            avatar_img = None
    if avatar_img is None:
        draw.ellipse(
            (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
            fill=colors["avatar_fill"],
            outline=colors["accent"],
            width=2,
        )
        draw.text(
            (avatar_x + avatar_size // 2, avatar_y + avatar_size // 2),
            nickname[:1] or "钓",
            font=title_font,
            fill=text_primary,
            anchor="mm",
        )
    draw.ellipse(
        (avatar_x, avatar_y, avatar_x + avatar_size, avatar_y + avatar_size),
        outline=colors["panel_border"],
        width=2,
    )

    text_x = avatar_x + avatar_size + 20
    draw.text((text_x, outer + 24), "典藏展示柜", font=title_font, fill=text_primary)
    draw.text(
        (text_x, outer + 61),
        _fit_text(draw, nickname, name_font, 360),
        font=name_font,
        fill=text_secondary,
    )
    signature_lines = _wrap_text(draw, signature, small_font, 390, 2)
    for line_index, line in enumerate(signature_lines):
        draw.text(
            (text_x, outer + 91 + line_index * 16),
            line,
            font=small_font,
            fill=text_muted,
        )

    stat_x1, stat_y1, stat_x2, stat_y2 = IMG_WIDTH - outer - 24 - 132, outer + 25, IMG_WIDTH - outer - 24, outer + 107
    draw.rounded_rectangle(
        (stat_x1, stat_y1, stat_x2, stat_y2),
        radius=16,
        fill=colors["stat_fill"],
        outline=colors["stat_border"],
        width=1,
    )
    draw.text(((stat_x1 + stat_x2) // 2, stat_y1 + 22), "展出数量", font=tiny_font, fill=text_secondary, anchor="mm")
    draw.text(((stat_x1 + stat_x2) // 2, stat_y1 + 57), f"{count} / {capacity}", font=stat_font, fill=colors["accent"], anchor="mm")

    # 区域标题
    section_y = outer + header_height + 18
    draw.text((outer, section_y + 6), "展示物件", font=name_font, fill=text_primary)
    hint = "展示柜装备不会计入背包，可用短码取回"
    hint_x = IMG_WIDTH - outer - _text_size(draw, hint, tiny_font)[0]
    draw.text((hint_x, section_y + 10), hint, font=tiny_font, fill=text_muted)

    # 槽位卡片
    grid_y = section_y + section_height + 14
    for index in range(capacity):
        row, col = divmod(index, grid_cols)
        x1 = outer + col * (card_width + gap)
        y1 = grid_y + row * (card_height + gap)
        x2, y2 = x1 + card_width, y1 + card_height
        slot_item = slots[index] if index < len(slots) else None
        slot_theme = (
            slot_item.get("theme")
            if slot_item
            else slot_themes[index] if index < len(slot_themes) else "ocean"
        )
        slot_colors = get_showcase_theme(slot_theme)["colors"]

        if not slot_item:
            _draw_shadow_card(
                image,
                draw,
                (x1, y1, x2, y2),
                16,
                slot_colors["empty_fill"],
                slot_colors["empty_border"],
            )
            center_x = (x1 + x2) // 2
            draw.ellipse(
                (center_x - 19, y1 + 42, center_x + 19, y1 + 80),
                outline=slot_colors["empty_icon"],
                width=2,
            )
            draw.line(
                (center_x - 9, y1 + 61, center_x + 9, y1 + 61),
                fill=slot_colors["empty_icon"],
                width=2,
            )
            draw.line(
                (center_x, y1 + 52, center_x, y1 + 70),
                fill=slot_colors["empty_icon"],
                width=2,
            )
            draw.text(
                (center_x, y1 + 101),
                f"位置 {index + 1} · 空槽位",
                font=body_font,
                fill=slot_colors["text_secondary"],
                anchor="mm",
            )
            draw.text(
                (center_x, y1 + 128),
                "/放入展示柜 短码",
                font=tiny_font,
                fill=slot_colors["text_muted"],
                anchor="mm",
            )
            continue

        slot_accent = slot_colors["accent"]
        rarity_accent = _rarity_color(slot_item.get("rarity", 1))
        slot_text_primary = slot_colors["text_primary"]
        slot_text_muted = slot_colors["text_muted"]
        _draw_shadow_card(
            image,
            draw,
            (x1, y1, x2, y2),
            16,
            slot_colors["panel_fill"],
            slot_accent,
            2,
        )
        draw.rounded_rectangle((x1, y1, x2, y1 + 7), radius=4, fill=slot_accent)

        code = _fit_text(draw, slot_item.get("display_code", "EQ"), small_font, 70)
        item_type = "鱼竿" if slot_item.get("item_type") == "rod" else "饰品"
        draw.text((x1 + 17, y1 + 18), code, font=small_font, fill=slot_accent)
        slot_meta = f"位置 {index + 1} · {item_type}"
        slot_meta = _fit_text(draw, slot_meta, tiny_font, 122)
        type_width = _text_size(draw, slot_meta, tiny_font)[0]
        draw.text((x2 - 17 - type_width, y1 + 20), slot_meta, font=tiny_font, fill=slot_text_muted)

        refine_level = slot_item.get("refine_level", 1)
        try:
            refine_level = max(1, int(refine_level or 1))
        except (TypeError, ValueError):
            refine_level = 1
        refine = slot_item.get("refine_display", f"精炼等级 {refine_level}")
        refine_width = _text_size(draw, refine, tiny_font)[0] + 16
        draw.rounded_rectangle((x2 - 17 - refine_width, y1 + 42, x2 - 17, y1 + 64), radius=11, fill=slot_colors["refine_fill"])
        draw.text((x2 - 17 - refine_width // 2, y1 + 53), refine, font=tiny_font, fill=slot_colors["refine_text"], anchor="mm")

        name_max_width = max(120, card_width - 34 - refine_width - 10)
        draw.text((x1 + 17, y1 + 46), _fit_text(draw, slot_item.get("name", "未命名装备"), name_font, name_max_width), font=name_font, fill=slot_text_primary)
        rarity = slot_item.get("rarity", 1)
        rarity_label = f"{format_rarity_display(rarity)}  稀有度 {rarity} 星"
        draw.text((x1 + 17, y1 + 76), rarity_label, font=tiny_font, fill=rarity_accent)

        attributes = _attribute_lines(slot_item)
        if attributes:
            for line_index, line in enumerate(attributes):
                draw.text((x1 + 17, y1 + 103 + line_index * 18), line, font=tiny_font, fill=slot_accent)
        else:
            draw.text((x1 + 17, y1 + 106), "基础属性稳定", font=tiny_font, fill=slot_text_muted)
        draw.line((x1 + 17, y2 - 35, x2 - 17, y2 - 35), fill=slot_colors["divider"], width=1)
        draw.text((x1 + 17, y2 - 24), "展示保护中", font=tiny_font, fill=slot_colors["lock_text"])

    footer_y = grid_y + grid_height + 20
    footer = (outer, footer_y, IMG_WIDTH - outer, footer_y + footer_height)
    draw.rounded_rectangle(footer, radius=14, fill=colors["footer_fill"], outline=colors["footer_border"], width=1)
    footer_text = "取出装备：/取出展示柜 短码    |    修改宣言：/展示柜签名 文本"
    draw.text(((footer[0] + footer[2]) // 2, footer[1] + footer_height // 2), footer_text, font=tiny_font, fill=text_secondary, anchor="mm")

    return image
