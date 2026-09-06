import asyncio
import os
from typing import Dict, Any, List

from PIL import Image, ImageDraw, ImageFont
from astrbot.api import logger

from .styles import (
    IMG_WIDTH, PADDING, CORNER_RADIUS,
    HEADER_HEIGHT, USER_CARD_HEIGHT, USER_CARD_MARGIN,
    COLOR_BACKGROUND, COLOR_HEADER_BG, COLOR_TEXT_WHITE as COLOR_HEADER_TEXT,
    COLOR_CARD_BG, COLOR_CARD_BORDER, COLOR_TEXT_DARK,
    COLOR_TEXT_GRAY, COLOR_ACCENT, COLOR_SUCCESS, COLOR_ERROR, COLOR_WARNING,
    COLOR_GOLD, load_font,
)
from .rank import draw_rounded_rectangle, get_text_metrics, format_large_number
from .utils import get_user_avatar, run_in_thread


def format_number(number):
    """格式化数字，超过1万显示带单位的短格式"""
    if isinstance(number, str):
        # 已是格式化后的字符串（如成功率），直接返回
        return number
    if number < 10000:
        return str(number)
    return format_large_number(number)


def draw_user_statistics_image(data: Dict[str, Any], output_path: str) -> None:
    """
    绘制个人统计图片。

    展示内容：
        - 统计范围（今天/本周/本月）
        - 用户昵称
        - 行为概览：偷鱼 / 电鱼 / 卖鱼 / 总次数
        - 成功情况：成功次数 / 失败次数 / 成功率
        - 鱼数情况：偷到、电到、卖出的鱼数合计
    """
    try:
        font_title = load_font(36)
        font_subtitle = load_font(24)
        font_section = load_font(20)
        font_regular = load_font(18)
        font_small = load_font(16)
        font_value = load_font(22)
    except IOError:
        logger.warning("指定的字体文件未找到，使用默认字体。")
        font_title = ImageFont.load_default()
        font_subtitle = ImageFont.load_default()
        font_section = ImageFont.load_default()
        font_regular = ImageFont.load_default()
        font_small = ImageFont.load_default()
        font_value = ImageFont.load_default()

    nickname = data.get("nickname", "未知用户")
    if len(nickname) > 16:
        nickname = nickname[:14] + "..."

    period = data.get("period", "today")
    period_labels = {"today": "📊 今日统计", "week": "📊 本周统计", "month": "📊 本月统计"}
    period_title = period_labels.get(period, "📊 统计")

    # 卡片常量
    card_inner_margin = 15
    card_count = 3
    card_height = 108
    card_gap = 12
    note_gap = 18

    # 预留足够画布，最后裁剪到实际内容高度。
    # 若画布高度不足再裁剪到更高区域，Pillow 会用黑色补齐，导致图片底部出现黑底。
    total_height = (
        PADDING + HEADER_HEIGHT + 10 + 45
        + card_count * card_height
        + (card_count - 1) * card_gap
        + note_gap + 35 + PADDING
    )

    img = Image.new("RGB", (IMG_WIDTH, total_height), COLOR_BACKGROUND)
    draw = ImageDraw.Draw(img)

    # -- 标题区域 --
    draw_rounded_rectangle(
        draw,
        (PADDING, PADDING, IMG_WIDTH - PADDING, PADDING + HEADER_HEIGHT),
        radius=CORNER_RADIUS, fill=COLOR_HEADER_BG,
    )
    _, (tw, th) = get_text_metrics(period_title, font_title, draw)
    draw.text(
        ((IMG_WIDTH - tw) // 2, PADDING + (HEADER_HEIGHT - th) // 2),
        period_title, font=font_title, fill=COLOR_HEADER_TEXT,
    )

    # -- 昵称副标题 --
    current_y = PADDING + HEADER_HEIGHT + 10
    _, (nw, nh) = get_text_metrics(f"👤 {nickname}", font_subtitle, draw)
    draw.text(
        ((IMG_WIDTH - nw) // 2, current_y),
        f"👤 {nickname}", font=font_subtitle, fill=COLOR_TEXT_DARK,
    )
    current_y += nh + 15

    # -- 辅助：绘制数据卡片 --
    def draw_data_card(y_start, label_text, items, card_height=108):
        """绘制一个圆角卡片，包含一行多列数据。"""
        x1 = PADDING
        y1 = y_start
        x2 = IMG_WIDTH - PADDING
        y2 = y_start + card_height

        draw_rounded_rectangle(
            draw, (x1, y1, x2, y2),
            radius=10, fill=COLOR_CARD_BG, outline=COLOR_CARD_BORDER, width=2,
        )

        # 卡片左侧标签
        _, (lw, lh) = get_text_metrics(label_text, font_section, draw)
        label_x = x1 + card_inner_margin
        label_y = y1 + (card_height - lh) // 2
        draw.text((label_x, label_y), label_text, font=font_section, fill=COLOR_ACCENT)

        if not items:
            return

        # 卡片右侧内容。固定单行多列，避免 4 项数据换行后与卡片内容重叠。
        content_x = x1 + 150
        content_right = x2 - card_inner_margin
        max_content_width = content_right - content_x
        col_count = len(items)
        col_width = max_content_width // col_count
        item_y = y1 + 27

        for idx, (item_label, item_value, item_color) in enumerate(items):
            item_x = content_x + idx * col_width

            # 标签
            draw.text((item_x, item_y), item_label, font=font_small, fill=COLOR_TEXT_GRAY)
            # 值
            value_str = format_number(item_value)
            _, (vw, vh) = get_text_metrics(value_str, font_value, draw)
            # 如果值太长，缩小字体
            use_font = font_value
            if vw > col_width - 10:
                _, (vw_s, vh_s) = get_text_metrics(value_str, font_regular, draw)
                if vw_s > col_width - 10:
                    value_str = format_large_number(item_value)
                    _, (vw, vh) = get_text_metrics(value_str, font_regular, draw)
                    use_font = font_regular
                else:
                    use_font = font_regular
                    vw = vw_s
                    vh = vh_s

            draw.text((item_x, item_y + 26), value_str, font=use_font, fill=item_color)

    # 卡片1: 行为概览
    draw_data_card(
        current_y,
        "🎯 行为概览",
        [
            ("偷鱼", data["steal_count"], COLOR_ACCENT),
            ("电鱼", data["electric_fish_count"], COLOR_WARNING),
            ("卖鱼", data["sell_fish_count"], COLOR_SUCCESS),
            ("总次数", data["total_actions"], COLOR_TEXT_DARK),
        ],
    )
    current_y += card_height + card_gap

    # 卡片2: 成功情况
    success_rate_display = f"{data['success_rate']:.1f}%"
    draw_data_card(
        current_y,
        "✅ 成功情况",
        [
            ("成功", data["success_count"], COLOR_SUCCESS),
            ("失败", data["fail_count"], COLOR_ERROR),
            ("成功率", success_rate_display, COLOR_GOLD),
        ],
    )
    current_y += card_height + card_gap

    # 卡片3: 鱼数情况
    draw_data_card(
        current_y,
        "🐟 鱼数情况",
        [
            ("偷到鱼数", data.get("steal_fish_cnt", 0), COLOR_ACCENT),
            ("电到鱼数", data.get("electric_fish_cnt", 0), COLOR_WARNING),
            ("卖出的鱼", data.get("sell_fish_cnt", 0), COLOR_SUCCESS),
            ("合计", data["fish_count"], COLOR_TEXT_DARK),
        ],
    )

    # 底部提示
    current_y += card_height + note_gap
    note_text = "💡 统计自功能上线后开始累计"
    _, (ntw, nth) = get_text_metrics(note_text, font_small, draw)
    draw.text(
        ((IMG_WIDTH - ntw) // 2, current_y),
        note_text, font=font_small, fill=COLOR_TEXT_GRAY,
    )

    # 裁剪到实际内容高度
    final_height = min(current_y + nth + PADDING, total_height)
    img = img.crop((0, 0, IMG_WIDTH, final_height))

    try:
        img.save(output_path, compress_level=1)
        logger.info(f"统计图片已保存到 {output_path}")
    except Exception as e:
        logger.error(f"保存统计图片失败: {e}")
        raise e


def draw_statistics_ranking_image(
    data: List[Dict[str, Any]],
    output_path: str,
    period_label: str,
) -> None:
    """
    绘制统计排行榜图片。

    展示 TOP5：
        - 排名
        - 昵称
        - 总次数 / 偷鱼/电鱼/卖鱼
        - 成功/失败/成功率
    """
    try:
        font_title = load_font(36)
        font_rank = load_font(28)
        font_name = load_font(20)
        font_value = load_font(18)
        font_small = load_font(15)
    except IOError:
        logger.warning("指定的字体文件未找到，使用默认字体。")
        font_title = ImageFont.load_default()
        font_rank = ImageFont.load_default()
        font_name = ImageFont.load_default()
        font_value = ImageFont.load_default()
        font_small = ImageFont.load_default()

    # TOP5 排行榜
    top_users = data[:5] if data else []

    # 奖杯加载（使用常驻内存缓存）
    from .utils import get_static_resource
    gold_trophy = get_static_resource("gold.png", (40, 40))
    silver_trophy = get_static_resource("silver.png", (35, 35))
    bronze_trophy = get_static_resource("bronze.png", (35, 35))
    if gold_trophy and silver_trophy and bronze_trophy:
        trophy_symbols = [gold_trophy, silver_trophy, bronze_trophy]
    else:
        trophy_symbols = ["🥇", "🥈", "🥉"]

    from .styles import COLOR_TEXT_GOLD, COLOR_TEXT_SILVER, COLOR_TEXT_BRONZE

    rank_colors = [COLOR_TEXT_GOLD, COLOR_TEXT_SILVER, COLOR_TEXT_BRONZE]

    # 计算图片高度
    list_item_height = 140  # 排行榜每项高度
    total_height = HEADER_HEIGHT + len(top_users) * (list_item_height + USER_CARD_MARGIN) + PADDING * 2 + 30
    total_height = max(total_height, 350)

    img = Image.new("RGB", (IMG_WIDTH, total_height), COLOR_BACKGROUND)
    draw = ImageDraw.Draw(img)

    # 标题
    title_text = f"📊 统计排行榜 TOP5 ({period_label})"
    draw_rounded_rectangle(
        draw,
        (PADDING, PADDING, IMG_WIDTH - PADDING, PADDING + HEADER_HEIGHT),
        radius=CORNER_RADIUS, fill=COLOR_HEADER_BG,
    )
    _, (tw, th) = get_text_metrics(title_text, font_title, draw)
    draw.text(
        ((IMG_WIDTH - tw) // 2, PADDING + (HEADER_HEIGHT - th) // 2),
        title_text, font=font_title, fill=COLOR_HEADER_TEXT,
    )

    # 无数据
    if not top_users:
        no_data_y = PADDING + HEADER_HEIGHT + 30
        no_data_text = "暂无统计数据"
        _, (ndw, ndh) = get_text_metrics(no_data_text, font_name, draw)
        draw.text(
            ((IMG_WIDTH - ndw) // 2, no_data_y),
            no_data_text, font=font_name, fill=COLOR_TEXT_GRAY,
        )
        try:
            img.save(output_path, compress_level=1)
        except Exception as e:
            logger.error(f"保存统计排行榜图片失败: {e}")
            raise e
        return

    # 绘制排行榜项
    current_y = PADDING + HEADER_HEIGHT + USER_CARD_MARGIN

    for idx, user in enumerate(top_users):
        card_y1 = current_y
        card_y2 = card_y1 + list_item_height

        draw_rounded_rectangle(
            draw,
            (PADDING, card_y1, IMG_WIDTH - PADDING, card_y2),
            radius=10, fill=COLOR_CARD_BG, outline=COLOR_CARD_BORDER, width=2,
        )

        nickname = user.get("nickname", "未知用户")
        if len(nickname) > 12:
            nickname = nickname[:10] + "..."

        # 排名
        rank_x = PADDING + 15
        if idx < 3 and isinstance(trophy_symbols[idx], Image.Image):
            trophy_img = trophy_symbols[idx]
            trophy_x = PADDING + 15
            trophy_y = card_y1 + (list_item_height - trophy_img.height) // 2
            img.paste(trophy_img, (trophy_x, trophy_y), trophy_img if trophy_img.mode == "RGBA" else None)
        else:
            rank_text = f"#{idx + 1}"
            rank_y = card_y1 + (list_item_height - get_text_metrics(rank_text, font_rank, draw)[1][1]) // 2
            rank_color = rank_colors[idx] if idx < 3 else COLOR_TEXT_DARK
            draw.text((rank_x, rank_y), rank_text, font=font_rank, fill=rank_color)

        # 内容起始 x
        content_x = PADDING + 75
        name_y = card_y1 + 12
        draw.text((content_x, name_y), nickname, font=font_name, fill=COLOR_TEXT_DARK)

        # 行为统计行
        stat_y = name_y + 28
        steal_str = f"偷鱼:{user['steal_count']}"
        electric_str = f"电鱼:{user['electric_fish_count']}"
        sell_str = f"卖鱼:{user['sell_fish_count']}"
        total_str = f"总计:{user['total_actions']}次"

        stat_parts = [total_str, steal_str, electric_str, sell_str]
        stat_x = content_x
        for part in stat_parts:
            draw.text((stat_x, stat_y), part, font=font_small, fill=COLOR_TEXT_DARK)
            _, (pw, _) = get_text_metrics(part, font_small, draw)
            stat_x += pw + 20

        # 成功/失败行
        result_y = stat_y + 24
        success_rate_display = f"{user['success_rate']:.1f}%"
        result_text = f"成功:{user['success_count']}  失败:{user['fail_count']}  成功率:{success_rate_display}"
        draw.text((content_x, result_y), result_text, font=font_small, fill=COLOR_TEXT_DARK)

        current_y = card_y2 + USER_CARD_MARGIN

    try:
        img.save(output_path, compress_level=1)
        logger.info(f"统计排行榜图片已保存到 {output_path}")
    except Exception as e:
        logger.error(f"保存统计排行榜图片失败: {e}")
        raise e


async def draw_period_report_image_async(
    data: Dict[str, Any],
    output_path: str,
    data_dir: str = None,
    avatar_config: dict = None,
) -> None:
    """参考其他用户图片的绘制流程，异步获取头像后在线程中绘制报表。"""
    avatars = {}
    user_ids = []
    for key in ("coins_net", "coins_earned", "coins_spent", "fishing", "steal", "electric_fish"):
        row = data.get(key) or {}
        user_id = str(row.get("user_id") or "").strip()
        if user_id and user_id not in user_ids:
            user_ids.append(user_id)

    async def fetch_avatar(user_id):
        try:
            return user_id, await get_user_avatar(
                user_id, data_dir, avatar_size=46, avatar_config=avatar_config
            )
        except Exception as e:
            logger.warning(f"获取统计报表用户头像失败: {e}, user_id={user_id}")
            return user_id, None

    if data_dir and user_ids:
        avatar_results = await asyncio.gather(
            *(fetch_avatar(user_id) for user_id in user_ids)
        )
        avatars = {
            user_id: avatar
            for user_id, avatar in avatar_results
            if avatar is not None
        }

    await run_in_thread(draw_period_report_image, data, output_path, avatars)


def draw_period_report_image(
    data: Dict[str, Any], output_path: str, avatars: Dict[str, Image.Image] = None
) -> None:
    """绘制面向群聊的日报/周报图片，使用四列统一卡片布局。"""
    try:
        font_title = load_font(30)
        font_section = load_font(18)
        font_name = load_font(14)
        font_value = load_font(22)
        font_meta = load_font(12)
    except IOError:
        fallback_font = ImageFont.load_default()
        font_title = font_section = font_name = font_value = font_meta = fallback_font

    period_label = data.get("period_label", "统计")
    title = f"{period_label}钓鱼世界报表"
    avatars = avatars or {}
    header_height = 82
    card_height = 286
    card_gap = 10
    grid_y = PADDING + header_height + 18
    content_width = IMG_WIDTH - PADDING * 2
    card_width = (content_width - card_gap * 3) // 4
    total_height = grid_y + card_height + PADDING

    img = Image.new("RGB", (IMG_WIDTH, total_height), COLOR_BACKGROUND)
    draw = ImageDraw.Draw(img)
    draw_rounded_rectangle(
        draw, (PADDING, PADDING, IMG_WIDTH - PADDING, PADDING + header_height),
        radius=CORNER_RADIUS, fill=COLOR_HEADER_BG,
    )
    def draw_centered_text(text, center_x, center_y, font, fill):
        """按实际字形包围盒居中，避免字体左/右留白造成视觉偏移。"""
        bbox = draw.textbbox((0, 0), text, font=font)
        text_center_x = (bbox[0] + bbox[2]) / 2
        text_center_y = (bbox[1] + bbox[3]) / 2
        draw.text(
            (center_x - text_center_x, center_y - text_center_y),
            text,
            font=font,
            fill=fill,
        )

    draw_centered_text(
        title,
        IMG_WIDTH // 2,
        PADDING + header_height // 2,
        font_title,
        COLOR_HEADER_TEXT,
    )
    def name_lines(row, max_width, max_lines=2):
        if not row:
            return ["暂无数据"]
        name = str(row.get("nickname") or row.get("user_id") or "未知用户")
        if get_text_metrics(name, font_name, draw)[1][0] <= max_width:
            return [name]

        lines = []
        current = ""
        for char in name:
            candidate = current + char
            if not current or get_text_metrics(candidate, font_name, draw)[1][0] <= max_width:
                current = candidate
            else:
                lines.append(current)
                current = char
        if current:
            lines.append(current)

        if len(lines) <= max_lines:
            return lines

        lines = lines[:max_lines]
        last_line = lines[-1]
        while last_line and get_text_metrics(last_line + "…", font_name, draw)[1][0] > max_width:
            last_line = last_line[:-1]
        lines[-1] = (last_line or "…") + "…"
        return lines

    def display_value(row, key):
        if not row:
            return "—"
        value = int(row.get(key, 0) or 0)
        return format_number(value)

    def centered_text(text, center_x, center_y, font, fill):
        draw_centered_text(text, center_x, center_y, font, fill)

    def draw_name(row, center_x, top_y, max_width):
        lines = name_lines(row, max_width)
        line_height = 17
        for index, line in enumerate(lines):
            centered_text(
                line,
                center_x,
                top_y + index * line_height + line_height / 2,
                font_name,
                COLOR_TEXT_DARK,
            )

    def draw_centered_group(items, center_x, top_y, gap=6):
        """按实际字形高度垂直排列文字，保证不同字号之间的视觉间距一致。"""
        current_y = top_y
        for text, font, fill in items:
            bbox = draw.textbbox((0, 0), text, font=font)
            text_height = max(1, bbox[3] - bbox[1])
            centered_text(text, center_x, current_y + text_height / 2, font, fill)
            current_y += text_height + gap

    def draw_avatar(row, center_x, center_y, size=46):
        avatar = avatars.get(str((row or {}).get("user_id") or "")) if row else None
        x1 = int(center_x - size / 2)
        y1 = int(center_y - size / 2)
        x2 = x1 + size
        y2 = y1 + size
        if avatar is not None:
            try:
                resampling = getattr(Image, "Resampling", Image)
                avatar = avatar.convert("RGBA").resize((size, size), resampling.LANCZOS)
                mask = Image.new("L", (size, size), 0)
                ImageDraw.Draw(mask).ellipse((0, 0, size, size), fill=255)
                img.paste(avatar, (x1, y1), mask)
            except Exception:
                avatar = None
        if avatar is None:
            fallback_text = "—"
            fallback_fill = (232, 240, 248)
            if row:
                fallback_text = str(row.get("nickname") or row.get("user_id") or "?")[:1]
                fallback_fill = (214, 231, 245)
            draw.ellipse((x1, y1, x2, y2), fill=fallback_fill, outline=COLOR_CARD_BORDER, width=2)
            centered_text(fallback_text, center_x, center_y, font_section, COLOR_ACCENT)
        draw.ellipse((x1, y1, x2, y2), outline=(214, 225, 236), width=2)

    def draw_card_frame(x1, y1, x2, y2, accent):
        draw_rounded_rectangle(
            draw, (x1, y1, x2, y2), radius=12,
            fill=COLOR_CARD_BG, outline=COLOR_CARD_BORDER, width=2,
        )
        draw.rounded_rectangle((x1, y1, x2, y1 + 6), radius=6, fill=accent)

    def draw_coin_card(row, x1, x2):
        """绘制最终净收益冠军，所有金币数据归属于同一位用户。"""
        center_x = (x1 + x2) // 2
        draw_card_frame(x1, grid_y, x2, grid_y + card_height, COLOR_GOLD)
        centered_text("金币", center_x, grid_y + 30, font_section, COLOR_GOLD)
        draw_avatar(row, center_x, grid_y + 79, 42)
        draw_name(row, center_x, grid_y + 107, card_width - 18)

        draw.line(
            (x1 + 12, grid_y + 150, x2 - 12, grid_y + 150),
            fill=COLOR_CARD_BORDER,
            width=1,
        )
        divider_x = (x1 + x2) // 2
        left_x = (x1 + divider_x) // 2
        right_x = (divider_x + x2) // 2
        draw_centered_group(
            [
                ("获得", font_meta, COLOR_TEXT_GRAY),
                (display_value(row, "earned"), font_value, COLOR_GOLD),
                ("金币", font_meta, COLOR_TEXT_GRAY),
            ],
            left_x,
            grid_y + 160,
            gap=6,
        )
        draw_centered_group(
            [
                ("花费", font_meta, COLOR_TEXT_GRAY),
                (display_value(row, "spent"), font_value, COLOR_ERROR),
                ("金币", font_meta, COLOR_TEXT_GRAY),
            ],
            right_x,
            grid_y + 160,
            gap=6,
        )

        draw.line(
            (x1 + 12, grid_y + 220, x2 - 12, grid_y + 220),
            fill=COLOR_CARD_BORDER,
            width=1,
        )
        draw_centered_group(
            [
                ("最终获得", font_meta, COLOR_SUCCESS),
                (display_value(row, "amount"), font_value, COLOR_SUCCESS),
                ("金币", font_meta, COLOR_TEXT_GRAY),
            ],
            center_x,
            grid_y + 228,
            gap=6,
        )

    def draw_activity_card(index, title_text, row, accent, count_label, coin_label):
        x1 = PADDING + index * (card_width + card_gap)
        x2 = x1 + card_width
        draw_card_frame(x1, grid_y, x2, grid_y + card_height, accent)
        center_x = (x1 + x2) // 2
        centered_text(title_text, center_x, grid_y + 30, font_section, accent)
        draw_avatar(row, center_x, grid_y + 78, 46)
        draw_name(row, center_x, grid_y + 108, card_width - 18)
        draw.line((x1 + 12, grid_y + 150, x2 - 12, grid_y + 150), fill=COLOR_CARD_BORDER, width=1)
        divider_x = (x1 + x2) // 2
        draw.line((divider_x, grid_y + 165, divider_x, grid_y + 264), fill=COLOR_CARD_BORDER, width=1)
        left_x = (x1 + divider_x) // 2
        right_x = (divider_x + x2) // 2
        draw_centered_group(
            [
                (count_label, font_meta, COLOR_TEXT_GRAY),
                (display_value(row, "count"), font_value, accent),
                ("数量", font_meta, COLOR_TEXT_GRAY),
            ],
            left_x,
            grid_y + 185,
            gap=6,
        )
        draw_centered_group(
            [
                (coin_label, font_meta, COLOR_TEXT_GRAY),
                (display_value(row, "value"), font_value, COLOR_GOLD),
                ("金币", font_meta, COLOR_TEXT_GRAY),
            ],
            right_x,
            grid_y + 185,
            gap=6,
        )

    cards = [
        ("钓鱼", data.get("fishing"), COLOR_SUCCESS, "钓鱼数量", "获得金币"),
        ("偷鱼", data.get("steal"), COLOR_ACCENT, "偷鱼数量", "获得金币"),
        ("电鱼", data.get("electric_fish"), COLOR_WARNING, "电鱼数量", "获得金币"),
    ]

    # 第一列按最终净收益只展示一位用户，获得和花费并列，最终获得单独一行。
    first_x1 = PADDING
    first_x2 = first_x1 + card_width
    coin_row = data.get("coins_net")
    if coin_row is None:
        # 兼容旧数据结构；正式报表由仓储层提供 coins_net。
        earned_row = data.get("coins_earned") or {}
        coin_row = {
            **earned_row,
            "earned": earned_row.get("amount", 0),
            "spent": 0,
            "amount": earned_row.get("amount", 0),
        } if earned_row else None
    draw_coin_card(coin_row, first_x1, first_x2)

    for index, card in enumerate(cards, start=1):
        draw_activity_card(index, *card)

    try:
        img.save(output_path, compress_level=1)
        logger.info(f"群统计图片已保存到 {output_path}")
    except Exception as e:
        logger.error(f"保存群统计图片失败: {e}")
        raise e
