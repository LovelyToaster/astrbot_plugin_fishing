"""
决策快照写入封装 (SnapshotWriter)

将 `create` 和 `complete` 两步操作封装为简单接口，
统一 JSON 序列化与异常处理，方便动作类调用。

硬规则版：`predicted_prob` 恒为 NULL（保留字段方便日后重新引入模型）。
"""

import json
from typing import Optional, Dict

from astrbot.api import logger

from ...repositories.abstract_repository import AbstractAIDecisionSnapshotRepository


class SnapshotWriter:
    """决策快照写入器：封装 create/complete 两阶段与错误处理。"""

    def __init__(self, ai_user_id: str, repo: AbstractAIDecisionSnapshotRepository):
        self.ai_user_id = ai_user_id
        self._repo = repo

    def create(
        self,
        action_type: str,
        target_id: Optional[str],
        features: Dict[str, float],
        predicted_prob: Optional[float] = None,
    ) -> Optional[int]:
        """
        写决策快照，返回 snapshot_id；失败仅记 debug 并返回 None。
        """
        try:
            features_json = json.dumps(features, ensure_ascii=False)
            return self._repo.create(
                ai_user_id=self.ai_user_id,
                action_type=action_type,
                target_user_id=target_id,
                features_json=features_json,
                predicted_prob=predicted_prob,
            )
        except Exception as e:
            logger.debug(f"[AI] 写决策快照失败: {e}")
            return None

    def complete(
        self,
        snapshot_id: Optional[int],
        executed: int,
        success: Optional[int],
        fail_reason: Optional[str],
        reward_value: Optional[int],
    ) -> None:
        """回填快照执行结果，失败仅记 debug。

        `fail_reason` 若超过 100 字符会被截断，避免长错误信息撑爆列宽。
        """
        if snapshot_id is None:
            return
        truncated_reason = (
            fail_reason[:100] if isinstance(fail_reason, str) else fail_reason
        )
        try:
            self._repo.complete(
                snapshot_id=snapshot_id,
                executed=executed,
                success=success,
                fail_reason=truncated_reason,
                reward_value=reward_value,
            )
        except Exception as e:
            logger.debug(f"[AI] 回填决策快照失败: {e}")
