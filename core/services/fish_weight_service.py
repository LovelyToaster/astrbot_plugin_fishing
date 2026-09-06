import random
import threading
from collections import OrderedDict
from typing import List, Optional

from astrbot.api import logger

# 导入领域模型用于类型注释
from ..domain.models import Fish


class FishWeightService:
    """处理鱼类权重计算与期望价值拟合的服务"""
    
    def __init__(self, max_cache_size: int = 1000):
        self.weight_cache: OrderedDict = OrderedDict() # 核心改动：采用正规的有序字典
        self.max_cache_size: int = max_cache_size # 设定最大缓存条目数
        self._cache_lock: threading.Lock = threading.Lock() # 缓存读写互斥锁

    def _calculate_ev(self, fish_list: List[Fish], weights: List[float]) -> float:
        """
        计算给定鱼类列表和对应权重的数学期望价值 (Expected Value)。

        Args:
            fish_list: 包含鱼类实体模型的列表。
            weights: 与鱼类列表对应的权重列表。

        Returns:
            计算出的期望价值。
        """
        total_weight = sum(weights)
        if total_weight <= 0:
            return 0
        return sum(f.base_value * w for f, w in zip(fish_list, weights)) / total_weight

    def get_weights(self, fish_list: List[Fish], coins_chance: float = 0.0) -> List[float]:
        """
        返回候选鱼类的权重列表。
        现已采用公平随机抽取，避免赢者通吃导致低价鱼概率归零。
        """
        return [1.0 for _ in fish_list]

    def choose_fish(self, new_fish_list: List[Fish], coins_chance: float = 0.0) -> Optional[Fish]:
        """
        从候选鱼类列表中随机抽取一条鱼。
        金币加成已与鱼种抽取解耦（改为在结算时直接对金币产出进行加成），
        此处采用公平随机抽取，确保各鱼种出现几率均等，保障图鉴丰富度。

        Args:
            new_fish_list: 候选的鱼类列表。
            coins_chance: 金币加成概率因子（保留兼容接口）。

        Returns:
            抽取到的鱼类实体。如果候选列表为空，则返回 None。
        """
        if not new_fish_list:
            return None
        if len(new_fish_list) == 1:
            return new_fish_list[0]

        return random.choice(new_fish_list)