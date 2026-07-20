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
WEIGHT_TOP_ATTACKER = 0.5  # 头名 A：过去 24h 对 AI 施暴最多
WEIGHT_TOP_ACTOR = 0.3     # 头名 B：过去 24h 该动作总次数最多


def build_weighted_pool(
    eligible: List[Tuple[str, Dict[str, float]]],
    top_attacker_id: Optional[str],
    top_actor_id: Optional[str],
) -> Tuple[List[str], List[float]]:
    """
    根据合格候选与两个头名 id 构造 (user_ids, weights) 供 random.choices 用。

    规则：
    - 头名 A（top_attacker_id）占 WEIGHT_TOP_ATTACKER
    - 头名 B（top_actor_id）占 WEIGHT_TOP_ACTOR
    - 其余候选均分剩余
    - A == B 时视为同一人，仅按 WEIGHT_TOP_ATTACKER 计
    - A/B 不在 eligible 中 → 其对应权重合并入"其余"
    - 若"其余"为空（eligible 全由 A/B 组成），剩余权重按 A/B 现有比例回补

    参数：
        eligible: 合格候选列表 [(user_id, features), ...]，调用方保证非空
        top_attacker_id: 头名 A 的 user_id 或 None
        top_actor_id: 头名 B 的 user_id 或 None

    返回：
        (ids: List[str], weights: List[float])，长度相同，weights 总和归一到 1.0
        若 eligible 为空则返回 ([], [])
    """
    if not eligible:
        return [], []

    eligible_ids = [uid for uid, _ in eligible]
    eligible_set = set(eligible_ids)

    # 判定 A、B 是否有效（存在且在候选池内）
    a_valid = top_attacker_id is not None and top_attacker_id in eligible_set
    b_valid = (
        top_actor_id is not None
        and top_actor_id in eligible_set
        and top_actor_id != top_attacker_id  # A==B 时忽略 B
    )

    # 剩余候选（不含 A/B）
    special_ids = set()
    if a_valid:
        special_ids.add(top_attacker_id)
    if b_valid:
        special_ids.add(top_actor_id)
    others = [uid for uid in eligible_ids if uid not in special_ids]

    weight_a = WEIGHT_TOP_ATTACKER if a_valid else 0.0
    weight_b = WEIGHT_TOP_ACTOR if b_valid else 0.0
    remaining = 1.0 - weight_a - weight_b

    weights_map: Dict[str, float] = {}

    if others:
        # 常规：其余均分
        share = remaining / len(others)
        for uid in others:
            weights_map[uid] = share
    else:
        # others 为空 ⇔ eligible 全被 A/B 占满 ⇔ A、B 至少一个有效
        # remaining 按现有 A/B 权重比补回，避免浪费概率
        base = weight_a + weight_b
        weight_a += remaining * (weight_a / base)
        weight_b += remaining * (weight_b / base)

    if a_valid:
        weights_map[top_attacker_id] = weight_a
    if b_valid:
        weights_map[top_actor_id] = weight_b

    # 保持 eligible 的顺序输出
    ids: List[str] = []
    weights: List[float] = []
    for uid in eligible_ids:
        ids.append(uid)
        weights.append(weights_map.get(uid, 0.0))

    # 数值兜底：sum 极小时（如全 0）均分，避免 random.choices 抛异常
    total = sum(weights)
    if total <= 0:
        share = 1.0 / len(ids)
        weights = [share] * len(ids)

    return ids, weights
