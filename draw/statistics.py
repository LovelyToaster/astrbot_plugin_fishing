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
        img.save(output_path)
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

    # 奖杯加载
    trophy_symbols = []
    try:
        gold_trophy = Image.open(os.path.join(os.path.dirname(__file__), "resource", "gold.png")).resize((40, 40))
        silver_trophy = Image.open(os.path.join(os.path.dirname(__file__), "resource", "silver.png")).resize((35, 35))
        bronze_trophy = Image.open(os.path.join(os.path.dirname(__file__), "resource", "bronze.png")).resize((35, 35))
        trophy_symbols = [gold_trophy, silver_trophy, bronze_trophy]
    except Exception:
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
            img.save(output_path)
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
        img.save(output_path)
        logger.info(f"统计排行榜图片已保存到 {output_path}")
    except Exception as e:
        logger.error(f"保存统计排行榜图片失败: {e}")
        raise e
