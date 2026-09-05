"""
渐变背景生成工具函数
使用缓存与 numpy 加速渐变生成，提供统一的高性能渐变背景接口
"""
from typing import Tuple, Dict
from PIL import Image

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# 渐变背景图像缓存（限制条目避免占用过多内存）
_GRADIENT_CACHE: Dict[Tuple[int, int, Tuple[int, int, int], Tuple[int, int, int]], Image.Image] = {}
_MAX_GRADIENT_CACHE_SIZE = 32


def create_vertical_gradient(width: int, height: int, top_color: Tuple[int, int, int], bottom_color: Tuple[int, int, int]) -> Image.Image:
    """
    创建垂直渐变背景，使用缓存和 numpy 加速
    
    Args:
        width: 图像宽度
        height: 图像高度
        top_color: 顶部颜色 (R, G, B)
        bottom_color: 底部颜色 (R, G, B)
    
    Returns:
        PIL.Image.Image: 生成的渐变图像（从缓存返回拷贝）
    """
    cache_key = (width, height, top_color, bottom_color)
    if cache_key in _GRADIENT_CACHE:
        return _GRADIENT_CACHE[cache_key].copy()

    if _HAS_NUMPY:
        top_r, top_g, top_b = top_color
        bot_r, bot_g, bot_b = bottom_color
        
        y_coords = np.linspace(0, 1, height)
        r_gradient = (top_r + (bot_r - top_r) * y_coords).astype(np.uint8)
        g_gradient = (top_g + (bot_g - top_g) * y_coords).astype(np.uint8)
        b_gradient = (top_b + (bot_b - top_b) * y_coords).astype(np.uint8)
        
        gradient_array = np.zeros((height, width, 3), dtype=np.uint8)
        gradient_array[:, :, 0] = r_gradient[:, np.newaxis]
        gradient_array[:, :, 1] = g_gradient[:, np.newaxis]
        gradient_array[:, :, 2] = b_gradient[:, np.newaxis]
        
        img = Image.fromarray(gradient_array)
    else:
        img = _create_vertical_gradient_fallback(width, height, top_color, bottom_color)

    if len(_GRADIENT_CACHE) >= _MAX_GRADIENT_CACHE_SIZE:
        _GRADIENT_CACHE.pop(next(iter(_GRADIENT_CACHE)))
    _GRADIENT_CACHE[cache_key] = img
    return img.copy()


def _create_vertical_gradient_fallback(width: int, height: int, top_color: Tuple[int, int, int], bottom_color: Tuple[int, int, int]) -> Image.Image:
    """回退的渐变生成方法，当 numpy 不可用时使用双线性插值缩放"""
    base = Image.new('RGB', (1, 2))
    base.putpixel((0, 0), top_color)
    base.putpixel((0, 1), bottom_color)
    return base.resize((width, height), resample=Image.Resampling.BILINEAR)


def create_horizontal_gradient(width: int, height: int, left_color: Tuple[int, int, int], right_color: Tuple[int, int, int]) -> Image.Image:
    """
    创建水平渐变背景，使用缓存和 numpy 加速
    """
    cache_key = (width, height, left_color, right_color)
    if cache_key in _GRADIENT_CACHE:
        return _GRADIENT_CACHE[cache_key].copy()

    if _HAS_NUMPY:
        left_r, left_g, left_b = left_color
        right_r, right_g, right_b = right_color
        
        x_coords = np.linspace(0, 1, width)
        r_gradient = (left_r + (right_r - left_r) * x_coords).astype(np.uint8)
        g_gradient = (left_g + (right_g - left_g) * x_coords).astype(np.uint8)
        b_gradient = (left_b + (right_b - left_b) * x_coords).astype(np.uint8)
        
        gradient_array = np.zeros((height, width, 3), dtype=np.uint8)
        gradient_array[:, :, 0] = r_gradient
        gradient_array[:, :, 1] = g_gradient
        gradient_array[:, :, 2] = b_gradient
        
        img = Image.fromarray(gradient_array)
    else:
        base = Image.new('RGB', (2, 1))
        base.putpixel((0, 0), left_color)
        base.putpixel((1, 0), right_color)
        img = base.resize((width, height), resample=Image.Resampling.BILINEAR)

    if len(_GRADIENT_CACHE) >= _MAX_GRADIENT_CACHE_SIZE:
        _GRADIENT_CACHE.pop(next(iter(_GRADIENT_CACHE)))
    _GRADIENT_CACHE[cache_key] = img
    return img.copy()
