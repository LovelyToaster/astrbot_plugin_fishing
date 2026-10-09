import random
import math
import threading
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime, timezone, timedelta

from astrbot.api import logger
# 导入仓储接口和领域模型
from ..repositories.abstract_repository import (
    AbstractGachaRepository,
    AbstractUserRepository,
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractLogRepository,
    AbstractAchievementRepository
)
from ..domain.models import GachaPool, GachaPoolItem, GachaRecord, UserGachaPity
from ..utils import get_now
from .gacha_up import apply_personal_up_to_distribution, apply_personal_up_to_draw
from .hextech_gacha_balance import (
    GACHA_HEXTECH_IDS,
    TIER_EV_BUDGETS,
    configured_reward_value,
    expected_cycle_value,
    max_bonus_chance_for_value_budget,
    max_chance_for_budget,
    max_coin_refund_fraction,
    max_quantity_bonus_chance,
    max_weight_multiplier_for_budget,
    quantity_bonus,
    draw_probabilities,
)


def _perform_single_weighted_draw(
    pool: GachaPool,
    weight_multiplier: float = 1.0,
    max_rarity: int = 0,
    rarity_of=None,
) -> GachaPoolItem:
    """执行一次加权随机抽奖。"""
    def adjusted_weight(item):
        weight = max(0.0, float(getattr(item, "weight", 0) or 0))
        if (
            weight_multiplier > 1.0 and max_rarity > 0
            and getattr(item, "item_type", None) != "coins"
            and rarity_of is not None and rarity_of(item) >= max_rarity
        ):
            weight *= weight_multiplier
        return weight

    weights = [adjusted_weight(item) for item in pool.items]
    total_weight = sum(weights)
    if total_weight <= 0:
        return None
    rand_val = random.uniform(0, total_weight)

    current_weight = 0
    for item, weight in zip(pool.items, weights):
        current_weight += weight
        if rand_val <= current_weight:
            return item
    return None # 理论上不会发生


