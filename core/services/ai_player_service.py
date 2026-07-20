"""
AI 玩家服务 (AIPlayerService)

以后台守护线程周期性调度一系列 AIAction 完成 AI 玩家的自主行为。
本类只做编排：账号初始化、状态加载、tick 组装 AIContext、依次调用动作。
具体决策逻辑分散在 `core/services/ai/actions/` 下的各个动作类中。
"""

import threading
import time
from typing import Any, Callable, List, Optional

from astrbot.api import logger

from ..domain.models import User
from ..repositories.abstract_repository import (
    AbstractAIDecisionSnapshotRepository,
    AbstractAIPlayerStateRepository,
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractUserRepository,
)
from ..services.ai.actions import AIAction, build_actions
from ..services.ai.ai_context import AIContext
from ..services.ai.ai_state_holder import AIStateHolder
from ..services.ai.broadcast_helper import BroadcastHelper
from ..services.ai.feature_extractor import FeatureExtractor
from ..services.ai.snapshot_writer import SnapshotWriter
from ..services.fishing_service import FishingService
from ..services.gacha_service import GachaService
from ..services.game_mechanics_service import GameMechanicsService
from ..services.inventory_service import InventoryService
from ..services.user_service import UserService


class AIPlayerService:
    """AI 玩家服务：管理 AI 账号生命周期与周期性动作调度。"""

    def __init__(
        self,
        user_repo: AbstractUserRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        user_service: UserService,
        fishing_service: FishingService,
        game_mechanics_service: GameMechanicsService,
        inventory_service: InventoryService,
        gacha_service: GachaService,
        ai_state_repo: AbstractAIPlayerStateRepository,
        snapshot_repo: AbstractAIDecisionSnapshotRepository,
        feature_extractor: FeatureExtractor,
        statistics_repo: Any,
        config: dict,
        broadcast_callback: Optional[Callable[[str], None]] = None,
    ):
        # ---------- 依赖注入 ----------
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.user_service = user_service
        self.fishing_service = fishing_service
        self.game_mechanics_service = game_mechanics_service
        self.inventory_service = inventory_service
        self.gacha_service = gacha_service
        self.ai_state_repo = ai_state_repo
        self.snapshot_repo = snapshot_repo
        self.feature_extractor = feature_extractor
        # statistics_repo：AI 决策权重需要用它查询 24h 行为窗口
        self.statistics_repo = statistics_repo

        # ---------- 配置 ----------
        self.ai_config = config.get("ai_player", {}) or {}
        self.global_config = config

        self.ai_user_id = self.ai_config.get("user_id", "AI_FISHER_001")
        self.ai_nickname = self.ai_config.get("nickname", "钓鱼机器人小蓝")
        self.tick_seconds = int(self.ai_config.get("tick_seconds", 300))
        self.initial_coins = int(self.ai_config.get("initial_coins", 10000))

        # ---------- 广播 ----------
        self.broadcast = BroadcastHelper(
            ai_nickname=self.ai_nickname,
            callback=broadcast_callback,
        )

        # ---------- 状态 & 快照封装 ----------
        self.state = AIStateHolder(self.ai_user_id, self.ai_state_repo)
        self.snapshot = SnapshotWriter(self.ai_user_id, self.snapshot_repo)

        # ---------- 动作列表 ----------
        self.actions: List[AIAction] = build_actions(self.ai_config)

        # ---------- 后台线程 ----------
        self._running = False
        self._thread: Optional[threading.Thread] = None

    # ==================== 生命周期 ====================

    def ensure_ai_user_exists(self) -> None:
        """
        幂等地创建 AI 用户账号并发放初始装备。
        仅在 AI 账号不存在时执行注册和物品发放。
        """
        ai_user = self.user_repo.get_by_id(self.ai_user_id)
        if ai_user:
            logger.info(f"[AI] AI 用户已存在: {self.ai_user_id}")
            return

        logger.info(f"[AI] 创建 AI 用户: {self.ai_user_id}")

        # 1. 注册
        self.user_service.register(self.ai_user_id, self.ai_nickname)

        # 2. 设置 AI 标志、初始金币、自动钓鱼与钓鱼区域
        ai_user = self.user_repo.get_by_id(self.ai_user_id)
        ai_user.is_ai = True
        ai_user.coins = self.initial_coins
        ai_user.auto_fishing_enabled = True
        ai_user.fishing_zone_id = 1
        self.user_repo.update(ai_user)

        # 3. 发放初始鱼竿（新手木竿：rod_id=1）
        rod_inventory = self.inventory_service.get_user_rod_inventory(self.ai_user_id)
        if not rod_inventory.get("rods", []):
            logger.info("[AI] 发放初始鱼竿")
            self.user_service.add_item_to_user_inventory(
                self.ai_user_id, "rod", 1, 1
            )

        # 4. 发放初始鱼饵（普通蚯蚓：bait_id=1, 100 个）
        bait_inventory = self.inventory_service.get_user_bait_inventory(self.ai_user_id)
        baits = bait_inventory.get("baits", [])
        total_bait_qty = sum(b.get("quantity", 0) for b in baits)
        if total_bait_qty < 20:
            logger.info("[AI] 发放初始鱼饵")
            self.user_service.add_item_to_user_inventory(
                self.ai_user_id, "bait", 1, 100
            )

        # 5. 复用动作逻辑自动装备鱼竿并使用鱼饵
        self._run_initial_setup_actions()

        logger.info(f"[AI] AI 用户初始化完成: {self.ai_user_id}")
        # 上线公告
        self.broadcast.online()

    def _run_initial_setup_actions(self) -> None:
        """在 AI 用户初始化后立即执行一轮装备/鱼饵动作。"""
        ai_user = self.user_repo.get_by_id(self.ai_user_id)
        if ai_user is None:
            return

        ctx = self._build_context(ai_user)
        # 仅跑装备与鱼饵动作
        from ..services.ai.actions import (
            EquipBestAccessoryAction,
            EquipBestRodAction,
            UseBestBaitAction,
        )
        for action_cls in (EquipBestRodAction, EquipBestAccessoryAction, UseBestBaitAction):
            action_cls().run(ctx)

    def start_ai_loop(self) -> None:
        """启动 AI 决策循环的后台守护线程。"""
        if self._thread and self._thread.is_alive():
            logger.info("[AI] AI 决策循环线程已在运行中")
            return

        # 从数据库加载持久化状态（需在 ensure_ai_user_exists 之后，确保 FK 有效）
        self.state.load_from_db()

        self._running = True
        self._thread = threading.Thread(target=self._ai_loop, daemon=True)
        self._thread.start()
        logger.info(f"[AI] AI 决策循环线程已启动，间隔 {self.tick_seconds} 秒")

    def stop_ai_loop(self) -> None:
        """停止 AI 决策循环的后台线程。"""
        self._running = False
        if self._thread:
            self._thread.join(timeout=1.0)
            logger.info("[AI] AI 决策循环线程已停止")

    # ==================== 主循环 ====================

    def _ai_loop(self) -> None:
        """AI 决策主循环：每 tick_seconds 秒执行一轮所有动作。"""
        while self._running:
            try:
                self._tick()
            except Exception as e:
                logger.exception(f"[AI] 决策循环异常: {e}")
            time.sleep(self.tick_seconds)

    def _tick(self) -> None:
        """单轮决策：拉最新用户状态，依次执行所有动作（不 short-circuit）。"""
        ai_user = self.user_repo.get_by_id(self.ai_user_id)
        if not ai_user:
            logger.warning(f"[AI] AI 用户 {self.ai_user_id} 不存在，跳过本轮")
            return

        ctx = self._build_context(ai_user)
        for action in self.actions:
            action.run(ctx)

    # ==================== 内部工具 ====================

    def _build_context(self, ai_user: User) -> AIContext:
        """基于当前 tick 的 AI User 构造共享上下文。"""
        return AIContext(
            ai_user_id=self.ai_user_id,
            ai_nickname=self.ai_nickname,
            ai_user=ai_user,
            user_repo=self.user_repo,
            inventory_repo=self.inventory_repo,
            item_template_repo=self.item_template_repo,
            statistics_repo=self.statistics_repo,
            user_service=self.user_service,
            fishing_service=self.fishing_service,
            game_mechanics_service=self.game_mechanics_service,
            inventory_service=self.inventory_service,
            gacha_service=self.gacha_service,
            state=self.state,
            snapshot=self.snapshot,
            broadcast=self.broadcast,
            feature_extractor=self.feature_extractor,
            ai_config=self.ai_config,
            global_config=self.global_config,
        )
