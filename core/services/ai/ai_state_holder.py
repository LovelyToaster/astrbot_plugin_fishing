"""
AI 状态持有器 (AIStateHolder)

将节流/惩罚时间戳的内存值与数据库持久化统一在一个对象中，
调用方通过 `set(field, value)` 一次性完成"更新内存 + 落库"。

字段清单（与 `ai_player_state` 表 + `AIPlayerState` domain 对齐）：
- last_sell_fish_ts: float
- last_sell_equipment_ts: float
- last_paid_gacha_ts: float
- last_free_gacha_date: Optional[date]  # 内存中以 date 存，落库时序列化
"""

from datetime import date
from typing import Optional, Any

from astrbot.api import logger

from ...repositories.abstract_repository import AbstractAIPlayerStateRepository


# 可持久化字段白名单（与 ai_state_repo.update_field 保持一致）
_VALID_FIELDS = {
    "last_sell_fish_ts",
    "last_sell_equipment_ts",
    "last_paid_gacha_ts",
    "last_free_gacha_date",
}


class AIStateHolder:
    """AI 节流状态的内存 + DB 双写持有器。"""

    def __init__(self, ai_user_id: str, state_repo: AbstractAIPlayerStateRepository):
        self.ai_user_id = ai_user_id
        self._repo = state_repo

        # 内存字段（默认值）
        self.last_sell_fish_ts: float = 0.0
        self.last_sell_equipment_ts: float = 0.0
        self.last_paid_gacha_ts: float = 0.0
        self.last_free_gacha_date: Optional[date] = None

    # ---------- 加载 ----------

    def load_from_db(self) -> None:
        """从数据库加载状态到内存字段，失败时保留默认值并记 warning。"""
        try:
            state = self._repo.get_or_create(self.ai_user_id)
            self.last_sell_fish_ts = state.last_sell_fish_ts
            self.last_sell_equipment_ts = state.last_sell_equipment_ts
            self.last_paid_gacha_ts = state.last_paid_gacha_ts
            self.last_free_gacha_date = (
                date.fromisoformat(state.last_free_gacha_date)
                if state.last_free_gacha_date
                else None
            )
            logger.info(f"[AI] 从数据库加载状态成功: user_id={self.ai_user_id}")
        except Exception as e:
            logger.warning(f"[AI] 从数据库加载状态失败，使用默认值: {e}")

    # ---------- 写入 ----------

    def set(self, field: str, value: Any) -> None:
        """
        更新内存字段并落库。
        对不在白名单的字段直接抛异常，避免拼写错误。
        DB 失败仅记 warning，保证内存状态一致。
        """
        if field not in _VALID_FIELDS:
            raise ValueError(f"AIStateHolder.set 收到未知字段: {field}")

        # 内存写入
        setattr(self, field, value)

        # 落库：日期类型序列化
        db_value = value.isoformat() if isinstance(value, date) else value

        try:
            self._repo.update_field(self.ai_user_id, field, db_value)
        except Exception as e:
            logger.warning(f"[AI] 持久化状态字段 {field} 失败: {e}")
