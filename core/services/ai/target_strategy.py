"""AI 社交目标评分。

目标选择保持可解释：反击压力优先，其次是可兑现收益和历史成功率。所有
归一化和成本计算都在这里完成，偷鱼与电鱼动作只负责执行结果。
"""

from dataclasses import dataclass, field
import math
import random
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class TargetScore:
    target_id: str
    operation: str
    score: float
    revenge_pressure: float
    expected_value: float
    success_probability: float
    expected_penalty: float
    expected_net_value: float
    repeat_count: int = 0
    protected: bool = False
    features: Dict[str, Any] = field(default_factory=dict)

    def as_features(self) -> Dict[str, Any]:
        data = dict(self.features)
        data.update(
            {
                "operation": self.operation,
                "target_id": self.target_id,
                "revenge_pressure": round(self.revenge_pressure, 6),
                "expected_value": round(self.expected_value, 2),
                "success_probability": round(self.success_probability, 6),
                "expected_penalty": round(self.expected_penalty, 2),
                "expected_net_value": round(self.expected_net_value, 2),
                "repeat_count": self.repeat_count,
                "target_protected": self.protected,
                "score": round(self.score, 6),
            }
        )
        return data


class SocialTargetScorer:
    """为偷鱼/电鱼动作提供统一目标评分。"""

    REVENGE_WEIGHT = 0.50
    VALUE_WEIGHT = 0.30
    SUCCESS_WEIGHT = 0.20

    def __init__(self, context):
        self.ctx = context

    def _counts(self, operation: str):
        stats = self.ctx.statistics_repo
        action_type = "electric_fish" if operation == "electric_fish" else "steal"
        try:
            actor_counts = stats.get_user_action_counts_in_window(action_type, 24)
        except Exception:
            actor_counts = {}
        try:
            victim_counts = stats.get_victim_counts_in_window(action_type, 24)
        except Exception:
            victim_counts = {}
        try:
            targeted = stats.get_actor_target_counts_in_window(
                self.ctx.ai_user_id, action_type, 24
            )
        except Exception:
            targeted = {}
        try:
            incoming = stats.get_incoming_attacker_counts(
                self.ctx.ai_user_id, action_type, 24
            )
        except Exception:
            incoming = {}
        try:
            top_attacker = stats.get_top_attacker_of(
                self.ctx.ai_user_id, action_type, 24
            )
        except Exception:
            top_attacker = None
        try:
            target_rates = stats.get_target_success_rates(action_type, 168)
        except Exception:
            target_rates = {}
        return actor_counts, victim_counts, targeted, incoming, top_attacker, target_rates

    def _success_probability(self, operation: str, target_id: str, target_rates) -> float:
        data = target_rates.get(target_id) if isinstance(target_rates, dict) else None
        if data:
            attempts, successes = data[:2]
            # Beta(2,2) 平滑，避免历史样本过少导致极端概率。
            return (float(successes) + 2.0) / (float(attempts) + 4.0)
        if operation == "electric_fish":
            return float(
                self.ctx.global_config.get("electric_fish", {}).get(
                    "base_success_rate", 0.6
                )
            )
        return 0.90

    def score(
        self,
        operation: str,
        min_target_fish_count: int,
        candidates: Optional[Iterable] = None,
    ) -> List[TargetScore]:
        candidates = list(
            self.ctx.get_candidates() if candidates is None else candidates
        )
        if not candidates:
            return []

        _, victim_counts, targeted, incoming, top_attacker, target_rates = self._counts(operation)
        raw_values = [
            float(features.get("target_fish_value", 0) or 0)
            for _, features in candidates
        ]
        max_value = max(raw_values or [1.0]) or 1.0

        results: List[TargetScore] = []
        for target_id, raw_features in candidates:
            features = dict(raw_features)
            fish_count = float(features.get("target_fish_count", 0) or 0)
            if fish_count < min_target_fish_count:
                continue

            layers = int(features.get("target_protection_layers", 0) or 0)
            protected = layers > 0
            fish_value = float(features.get("target_fish_value", 0) or 0)
            if operation == "steal":
                expected_value = fish_value / max(fish_count, 1.0)
            else:
                # 电鱼平均抽取约 12.5% 鱼量，使用鱼塘估值作为长期收益近似。
                expected_value = fish_value * 0.125

            probability = max(
                0.01, min(0.99, self._success_probability(operation, target_id, target_rates))
            )
            penalty_rate = float(
                self.ctx.global_config.get("electric_fish", {}).get(
                    "failure_penalty_expected_rate", 0.025
                )
            )
            expected_penalty = (
                float(getattr(self.ctx.ai_user, "coins", 0) or 0)
                * penalty_rate
                * (1.0 - probability)
                if operation == "electric_fish"
                else 0.0
            )
            item_cost = 0.0
            try:
                item_cost = float(
                    self.ctx.item_strategy.estimate_social_item_cost(
                        operation, features
                    )
                )
            except Exception:
                pass
            expected_net = probability * expected_value - expected_penalty - item_cost

            direct_target_count = int(incoming.get(target_id, 0) or 0)
            revenge = min(1.0, direct_target_count / 3.0)
            if target_id == top_attacker:
                revenge = min(1.0, revenge + 0.35)
            # 主动施暴较多的人仍得到额外反击压力，但不超过 1。
            revenge = min(
                1.0,
                revenge
                + min(0.25, math.log1p(float(features.get("target_actor_count", 0) or 0)) / 12.0),
            )

            repeat_count = int(features.get("target_ai_action_count", 0) or 0)
            repeat_penalty = 1.0 / (1.0 + 0.25 * repeat_count)
            value_factor = max(0.0, min(1.0, expected_net / max(max_value, 1.0)))
            success_factor = probability
            score = (
                self.REVENGE_WEIGHT * revenge
                + self.VALUE_WEIGHT * value_factor
                + self.SUCCESS_WEIGHT * success_factor
            ) * repeat_penalty

            if protected:
                try:
                    can_handle = self.ctx.item_strategy.can_handle_protection(
                        operation, features
                    )
                except Exception:
                    can_handle = False
                if not can_handle:
                    continue

            if expected_net <= 0:
                continue

            features.update(
                {
                    "target_ai_action_count": repeat_count,
                    "target_actor_count": int(features.get("target_actor_count", 0) or 0),
                    "target_victim_count": int(victim_counts.get(target_id, 0) or 0),
                    "target_protection_layers": layers,
                    "weight_reason": "revenge_value_success",
                }
            )
            results.append(
                TargetScore(
                    target_id=target_id,
                    operation=operation,
                    score=score,
                    revenge_pressure=revenge,
                    expected_value=expected_value,
                    success_probability=probability,
                    expected_penalty=expected_penalty,
                    expected_net_value=expected_net,
                    repeat_count=repeat_count,
                    protected=protected,
                    features=features,
                )
            )
        return sorted(results, key=lambda item: item.score, reverse=True)

    @staticmethod
    def choose(scores: List[TargetScore]) -> Optional[TargetScore]:
        if not scores:
            return None
        weights = [max(0.001, score.score) for score in scores]
        return random.choices(scores, weights=weights, k=1)[0]
