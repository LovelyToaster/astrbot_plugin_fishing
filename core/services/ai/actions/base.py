"""
AIAction 基类 + 决策工具函数。

所有 AI 动作类继承 `AIAction`，实现 `_execute(ctx)`；
基类 `run(ctx)` 提供统一异常兜底与日志，保证主循环不会因单个动作崩溃。

`build_weighted_pool` 供偷/电动作对合格候选做加权抽样：
- 头名 A（对 AI 施暴最多）占 50%
- 头名 B（该动作总次数最多）占 30%
- 其余候选均分剩余部分
- A、B 缺席或不在合格候选中时权重合并入其余
"""

import math
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple

from astrbot.api import logger

from ..ai_context import AIContext


class AIAction(ABC):
    """AI 决策动作基类"""

    #: 用于日志的动作名，子类应覆盖
    name: str = "action"

    @abstractmethod
    def _execute(self, ctx: AIContext) -> None:
        """子类实现具体逻辑。抛出异常会被 `run` 捕获。"""
        ...

    def run(self, ctx: AIContext) -> None:
        """外部调度入口：捕获所有异常，避免影响后续动作。"""
        try:
            self._execute(ctx)
        except Exception as e:
            logger.debug(f"[AI] 动作 {self.name} 执行异常: {e}", exc_info=True)


def parse_int_safe(value) -> int:
    """从任意值尝试解析出 int，失败返回 0。"""
    if value is None:
        return 0
    try:
        if isinstance(value, (int, float)):
            return int(value)
        s = str(value).strip().replace(",", "").replace("，", "")
        return int(float(s))
    except Exception:
        return 0


# 权重常量，需与设计文档一致
WEIGHT_TOP_ATTACKER = 0.5  # 传统模式头名 A 权重
WEIGHT_TOP_ACTOR = 0.3     # 传统模式头名 B 权重
WEIGHT_REVENGE = 0.40      # 多因子模式反击目标基础身份权重


def build_weighted_pool(
    eligible: List[Tuple[str, Dict[str, float]]],
    top_attacker_id: Optional[str] = None,
    top_actor_id: Optional[str] = None,
    actor_counts: Optional[Dict[str, int]] = None,
    victim_counts: Optional[Dict[str, int]] = None,
    k_agg: float = 0.5,
    gamma: float = 0.6,
    min_factor: float = 0.1,
) -> Tuple[List[str], List[float]]:
    """
    根据合格候选与统计维度构造 (user_ids, weights) 供 random.choices 使用。

    当 actor_counts 或 victim_counts 传入时，采用多因子连续动态加权算法：
      - W_identity: 反击目标 0.40，其余均分剩余 0.60
      - beta(u) = 1.0 + k_agg * ln(1.0 + A(u))   (恶霸惩戒增益)
      - alpha(u) = max(min_factor, gamma ** V(u))  (受害者保护衰减)
      - W_raw(u) = W_identity(u) * beta(u) * alpha(u)
      - 归一化总概率为 1.0

    当未传入 Counts 字典时，退回双头名分桶传统模式（50%/30%/20%）。
    """
    if not eligible:
        return [], []

    eligible_ids = [uid for uid, _ in eligible]
    eligible_set = set(eligible_ids)

    # 判定是否使用多因子连续加权模式
    use_multi_factor = (actor_counts is not None) or (victim_counts is not None)

    if use_multi_factor:
        actor_counts = actor_counts or {}
        victim_counts = victim_counts or {}

        a_valid = top_attacker_id is not None and top_attacker_id in eligible_set
        num_eligible = len(eligible_ids)

        weights_map: Dict[str, float] = {}

        for uid in eligible_ids:
            # 1. 基础身份权重
            if a_valid:
                if uid == top_attacker_id:
                    w_id = WEIGHT_REVENGE
                else:
                    w_id = (1.0 - WEIGHT_REVENGE) / (num_eligible - 1) if num_eligible > 1 else 1.0
            else:
                w_id = 1.0 / num_eligible

            # 2. 恶霸惩戒增益 beta
            a_cnt = actor_counts.get(uid, 0)
            beta = 1.0 + k_agg * math.log(1.0 + max(0, a_cnt))

            # 3. 受害保护衰减 alpha
            v_cnt = victim_counts.get(uid, 0)
            alpha = max(min_factor, gamma ** max(0, v_cnt))

            w_raw = w_id * beta * alpha
            weights_map[uid] = w_raw

        ids = eligible_ids
        weights = [weights_map[uid] for uid in ids]
        total = sum(weights)
        if total > 0:
            weights = [w / total for w in weights]
        else:
            share = 1.0 / len(ids)
            weights = [share] * len(ids)
        return ids, weights

    # ---------- 传统分桶模式 fallback ----------
    a_valid = top_attacker_id is not None and top_attacker_id in eligible_set
    b_valid = (
        top_actor_id is not None
        and top_actor_id in eligible_set
        and top_actor_id != top_attacker_id
    )

    special_ids = set()
    if a_valid:
        special_ids.add(top_attacker_id)
    if b_valid:
        special_ids.add(top_actor_id)
    others = [uid for uid in eligible_ids if uid not in special_ids]

    weight_a = WEIGHT_TOP_ATTACKER if a_valid else 0.0
    weight_b = WEIGHT_TOP_ACTOR if b_valid else 0.0
    remaining = 1.0 - weight_a - weight_b

    legacy_weights_map: Dict[str, float] = {}

    if others:
        share = remaining / len(others)
        for uid in others:
            legacy_weights_map[uid] = share
    else:
        base = weight_a + weight_b
        if base > 0:
            weight_a += remaining * (weight_a / base)
            weight_b += remaining * (weight_b / base)

    if a_valid:
        legacy_weights_map[top_attacker_id] = weight_a
    if b_valid:
        legacy_weights_map[top_actor_id] = weight_b

    ids = eligible_ids
    weights = [legacy_weights_map.get(uid, 0.0) for uid in ids]

    total = sum(weights)
    if total <= 0:
        share = 1.0 / len(ids)
        weights = [share] * len(ids)

    return ids, weights

