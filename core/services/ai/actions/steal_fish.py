"""
动作：偷鱼（加权决策版）。

筛选条件：
- 目标未被系统排除（AI / SYSTEM 由 FeatureExtractor 已过滤）
- target_fish_count >= min_target_fish_count（默认 1，即有鱼就偷）
- target_has_shield == 0 AND target_has_protection == 0

抽样：对合格候选做加权抽样，头名 A（24h 对 AI 偷鱼最多）+ 头名 B（24h 偷鱼
总次数最多）分别 50%/30%，其余候选均分剩余 20%。详见 base.build_weighted_pool。
"""

import random
from typing import Dict, List, Tuple

from astrbot.api import logger

from ....utils import get_now
from ..ai_context import AIContext
from .base import AIAction, build_weighted_pool, parse_int_safe


class StealFishAction(AIAction):
    name = "steal_fish"

    def __init__(self, min_target_fish_count: int):
        self.min_target_fish_count = int(min_target_fish_count)

    def _execute(self, ctx: AIContext) -> None:
        # 服务层冷却预检
        cooldown = ctx.global_config.get("steal", {}).get("cooldown_seconds", 14400)
        if ctx.ai_user.last_steal_time is not None:
            if (get_now() - ctx.ai_user.last_steal_time).total_seconds() < cooldown:
                return

        # 3. 拉候选并按硬规则过滤
        candidates = ctx.get_candidates()
        if not candidates:
            return

        eligible: List[Tuple[str, Dict[str, float]]] = [
            (tid, feats)
            for tid, feats in candidates
            if feats.get("target_fish_count", 0) >= self.min_target_fish_count
            and feats.get("target_has_shield", 0) == 0
            and feats.get("target_has_protection", 0) == 0
        ]

        if not eligible:
            logger.debug("[AI] 偷鱼：无符合硬规则的候选")
            return

        # 4. 加权抽样：查 24h 反击头名、全员发起与受害统计 → 构造多因子权重池 → random.choices
        top_attacker_id = None
        top_actor_id = None
        actor_counts = {}
        victim_counts = {}
        try:
            top_attacker_id = ctx.statistics_repo.get_top_attacker_of(
                ctx.ai_user_id, "steal", 24
            )
            top_actor_id = ctx.statistics_repo.get_top_actor(
                "steal", 24, exclude_user_id=ctx.ai_user_id
            )
            actor_counts = ctx.statistics_repo.get_user_action_counts_in_window("steal", 24)
            victim_counts = ctx.statistics_repo.get_victim_counts_in_window("steal", 24)
        except Exception as e:
            logger.debug(f"[AI] 偷鱼：查询 24h 统计特征失败，回退默认参数: {e}")

        ids, weights = build_weighted_pool(
            eligible,
            top_attacker_id=top_attacker_id,
            top_actor_id=top_actor_id,
            actor_counts=actor_counts,
            victim_counts=victim_counts,
        )
        target_id = random.choices(ids, weights=weights, k=1)[0]
        # 找到对应 features 与权重（供快照分析）
        features_map = {tid: feats for tid, feats in eligible}
        weight_map = dict(zip(ids, weights))
        features = dict(features_map[target_id])
        features["weight_chosen"] = round(weight_map[target_id], 4)
        features["top_attacker_id"] = top_attacker_id or ""
        features["top_actor_id"] = top_actor_id or ""
        features["target_actor_count"] = actor_counts.get(target_id, 0)
        features["target_victim_count"] = victim_counts.get(target_id, 0)

        # 5. 写快照 → 执行 → 回填
        snapshot_id = ctx.snapshot.create(
            action_type="steal",
            target_id=target_id,
            features=features,
            predicted_prob=None,
        )
        result = ctx.game_mechanics_service.steal_fish(ctx.ai_user_id, target_id)
        target_nickname = ctx.resolve_target_nickname(target_id)

        if result.get("success"):
            logger.info(f"[AI] 偷鱼成功: 目标={target_nickname or target_id}")
            value = result.get("victim_notification", {}).get("value", "?")
            ctx.broadcast.steal_success(
                target_id=target_id,
                target_nickname=target_nickname,
                fish_count=1,  # steal_fish 每次固定偷 1 条
                value=value,
            )
            ctx.snapshot.complete(
                snapshot_id,
                executed=1,
                success=1,
                fail_reason=None,
                reward_value=parse_int_safe(value),
            )
            return

        err_msg = result.get("message", "")

        # 冷却错误：服务层实际未执行动作，快照标记 executed=0
        if "冷却" in err_msg:
            ctx.snapshot.complete(
                snapshot_id,
                executed=0,
                success=None,
                fail_reason=err_msg,
                reward_value=None,
            )
            return

        # 实际失败：广播 + 回填
        ctx.broadcast.steal_failure(
            target_id=target_id,
            target_nickname=target_nickname,
            err_msg=err_msg,
        )

        ctx.snapshot.complete(
            snapshot_id,
            executed=1,
            success=0,
            fail_reason=err_msg,
            reward_value=0,
        )