class GachaService:
    """封装与抽卡系统相关的业务逻辑"""

    _account_locks = tuple(threading.RLock() for _ in range(257))

    def __init__(
        self,
        gacha_repo: AbstractGachaRepository,
        user_repo: AbstractUserRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        log_repo: AbstractLogRepository,
        achievement_repo: AbstractAchievementRepository,
        pity_threshold: int = 80,
        max_draws_per_request: int = 100,
    ):
        self.gacha_repo = gacha_repo
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.achievement_repo = achievement_repo
        self.log_repo = log_repo
        self.pity_threshold = pity_threshold
        try:
            configured_max_draws = int(max_draws_per_request)
        except (TypeError, ValueError):
            configured_max_draws = 100
        self.max_draws_per_request = min(100, max(1, configured_max_draws))

    @classmethod
    def _account_lock(cls, user_id: str):
        """Return a bounded, cross-instance lock shared by this account's UP and draws."""
        return cls._account_locks[hash(str(user_id)) % len(cls._account_locks)]

    def get_all_pools(self) -> Dict[str, Any]:
        """提供查看所有卡池信息的功能。"""
        try:
            pools = self.gacha_repo.get_all_pools()
            logger.info(f"获取到 {len(pools)} 个卡池信息")
            return {"success": True, "pools": pools}
        except Exception as e:
            return {"success": False, "message": f"获取卡池信息失败: {str(e)}"}

    def get_daily_free_pools(self) -> List[GachaPool]:
        """获取可用于每日补给的卡池，不把高级货币成本带给签到/AI。"""
        free_pools = self.gacha_repo.get_free_pools()
        if free_pools:
            return free_pools

        # 旧数据库把签到池保存成 premium_currency=1，但业务语义仍是每日赠送。
        # 只识别明确带“每日/签到”语义且没有金币成本的池，避免误把普通高级池免单。
        try:
            pools = self.gacha_repo.get_all_pools()
            return [
                pool
                for pool in pools
                if getattr(pool, "cost_coins", 0) == 0
                and getattr(pool, "cost_premium_currency", 0) <= 1
                and any(
                    keyword in str(getattr(pool, "name", ""))
                    for keyword in ("每日", "签到")
                )
            ]
        except Exception:
            return []

    def get_daily_free_pool(self) -> Optional[GachaPool]:
        """获取默认每日补给池。"""
        pools = self.get_daily_free_pools()
        return pools[0] if pools else None

    def get_pool_details(self, pool_id: int, user_id: Optional[str] = None) -> Dict[str, Any]:
        """获取单个卡池的详细信息，包括奖品列表和概率。"""
        pool = self.gacha_repo.get_pool_by_id(pool_id)
        if not pool:
            return {"success": False, "message": "该卡池不存在"}

        template_cache: dict = {}
        up_item = None
        up_warning = None
        if user_id is not None:
            up_item, up_warning = self._resolve_user_up(user_id, pool, template_cache)
        total_weight = sum(max(0.0, float(item.weight or 0)) for item in pool.items)
        if total_weight == 0:
            return {
                "success": True,
                "pool": pool,
                "probabilities": [],
                "personal_up": None,
                "up_warning": up_warning,
            }
        base_probabilities = [
            (item, max(0.0, float(item.weight or 0)) / total_weight)
            for item in pool.items
            if max(0.0, float(item.weight or 0)) > 0
        ]
        personal_probabilities = apply_personal_up_to_distribution(
            base_probabilities,
            pool.items,
            lambda item: self._get_item_rarity(item, template_cache),
            up_item,
        )
        personal_probability_by_identity = {
            id(item): probability for item, probability in personal_probabilities
        }
        current_hextech_effect_id = None
        current_hextech_probability_by_identity = None
        hard_pity_probability_by_identity = None
        if user_id is not None:
            free_pool_ids = {
                int(free_pool.gacha_pool_id)
                for free_pool in self.gacha_repo.get_free_pools()
            }
            daily_free_pool_ids = {
                int(free_pool.gacha_pool_id)
                for free_pool in self.get_daily_free_pools()
            }
            use_pity = self.pity_threshold > 0 and int(pool_id) not in (
                free_pool_ids | daily_free_pool_ids
            )
            max_rarity = self._get_pool_max_rarity(pool, template_cache)
            if use_pity and max_rarity > 0:
                hard_pity_distribution = draw_probabilities(
                    pool.items,
                    lambda item: self._get_item_rarity(item, template_cache),
                    state=self.pity_threshold - 1,
                    pity_threshold=self.pity_threshold,
                    up_item=up_item,
                )
                hard_pity_probability_by_identity = hard_pity_distribution

            effect = self._get_hextech_gacha_effect(str(user_id))
            if effect:
                current_hextech_effect_id = effect["id"]
                if current_hextech_effect_id in {"C27", "P13", "G13"}:
                    ev_budget = self._hextech_gacha_budget(effect)
                    value_of = lambda item: self._hextech_gacha_reward_value(item, template_cache)
                    effect_params = effect.get("params", {})
                    if not isinstance(effect_params, dict):
                        effect_params = {}
                    chance = self._hextech_gacha_chance(
                        current_hextech_effect_id,
                        effect_params,
                        pool,
                        template_cache,
                        use_pity,
                        max_rarity,
                        value_of,
                        ev_budget,
                        up_item,
                    )
                    weight_multiplier = self._hextech_gacha_weight_multiplier(
                        current_hextech_effect_id,
                        effect_params,
                        pool,
                        template_cache,
                        use_pity,
                        value_of,
                        ev_budget,
                        up_item,
                    )
                    current_hextech_probability_by_identity = draw_probabilities(
                        pool.items,
                        lambda item: self._get_item_rarity(item, template_cache),
                        effect_id=current_hextech_effect_id,
                        chance=chance,
                        state=0,
                        pity_threshold=self.pity_threshold if use_pity else 0,
                        weight_multiplier=weight_multiplier,
                        up_item=up_item,
                    )
                else:
                    # C28/S13/S14 alter quantity or currency settlement, not
                    # which pool entry is selected.
                    current_hextech_probability_by_identity = personal_probability_by_identity

        probabilities = []
        for item in pool.items:
            base_probability = (
                max(0.0, float(item.weight or 0)) / total_weight
                if max(0.0, float(item.weight or 0)) > 0 else 0.0
            )
            probability = personal_probability_by_identity.get(id(item), 0.0)
            item_name = "未知物品"
            item_rarity = 1
            if item.item_type == "rod":
                rod = self.item_template_repo.get_rod_by_id(item.item_id)
                item_name = rod.name if rod else "未知鱼竿"
                item_rarity = rod.rarity if rod else 1
            elif item.item_type == "accessory":
                accessory = self.item_template_repo.get_accessory_by_id(item.item_id)
                item_name = accessory.name if accessory else "未知饰品"
                item_rarity = accessory.rarity if accessory else 1
            elif item.item_type == "bait":
                bait = self.item_template_repo.get_bait_by_id(item.item_id)
                item_name = bait.name if bait else "未知鱼饵"
                item_rarity = bait.rarity if bait else 1
            elif item.item_type == "item":
                general_item = self.item_template_repo.get_by_id(item.item_id)
                item_name = general_item.name if general_item else "未知道具"
                item_rarity = general_item.rarity if general_item else 1
            elif item.item_type == "coins":
                item_name = f"{item.quantity} 金币"
            elif item.item_type == "titles":
                title = self.item_template_repo.get_title_by_id(item.item_id)
                item_name = title.name if title else "未知称号"

            probabilities.append({
                "gacha_pool_item_id": item.gacha_pool_item_id,
                "item_type": item.item_type,
                "item_id": item.item_id,
                "item_name": item_name,
                "item_rarity": item_rarity if item.item_type != "titles" else 0,
                "weight": item.weight,
                "base_probability": round(base_probability, 8),
                "probability": round(probability, 8),
                "current_hextech_probability": (
                    round(current_hextech_probability_by_identity.get(id(item), 0.0), 8)
                    if current_hextech_probability_by_identity is not None else None
                ),
                "hard_pity_probability": (
                    round(hard_pity_probability_by_identity.get(id(item), 0.0), 8)
                    if hard_pity_probability_by_identity is not None else None
                ),
                "is_personal_up": bool(up_item and item is up_item),
            })
        personal_up = None
        if up_item:
            personal_up = self._format_up_item(up_item, self._get_item_rarity(up_item, template_cache))
        return {
            "success": True,
            "pool": pool,
            "probabilities": probabilities,
            "personal_up": personal_up,
            "up_warning": up_warning,
            "current_hextech_effect_id": current_hextech_effect_id,
        }

    def _validate_user_up(
        self, pool: GachaPool, item_pool_id: int, cache: Optional[dict] = None
    ) -> Tuple[Optional[GachaPoolItem], Optional[str]]:
        cache = cache if cache is not None else {}
        try:
            target_id = int(item_pool_id)
        except (TypeError, ValueError):
            return None, "UP奖品条目编号无效"
        target = next(
            (item for item in pool.items
             if int(getattr(item, "gacha_pool_item_id", -1)) == target_id),
            None,
        )
        if target is None:
            return None, "该奖品条目不属于此卡池，或已被删除"
        if target.item_type == "coins":
            return None, "金币奖励不能设置为UP"
        if float(getattr(target, "weight", 0) or 0) <= 0:
            return None, "该奖品权重必须大于0才能设置为UP"
        rarity = self._get_item_rarity(target, cache)
        if rarity <= 0:
            return None, "该奖品模板不存在或没有有效星级"
        alternatives = [
            item for item in pool.items
            if item.item_type != "coins"
            and (item.item_type, int(item.item_id)) != (target.item_type, int(target.item_id))
            and float(getattr(item, "weight", 0) or 0) > 0
            and self._get_item_rarity(item, cache) == rarity
        ]
        if not alternatives:
            return None, f"{rarity}星没有其他正权重奖品，无法满足同星级50%分配"
        return target, None

    def _resolve_user_up(
        self, user_id: str, pool: GachaPool, cache: Optional[dict] = None
    ) -> Tuple[Optional[GachaPoolItem], Optional[str]]:
        get_choice = getattr(self.gacha_repo, "get_user_up", None)
        if not callable(get_choice):
            return None, None
        choice = get_choice(str(user_id), int(pool.gacha_pool_id))
        if not choice:
            take_invalidation = getattr(
                self.gacha_repo, "take_user_up_invalidation", None
            )
            reason = (
                take_invalidation(str(user_id), int(pool.gacha_pool_id))
                if callable(take_invalidation)
                else None
            )
            if reason:
                return None, f"原个人UP已失效并自动关闭：{reason}。请重新选择。"
            return None, None
        item_pool_id = getattr(choice, "up_pool_item_id", None)
        target, error = self._validate_user_up(pool, item_pool_id, cache)
        if error:
            invalidate_choice = getattr(self.gacha_repo, "invalidate_user_up", None)
            take_invalidation = getattr(
                self.gacha_repo, "take_user_up_invalidation", None
            )
            if callable(invalidate_choice):
                invalidate_choice(str(user_id), int(pool.gacha_pool_id), error)
                stored_reason = (
                    take_invalidation(str(user_id), int(pool.gacha_pool_id))
                    if callable(take_invalidation)
                    else error
                )
                error = stored_reason or error
            else:
                delete_choice = getattr(self.gacha_repo, "delete_user_up", None)
                if callable(delete_choice):
                    delete_choice(str(user_id), int(pool.gacha_pool_id))
            return None, f"原个人UP已失效并自动关闭：{error}。请重新选择。"
        return target, None

    def _format_up_item(self, item: GachaPoolItem, rarity: int) -> Dict[str, Any]:
        template = self._get_template(item.item_type, item.item_id, {})
        return {
            "entry_id": int(item.gacha_pool_item_id),
            "item_type": item.item_type,
            "item_id": int(item.item_id),
            "item_name": getattr(template, "name", "未知物品"),
            "rarity": int(rarity),
        }

    def get_user_up_overview(self, user_id: str) -> List[Dict[str, Any]]:
        """Return this account's currently valid UP choice for every pool."""
        output = []
        with self._account_lock(user_id):
            try:
                pools = self.gacha_repo.get_all_pools()
            except Exception:
                return output
            cache: dict = {}
            for pool in pools:
                item, warning = self._resolve_user_up(user_id, pool, cache)
                output.append({
                    "pool_id": int(pool.gacha_pool_id),
                    "pool_name": pool.name,
                    "up": self._format_up_item(item, self._get_item_rarity(item, cache)) if item else None,
                    "warning": warning,
                })
        return output

    def set_user_up(self, user_id: str, pool_id: int, item_pool_id: int) -> Dict[str, Any]:
        """Set the caller's choice in one pool; no global pool state is changed."""
        user_id = str(user_id)
        with self._account_lock(user_id):
            if not self.user_repo.get_by_id(user_id):
                return {"success": False, "message": "您还没有注册，请先使用 /注册 命令注册。"}
            pool = self.gacha_repo.get_pool_by_id(int(pool_id))
            if not pool:
                return {"success": False, "message": "该卡池不存在"}
            target, error = self._validate_user_up(pool, item_pool_id)
            if error:
                return {"success": False, "message": error}
            set_choice = getattr(self.gacha_repo, "set_user_up", None)
            if not callable(set_choice):
                return {"success": False, "message": "当前抽卡仓储未启用个人UP存储"}
            set_choice(user_id, int(pool_id), int(item_pool_id))
            rarity = self._get_item_rarity(target, {})
            return {
                "success": True,
                "pool": pool,
                "up": self._format_up_item(target, rarity),
                "message": f"已将「{pool.name}」的个人UP设为「{self._format_up_item(target, rarity)['item_name']}」（{rarity}星）。最终抽到{rarity}星时有50%命中该UP，下一次抽卡生效。",
            }

    def close_user_up(self, user_id: str, pool_id: int) -> Dict[str, Any]:
        """Close the caller's choice in one pool. Repeated closes are successful."""
        user_id = str(user_id)
        with self._account_lock(user_id):
            if not self.user_repo.get_by_id(user_id):
                return {"success": False, "message": "您还没有注册，请先使用 /注册 命令注册。"}
            if not self.gacha_repo.get_pool_by_id(int(pool_id)):
                return {"success": False, "message": "该卡池不存在"}
            delete_choice = getattr(self.gacha_repo, "delete_user_up", None)
            if not callable(delete_choice):
                return {"success": False, "message": "当前抽卡仓储未启用个人UP存储"}
            delete_choice(user_id, int(pool_id))
            clear_invalidation = getattr(
                self.gacha_repo, "clear_user_up_invalidation", None
            )
            if callable(clear_invalidation):
                clear_invalidation(user_id, int(pool_id))
            return {"success": True, "message": f"已关闭卡池 {int(pool_id)} 的个人UP。"}

    def get_user_up(self, user_id: str, pool_id: int) -> Dict[str, Any]:
        """Query and validate the caller's choice for a pool."""
        with self._account_lock(user_id):
            pool = self.gacha_repo.get_pool_by_id(int(pool_id))
            if not pool:
                return {"success": False, "message": "该卡池不存在"}
            item, warning = self._resolve_user_up(str(user_id), pool, {})
            return {
                "success": True,
                "pool": pool,
                "up": self._format_up_item(item, self._get_item_rarity(item, {})) if item else None,
                "warning": warning,
            }

    def perform_draw(
        self,
        user_id: str,
        pool_id: int,
        num_draws: int = 1,
        is_daily_free: bool = False,
    ) -> Dict[str, Any]:
        try:
            num_draws = int(num_draws)
        except (TypeError, ValueError):
            return {"success": False, "message": "抽卡数量无效"}
        if num_draws <= 0:
            return {"success": False, "message": "抽卡数量必须大于0"}
        if num_draws > self.max_draws_per_request:
            return {
                "success": False,
                "message": f"单次最多只能抽 {self.max_draws_per_request} 张",
            }
        with self._account_lock(user_id):
            return self._perform_draw_locked(
                str(user_id), int(pool_id), num_draws, is_daily_free
            )

    def _perform_draw_locked(
        self, user_id: str, pool_id: int, num_draws: int, is_daily_free: bool
    ) -> Dict[str, Any]:
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        pool = self.gacha_repo.get_pool_by_id(pool_id)
        if not pool or not pool.items:
            return {"success": False, "message": "卡池不存在或卡池为空"}

        # The pool and this account's UP choice form one immutable request snapshot.
        template_cache: dict = {}
        up_item, up_warning = self._resolve_user_up(user_id, pool, template_cache)
        if up_warning:
            return {"success": False, "message": up_warning}

        # 每日补给限制检查。兼容旧库将签到池存成 1 点高级货币的情况，
        # 只有签到/AI显式传入 is_daily_free 才免除该成本。
        data_free_pool_ids = {
            int(pool.gacha_pool_id) for pool in self.gacha_repo.get_free_pools()
        }
        daily_free_pool_ids = {
            int(pool.gacha_pool_id) for pool in self.get_daily_free_pools()
        }
        is_data_free_pool = int(pool_id) in data_free_pool_ids
        is_daily_free_draw = bool(is_daily_free and int(pool_id) in daily_free_pool_ids)
        if is_data_free_pool or is_daily_free_draw:
            if num_draws > 1:
                return {"success": False, "message": "每日免费补给一次只能抽一张哦！"}
            draws_today = self.log_repo.get_gacha_records_count_today(
                user_id, pool_id
            )
            if draws_today >= 1:
                return {"success": False, "message": "今天的免费补给已经领过啦，明天再来吧！"}

        # 限时卡池过期校验
        try:
            is_limited = bool(getattr(pool, "is_limited_time", 0))
            open_until_raw = getattr(pool, "open_until", None)
            if is_limited and open_until_raw:
                normalized = open_until_raw.replace("T", " ")
                dt = None
                for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
                    try:
                        dt = datetime.strptime(normalized, fmt)
                        break
                    except ValueError:
                        continue
                if dt is not None:
                    dt = dt.replace(tzinfo=timezone(timedelta(hours=8)))
                    now = get_now()
                    if now > dt:
                        display_time = f"{dt.year}/{dt.month:02d}/{dt.day:02d} {dt.hour:02d}:{dt.minute:02d}"
                        return {"success": False, "message": f"该卡池已结束开放（截止: {display_time}），无法抽卡"}
        except Exception:
            pass

        # 计算费用
        use_premium_currency = (
            not is_daily_free_draw
            and (getattr(pool, "cost_premium_currency", 0) or 0) > 0
        )
        total_premium_cost = (
            0 if is_daily_free_draw else (pool.cost_premium_currency or 0) * num_draws
        )
        total_coin_cost = 0 if is_daily_free_draw else (pool.cost_coins or 0) * num_draws

        if use_premium_currency:
            if user.premium_currency < total_premium_cost:
                return {"success": False, "message": f"高级货币不足，需要 {total_premium_cost} 点高级货币"}
        else:
            if not user.can_afford(total_coin_cost):
                return {"success": False, "message": f"金币不足，需要 {total_coin_cost} 金币"}

        # 初始化缓存、保底、批量收集器
        total_coin_reward = 0
        log_records: List[GachaRecord] = []
        granted_rewards = []
        pending_awards = []
        up_hit_count = 0
        current_pity = 0
        max_rarity = 0

        # 保底初始化
        use_pity = self.pity_threshold > 0 and not (
            is_data_free_pool or is_daily_free_draw
        )
        if use_pity:
            max_rarity = self._get_pool_max_rarity(pool, template_cache)
            if max_rarity > 0:
                pity_data = self.gacha_repo.get_user_pity(user_id, pool_id)
                current_pity = pity_data.current_pity if pity_data else 0
            else:
                use_pity = False

        # Only new balance-version cards carry gacha effects. The selected
        # snapshot is immutable, and catalog conflicts are also enforced here
        # by activating at most one of the six gacha effects.
        hextech_effect = self._get_hextech_gacha_effect(user_id)
        effect_id = hextech_effect.get("id") if hextech_effect else None
        effect_params = hextech_effect.get("params", {}) if hextech_effect else {}
        if not isinstance(effect_params, dict):
            effect_params = {}
        pool_max_rarity = max_rarity
        if effect_id in {"C27", "P13", "G13"} and pool_max_rarity <= 0:
            pool_max_rarity = self._get_pool_max_rarity(pool, template_cache)
        ev_budget = self._hextech_gacha_budget(hextech_effect)
        reference_value = lambda item: self._hextech_gacha_reward_value(item, template_cache)
        hextech_chance = self._hextech_gacha_chance(
            effect_id, effect_params, pool, template_cache, use_pity,
            pool_max_rarity, reference_value, ev_budget, up_item,
        )
        hextech_weight_multiplier = self._hextech_gacha_weight_multiplier(
            effect_id, effect_params, pool, template_cache, use_pity,
            reference_value, ev_budget, up_item,
        )
        hextech_quantity_fraction = self._bounded_float(
            effect_params.get("fraction", 0.0), 0.0, 1.0
        )
        hextech_s14_bonus_cap = self._bounded_float(
            effect_params.get("bonus_cap", 0.0), 0.0, 1.0
        )
        hextech_s13_refund_per_draw = 0
        if effect_id == "S13" and not (
            is_data_free_pool or is_daily_free_draw or use_premium_currency
        ):
            long_run_value = expected_cycle_value(
                pool.items, lambda item: self._get_item_rarity(item, template_cache),
                reference_value, self.pity_threshold if use_pity else 0,
                up_item=up_item,
            )
            refund_fraction = max_coin_refund_fraction(
                ev_budget, long_run_value, int(getattr(pool, "cost_coins", 0) or 0),
                effect_params.get("fraction", 0.0),
                int(self._bounded_float(effect_params.get("bonus_cap", 500), 0, 500)),
            )
            hextech_s13_refund_per_draw = int(math.floor(
                int(getattr(pool, "cost_coins", 0) or 0) * refund_fraction + 1e-9
            ))
        hextech_s14_bonus_coins = 0
        hextech_s14_bonus_coins_total = 0
        hextech_triggered_count = 0
        if effect_id == "S14" and not (
            is_data_free_pool or is_daily_free_draw or use_premium_currency
        ):
            coin_cost = int(getattr(pool, "cost_coins", 0) or 0)
            hextech_s14_bonus_coins = int(math.floor(coin_cost * hextech_s14_bonus_cap + 1e-9))
            hextech_chance = self._bounded_coin_bonus_chance(
                pool, template_cache, use_pity, ev_budget,
                hextech_chance, hextech_s14_bonus_coins, up_item,
            )
        elif effect_id == "S14":
            # Do not report an active chance for free or premium-currency draws.
            hextech_chance = 0.0

        # 执行抽卡 + 发放奖励 + 收集日志
        for _ in range(num_draws):
            # 保底判定
            hard_pity_draw = use_pity and current_pity >= self.pity_threshold - 1
            if hard_pity_draw:
                drawn_item = self._pick_pity_item(pool, max_rarity, template_cache)
            elif hextech_weight_multiplier > 1.0:
                drawn_item = _perform_single_weighted_draw(
                    pool,
                    weight_multiplier=hextech_weight_multiplier,
                    max_rarity=pool_max_rarity,
                    rarity_of=lambda item: self._get_item_rarity(item, template_cache),
                )
            else:
                drawn_item = _perform_single_weighted_draw(pool)
            if not drawn_item:
                continue

            # C27/P13 inspect an optional second candidate, but still commit
            # exactly one final item and one pity/log entry for this draw.
            if (
                not hard_pity_draw and effect_id == "C27"
                and hextech_chance > 0
                and self._get_item_rarity(drawn_item, template_cache)
                == min(
                    self._get_item_rarity(item, template_cache)
                    for item in pool.items
                    if float(getattr(item, "weight", 0) or 0) > 0
                )
                and random.random() < hextech_chance
            ):
                second = _perform_single_weighted_draw(pool)
                if second and self._get_item_rarity(second, template_cache) > self._get_item_rarity(drawn_item, template_cache):
                    drawn_item = second
                    hextech_triggered_count += 1
            elif (
                not hard_pity_draw and effect_id == "P13"
                and hextech_chance > 0 and random.random() < hextech_chance
            ):
                second = _perform_single_weighted_draw(pool)
                if second and self._get_item_rarity(second, template_cache) > self._get_item_rarity(drawn_item, template_cache):
                    drawn_item = second
                    hextech_triggered_count += 1

            # UP is applied to the final candidate after pity and C27/P13, but
            # before reward-type effects such as C28 and S14 are evaluated.
            drawn_item, is_up = apply_personal_up_to_draw(
                drawn_item,
                pool.items,
                lambda item: self._get_item_rarity(item, template_cache),
                up_item,
            )
            if is_up:
                up_hit_count += 1

            reward_quantity = int(getattr(drawn_item, "quantity", 1) or 1)
            if (
                effect_id == "C28" and drawn_item.item_type in ("bait", "item")
                and hextech_chance > 0 and random.random() < hextech_chance
            ):
                reward_quantity += quantity_bonus(reward_quantity, hextech_quantity_fraction)
                hextech_triggered_count += 1
            extra_coin_reward = 0
            if (
                effect_id == "S14" and drawn_item.item_type == "coins"
                and hextech_s14_bonus_coins > 0
                and hextech_chance > 0 and random.random() < hextech_chance
            ):
                extra_coin_reward = hextech_s14_bonus_coins
                reward_quantity += extra_coin_reward
                hextech_s14_bonus_coins_total += extra_coin_reward
                hextech_triggered_count += 1

            # Collect the reward snapshot first. Currency is settled atomically
            # before any inventory/title grant is written.
            item_name = "未知物品"
            item_rarity = 1
            template = None

            if drawn_item.item_type == "rod":
                template = self._get_template("rod", drawn_item.item_id, template_cache)
            elif drawn_item.item_type == "accessory":
                template = self._get_template("accessory", drawn_item.item_id, template_cache)
            elif drawn_item.item_type == "bait":
                template = self._get_template("bait", drawn_item.item_id, template_cache)
            elif drawn_item.item_type == "item":
                template = self._get_template("item", drawn_item.item_id, template_cache)
            elif drawn_item.item_type == "coins":
                total_coin_reward += reward_quantity
                item_name = f"{reward_quantity} 金币"
            elif drawn_item.item_type == "titles":
                template = self._get_template("titles", drawn_item.item_id, template_cache)

            if template:
                item_name = template.name
                item_rarity = template.rarity if hasattr(template, "rarity") else 1

            # 构建用户可见奖励
            if drawn_item.item_type == "coins":
                granted_rewards.append({"type": "coins", "quantity": reward_quantity})
            elif drawn_item.item_type == "titles":
                granted_rewards.append({"type": "title", "id": drawn_item.item_id, "name": item_name})
            else:
                granted_rewards.append({
                    "type": drawn_item.item_type,
                    "id": drawn_item.item_id,
                    "name": item_name,
                    "rarity": item_rarity,
                    "quantity": reward_quantity if drawn_item.item_type in ("bait", "item") else 1,
                    "is_up": is_up,
                })

            if drawn_item.item_type not in ("coins",):
                pending_awards.append({
                    "item_type": drawn_item.item_type,
                    "item_id": drawn_item.item_id,
                    "quantity": reward_quantity,
                    "durability": getattr(template, "durability", None),
                })

            # 收集日志
            log_records.append(GachaRecord(
                record_id=0, user_id=user_id, gacha_pool_id=pool_id,
                item_type=drawn_item.item_type, item_id=drawn_item.item_id,
                item_name=item_name, quantity=reward_quantity,
                rarity=item_rarity, timestamp=get_now()
            ))

            # 更新保底计数
            if use_pity:
                if item_rarity >= max_rarity and drawn_item.item_type != "coins":
                    current_pity = 0
                else:
                    current_pity += 1

        if not granted_rewards:
            return {"success": False, "message": "抽卡失败，请检查卡池配置"}

        # 批量结算
        hextech_refund_coins = hextech_s13_refund_per_draw * num_draws
        charged_coin_cost = 0 if use_premium_currency else total_coin_cost
        coin_delta = total_coin_reward + hextech_refund_coins - charged_coin_cost
        premium_delta = -total_premium_cost if use_premium_currency else 0
        adjust_balance = getattr(self.user_repo, "adjust_balance", None)
        if callable(adjust_balance):
            balance_updated = adjust_balance(
                user_id,
                coins_delta=coin_delta,
                premium_currency_delta=premium_delta,
                required_coins=charged_coin_cost,
                required_premium_currency=total_premium_cost,
            )
        else:
            # Compatibility for older repository fakes/adapters. Production
            # SqliteUserRepository uses the atomic path above.
            latest_user = self.user_repo.get_by_id(user_id)
            balance_updated = bool(latest_user)
            if balance_updated:
                latest_user.coins += coin_delta
                latest_user.premium_currency += premium_delta
                balance_updated = latest_user.coins >= 0 and latest_user.premium_currency >= 0
                if balance_updated:
                    self.user_repo.update(latest_user)
        if not balance_updated:
            return {"success": False, "message": "余额已变化或不足，本次抽卡未结算，请重试"}

        for award in pending_awards:
            item_type = award["item_type"]
            item_id = award["item_id"]
            if item_type == "rod":
                self.inventory_repo.add_rod_instance(user_id, item_id, award["durability"])
            elif item_type == "accessory":
                self.inventory_repo.add_accessory_instance(user_id, item_id)
            elif item_type == "bait":
                self.inventory_repo.update_bait_quantity(user_id, item_id, award["quantity"])
            elif item_type == "item":
                self.inventory_repo.update_item_quantity(user_id, item_id, award["quantity"])
            elif item_type == "titles":
                self.achievement_repo.grant_title_to_user(user_id, item_id)

        if log_records:
            self.log_repo.add_gacha_records_batch(log_records)

        if use_pity:
            self.gacha_repo.set_user_pity(user_id, pool_id, current_pity)

        return {
            "success": True,
            "results": granted_rewards,
            "up_hit_count": up_hit_count,
            "personal_up": self._format_up_item(
                up_item, self._get_item_rarity(up_item, template_cache)
            ) if up_item else None,
            "pity": current_pity,
            "pity_threshold": self.pity_threshold if use_pity else 0,
            "hextech_refund_coins": hextech_refund_coins,
            "hextech_effect": ({
                "id": effect_id,
                "chance": hextech_chance,
                "weight_multiplier": hextech_weight_multiplier,
                "triggered_count": hextech_triggered_count,
                "bonus_coins_total": hextech_s14_bonus_coins_total,
            } if effect_id else None),
        }

    @staticmethod
    def _bounded_float(value: Any, low: float, high: float) -> float:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return low
        if not math.isfinite(number):
            return low
        return min(high, max(low, number))

    def _get_hextech_gacha_effect(self, actor_id: str) -> Optional[Dict[str, Any]]:
        service = getattr(self, "hextech_service", None)
        if service is None:
            return None
        try:
            card = service.get_selected_card(actor_id)
        except Exception:
            return None
        if not isinstance(card, dict):
            return None
        try:
            if int(card.get("balance_version", 1)) < 3:
                return None
        except (TypeError, ValueError):
            return None
        effects = card.get("effects", [])
        if not isinstance(effects, list):
            return None
        for effect in effects:
            if not isinstance(effect, dict) or effect.get("id") not in GACHA_HEXTECH_IDS:
                continue
            return {
                "id": effect["id"],
                "params": effect.get("params", {}),
                "tier": str(card.get("tier", "prismatic")).lower(),
                "balance_version": card.get("balance_version", 3),
            }
        return None

    @staticmethod
    def _hextech_gacha_budget(effect: Optional[Dict[str, Any]]) -> float:
        if not effect:
            return 0.0
        params = effect.get("params", {})
        budgets = {"silver": 0.04, "gold": 0.055, "prismatic": 0.07} if effect.get("balance_version", 3) >= 4 else TIER_EV_BUDGETS
        tier_budget = budgets.get(str(effect.get("tier", "")).lower(), 0.08)
        # The selected card tier is recovered by _get_hextech_gacha_effect and
        # attached to the effect below; card-authored values are always clamped.
        return GachaService._bounded_float(params.get("ev_budget", tier_budget), 0.0, tier_budget)

    def _hextech_gacha_reward_value(self, item: GachaPoolItem, cache: dict) -> Optional[float]:
        return configured_reward_value(
            item,
            lambda item_type, item_id: self._get_template(item_type, item_id, cache),
            getattr(self, "game_config", {}),
        )

    def _hextech_gacha_chance(
        self, effect_id: Optional[str], params: Dict[str, Any], pool: GachaPool,
        cache: dict, use_pity: bool, max_rarity: int,
        value_of, budget: float, up_item: Optional[GachaPoolItem] = None,
    ) -> float:
        requested = self._bounded_float(params.get("chance", 0.0), 0.0, 1.0)
        rarity_of = lambda item: self._get_item_rarity(item, cache)
        pity_threshold = self.pity_threshold if use_pity else 0
        if effect_id in {"C27", "P13"}:
            return max_chance_for_budget(
                pool.items, rarity_of, value_of, budget, requested,
                pity_threshold, effect_id, up_item=up_item,
            )
        if effect_id == "C28":
            fraction = self._bounded_float(params.get("fraction", 0.0), 0.0, 1.0)
            baseline = expected_cycle_value(
                pool.items, rarity_of, value_of, pity_threshold, up_item=up_item
            )
            if baseline is None or baseline <= 0:
                return max_quantity_bonus_chance(
                    pool.items, budget, requested, fraction
                )

            def bonus_value(item):
                if item.item_type not in ("bait", "item"):
                    return 0.0
                base = value_of(item)
                if base is None:
                    return None
                quantity = max(1, int(getattr(item, "quantity", 1) or 1))
                return float(base) * quantity_bonus(quantity, fraction) / quantity

            bonus_ev = expected_cycle_value(
                pool.items, rarity_of, bonus_value, pity_threshold, up_item=up_item
            )
            if bonus_ev is None or bonus_ev <= 0:
                return max_quantity_bonus_chance(pool.items, budget, requested, fraction)
            return min(requested, budget * baseline / bonus_ev)
        if effect_id == "S14":
            # The exact chance is further capped after computing the per-draw
            # coin bonus, whose amount depends on the actual pool cost.
            return requested
        return 0.0

    def _hextech_gacha_weight_multiplier(
        self, effect_id: Optional[str], params: Dict[str, Any], pool: GachaPool,
        cache: dict, use_pity: bool, value_of, budget: float,
        up_item: Optional[GachaPoolItem] = None,
    ) -> float:
        if effect_id != "G13":
            return 1.0
        requested = self._bounded_float(params.get("weight_multiplier", 1.0), 1.0, 2.0)
        rarity_of = lambda item: self._get_item_rarity(item, cache)
        return max_weight_multiplier_for_budget(
            pool.items, rarity_of, value_of, budget, requested,
            self.pity_threshold if use_pity else 0, up_item=up_item,
        )

    def _bounded_coin_bonus_chance(
        self, pool: GachaPool, cache: dict, use_pity: bool, budget: float,
        requested: float, bonus_coins: int,
        up_item: Optional[GachaPoolItem] = None,
    ) -> float:
        if bonus_coins <= 0 or budget <= 0:
            return 0.0
        rarity_of = lambda item: self._get_item_rarity(item, cache)
        pity_threshold = self.pity_threshold if use_pity else 0
        return max_bonus_chance_for_value_budget(
            pool.items,
            rarity_of,
            lambda item: self._hextech_gacha_reward_value(item, cache),
            lambda item: float(bonus_coins) if item.item_type == "coins" else 0.0,
            budget,
            requested,
            pity_threshold,
            up_item=up_item,
        )

    def _get_template(self, item_type: str, item_id: int, cache: dict):
        """带缓存的模板查询"""
        key = (item_type, item_id)
        if key not in cache:
            if item_type == "rod":
                cache[key] = self.item_template_repo.get_rod_by_id(item_id)
            elif item_type == "accessory":
                cache[key] = self.item_template_repo.get_accessory_by_id(item_id)
            elif item_type == "bait":
                cache[key] = self.item_template_repo.get_bait_by_id(item_id)
            elif item_type == "item":
                cache[key] = self.item_template_repo.get_by_id(item_id)
            elif item_type == "titles":
                cache[key] = self.item_template_repo.get_title_by_id(item_id)
            else:
                cache[key] = None
        return cache[key]

    def _get_item_rarity(self, item: GachaPoolItem, cache: dict) -> int:
        """获取物品稀有度（带缓存）"""
        if item.item_type == "coins":
            return 0
        template = self._get_template(item.item_type, item.item_id, cache)
        return template.rarity if template and hasattr(template, "rarity") else 0

    def _get_pool_max_rarity(self, pool: GachaPool, cache: dict) -> int:
        """计算卡池中最高的稀有度"""
        max_r = 0
        for item in pool.items:
            if float(getattr(item, "weight", 0) or 0) <= 0:
                continue
            r = self._get_item_rarity(item, cache)
            if r > max_r:
                max_r = r
        return max_r

    def _pick_pity_item(self, pool: GachaPool, max_rarity: int, cache: dict) -> GachaPoolItem:
        """保底时从最高稀有度物品中加权随机"""
        candidates = [it for it in pool.items if self._get_item_rarity(it, cache) >= max_rarity]
        if not candidates:
            return _perform_single_weighted_draw(pool)
        total_weight = sum(c.weight for c in candidates)
        rand_val = random.uniform(0, total_weight)
        cur = 0
        for c in candidates:
            cur += c.weight
            if rand_val <= cur:
                return c
        return candidates[-1]

    def get_user_gacha_history(self, user_id: str, limit: int = 10) -> Dict[str, Any]:
        """提供查询抽卡历史记录的功能。"""
        records = self.log_repo.get_gacha_records(user_id, limit)
        return {"success": True, "records": records}
