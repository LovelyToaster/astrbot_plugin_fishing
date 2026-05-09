import random
from typing import Dict, Any, Optional, List
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


def _perform_single_weighted_draw(pool: GachaPool) -> GachaPoolItem:
    """执行一次加权随机抽奖。"""
    total_weight = sum(item.weight for item in pool.items)
    rand_val = random.uniform(0, total_weight)

    current_weight = 0
    for item in pool.items:
        current_weight += item.weight
        if rand_val <= current_weight:
            return item
    return None # 理论上不会发生


class GachaService:
    """封装与抽卡系统相关的业务逻辑"""

    def __init__(
        self,
        gacha_repo: AbstractGachaRepository,
        user_repo: AbstractUserRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        log_repo: AbstractLogRepository,
        achievement_repo: AbstractAchievementRepository,
        pity_threshold: int = 80
    ):
        self.gacha_repo = gacha_repo
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.achievement_repo = achievement_repo
        self.log_repo = log_repo
        self.pity_threshold = pity_threshold

    def get_all_pools(self) -> Dict[str, Any]:
        """提供查看所有卡池信息的功能。"""
        try:
            pools = self.gacha_repo.get_all_pools()
            logger.info(f"获取到 {len(pools)} 个卡池信息")
            return {"success": True, "pools": pools}
        except Exception as e:
            return {"success": False, "message": f"获取卡池信息失败: {str(e)}"}

    def get_daily_free_pool(self) -> Optional[GachaPool]:
        """获取每日免费池 (第一个成本为0的池)"""
        free_pools = self.gacha_repo.get_free_pools()
        return free_pools[0] if free_pools else None

    def get_pool_details(self, pool_id: int) -> Dict[str, Any]:
        """获取单个卡池的详细信息，包括奖品列表和概率。"""
        pool = self.gacha_repo.get_pool_by_id(pool_id)
        if not pool:
            return {"success": False, "message": "该卡池不存在"}

        total_weight = sum(item.weight for item in pool.items)
        if total_weight == 0:
            return {"success": True, "pool": pool, "probabilities": {}}

        probabilities = []
        for item in pool.items:
            probability = float(item.weight / total_weight)
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
                item_name = self.item_template_repo.get_title_by_id(item.item_id).name

            probabilities.append({
                "item_type": item.item_type,
                "item_id": item.item_id,
                "item_name": item_name,
                "item_rarity": item_rarity if item.item_type != "titles" else 0,
                "weight": item.weight,
                "probability": 1.0 + round(probability, 4)
            })
        return {"success": True, "pool": pool, "probabilities": probabilities}

    def perform_draw(self, user_id: str, pool_id: int, num_draws: int = 1) -> Dict[str, Any]:
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        pool = self.gacha_repo.get_pool_by_id(pool_id)
        if not pool or not pool.items:
            return {"success": False, "message": "卡池不存在或卡池为空"}

        # 每日免费池限制检查
        free_pool = self.get_daily_free_pool()
        if free_pool and pool_id == free_pool.gacha_pool_id:
            if num_draws > 1:
                return {"success": False, "message": "每日免费补给一次只能抽一张哦！"}
            draws_today = self.log_repo.get_gacha_records_count_today(
                user_id, free_pool.gacha_pool_id
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
        use_premium_currency = (getattr(pool, "cost_premium_currency", 0) or 0) > 0
        total_premium_cost = (pool.cost_premium_currency or 0) * num_draws
        total_coin_cost = (pool.cost_coins or 0) * num_draws

        if use_premium_currency:
            if user.premium_currency < total_premium_cost:
                return {"success": False, "message": f"高级货币不足，需要 {total_premium_cost} 点高级货币"}
        else:
            if not user.can_afford(total_coin_cost):
                return {"success": False, "message": f"金币不足，需要 {total_coin_cost} 金币"}

        # 初始化缓存、保底、批量收集器
        template_cache: dict = {}
        total_coin_reward = 0
        log_records: List[GachaRecord] = []
        granted_rewards = []
        current_pity = 0
        max_rarity = 0

        # 保底初始化
        use_pity = (self.pity_threshold > 0
                    and pool_id != (free_pool.gacha_pool_id if free_pool else None))
        if use_pity:
            max_rarity = self._get_pool_max_rarity(pool, template_cache)
            if max_rarity > 0:
                pity_data = self.gacha_repo.get_user_pity(user_id, pool_id)
                current_pity = pity_data.current_pity if pity_data else 0
            else:
                use_pity = False

        # 执行抽卡 + 发放奖励 + 收集日志
        for _ in range(num_draws):
            # 保底判定
            if use_pity and current_pity >= self.pity_threshold - 1:
                drawn_item = self._pick_pity_item(pool, max_rarity, template_cache)
            else:
                drawn_item = _perform_single_weighted_draw(pool)
            if not drawn_item:
                continue

            # 发放奖励 + 收集模板数据
            item_name = "未知物品"
            item_rarity = 1
            template = None

            if drawn_item.item_type == "rod":
                template = self._get_template("rod", drawn_item.item_id, template_cache)
                durability = template.durability if template else None
                self.inventory_repo.add_rod_instance(user_id, drawn_item.item_id, durability)
            elif drawn_item.item_type == "accessory":
                self.inventory_repo.add_accessory_instance(user_id, drawn_item.item_id)
                template = self._get_template("accessory", drawn_item.item_id, template_cache)
            elif drawn_item.item_type == "bait":
                self.inventory_repo.update_bait_quantity(user_id, drawn_item.item_id, drawn_item.quantity)
                template = self._get_template("bait", drawn_item.item_id, template_cache)
            elif drawn_item.item_type == "item":
                self.inventory_repo.update_item_quantity(user_id, drawn_item.item_id, drawn_item.quantity)
                template = self._get_template("item", drawn_item.item_id, template_cache)
            elif drawn_item.item_type == "coins":
                total_coin_reward += drawn_item.quantity
                item_name = f"{drawn_item.quantity} 金币"
            elif drawn_item.item_type == "titles":
                self.achievement_repo.grant_title_to_user(user_id, drawn_item.item_id)
                template = self._get_template("titles", drawn_item.item_id, template_cache)

            if template:
                item_name = template.name
                item_rarity = template.rarity if hasattr(template, "rarity") else 1

            # 构建用户可见奖励
            if drawn_item.item_type == "coins":
                granted_rewards.append({"type": "coins", "quantity": drawn_item.quantity})
            elif drawn_item.item_type == "titles":
                granted_rewards.append({"type": "title", "id": drawn_item.item_id, "name": item_name})
            else:
                granted_rewards.append({
                    "type": drawn_item.item_type,
                    "id": drawn_item.item_id,
                    "name": item_name,
                    "rarity": item_rarity,
                    "quantity": drawn_item.quantity if drawn_item.item_type in ("bait", "item") else 1
                })

            # 收集日志
            log_records.append(GachaRecord(
                record_id=0, user_id=user_id, gacha_pool_id=pool_id,
                item_type=drawn_item.item_type, item_id=drawn_item.item_id,
                item_name=item_name, quantity=drawn_item.quantity,
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
        if use_premium_currency:
            user.premium_currency -= total_premium_cost
        else:
            user.coins -= total_coin_cost
        if total_coin_reward > 0:
            user.coins += total_coin_reward
        self.user_repo.update(user)

        if log_records:
            self.log_repo.add_gacha_records_batch(log_records)

        if use_pity:
            self.gacha_repo.set_user_pity(user_id, pool_id, current_pity)

        return {
            "success": True,
            "results": granted_rewards,
            "pity": current_pity,
            "pity_threshold": self.pity_threshold if use_pity else 0,
        }

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
