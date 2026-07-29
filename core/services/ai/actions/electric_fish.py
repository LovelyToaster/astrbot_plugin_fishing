"""
动作：电鱼（加权决策版）。

筛选条件：
- target_fish_count >= min_target_fish_count（默认 100）
- target_has_shield == 0 AND target_has_protection == 0

抽样：对合格候选做加权抽样，头名 A（24h 对 AI 电鱼最多）+ 头名 B（24h 电鱼
总次数最多）分别 50%/30%，其余候选均分剩余 20%。详见 base.build_weighted_pool。
"""

import random
from typing import Dict, List, Tuple

from astrbot.api import logger

from ....utils import get_now
from ..ai_context import AIContext
from .base import AIAction, build_weighted_pool, parse_int_safe


class ElectricFishAction(AIAction):
    name = "electric_fish"

    def __init__(self, min_target_fish_count: int):
        self.min_target_fish_count = int(min_target_fish_count)

    def _execute(self, ctx: AIContext) -> None:
        # 服务层冷却预检
        cooldown = ctx.global_config.get("electric_fish", {}).get(
            "cooldown_seconds", 10800
        )
        if ctx.ai_user.last_electric_fish_time is not None:
            if (
                get_now() - ctx.ai_user.last_electric_fish_time
            ).total_seconds() < cooldown:
                return

        # 3. 硬规则过滤
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
            logger.debug(
                f"[AI] 电鱼：无符合硬规则的候选 "
                f"(需鱼数>={self.min_target_fish_count})"
            )
            return

        # 4. 加权抽样：查 24h 反击头名、全员发起与受害统计 → 构造多因子权重池 → random.choices
        top_attacker_id = None
        top_actor_id = None
        actor_counts = {}
        victim_counts = {}
        try:
            top_attacker_id = ctx.statistics_repo.get_top_attacker_of(
                ctx.ai_user_id, "electric_fish", 24
            )
            top_actor_id = ctx.statistics_repo.get_top_actor(
                "electric_fish", 24, exclude_user_id=ctx.ai_user_id
            )
            actor_counts = ctx.statistics_repo.get_user_action_counts_in_window("electric_fish", 24)
            victim_counts = ctx.statistics_repo.get_victim_counts_in_window("electric_fish", 24)
        except Exception as e:
            logger.debug(f"[AI] 电鱼：查询 24h 统计特征失败，回退默认参数: {e}")

        ids, weights = build_weighted_pool(
            eligible,
            top_attacker_id=top_attacker_id,
            top_actor_id=top_actor_id,
            actor_counts=actor_counts,
            victim_counts=victim_counts,
        )
        target_id = random.choices(ids, weights=weights, k=1)[0]
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
            action_type="electric_fish",
            target_id=target_id,
            features=features,
            predicted_prob=None,
        )
        result = ctx.game_mechanics_service.electric_fish(ctx.ai_user_id, target_id)
        target_nickname = ctx.resolve_target_nickname(target_id)

        if result.get("success"):
            logger.info(f"[AI] 电鱼成功: 目标={target_nickname or target_id}")
            fish_count = result.get("victim_notification", {}).get(
                "stolen_count", "?"
            )
            value = result.get("victim_notification", {}).get("total_value", "?")
            ctx.broadcast.electric_success(
                target_id=target_id,
                target_nickname=target_nickname,
                fish_count=fish_count,
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

        # 冷却错误：服务层实际未执行动作
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
        ctx.broadcast.electric_failure(
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
