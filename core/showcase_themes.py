"""展示柜预设主题。

主题只保存稳定的标识符，具体颜色集中在这里管理，避免用户输入任意颜色
导致不同客户端上的对比度和可读性失控。
"""

from typing import Any, Dict


DEFAULT_SHOWCASE_THEME = "ocean"

SHOWCASE_THEME_OPTIONS: Dict[str, Dict[str, Any]] = {
    "ocean": {
        "label": "海蓝",
        "description": "清爽的海天蓝，默认主题",
        "colors": {
            "bg_top": (238, 246, 252),
            "bg_bottom": (207, 222, 235),
            "accent": (66, 143, 205),
            "accent_soft": (221, 237, 248),
            "panel_fill": (255, 255, 255, 226),
            "panel_border": (255, 255, 255, 190),
            "avatar_fill": (221, 232, 241),
            "stat_fill": (236, 244, 249, 235),
            "stat_border": (207, 221, 232, 255),
            "empty_fill": (247, 250, 252, 185),
            "empty_border": (210, 222, 232, 220),
            "empty_icon": (171, 190, 204),
            "footer_fill": (227, 238, 246, 195),
            "footer_border": (207, 222, 233, 220),
            "divider": (231, 237, 242),
            "text_primary": (38, 57, 77),
            "text_secondary": (91, 112, 132),
            "text_muted": (132, 150, 166),
            "refine_fill": (247, 235, 218),
            "refine_text": (177, 111, 49),
            "lock_text": (106, 139, 162),
        },
    },
    "forest": {
        "label": "森林",
        "description": "自然的松柏绿，沉稳耐看",
        "colors": {
            "bg_top": (239, 248, 241),
            "bg_bottom": (207, 230, 213),
            "accent": (67, 139, 91),
            "accent_soft": (222, 241, 225),
            "panel_fill": (253, 255, 253, 226),
            "panel_border": (230, 244, 232, 220),
            "avatar_fill": (218, 235, 220),
            "stat_fill": (232, 245, 233, 235),
            "stat_border": (198, 222, 201, 255),
            "empty_fill": (246, 251, 247, 190),
            "empty_border": (196, 218, 199, 220),
            "empty_icon": (126, 167, 133),
            "footer_fill": (226, 242, 228, 200),
            "footer_border": (194, 220, 197, 220),
            "divider": (220, 236, 222),
            "text_primary": (42, 73, 51),
            "text_secondary": (76, 111, 83),
            "text_muted": (120, 151, 125),
            "refine_fill": (238, 242, 218),
            "refine_text": (113, 127, 49),
            "lock_text": (79, 128, 88),
        },
    },
    "sunset": {
        "label": "夕阳",
        "description": "温暖的珊瑚橙，活泼明亮",
        "colors": {
            "bg_top": (255, 246, 237),
            "bg_bottom": (246, 218, 196),
            "accent": (218, 111, 61),
            "accent_soft": (252, 231, 215),
            "panel_fill": (255, 253, 250, 230),
            "panel_border": (255, 240, 226, 230),
            "avatar_fill": (250, 224, 202),
            "stat_fill": (253, 237, 222, 240),
            "stat_border": (239, 199, 169, 255),
            "empty_fill": (255, 249, 243, 200),
            "empty_border": (234, 201, 176, 220),
            "empty_icon": (205, 143, 106),
            "footer_fill": (252, 233, 216, 205),
            "footer_border": (235, 197, 166, 220),
            "divider": (242, 222, 206),
            "text_primary": (92, 56, 42),
            "text_secondary": (134, 84, 61),
            "text_muted": (169, 119, 93),
            "refine_fill": (252, 229, 202),
            "refine_text": (169, 98, 40),
            "lock_text": (160, 103, 77),
        },
    },
    "rose": {
        "label": "樱粉",
        "description": "柔和的玫瑰粉，精致轻盈",
        "colors": {
            "bg_top": (255, 243, 248),
            "bg_bottom": (241, 213, 226),
            "accent": (205, 91, 139),
            "accent_soft": (250, 222, 235),
            "panel_fill": (255, 252, 254, 230),
            "panel_border": (255, 233, 243, 230),
            "avatar_fill": (248, 221, 234),
            "stat_fill": (252, 231, 241, 240),
            "stat_border": (235, 191, 211, 255),
            "empty_fill": (255, 248, 252, 200),
            "empty_border": (226, 190, 208, 220),
            "empty_icon": (199, 131, 159),
            "footer_fill": (250, 228, 240, 205),
            "footer_border": (229, 188, 211, 220),
            "divider": (242, 218, 231),
            "text_primary": (86, 48, 68),
            "text_secondary": (135, 79, 105),
            "text_muted": (168, 117, 140),
            "refine_fill": (250, 226, 213),
            "refine_text": (172, 98, 74),
            "lock_text": (155, 91, 122),
        },
    },
    "midnight": {
        "label": "黑金",
        "description": "深邃的夜色黑金，典藏感最强",
        "colors": {
            "bg_top": (31, 38, 53),
            "bg_bottom": (12, 17, 27),
            "accent": (226, 177, 73),
            "accent_soft": (75, 61, 34),
            "panel_fill": (31, 39, 54, 238),
            "panel_border": (109, 91, 52, 235),
            "avatar_fill": (52, 63, 82),
            "stat_fill": (40, 48, 64, 245),
            "stat_border": (112, 93, 53, 255),
            "empty_fill": (28, 36, 50, 220),
            "empty_border": (76, 87, 105, 220),
            "empty_icon": (139, 153, 172),
            "footer_fill": (35, 44, 59, 235),
            "footer_border": (82, 77, 64, 235),
            "divider": (67, 75, 90),
            "text_primary": (244, 237, 218),
            "text_secondary": (211, 202, 179),
            "text_muted": (157, 165, 177),
            "refine_fill": (82, 61, 37),
            "refine_text": (245, 192, 105),
            "lock_text": (170, 187, 207),
        },
    },
}

_THEME_ALIASES = {
    "海蓝": "ocean",
    "海洋": "ocean",
    "蓝": "ocean",
    "森林": "forest",
    "绿": "forest",
    "夕阳": "sunset",
    "橙": "sunset",
    "樱粉": "rose",
    "粉": "rose",
    "黑金": "midnight",
    "夜色": "midnight",
    "金": "midnight",
}


def normalize_showcase_theme(value: Any) -> str:
    """将主题 ID 或中文别名规范化为稳定 ID。"""
    key = str(value or "").strip().lower()
    key = _THEME_ALIASES.get(key, key)
    return key if key in SHOWCASE_THEME_OPTIONS else DEFAULT_SHOWCASE_THEME


def get_showcase_theme(value: Any) -> Dict[str, Any]:
    """获取主题配置；非法值安全回退到默认主题。"""
    return SHOWCASE_THEME_OPTIONS[normalize_showcase_theme(value)]


def is_valid_showcase_theme(value: Any) -> bool:
    key = str(value or "").strip().lower()
    return key in SHOWCASE_THEME_OPTIONS or key in _THEME_ALIASES


def get_showcase_theme_label(value: Any) -> str:
    return get_showcase_theme(value)["label"]


def format_showcase_theme_options() -> str:
    lines = ["🎨 展示柜颜色选项："]
    for theme_id, option in SHOWCASE_THEME_OPTIONS.items():
        lines.append(f"• {option['label']}（{theme_id}）— {option['description']}")
    lines.append("用法：/展示柜颜色 <位置编号或装备短码> <选项>")
    lines.append("例如：/展示柜颜色 1 樱粉，或 /展示柜颜色 R1 樱粉")
    return "\n".join(lines)
