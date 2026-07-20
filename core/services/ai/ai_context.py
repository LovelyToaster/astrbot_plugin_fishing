"""
AI tick 上下文 (AIContext)

单次 tick 内，各个 Action 共享的依赖与懒缓存：
- 各类 repo / service（构造时注入）
- 当前 tick 的 AI User 对象（可 refresh）
- 候选真人目标特征（首次访问时才拉取）
- AIStateHolder / SnapshotWriter / BroadcastHelper

设计要点：
- Action 不直接访问 AIPlayerService，只通过 AIContext 获取需要的依赖，
  这样重构后 Action 的 tests 也能独立构造 mock context。
- `refresh_ai_user()` 在装备/鱼饵变更后由动作主动调用。
- `get_candidates()` 采用 lazy + 每 tick 缓存，偷和电共用同一次查询。
"""

from typing import Any, Dict, List, Optional, Tuple

from astrbot.api import logger

from ...domain.models import User
from ...repositories.abstract_repository import (
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractUserRepository,
)
from ..fishing_service import FishingService
from ..gacha_service import GachaService
from ..game_mechanics_service import GameMechanicsService
from ..inventory_service import InventoryService
from ..user_service import UserService
from .ai_state_holder import AIStateHolder
from .broadcast_helper import BroadcastHelper
from .feature_extractor import FeatureExtractor
from .snapshot_writer import SnapshotWriter


class AIContext:
    """单次 tick 内共享的上下文对象。"""

    def __init__(
        self,
        *,
        ai_user_id: str,
        ai_nickname: str,
        ai_user: User,
        # repos
        user_repo: AbstractUserRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        statistics_repo: Any,
        # services
        user_service: UserService,
        fishing_service: FishingService,
        game_mechanics_service: GameMechanicsService,
        inventory_service: InventoryService,
        gacha_service: GachaService,
        # AI 专属工具
        state: AIStateHolder,
        snapshot: SnapshotWriter,
        broadcast: BroadcastHelper,
        feature_extractor: FeatureExtractor,
        # config
        ai_config: Dict[str, Any],
        global_config: Dict[str, Any],
    ):
        self.ai_user_id = ai_user_id
        self.ai_nickname = ai_nickname
        self.ai_user = ai_user

        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        # SqliteStatisticsRepository 没有抽象基类，此处用 Any 避免循环导入。
        # 需要提供 get_top_attacker_of / get_top_actor 两个方法。
        self.statistics_repo = statistics_repo

        self.user_service = user_service
        self.fishing_service = fishing_service
        self.game_mechanics_service = game_mechanics_service
        self.inventory_service = inventory_service
        self.gacha_service = gacha_service

        self.state = state
        self.snapshot = snapshot
        self.broadcast = broadcast
        self.feature_extractor = feature_extractor

        self.ai_config = ai_config
        self.global_config = global_config

        # 懒缓存：候选特征
        self._candidates_cache: Optional[List[Tuple[str, Dict[str, float]]]] = None

    # ---------- 用户对象刷新 ----------

    def refresh_ai_user(self) -> User:
        """
        重新从仓储拉取 AI User，装备/鱼饵/金币变化后需要调用。
        同时清空候选特征缓存——`attacker_rod_rarity` / `attacker_accessory_rarity`
        依赖 AI 自身装备状态，装备变更后旧缓存中的攻击者特征字段会失真。
        拉取失败时保留旧对象并记 debug。
        """
        try:
            refreshed = self.user_repo.get_by_id(self.ai_user_id)
            if refreshed is not None:
                self.ai_user = refreshed
        except Exception as e:
            logger.debug(f"[AI] refresh_ai_user 失败，沿用旧对象: {e}")
        # 装备/金币变化后候选特征缓存不再准确，强制下轮 get_candidates 重新拉取
        self._candidates_cache = None
        return self.ai_user

    # ---------- 候选特征懒加载 ----------

    def get_candidates(self) -> List[Tuple[str, Dict[str, float]]]:
        """
        懒加载所有候选真人目标的特征。tick 内多次调用只查一次。
        失败返回空列表并记 debug。
        """
        if self._candidates_cache is not None:
            return self._candidates_cache

        try:
            self._candidates_cache = self.feature_extractor.batch_extract(
                attacker_user=self.ai_user,
                exclude_ids=[self.ai_user_id],
            )
        except Exception as e:
            logger.debug(f"[AI] 批量提取候选特征失败: {e}")
            self._candidates_cache = []

        return self._candidates_cache

    # ---------- 目标信息 ----------

    def resolve_target_nickname(self, target_id: str) -> Optional[str]:
        """查目标用户昵称，失败返回 None。"""
        try:
            target = self.user_repo.get_by_id(target_id)
            return target.nickname if target else None
        except Exception:
            return None
