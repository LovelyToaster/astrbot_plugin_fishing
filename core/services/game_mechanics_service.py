import requests
import random
import json
import math
from collections import Counter
from typing import Dict, Any, Optional, Tuple, TYPE_CHECKING
from concurrent.futures import ThreadPoolExecutor
from astrbot.api import logger

# 导入仓储接口和领域模型
from ..repositories.abstract_repository import (
    AbstractUserRepository,
    AbstractLogRepository,
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractUserBuffRepository,
)
from ..domain.models import WipeBombLog, User
from ...core.utils import get_now, get_today, format_remaining_time, calculate_fish_unit_value, get_user_coins_chance_by_repo
from .hextech_game_balance import (
    WIPE_RETURN_CAPS,
    budgeted_chance,
    clamp as clamp_hextech_value,
    effect_params as get_hextech_effect_params,
    ev_budget as get_hextech_ev_budget,
    expected_best_value,
    expected_conditional_reroll_gain,
    expected_electric_success_values,
    expected_wipe_base_payout_ratio,
    expected_wipe_fill_bonus,
    expected_wipe_interval_best_bonus,
    expected_wipe_loss_ratio,
    expected_wipe_profit_bonus,
    expected_wipe_reroll_bonus,
    first_effect as get_first_hextech_effect,
    valid_card as is_v3_hextech_card,
    steal_cooldown,
)

if TYPE_CHECKING:
    from ..repositories.sqlite_user_repo import SqliteUserRepository

def weighted_random_choice(choices: list[tuple[any, any, float]]) -> tuple[any, any, float]:
    """
    带权重的随机选择。
    :param choices: 一个列表，每个元素是一个元组 (min_val, max_val, weight)。
    :return: 选中的元组。
    """
    total_weight = sum(w for _, _, w in choices)
    if total_weight == 0:
        raise ValueError("Total weight cannot be zero")
    rand_val = random.uniform(0, total_weight)
    
    current_weight = 0
    for choice in choices:
        current_weight += choice[2] # weight is the 3rd element
        if rand_val <= current_weight:
            return choice
    
    # Fallback in case of floating point inaccuracies
    return choices[-1]

class GameMechanicsService:
    """封装特殊或独立的游戏机制"""

    FORTUNE_TIERS = {
        "kyokudaikichi": {"min": 200.0, "max": 1500.0, "label": "極大吉", "message": "🔮 沙漏中爆发出天界般的神圣光辉，预示着天降横财，这是上天的恩赐！"},
        "chodaikichi": {"min": 50.0, "max": 200.0, "label": "超大吉", "message": "🔮 沙漏中爆发出神迹般的光芒，预示着传说中的财富即将降临！这是千载难逢的机会！"},
        "daikichi": {"min": 15.0, "max": 50.0, "label": "大吉", "message": "🔮 沙漏中爆发出神圣的光芒，预示着天降横财，这是神明赐予的奇迹！"},
        "chukichi": {"min": 6.0, "max": 15.0, "label": "中吉", "message": "🔮 沙漏中降下璀璨的星辉，预示着一笔泼天的横财即将到来。莫失良机！"},
        "kichi": {"min": 3.0, "max": 6.0, "label": "吉", "message": "🔮 金色的流沙汇成满月之形，预示着时运亨通，机遇就在眼前。"},
        "shokichi": {"min": 2.0, "max": 3.0, "label": "小吉", "message": "🔮 沙漏中的光芒温暖而和煦，预示着前路顺遂，稳中有进。"},
        "suekichi": {"min": 1.0, "max": 2.0, "label": "末吉", "message": "🔮 流沙平稳，波澜不惊。预示着平安喜乐，凡事皆顺。"},
        "kyo": {"min": 0.0, "max": 1.0, "label": "凶", "message": "🔮 沙漏中泛起一丝阴霾，预示着运势不佳，行事务必三思。"},
        "daikyo": {"min": 0.0, "max": 0.8, "label": "大凶", "message": "🔮 暗色的流沙汇成不祥之兆，警示着灾祸将至，请务必谨慎避让！"},
    }

    # --- 新增：命运之轮游戏内置配置 ---
    WHEEL_OF_FATE_CONFIG = {
        "min_entry_fee": 500,
        "max_entry_fee": 50000,
        "cooldown_seconds": 60,
        "timeout_seconds": 60,
        "levels": [
            { "level": 1, "success_rate": 0.65, "multiplier": 1.55 },  # 高风险起点，期望微盈利0.75%
            { "level": 2, "success_rate": 0.60, "multiplier": 1.45 },  # 开始亏损，防止稳赚
            { "level": 3, "success_rate": 0.55, "multiplier": 1.55 },  # 风险递增
            { "level": 4, "success_rate": 0.50, "multiplier": 1.70 },  # 中等风险
            { "level": 5, "success_rate": 0.45, "multiplier": 1.90 },  # 较高风险
            { "level": 6, "success_rate": 0.40, "multiplier": 2.15 },  # 高风险
            { "level": 7, "success_rate": 0.35, "multiplier": 2.50 },  # 极高风险
            { "level": 8, "success_rate": 0.30, "multiplier": 3.00 },  # 冒险者区域
            { "level": 9, "success_rate": 0.25, "multiplier": 3.70 },  # 追梦者区域
            { "level": 10, "success_rate": 0.20, "multiplier": 4.80 }  # 通关巨奖
        ]
    }
    # ------------------------------------

    def __init__(
        self,
        user_repo: AbstractUserRepository,
        log_repo: AbstractLogRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        buff_repo: AbstractUserBuffRepository,
        config: Dict[str, Any],
        statistics_repo=None,
    ):
        self.user_repo = user_repo
        self.log_repo = log_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.buff_repo = buff_repo
        self.config = config
        self.statistics_repo = statistics_repo
        # Wired by the composition root when daily Hextech is enabled.
        self.hextech_service = None
        # 服务器级别的抑制状态
        self._server_suppressed = False
        self._last_suppression_date = None
        self.thread_pool = ThreadPoolExecutor(max_workers=5)
        # 命运之轮：跨回合补救期状态缓存 (user_id -> bool)
        self._wof_pending_protection = {}

    def _get_selected_hextech_card(self, actor_id: str) -> Optional[Dict[str, Any]]:
        """Read only the selected v3 card; legacy daily cards stay inert."""
        service = getattr(self, "hextech_service", None)
        if service is None:
            return None
        try:
            card = service.get_selected_card(str(actor_id))
        except Exception as exc:
            logger.warning(f"读取海克斯卡失败，继续原游戏结算: actor={actor_id}, error={exc}")
            return None
        return card if is_v3_hextech_card(card) else None

    @staticmethod
    def _hextech_chance_ceiling(params: Dict[str, Any]) -> float:
        # A missing chance must not turn an incomplete catalog entry into a
        # guaranteed proc.  Catalog v3 stores chance on every random effect.
        return clamp_hextech_value(params.get("chance", 0.0))

    @staticmethod
    def _hextech_budget(card: Optional[Dict[str, Any]], params: Dict[str, Any]) -> float:
        return get_hextech_ev_budget(card, params) if card else 0.0

    @staticmethod
    def _log_hextech_change(action: str, actor_id: str, effect_id: str,
                            details: Dict[str, Any]) -> None:
        logger.info(
            f"海克斯游戏效果结算: action={action} actor={actor_id} effect={effect_id} "
            f"details={json.dumps(details, ensure_ascii=False, sort_keys=True)}"
        )

    def _get_wof_hextech_card(self, user: User) -> Optional[Dict[str, Any]]:
        """Load the immutable card snapshot attached to this WOF round."""
        snapshot = getattr(user, "wof_hextech_snapshot", None)
        if not snapshot:
            return None
        if isinstance(snapshot, dict):
            card = snapshot
        else:
            try:
                card = json.loads(snapshot)
            except (TypeError, json.JSONDecodeError):
                return None
        return card if is_v3_hextech_card(card) else None

    @staticmethod
    def _set_wof_hextech_snapshot(user: User, card: Optional[Dict[str, Any]]) -> None:
        # Store {} when the game starts without a card.  A nullable column is
        # reserved for legacy in-progress rounds created before this feature.
        user.wof_hextech_snapshot = json.dumps(card or {}, ensure_ascii=False, separators=(",", ":"))

    @staticmethod
    def _social_fish_unit_value(item: Any, template: Any, coins_chance: float) -> int:
        """Transfer the pond's saved price, including its original Hextech bonus."""
        return calculate_fish_unit_value(template.base_value, item.quality_level, coins_chance) if template else 0

    @staticmethod
    def _electric_fish_population(
        victim_inventory: list,
        fish_templates: Dict[int, Any],
        victim_coins_chance: float,
    ) -> Tuple[list, Dict[Tuple[int, int, int], float]]:
        population = []
        unit_values: Dict[Tuple[int, int, int], float] = {}
        for item in victim_inventory:
            count = max(0, int(getattr(item, "quantity", 0) or 0))
            if not count:
                continue
            fish_key = (int(item.fish_id), int(item.quality_level), int(getattr(item, "unit_value", 0) or 0))
            template = fish_templates.get(item.fish_id)
            if template:
                value = GameMechanicsService._social_fish_unit_value(item, template, victim_coins_chance)
                is_high = getattr(template, "rarity", 0) >= 5
            else:
                value = 0
                is_high = False
            unit_values[fish_key] = float(value)
            population.append((count, float(value), is_high))
        return population, unit_values

    def _add_statistics_log(
        self,
        user_id: str,
        action_type: str,
        success: bool,
        target_id: Optional[str] = None,
        fish_count: int = 0,
        coin_amount: int = 0,
        details: Optional[Dict[str, Any]] = None,
    ):
        """安全写入统计日志，写入失败不影响主业务。"""
        if not self.statistics_repo:
            return
        try:
            self.statistics_repo.add_log(
                user_id=user_id,
                target_id=target_id,
                action_type=action_type,
                success=success,
                fish_count=fish_count,
                coin_amount=coin_amount,
                details=details,
            )
        except Exception as e:
            logger.warning(f"[统计] 写入统计日志失败: {e} (action={action_type}, user={user_id})")

    def _check_server_suppression(self) -> bool:
        """检查服务器级别的抑制状态，如果需要则重置"""
        today = get_today()
        
        # 如果是新的一天，重置抑制状态
        if self._last_suppression_date is None or self._last_suppression_date < today:
            self._server_suppressed = False
            self._last_suppression_date = today
        
        return self._server_suppressed
    
    def _trigger_server_suppression(self):
        """触发服务器级别的抑制状态"""
        self._server_suppressed = True
        self._last_suppression_date = get_today()

    def _get_fortune_tier_for_multiplier(self, multiplier: float) -> str:
        if multiplier >= 200.0: return "kyokudaikichi"    # 極大吉 (200-1500倍)
        if multiplier >= 50.0: return "chodaikichi"       # 超大吉 (50-200倍)
        if multiplier >= 15.0: return "daikichi"          # 大吉 (15-50倍)
        if multiplier >= 6.0: return "chukichi"           # 中吉 (6-15倍)
        if multiplier >= 3.0: return "kichi"              # 吉 (3-6倍)
        if multiplier >= 2.0: return "shokichi"           # 小吉 (2-3倍)
        if multiplier >= 1.0: return "suekichi"           # 末吉 (1.0-2倍)
        return "kyo"                                       # 凶 (0-1倍)
    
    def _parse_wipe_bomb_forecast(self, forecast_value: Optional[str]) -> Optional[Dict[str, Any]]:
        """解析存储在用户上的擦弹预测信息，兼容旧格式。"""
        if not forecast_value:
            return None

        if isinstance(forecast_value, dict):
            return forecast_value

        try:
            data = json.loads(forecast_value)
            if isinstance(data, dict) and data.get("mode"):
                return data
        except (TypeError, json.JSONDecodeError):
            pass

        # 兼容旧版本仅存储等级字符串的情况
        return {"mode": "legacy", "tier": forecast_value}


    def forecast_wipe_bomb(self, user_id: str) -> Dict[str, Any]:
        """
        预知下一次擦弹的结果是"吉"还是"凶"。
        削弱版本：33.3%准确率 + 33.3%占卜失败 + 33.4%错误预测，保持详细等级
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 检查是否已有预测结果
        if user.wipe_bomb_forecast:
            return {"success": False, "message": "你已经预知过一次了，请先去擦弹吧！"}

        # 模拟一次随机过程来决定结果
        wipe_bomb_config = self.config.get("wipe_bomb", {})
        # 使用与 perform_wipe_bomb 相同的新配置以确保一致性
        # 使用与perform_wipe_bomb相同的权重系统
        normal_ranges = [
            (0.0, 0.2, 10000),     # 严重亏损
            (0.2, 0.5, 18000),     # 普通亏损
            (0.5, 0.8, 15000),     # 小亏损
            (0.8, 1.2, 25000),     # 小赚
            (1.2, 2.0, 14100),     # 中赚（修正）
            (2.0, 3.0, 4230),      # 大赚（修正）
            (3.0, 6.0, 705),       # 超大赚（修正）
            (6.0, 15.0, 106),      # 高倍率（修正）
            (15.0, 50.0, 21),      # 超级头奖（修正）
            (50.0, 200.0, 7),      # 传说级奖励（修正）
            (200.0, 1500.0, 1),    # 神话级奖励（修正）
        ]
        
        suppressed_ranges = [
            (0.0, 0.2, 10000),     # 严重亏损
            (0.2, 0.5, 18000),     # 普通亏损
            (0.5, 0.8, 15000),     # 小亏损
            (0.8, 1.2, 25000),     # 小赚
            (1.2, 2.0, 20000),     # 中赚
            (2.0, 3.0, 6000),      # 大赚
            (3.0, 6.0, 1000),      # 超大赚
            (6.0, 15.0, 150),      # 高倍率
            (15.0, 50.0, 0),       # 超级头奖（禁用）
            (50.0, 200.0, 0),      # 传说级奖励（禁用）
            (200.0, 1500.0, 0),    # 神话级奖励（禁用）
        ]
        
        # 检查服务器级别的抑制状态
        suppressed = self._check_server_suppression()
        ranges = wipe_bomb_config.get(
            "suppressed_ranges" if suppressed else "normal_ranges",
            suppressed_ranges if suppressed else normal_ranges
        )
        
        # 模拟一次抽奖来决定运势
        try:
            chosen_range = weighted_random_choice(ranges)
            simulated_multiplier = random.uniform(chosen_range[0], chosen_range[1])
        except (ValueError, IndexError) as e:
            logger.error(f"擦弹预测时随机选择出错: {e}", exc_info=True)
            return {"success": False, "message": "占卜失败，似乎天机不可泄露..."}

        # 获取真实的运势等级
        real_tier_key = self._get_fortune_tier_for_multiplier(simulated_multiplier)
        
        # 削弱机制：33.3%准确率 + 33.3%占卜失败
        prediction_accuracy = 0.333  # 33.3%准确率
        divination_failure_rate = 0.333  # 33.3%占卜失败率
        random_value = random.random()
        
        if random_value < divination_failure_rate:
            # 占卜失败：无法获得预测结果
            user.wipe_bomb_forecast = None
            message = "❌ 占卜失败,"
            failure_messages = [
                "🔮 沙漏中的流沙突然变得混乱不堪，天机被遮蔽，无法窥探未来...",
                "🔮 沙漏中泛起诡异的迷雾，占卜之力被干扰，预测失败...",
                "🔮 沙漏中的光芒瞬间熄灭，似乎有什么力量阻止了预知...",
                "🔮 沙漏中的流沙停滞不前，占卜仪式未能完成...",
                "🔮 沙漏中传来低沉的嗡鸣声，预知之力被封印，占卜失败..."
            ]
            message += random.choice(failure_messages)
        elif random_value < divination_failure_rate + prediction_accuracy:
            # 准确预测：使用真实的详细运势等级
            user.wipe_bomb_forecast = json.dumps({
                "mode": "accurate",
                "tier": real_tier_key,
                "multiplier": simulated_multiplier
            })
            message = self.FORTUNE_TIERS[real_tier_key]["message"]
        else:
            # 错误预测：随机选择一个详细运势等级
            all_tiers = [t for t in self.FORTUNE_TIERS.keys() if t != real_tier_key]
            # 在消息中添加不确定性提示
            message = "⚠️ 注意：沙漏的样子有些奇怪..."
            wrong_tier_key = random.choice(all_tiers) if all_tiers else real_tier_key
            user.wipe_bomb_forecast = json.dumps({
                "mode": "inaccurate",
                "tier": wrong_tier_key
            })
            message += self.FORTUNE_TIERS[wrong_tier_key]["message"]
        
        # 保存预测结果
        self.user_repo.update(user)
        
        return {"success": True, "message": message}

    def perform_wipe_bomb(self, user_id: str, contribution_amount: int) -> Dict[str, Any]:
        """
        处理“擦弹”的完整逻辑。
        """
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "用户不存在"}

        # 1. 验证投入金额
        if contribution_amount <= 0:
            return {"success": False, "message": "投入金额必须大于0"}
        if not user.can_afford(contribution_amount):
            return {"success": False, "message": f"金币不足，当前拥有 {user.coins} 金币"}

        # 2. 检查每日次数限制 (性能优化)
        wipe_bomb_config = self.config.get("wipe_bomb", {})
        base_max_attempts = wipe_bomb_config.get("max_attempts_per_day", 3)

        # 检查是否有增加次数的 buff
        extra_attempts = 0
        boost_buff = self.buff_repo.get_active_by_user_and_type(
            user_id, "WIPE_BOMB_ATTEMPTS_BOOST"
        )
        if boost_buff and boost_buff.payload:
            try:
                payload = json.loads(boost_buff.payload)
                extra_attempts = payload.get("amount", 0)
            except json.JSONDecodeError:
                logger.warning(f"解析擦弹buff载荷失败: user_id={user_id}")

        total_max_attempts = base_max_attempts + extra_attempts
        
        # 获取今天的日期字符串
        today_str = get_today().strftime('%Y-%m-%d')
        
        # 检查是否是新的一天，如果是，则重置用户的每日擦弹计数
        if user.last_wipe_bomb_date != today_str:
            user.wipe_bomb_attempts_today = 0
            user.last_wipe_bomb_date = today_str

        # 使用用户对象中的计数值进行判断，不再查询日志
        if user.wipe_bomb_attempts_today >= total_max_attempts:
            return {
                "success": False, 
                "message": f"你今天的擦弹次数已用完({user.wipe_bomb_attempts_today}/{total_max_attempts})，明天再来吧！"
            }
        
        # 3. 计算随机奖励倍数 (使用加权随机)
        # 默认奖励范围和权重: (min_multiplier, max_multiplier, weight)
        # 专家建议配置：根据计算结果重新调整的权重分布
        # 使用整数权重（放大1000倍）避免小数计算
        normal_ranges = [
            (0.0, 0.2, 10000),     # 严重亏损
            (0.2, 0.5, 18000),     # 普通亏损
            (0.5, 0.8, 15000),     # 小亏损
            (0.8, 1.2, 25000),     # 小赚
            (1.2, 2.0, 14100),     # 中赚（增加）
            (2.0, 3.0, 4230),      # 大赚（增加）
            (3.0, 6.0, 705),       # 超大赚（增加）
            (6.0, 15.0, 106),      # 高倍率（增加）
            (15.0, 50.0, 21),      # 超级头奖（维持）
            (50.0, 200.0, 7),      # 传说级奖励（维持）
            (200.0, 1500.0, 1),    # 神话级奖励（维持）
        ]

        # 抑制模式：当一天内已开出≥15x高倍率后，禁用高倍率区间
        suppressed_ranges = [
            (0.0, 0.2, 10000),     # 严重亏损
            (0.2, 0.5, 18000),     # 普通亏损
            (0.5, 0.8, 15000),     # 小亏损
            (0.8, 1.2, 25000),     # 小赚
            (1.2, 2.0, 20000),     # 中赚
            (2.0, 3.0, 6000),      # 大赚
            (3.0, 6.0, 1000),      # 超大赚
            (6.0, 15.0, 150),      # 高倍率
            (15.0, 50.0, 0),       # 超级头奖（禁用）
            (50.0, 200.0, 0),      # 传说级奖励（禁用）
            (200.0, 1500.0, 0),    # 神话级奖励（禁用）
        ]

        # 检查服务器级别的抑制状态
        suppressed = self._check_server_suppression()

        # 根据抑制状态选择权重表
        if suppressed:
            ranges = wipe_bomb_config.get("suppressed_ranges", suppressed_ranges)
        else:
            ranges = wipe_bomb_config.get("normal_ranges", normal_ranges)

        # 4. 处理预知结果 (使用详细逻辑)
        forecast_info = self._parse_wipe_bomb_forecast(user.wipe_bomb_forecast)
        predetermined_multiplier: Optional[float] = None

        if forecast_info:
            mode = forecast_info.get("mode")
            if mode == "accurate":
                predetermined_multiplier = forecast_info.get("multiplier")
                if predetermined_multiplier is None:
                    # 兼容没有存储 multiplier 的情况，基于等级随机一个值
                    tier_key = forecast_info.get("tier")
                    tier_info = self.FORTUNE_TIERS.get(tier_key) if tier_key else None
                    if tier_info:
                        predetermined_multiplier = random.uniform(
                            tier_info.get("min", 0.0), tier_info.get("max", 1.0)
                        )
            # 使用后清空预测
            user.wipe_bomb_forecast = None

        # 5. 计算随机奖励倍数 (使用加权随机)
        try:
            if predetermined_multiplier is not None:
                reward_multiplier = predetermined_multiplier
            else:
                chosen_range = weighted_random_choice(ranges)
                reward_multiplier = random.uniform(chosen_range[0], chosen_range[1])
        except (ValueError, IndexError) as e:
            logger.error(f"擦弹时随机选择出错: {e}", exc_info=True)
            return {"success": False, "message": "擦弹失败，似乎时空发生了扭曲..."}

        # 6. 计算最终金额并执行事务
        reward_amount = int(contribution_amount * reward_multiplier)
        raw_reward_amount = reward_amount
        hextech_bonus = 0
        hextech_effect_id = None
        # A forecast is treated as locked knowledge.  Disable every bonus on
        # that play so it cannot be combined with a predicted interval.
        if not forecast_info:
            card = self._get_selected_hextech_card(user_id)
            wipe_effect = get_first_hextech_effect(
                card, ("C29", "C30", "S15", "G14", "G15", "P14")
            )
            if wipe_effect:
                hextech_effect_id = wipe_effect.get("id")
                params = get_hextech_effect_params(wipe_effect)
                tier_return_cap = WIPE_RETURN_CAPS.get(card.get("tier"), 1.01)
                return_cap = clamp_hextech_value(
                    params.get("return_cap", tier_return_cap),
                    1.0,
                    tier_return_cap,
                )
                base_return = expected_wipe_base_payout_ratio(ranges)
                # The continuous payout integral is an upper bound for the
                # integer payout; reserve one coin for per-play floor rounding.
                remaining_ev = max(0.0, contribution_amount * (return_cap - base_return) - 1.0)
                remaining_ev *= clamp_hextech_value(params.get("ev_scale", 1.0))
                configured_chance = self._hextech_chance_ceiling(params)
                chance = 0.0

                if wipe_effect.get("id") in ("C29", "P14"):
                    nominal_cap = min(
                        contribution_amount * clamp_hextech_value(params.get("fraction", 0.20), 0.0, 0.20),
                        float(params.get("bonus_cap", 20000) or 20000),
                        20000.0,
                    )
                    if wipe_effect.get("id") == "C29":
                        per_chance_ev = expected_wipe_reroll_bonus(
                            contribution_amount, ranges, 1.0, nominal_cap
                        )
                        chance = budgeted_chance(
                            1.0, per_chance_ev, remaining_ev, configured_chance
                        )
                    else:
                        # P14 always tries again below 0.5x.  Calibrate its
                        # per-play extra cap against the remaining EV allowance.
                        lower_cap, upper_cap = 0.0, max(0.0, nominal_cap)
                        for _ in range(36):
                            middle_cap = (lower_cap + upper_cap) / 2.0
                            expected_bonus = expected_wipe_reroll_bonus(
                                contribution_amount, ranges, 1.0, middle_cap
                            )
                            if expected_bonus <= remaining_ev:
                                lower_cap = middle_cap
                            else:
                                upper_cap = middle_cap
                        nominal_cap = lower_cap
                        chance = 1.0

                    if reward_multiplier < 0.5 and chance > 0 and random.random() < chance:
                        reroll_range = weighted_random_choice(ranges)
                        reroll_multiplier = random.uniform(reroll_range[0], reroll_range[1])
                        if reroll_multiplier > reward_multiplier:
                            reroll_reward = int(contribution_amount * reroll_multiplier)
                            hextech_bonus = min(
                                max(0, reroll_reward - raw_reward_amount),
                                max(0, int(nominal_cap)),
                            )

                elif wipe_effect.get("id") == "C30":
                    loss_ratio = expected_wipe_loss_ratio(ranges)
                    requested_fraction = clamp_hextech_value(params.get("fraction", 0.0))
                    try:
                        bonus_cap = max(0.0, float(params.get("bonus_cap", float("inf"))))
                    except (TypeError, ValueError):
                        bonus_cap = float("inf")
                    per_fraction_ev = contribution_amount * loss_ratio
                    allowed_fraction = (
                        remaining_ev / per_fraction_ev if per_fraction_ev > 0 else 0.0
                    )
                    fraction = min(requested_fraction, allowed_fraction)
                    if math.isfinite(bonus_cap) and per_fraction_ev > 0:
                        # The cap only reduces EV, so no additional adjustment is needed.
                        pass
                    if reward_amount < contribution_amount and fraction > 0:
                        hextech_bonus = min(
                            int((contribution_amount - raw_reward_amount) * fraction),
                            int(bonus_cap) if math.isfinite(bonus_cap)
                            else max(0, contribution_amount - raw_reward_amount),
                        )

                elif wipe_effect.get("id") == "S15":
                    per_chance_ev = expected_wipe_fill_bonus(
                        contribution_amount, ranges, 1.0
                    )
                    chance = budgeted_chance(
                        1.0, per_chance_ev, remaining_ev, configured_chance
                    )
                    if 0.8 <= reward_multiplier < 1.0 and chance > 0 and random.random() < chance:
                        hextech_bonus = max(0, contribution_amount - raw_reward_amount)

                elif wipe_effect.get("id") == "G14":
                    requested_fraction = clamp_hextech_value(params.get("fraction", 0.0))
                    price_fraction = clamp_hextech_value(params.get("price_fraction", 0.10), 0.0, 1.0)
                    bonus_cap = min(
                        contribution_amount * price_fraction,
                        float(params.get("bonus_cap", 20000) or 20000),
                        20000.0,
                    )
                    lower_fraction, upper_fraction = 0.0, requested_fraction
                    for _ in range(36):
                        middle_fraction = (lower_fraction + upper_fraction) / 2.0
                        expected_bonus = expected_wipe_profit_bonus(
                            contribution_amount, ranges, middle_fraction, bonus_cap
                        )
                        if expected_bonus <= remaining_ev:
                            lower_fraction = middle_fraction
                        else:
                            upper_fraction = middle_fraction
                    fraction = lower_fraction
                    if reward_multiplier > 1.0 and fraction > 0:
                        hextech_bonus = min(
                            int(max(0, reward_amount - contribution_amount) * fraction),
                            int(bonus_cap),
                        )

                elif wipe_effect.get("id") == "G15":
                    per_chance_ev = expected_wipe_interval_best_bonus(
                        contribution_amount, ranges, 1.0
                    )
                    chance = budgeted_chance(
                        1.0, per_chance_ev, remaining_ev, configured_chance
                    )
                    if (
                        reward_multiplier >= chosen_range[0]
                        and reward_multiplier <= chosen_range[1]
                        and chance > 0
                        and random.random() < chance
                    ):
                        reroll_multiplier = random.uniform(chosen_range[0], chosen_range[1])
                        if reroll_multiplier > reward_multiplier:
                            hextech_bonus = max(
                                0,
                                int(contribution_amount * reroll_multiplier) - raw_reward_amount,
                            )

                # Apply the stored (possibly gift-scaled) cap to every effect;
                # the server's 20,000 coin ceiling is still the upper bound.
                absolute_cap = int(clamp_hextech_value(params.get("bonus_cap", 20000), 0.0, 20000.0))
                hextech_bonus = min(max(0, hextech_bonus), absolute_cap)
                if hextech_bonus > 0:
                    reward_amount += hextech_bonus
                    self._log_hextech_change(
                        "wipe_bomb",
                        user_id,
                        hextech_effect_id,
                        {
                            "raw_multiplier": reward_multiplier,
                            "raw_reward": raw_reward_amount,
                            "bonus": hextech_bonus,
                            "effective_chance": chance,
                            "return_cap": return_cap,
                            "suppressed_table": suppressed,
                        },
                    )

        profit = reward_amount - contribution_amount

        # 检查是否触发服务器级别抑制（开出≥15x高倍率）
        suppression_triggered = False
        if reward_multiplier >= 15.0 and not suppressed:
            self._trigger_server_suppression()
            suppression_triggered = True

        # 7. 在同一个 user 对象上更新所有需要修改的属性
        user.coins += profit
        user.wipe_bomb_attempts_today += 1 # 增加当日计数

        if reward_multiplier > user.max_wipe_bomb_multiplier:
            user.max_wipe_bomb_multiplier = reward_multiplier
    
        if user.min_wipe_bomb_multiplier is None or reward_multiplier < user.min_wipe_bomb_multiplier:
            user.min_wipe_bomb_multiplier = reward_multiplier
        
        # 8. 一次性将所有用户数据的变更保存到数据库
        self.user_repo.update(user)

        # 9. 记录日志
        log_entry = WipeBombLog(
            log_id=0, # DB自增
            user_id=user_id,
            contribution_amount=contribution_amount,
            reward_multiplier=reward_multiplier,
            reward_amount=reward_amount,
            timestamp=get_now()
        )
        self.log_repo.add_wipe_bomb_log(log_entry)

        # 上传非敏感数据到服务器
        def upload_data_async():
            upload_data = {
                "user_id": user_id,
                "contribution_amount": contribution_amount,
                "reward_multiplier": reward_multiplier,
                "reward_amount": reward_amount,
                "raw_reward_amount": raw_reward_amount,
                "hextech_bonus": hextech_bonus,
                "profit": profit,
                "timestamp": log_entry.timestamp.isoformat()
            }
            api_url = "http://veyu.me/api/record"
            try:
                response = requests.post(api_url, json=upload_data)
                if response.status_code != 200:
                    logger.info(f"上传数据失败: {response.text}")
            except Exception as e:
                logger.error(f"上传数据时发生错误: {e}")

        # 启动异步线程进行数据上传，不阻塞主流程
        self.thread_pool.submit(upload_data_async)

        # 10. 构建返回结果
        result = {
            "success": True,
            "contribution": contribution_amount,
            "multiplier": reward_multiplier,
            "reward": reward_amount,
            "raw_reward": raw_reward_amount,
            "hextech_bonus": hextech_bonus,
            "hextech_effect_id": hextech_effect_id,
            "profit": profit,
            # 使用 user 对象中的新计数值来计算剩余次数
            "remaining_today": total_max_attempts - user.wipe_bomb_attempts_today,
        }
        
        if suppression_triggered:
            result["suppression_notice"] = "✨ 天界之力降临！你的惊人运气触发了时空沙漏的平衡法则！为了避免时空扭曲，命运女神暂时调整了概率之流，但宝藏之门依然为你敞开！"
        
        return result

    # ============================================================
    # ================= 新增功能：命运之轮 (交互版) 开始 ===========
    # ============================================================
    
    def _reset_wof_state(self, user: User, cash_out_prize: int = 0) -> None:
        """内部辅助函数，用于重置用户的游戏状态并保存。"""
        if cash_out_prize > 0:
            user.coins += cash_out_prize
        user.in_wheel_of_fate = False
        user.last_wof_play_time = get_now()
        user.wof_last_action_time = None
        user.wof_used_protection = False  # 重置保护道具使用状态
        user.wof_hextech_snapshot = None
        
        # 清除内存标识
        if user.user_id in self._wof_pending_protection:
            del self._wof_pending_protection[user.user_id]
            
        # 清除"操纵现实"buff
        active_boost = self.buff_repo.get_active_by_user_and_type(
            user.user_id, "WOF_PROBABILITY_BOOST"
        )
        if active_boost:
            self.buff_repo.delete(active_boost.id)

        self.user_repo.update(user)

    def _wof_failure_refund(self, user: User) -> Tuple[int, Optional[str], Dict[str, Any]]:
        card = self._get_wof_hextech_card(user)
        effect = get_first_hextech_effect(card, ("C31", "S16", "P15"))
        if not effect:
            return 0, None, {}
        effect_id = effect.get("id")
        params = get_hextech_effect_params(effect)
        entry_fee = max(0, int(getattr(user, "wof_entry_fee", 0) or 0))
        if effect_id in ("C31", "P15") and int(getattr(user, "wof_current_level", 0) or 0) < 3:
            return 0, effect_id, {"eligible": False, "completed_levels": getattr(user, "wof_current_level", 0)}

        fraction = clamp_hextech_value(params.get("fraction", 0.0), 0.0, 0.30)
        chance = self._hextech_chance_ceiling(params)
        if effect_id == "S16":
            # The chance times refund fraction stays within the card's tier EV
            # budget, including malformed or over-budget snapshots.
            budget = self._hextech_budget(card, params)
            chance = min(chance, budget / fraction) if fraction > 0 else 0.0
        triggered = chance > 0 and random.random() < chance
        amount = int(entry_fee * fraction) if triggered else 0
        details = {
            "chance": chance,
            "fraction": fraction,
            "refund": amount,
            "completed_levels": int(getattr(user, "wof_current_level", 0) or 0),
        }
        if amount > 0:
            self._log_hextech_change("wheel_of_fate_failure", user.user_id, effect_id, details)
        return amount, effect_id, details

    def _wof_success_bonus(
        self, user: User, base_prize: int, *, normal_settlement: bool
    ) -> Tuple[int, Optional[str], Dict[str, Any]]:
        if not normal_settlement:
            return 0, None, {}
        card = self._get_wof_hextech_card(user)
        effect = get_first_hextech_effect(card, ("C32", "G16", "P16"))
        if not effect:
            return 0, None, {}

        effect_id = effect.get("id")
        params = get_hextech_effect_params(effect)
        entry_fee = max(0, int(getattr(user, "wof_entry_fee", 0) or 0))
        prize = max(0, int(base_prize or 0))
        profit = max(0, prize - entry_fee)
        fraction = clamp_hextech_value(params.get("fraction", 0.0), 0.0, 1.0)
        cap_fraction = clamp_hextech_value(params.get("bonus_cap", 0.0), 0.0, 0.30)
        bonus = 0
        params_detail = {"fraction": fraction, "bonus_cap": cap_fraction}

        if effect_id == "C32" and profit > 0:
            bonus = min(int(profit * fraction), int(entry_fee * cap_fraction))
        elif effect_id == "G16" and int(getattr(user, "wof_current_level", 0) or 0) >= 5 and profit > 0:
            bonus = min(int(profit * fraction), int(entry_fee * cap_fraction))
        elif effect_id == "P16":
            milestones = params.get("milestones")
            if not isinstance(milestones, dict):
                milestones = {"3": 0.10, "6": 0.20, "10": 0.30}
            completed = int(getattr(user, "wof_current_level", 0) or 0)
            eligible = []
            for raw_level, raw_fraction in milestones.items():
                try:
                    level = int(raw_level)
                    refund_fraction = clamp_hextech_value(raw_fraction, 0.0, 0.30)
                except (TypeError, ValueError):
                    continue
                if level <= completed:
                    eligible.append((level, refund_fraction))
            if eligible:
                level, refund_fraction = max(eligible, key=lambda row: row[0])
                bonus = int(entry_fee * refund_fraction)
                params_detail = {"milestone": level, "fraction": refund_fraction}
            else:
                params_detail = {"milestone": None, "fraction": 0.0}
        else:
            params_detail = {"fraction": fraction, "bonus_cap": cap_fraction}

        bonus = min(max(0, bonus), int(entry_fee * 0.30))
        details = {
            "base_prize": prize,
            "profit": profit,
            "bonus": bonus,
            "completed_levels": int(getattr(user, "wof_current_level", 0) or 0),
            **params_detail,
        }
        if bonus > 0:
            self._log_hextech_change("wheel_of_fate_settlement", user.user_id, effect_id, details)
        return bonus, effect_id, details

    def handle_wof_timeout(self, user_id: str) -> Dict[str, Any] | None:
        """检查并处理指定用户的游戏超时。如果处理了超时，返回一个结果字典。"""
        user = self.user_repo.get_by_id(user_id)
        if not hasattr(user, 'in_wheel_of_fate') or not user.in_wheel_of_fate or not user.wof_last_action_time:
            return None

        config = self.WHEEL_OF_FATE_CONFIG
        timeout_seconds = config.get("timeout_seconds", 60)
        now = get_now()
        
        if (now - user.wof_last_action_time).total_seconds() > timeout_seconds:
            is_awaiting = self._wof_pending_protection.get(user_id, False)
            prize = user.wof_current_prize if not is_awaiting else 0
            if is_awaiting:
                extra, effect_id, effect_details = self._wof_failure_refund(user)
            else:
                extra, effect_id, effect_details = self._wof_success_bonus(
                    user, prize, normal_settlement=True
                )
            self._reset_wof_state(user, cash_out_prize=prize + extra)
            
            if is_awaiting:
                message = f"[CQ:at,qq={user_id}] ⏰ 由于你超时未做出补救决定，挑战已宣告失败！你失去了一切奖金。"
                if extra > 0:
                    message += f"\n🎴 海克斯返还 {extra} 金币。"
            else:
                message = f"[CQ:at,qq={user_id}] ⏰ 你的操作已超时，系统已自动为你结算当前奖金 {prize} 金币。"
                if extra > 0:
                    message += f"\n🎴 海克斯额外结算 {extra} 金币。"
                
            logger.info(f"用户 {user_id} 命运之轮超时，自动结算 {prize} 金币。 (补救期缓存: {is_awaiting})")
            
            return {
                "success": True,
                "status": "timed_out",
                "message": message,
                "base_prize": prize,
                "hextech_bonus": extra,
                "hextech_effect_id": effect_id,
                "hextech_details": effect_details,
            }
        return None

    def start_wheel_of_fate(self, user_id: str, entry_fee: int) -> Dict[str, Any]:
        """开始一局“命运之轮”游戏。"""
        user = self.user_repo.get_by_id(user_id)
        if not user: return {"success": False, "message": "用户不存在"}
        
        # 检查 User 对象是否具有所需属性，提供向后兼容性
        if not all(hasattr(user, attr) for attr in ['in_wheel_of_fate', 'wof_last_action_time', 'last_wof_play_time', 'wof_plays_today', 'last_wof_date']):
             return {"success": False, "message": "错误：用户数据结构不完整，请联系管理员更新数据库。"}

        timeout_result = self.handle_wof_timeout(user_id)
        if timeout_result:
            user = self.user_repo.get_by_id(user_id)

        if user.in_wheel_of_fate:
            return {"success": False, "message": f"[CQ:at,qq={user_id}] 你已经在游戏中了，请回复【继续】或【放弃】。"}

        # --- [新功能] 每日次数限制逻辑 ---
        wheel_of_fate_daily_limit = self.config.get("wheel_of_fate_daily_limit", 3)
        today_str = get_today().strftime('%Y-%m-%d')

        # 如果记录的日期不是今天，重置计数器
        if user.last_wof_date != today_str:
            user.wof_plays_today = 0
            user.last_wof_date = today_str

        # 检查次数是否已达上限
        if user.wof_plays_today >= wheel_of_fate_daily_limit:
            return {"success": False, "message": f"今天的运气已经用光啦！你今天已经玩了 {user.wof_plays_today}/{wheel_of_fate_daily_limit} 次命运之轮，请明天再来吧。"}
        # --- 限制逻辑结束 ---

        config = self.WHEEL_OF_FATE_CONFIG
        min_fee = config.get("min_entry_fee", 500)
        max_fee = config.get("max_entry_fee", 50000)
        cooldown = config.get("cooldown_seconds", 60)
        now = get_now()

        if user.last_wof_play_time and (now - user.last_wof_play_time).total_seconds() < cooldown:
            remaining = int(cooldown - (now - user.last_wof_play_time).total_seconds())
            return {"success": False, "message": f"[CQ:at,qq={user_id}] 命运之轮冷却中，请等待 {remaining} 秒后再试。"}

        if not min_fee <= entry_fee <= max_fee:
            return {"success": False, "message": f"[CQ:at,qq={user_id}] 入场费必须在 {min_fee} 到 {max_fee} 金币之间。"}
        if not user.can_afford(entry_fee):
            return {"success": False, "message": f"[CQ:at,qq={user_id}] 金币不足，当前拥有 {user.coins} 金币。"}

        user.coins -= entry_fee
        user.in_wheel_of_fate = True
        user.wof_current_level = 0
        user.wof_current_prize = entry_fee
        user.wof_entry_fee = entry_fee
        user.wof_last_action_time = now
        self._set_wof_hextech_snapshot(user, self._get_selected_hextech_card(user_id))
        
        # [新功能] 游戏次数加一
        user.wof_plays_today += 1
        user.wof_used_protection = False  # 初始化单局保护标识
        
        self.user_repo.update(user) # 保存所有更新

        return self.continue_wheel_of_fate(user_id, user_obj=user)

    def _try_use_wof_protection(self, user: User) -> bool:
        """尝试使用命运之轮保护道具。"""
        # 增加单局仅限一次的校验
        if getattr(user, 'wof_used_protection', False):
            return False

        # 1. 查找具有 WOF_PROTECTION 效果的道具模板
        all_items = self.item_template_repo.get_all_items()
        
        protection_item = next((item for item in all_items if (getattr(item, 'effect_type', None) == "WOF_PROTECTION") or (item.name == "逆转天平")), None)
        
        if not protection_item:
            return False
            
        # 2. 检查用户库存
        inventory = self.inventory_repo.get_user_item_inventory(user.user_id)
        count = inventory.get(protection_item.item_id, 0)
        
        if count > 0:
            # 3. 扣除道具并设置本局已使用标识
            self.inventory_repo.update_item_quantity(user.user_id, protection_item.item_id, -1)
            user.wof_used_protection = True
            return True
            
        return False

    def continue_wheel_of_fate(self, user_id: str, user_obj: User | None = None) -> Dict[str, Any]:
        """在命运之轮中继续挑战下一层。"""

        if timeout_result := self.handle_wof_timeout(user_id):
            return timeout_result

        user = user_obj if user_obj else self.user_repo.get_by_id(user_id)
        if not hasattr(user, 'in_wheel_of_fate') or not user.in_wheel_of_fate:
            return {"success": False, "status": "not_in_game", "message": "⚠️ 你当前不在命运之轮游戏中，无法继续。"}

        config = self.WHEEL_OF_FATE_CONFIG
        levels = config.get("levels", [])
        next_level_index = user.wof_current_level

        # 检测"操纵现实"buff
        boost_multiplier = None
        boost_max_prob = None
        active_boost_buff = self.buff_repo.get_active_by_user_and_type(
            user_id, "WOF_PROBABILITY_BOOST"
        )
        if active_boost_buff:
            boost_payload = json.loads(active_boost_buff.payload or "{}")
            boost_multiplier = boost_payload.get("probability_multiplier", 1.2)
            boost_max_prob = boost_payload.get("max_probability", 0.95)

        # --- 1. 处理"补救"逻辑：如果当前正处于等待保护确认状态 ---
        used_protection = False
        if self._wof_pending_protection.get(user_id, False):
            # 尝试正式消耗道具
            if self._try_use_wof_protection(user):
                is_success = True
                used_protection = True
                # 补救成功，清除状态
                if user_id in self._wof_pending_protection:
                    del self._wof_pending_protection[user_id]
                # 补救成功，直接走下方“成功流程” (is_success=True)
            else:
                # 如果点继续时道具刚好没了，清除状态并走常规逻辑（或直接失败）
                if user_id in self._wof_pending_protection:
                    del self._wof_pending_protection[user_id]
                return {"success": False, "message": "❌ 道具已失效或不再可用，挑战结束。"}
        else:
            # --- 2. 正常随机判定 ---
            if next_level_index >= len(levels):
                return self.cash_out_wheel_of_fate(user_id, is_final_win=True)

            level_data = levels[next_level_index]
            success_rate = level_data.get("success_rate", 0.5)
            if boost_multiplier is not None:
                adjusted_rate = min(success_rate * boost_multiplier, boost_max_prob)
            else:
                adjusted_rate = success_rate
            is_success = random.random() < adjusted_rate

            if not is_success:
                # --- 3. 失败拦截：如果持有保护道具，不直接结算而是询问 ---
                # 检查是否持有逆转天平（但不消耗）
                all_items = self.item_template_repo.get_all_items()
                protection_item = next((item for item in all_items if (getattr(item, 'effect_type', None) == "WOF_PROTECTION") or (item.name == "逆转天平")), None)
                
                if protection_item and not getattr(user, 'wof_used_protection', False):
                    inventory = self.inventory_repo.get_user_item_inventory(user.user_id)
                    if inventory.get(protection_item.item_id, 0) > 0:
                        # 触发询问状态，写入服务级内存缓存
                        self._wof_pending_protection[user.user_id] = True
                        user.wof_last_action_time = get_now()  # 重新开始配置的选择超时窗口
                        self.user_repo.update(user)
                        return {
                            "success": True, "status": "ongoing",
                            "message": (f"[CQ:at,qq={user_id}] ❌ 糟糕，挑战失败了！\n\n"
                                        f"但你拥有【{protection_item.name}】，可以抵消本次失败。\n"
                                        f"⏱️ 请在{config.get('timeout_seconds', 60)}秒内选择：\n"
                                        f"回复【继续】：消耗道具并【直接通关】本层\n"
                                        f"回复【放弃】：不消耗道具，接受失败并结束游戏")
                        }

        if is_success:
            # --- 4. 成功流程 (包括补救成功和随机成功) ---
            level_data = levels[next_level_index]
            multiplier = level_data.get("multiplier", 1.0)
            
            user.wof_current_level += 1
            user.wof_current_prize = round(user.wof_current_prize * multiplier)
            user.wof_last_action_time = get_now()
            
            if user.wof_current_level == len(levels):
                self.user_repo.update(user)
                return self.cash_out_wheel_of_fate(user_id, is_final_win=True)
            
            self.user_repo.update(user)
            
            next_level_data = levels[user.wof_current_level]
            raw_next_rate = next_level_data.get("success_rate", 0.5)
            if boost_multiplier is not None:
                adjusted_next = min(raw_next_rate * boost_multiplier, boost_max_prob)
                rate_display = f"{int(adjusted_next * 100)}%（🔮原始{int(raw_next_rate * 100)}%）"
            else:
                rate_display = f"{int(raw_next_rate * 100)}%"
            
            protection_msg = "（✨ 触发了【逆转天平】，抵消了一次失败！）" if used_protection else ""
            
            return {
                "success": True, "status": "ongoing",
                "message": (f"[CQ:at,qq={user_id}] 🎯 第 {user.wof_current_level} 层幸存！{protection_msg} (下一层成功率: {rate_display})\n"
                            f"💰 当前累积奖金 {user.wof_current_prize} 金币。\n"
                            f"⏱️ 请在{config.get('timeout_seconds', 60)}秒内回复【继续】或【放弃】！")
            }
        else:
            # --- 5. 彻底失败逻辑 (无道具或已用过) ---
            lost_amount = user.wof_entry_fee
            refund, effect_id, effect_details = self._wof_failure_refund(user)
            self._reset_wof_state(user, cash_out_prize=refund)
            refund_message = f"\n🎴 海克斯返还 {refund} 金币。" if refund > 0 else ""
            return {
                "success": True, "status": "lost",
                "message": (f"[CQ:at,qq={user_id}] 💥 湮灭！ "
                            f"你在通往第 {user.wof_current_level + 1} 层的路上失败了，失去了入场的 {lost_amount} 金币..."
                            f"{refund_message}"),
                "hextech_bonus": refund,
                "hextech_effect_id": effect_id,
                "hextech_details": effect_details,
            }

    def cash_out_wheel_of_fate(self, user_id: str, is_final_win: bool = False) -> Dict[str, Any]:
        """从命运之轮中提现并结束游戏。"""

        if timeout_result := self.handle_wof_timeout(user_id):
            return timeout_result

        user = self.user_repo.get_by_id(user_id)
        if not hasattr(user, 'in_wheel_of_fate') or not user.in_wheel_of_fate:
            return {"success": False, "status": "not_in_game", "message": "⚠️ 你当前不在命运之轮游戏中，无法继续。"}

        is_awaiting = self._wof_pending_protection.get(user_id, False)
        prize = user.wof_current_prize if not is_awaiting else 0
        entry = user.wof_entry_fee
        if is_awaiting:
            extra, effect_id, effect_details = self._wof_failure_refund(user)
        else:
            extra, effect_id, effect_details = self._wof_success_bonus(
                user, prize, normal_settlement=True
            )
        self._reset_wof_state(user, cash_out_prize=prize + extra)

        if is_final_win:
            message = (f"🏆 [CQ:at,qq={user_id}] 命运的宠儿诞生了！ "
                       f"你成功征服了命运之轮的10层，最终赢得了 {prize} 金币的神话级奖励！")
        elif is_awaiting:
            message = (f"❌ [CQ:at,qq={user_id}] 你选择了放弃补救，挑战失败！ "
                       f"你失去了本局累计的所有金币，本次入场费 {entry} 金币已损失。")
        else:
            message = (f"✅ [CQ:at,qq={user_id}] 明智的选择！ "
                       f"你成功将 {prize} 金币带回了家，本次游戏净赚 {prize - entry} 金币。")
        if extra > 0:
            word = "返还" if is_awaiting else "额外结算"
            message += f"\n🎴 海克斯{word} {extra} 金币。"

        return {
            "success": True,
            "status": "cashed_out" if not is_awaiting else "failed",
            "message": message,
            "base_prize": prize,
            "hextech_bonus": extra,
            "hextech_effect_id": effect_id,
            "hextech_details": effect_details,
        }

    # ============================================================
    # ================== 新增功能：命运之轮 结束 ==================
    # ============================================================

    def get_wipe_bomb_history(self, user_id: str, limit: int = 10) -> Dict[str, Any]:
        """
        获取用户的擦弹历史记录。
        """
        logs = self.log_repo.get_wipe_bomb_logs(user_id, limit)
        return {
            "success": True,
            "logs": [
                {
                    "contribution": log.contribution_amount,
                    "multiplier": log.reward_multiplier,
                    "reward": log.reward_amount,
                    "timestamp": log.timestamp
                } for log in logs
            ]
        }

    def steal_fish(self, thief_id: str, victim_id: str) -> Dict[str, Any]:
        """
        处理"偷鱼"的逻辑。
        """
        if thief_id == victim_id:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="steal",
                success=False,
                details={"reason": "self_target"},
            )
            return {"success": False, "message": "不能偷自己的鱼！"}

        thief = self.user_repo.get_by_id(thief_id)
        if not thief:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="steal",
                success=False,
                details={"reason": "thief_not_found"},
            )
            return {"success": False, "message": "偷窃者用户不存在"}

        victim = self.user_repo.get_by_id(victim_id)
        if not victim:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="steal",
                success=False,
                details={"reason": "victim_not_found"},
            )
            return {"success": False, "message": "目标用户不存在"}

        # 0. 首先检查偷窃CD
        cooldown_seconds = self.config.get("steal", {}).get("cooldown_seconds", 14400) # 默认4小时
        now = get_now()
        steal_card = self._get_selected_hextech_card(thief_id)
        steal_effect = get_first_hextech_effect(
            steal_card, ("C21", "C22", "C23", "S11", "G11", "P11")
        )
        steal_effect_id = steal_effect.get("id") if steal_effect else None
        steal_params = get_hextech_effect_params(steal_effect)
        cooldown_seconds, cooldown_reduction = steal_cooldown(cooldown_seconds, steal_card)

        # 修复时区问题
        last_steal_time = thief.last_steal_time
        if last_steal_time and last_steal_time.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif last_steal_time and last_steal_time.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=last_steal_time.tzinfo)

        if last_steal_time and (now - last_steal_time).total_seconds() < cooldown_seconds:
            remaining = math.ceil(cooldown_seconds - (now - last_steal_time).total_seconds())
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="steal",
                success=False,
                details={"reason": "cooldown", "remaining_seconds": remaining},
            )
            return {"success": False, "message": f"偷鱼冷却中，请等待 {format_remaining_time(remaining)}后再试"}

        # ========== 守护海灵破盾机制（三段式）==========
        protection_buff = self.buff_repo.get_active_by_user_and_type(
            victim_id, "STEAL_PROTECTION_BUFF"
        )
        
        penetration_buff = self.buff_repo.get_active_by_user_and_type(
            thief_id, "STEAL_PENETRATION_BUFF"
        )
        shadow_cloak_buff = self.buff_repo.get_active_by_user_and_type(
            thief_id, "SHADOW_CLOAK_BUFF"
        )
        
        shield_broken = False  # 标志：本次攻击是否打破了盾
        notification_events = []
        
        if protection_buff:
            prot_payload = json.loads(protection_buff.payload or "{}")
            current_layers = prot_payload.get("layers", 1)
            max_layers = prot_payload.get("max_layers", 2)
            resist_chance = prot_payload.get("resist_chance", 0.05)
            break_threshold = prot_payload.get("break_threshold", 3)
            broken_steals = prot_payload.get("broken_steals", 0)
            old_payload_str = protection_buff.payload  # 乐观锁用
            
            if current_layers > 0:
                # Phase 1: 盾还在，需要穿透才能减层（但偷不到鱼）
                if not penetration_buff and not shadow_cloak_buff:
                    self._add_statistics_log(
                        user_id=thief_id,
                        target_id=victim_id,
                        action_type="steal",
                        success=False,
                        details={"reason": "protected", "layers": current_layers},
                    )
                    return {"success": False, "message": f"❌ 无法偷窃，【{victim.nickname}】的鱼塘被守护海灵保护着！"}
                
                # 抵抗判定
                if random.random() < resist_chance:
                    # 抵抗成功，暗影斗篷消耗1次
                    msg = f"🛡️ 守护海灵抵抗了你的穿透！（目标还剩 {current_layers} 层守护）"
                    if shadow_cloak_buff:
                        sc_payload = json.loads(shadow_cloak_buff.payload or "{}")
                        sc_charges = sc_payload.get("charges", 1) - 1
                        if sc_charges <= 0:
                            self.buff_repo.delete(shadow_cloak_buff.id)
                            msg += "\n🌑 暗影斗篷消耗了最后 1 次反制机会，已消失。"
                        else:
                            shadow_cloak_buff.payload = json.dumps({"charges": sc_charges})
                            self.buff_repo.update(shadow_cloak_buff)
                            msg += f"\n🌑 暗影斗篷消耗了 1 次反制机会（剩余 {sc_charges} 次）。"
                    self._add_statistics_log(
                        user_id=thief_id,
                        target_id=victim_id,
                        action_type="steal",
                        success=False,
                        details={"reason": "protection_resisted", "layers": current_layers},
                    )
                    return {"success": False, "message": msg}
                
                # 穿透成功：减层但仍挡偷
                old_layers = current_layers
                current_layers -= 1
                
                if current_layers > 0:
                    # 盾还在
                    new_payload = json.dumps({
                        "layers": current_layers,
                        "max_layers": max_layers,
                        "resist_chance": resist_chance,
                        "break_threshold": break_threshold,
                        "broken_steals": broken_steals,
                    })
                    updated = self.buff_repo.update_payload_if_match(
                        protection_buff.id, old_payload_str, new_payload, protection_buff.expires_at
                    )
                    if not updated:
                        self._add_statistics_log(
                            user_id=thief_id,
                            target_id=victim_id,
                            action_type="steal",
                            success=False,
                            details={"reason": "conflict"},
                        )
                        return {"success": False, "message": "⚠️ 操作冲突，请重试。"}
                    
                    # 消耗暗影斗篷
                    if shadow_cloak_buff:
                        sc_payload = json.loads(shadow_cloak_buff.payload or "{}")
                        sc_charges = sc_payload.get("charges", 1) - 1
                        if sc_charges <= 0:
                            self.buff_repo.delete(shadow_cloak_buff.id)
                        else:
                            shadow_cloak_buff.payload = json.dumps({"charges": sc_charges})
                            self.buff_repo.update(shadow_cloak_buff)
                    
                    counter_msg = "⚡ 破灵符的力量穿透了海灵守护！" if penetration_buff else "🌑 暗影斗篷让你在阴影中行动！"
                    notification_events.append(
                        {
                            "type": "protection_damaged",
                            "details": {
                                "old_layers": old_layers,
                                "new_layers": current_layers,
                                "layers_lost": old_layers - current_layers,
                            },
                        }
                    )
                    self._add_statistics_log(
                        user_id=thief_id,
                        target_id=victim_id,
                        action_type="steal",
                        success=False,
                        details={"reason": "shield_blocked", "remaining_layers": current_layers},
                    )
                    return {
                        "success": False,
                        "message": f"{counter_msg}\n但守护海灵挡住了你的偷窃！（目标还剩 {current_layers} 层守护）",
                        "notification_events": notification_events,
                    }
                else:
                    # 盾破了！
                    shield_broken = True
                    new_payload = json.dumps({
                        "layers": 0,
                        "max_layers": max_layers,
                        "resist_chance": resist_chance,
                        "break_threshold": break_threshold,
                        "broken_steals": 0,
                    })
                    updated = self.buff_repo.update_payload_if_match(
                        protection_buff.id, old_payload_str, new_payload, protection_buff.expires_at
                    )
                    if not updated:
                        self._add_statistics_log(
                            user_id=thief_id,
                            target_id=victim_id,
                            action_type="steal",
                            success=False,
                            details={"reason": "conflict"},
                        )
                        return {"success": False, "message": "⚠️ 操作冲突，请重试。"}
                    
                    # 消耗暗影斗篷
                    if shadow_cloak_buff:
                        sc_payload = json.loads(shadow_cloak_buff.payload or "{}")
                        sc_charges = sc_payload.get("charges", 1) - 1
                        if sc_charges <= 0:
                            self.buff_repo.delete(shadow_cloak_buff.id)
                        else:
                            shadow_cloak_buff.payload = json.dumps({"charges": sc_charges})
                            self.buff_repo.update(shadow_cloak_buff)
                    
                    counter_msg = "⚡ 破灵符的力量穿透了海灵守护！" if penetration_buff else "🌑 暗影斗篷让你在阴影中行动！"
                    notification_events.append(
                        {
                            "type": "protection_broken",
                            "details": {
                                "old_layers": old_layers,
                                "new_layers": 0,
                                "layers_lost": old_layers,
                            },
                        }
                    )
                    self._add_statistics_log(
                        user_id=thief_id,
                        target_id=victim_id,
                        action_type="steal",
                        success=False,
                        details={"reason": "shield_broken"},
                    )
                    return {
                        "success": False,
                        "message": f"{counter_msg}\n💥 守护海灵的护盾破碎了！鱼塘现在毫无防备！",
                        "notification_events": notification_events,
                    }
            else:
                # Phase 2: 盾已破（layers == 0），可以偷鱼
                pass  # 继续往下走到偷鱼逻辑
        
        # ========== 守护海灵机制结束 ==========

        # 2. 检查受害者是否有鱼可偷
        victim_inventory = self.inventory_repo.get_fish_inventory(victim_id)
        if not victim_inventory:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="steal",
                success=False,
                details={"reason": "empty_pond"},
            )
            return {"success": False, "message": f"目标用户【{victim.nickname}】的鱼塘是空的！"}

        # 3. 随机选择一条鱼偷取
        victim_coins_chance = get_user_coins_chance_by_repo(
            self.inventory_repo, self.item_template_repo, victim_id
        )
        steal_values = []
        steal_templates = []
        for inventory_item in victim_inventory:
            template = self.item_template_repo.get_fish_by_id(inventory_item.fish_id)
            steal_templates.append(template)
            if template:
                value = self._social_fish_unit_value(inventory_item, template, victim_coins_chance)
            else:
                value = 0
            steal_values.append(float(value))

        base_value_ev = sum(steal_values) / len(steal_values)
        configured_chance = self._hextech_chance_ceiling(steal_params)
        budget = self._hextech_budget(steal_card, steal_params)
        effective_chance = 0.0
        target_indexes = []
        ev_gain_per_trigger = 0.0
        if steal_effect_id == "C21":
            ev_gain_per_trigger = expected_best_value(steal_values, 2) - base_value_ev
        elif steal_effect_id == "C22":
            upgraded_values = []
            for inventory_item, template, base_value in zip(
                victim_inventory, steal_templates, steal_values
            ):
                if template and int(inventory_item.quality_level) == 0:
                    upgraded_values.append(base_value * 2)
                else:
                    upgraded_values.append(base_value)
            ev_gain_per_trigger = sum(
                max(0.0, upgraded - base)
                for upgraded, base in zip(upgraded_values, steal_values)
            ) / len(steal_values)
        elif steal_effect_id == "S11":
            ranked_indexes = sorted(range(len(steal_values)), key=lambda index: steal_values[index])
            target_indexes = ranked_indexes[:max(1, int(math.ceil(len(ranked_indexes) * 0.25)))]
            ev_gain_per_trigger = expected_conditional_reroll_gain(steal_values, target_indexes)
        elif steal_effect_id == "G11":
            ev_gain_per_trigger = expected_best_value(steal_values, 3) - base_value_ev
        elif steal_effect_id == "P11":
            rarities = [getattr(template, "rarity", 0) if template else 0 for template in steal_templates]
            highest_rarity = max(rarities or [0])
            target_indexes = [index for index, rarity in enumerate(rarities) if rarity == highest_rarity]
            if target_indexes:
                target_mean = sum(steal_values[index] for index in target_indexes) / len(target_indexes)
                ev_gain_per_trigger = target_mean - base_value_ev

        if steal_effect_id in ("C21", "C22", "S11", "G11", "P11"):
            effective_chance = budgeted_chance(
                base_value_ev,
                max(0.0, ev_gain_per_trigger),
                budget,
                configured_chance,
            )

        selected_index = victim_inventory.index(random.choice(victim_inventory))
        baseline_selected_value = steal_values[selected_index]
        upgraded_steal = False
        if steal_effect_id == "C21" and effective_chance > 0 and random.random() < effective_chance:
            candidate = victim_inventory.index(random.choice(victim_inventory))
            if steal_values[candidate] > steal_values[selected_index]:
                selected_index = candidate
        elif steal_effect_id == "C22" and effective_chance > 0 and random.random() < effective_chance:
            selected_item = victim_inventory[selected_index]
            selected_template = steal_templates[selected_index]
            if selected_template and int(selected_item.quality_level) == 0:
                upgraded_value = steal_values[selected_index] * 2
                if upgraded_value > steal_values[selected_index]:
                    # Keep the original inventory key for removal and store the
                    # upgraded quality only for the thief's received fish.
                    upgraded_steal = True

        if steal_effect_id == "S11" and selected_index in target_indexes and effective_chance > 0 and random.random() < effective_chance:
            candidate = victim_inventory.index(random.choice(victim_inventory))
            if steal_values[candidate] > steal_values[selected_index]:
                selected_index = candidate
        elif steal_effect_id == "G11" and effective_chance > 0 and random.random() < effective_chance:
            for _ in range(2):
                candidate = victim_inventory.index(random.choice(victim_inventory))
                if steal_values[candidate] > steal_values[selected_index]:
                    selected_index = candidate
        elif steal_effect_id == "P11" and target_indexes and effective_chance > 0 and random.random() < effective_chance:
            selected_index = random.choice(target_indexes)

        stolen_fish_item = victim_inventory[selected_index]
        stolen_fish_template = self.item_template_repo.get_fish_by_id(stolen_fish_item.fish_id)

        if not stolen_fish_template:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="steal",
                success=False,
                details={
                    "reason": "fish_template_not_found",
                    "fish_id": stolen_fish_item.fish_id,
                },
            )
            return {"success": False, "message": "发生内部错误，无法识别被偷的鱼"}

        # 4. 保留鱼塘已保存的单价。操作者的品质升级只增加接收价值。
        victim_loss_value = int(steal_values[selected_index])
        transfer_value = victim_loss_value * (2 if upgraded_steal else 1)

        # 5. 执行偷窃事务（保持品质与结算单价）
        self.inventory_repo.update_fish_quantity(
            victim_id,
            stolen_fish_item.fish_id,
            delta=-1,
            quality_level=stolen_fish_item.quality_level,
            unit_value=stolen_fish_item.unit_value,
        )
        self.inventory_repo.add_fish_to_inventory(
            thief_id,
            stolen_fish_item.fish_id,
            quantity=1,
            quality_level=1 if upgraded_steal else stolen_fish_item.quality_level,
            unit_value=transfer_value,
        )

        # 6. 更新偷窃者的CD时间
        thief.last_steal_time = now
        self.user_repo.update(thief)

        # ========== 盾破后配额计数与恢复 ==========
        shield_recovery_msg = ""
        if protection_buff:
            prot_payload = json.loads(protection_buff.payload or "{}")
            current_layers = prot_payload.get("layers", 0)
            
            if current_layers == 0:
                # 盾破状态，计数 +1
                max_layers = prot_payload.get("max_layers", 2)
                resist_chance = prot_payload.get("resist_chance", 0.05)
                break_threshold = prot_payload.get("break_threshold", 3)
                broken_steals = prot_payload.get("broken_steals", 0) + 1
                
                if broken_steals >= break_threshold:
                    # 配额用完，恢复满层
                    new_payload = json.dumps({
                        "layers": max_layers,
                        "max_layers": max_layers,
                        "resist_chance": resist_chance,
                        "break_threshold": break_threshold,
                        "broken_steals": 0,
                    })
                    old_payload_str = protection_buff.payload
                    updated = self.buff_repo.update_payload_if_match(
                        protection_buff.id, old_payload_str, new_payload, protection_buff.expires_at
                    )
                    if not updated:
                        # 并发冲突，退化为普通更新（数据最终一致）
                        protection_buff.payload = new_payload
                        self.buff_repo.update(protection_buff)
                    shield_recovery_msg = "\n🛡️ 守护海灵恢复了力量！鱼塘重新被守护。"
                    notification_events.append(
                        {
                            "type": "protection_restored",
                            "details": {
                                "layers_restored": max_layers,
                                "new_layers": max_layers,
                            },
                        }
                    )
                else:
                    # 更新 broken_steals
                    new_payload = json.dumps({
                        "layers": 0,
                        "max_layers": max_layers,
                        "resist_chance": resist_chance,
                        "break_threshold": break_threshold,
                        "broken_steals": broken_steals,
                    })
                    old_payload_str = protection_buff.payload
                    updated = self.buff_repo.update_payload_if_match(
                        protection_buff.id, old_payload_str, new_payload, protection_buff.expires_at
                    )
                    if not updated:
                        # 并发冲突，退化为普通更新（数据最终一致）
                        protection_buff.payload = new_payload
                        self.buff_repo.update(protection_buff)
                    remaining = break_threshold - broken_steals
                    shield_recovery_msg = f"\n💥 守护海灵护盾已碎！还可偷 {remaining} 次后恢复。"
            elif shield_broken:
                # 刚破盾的情况（本次穿透成功减层至0），无需额外计数
                pass
        # ========== 盾破计数结束（steal_fish）==========
        # 7. 生成成功消息。转移后的鱼保留原入塘单价。
        # 构建品质信息
        delivered_quality = 1 if upgraded_steal else stolen_fish_item.quality_level
        quality_info = "（✨高品质）" if delivered_quality == 1 else ""
        actual_hextech_value_gain = max(0, transfer_value - baseline_selected_value)
        hextech_message = ""
        if steal_effect_id == "C23" and cooldown_reduction > 0:
            hextech_message = f"\n🎴 海克斯缩短偷鱼冷却 {cooldown_reduction * 100:.1f}%（{cooldown_seconds} 秒）。"
        elif actual_hextech_value_gain > 0:
            hextech_message = (
                f"\n🎴 海克斯择优生效，转移价值增加 {actual_hextech_value_gain} 金币。"
                if not upgraded_steal else
                f"\n🎴 海克斯将这条鱼提升为高品质，增加 {actual_hextech_value_gain} 金币价值。"
            )

        # 写入偷鱼统计日志（记录转移鱼的固定结算价值）
        self._add_statistics_log(
            user_id=thief_id,
            target_id=victim_id,
            action_type="steal",
            success=True,
            fish_count=1,
            coin_amount=transfer_value,
            details={
                "fish_id": stolen_fish_item.fish_id,
                "fish_name": stolen_fish_template.name,
                "rarity": stolen_fish_template.rarity,
                "quality_level": delivered_quality,
                "value": transfer_value,
                "victim_value": victim_loss_value,
                "hextech_effect_id": steal_effect_id,
                "hextech_effect": {
                    "chance": effective_chance,
                    "cooldown_reduction": cooldown_reduction,
                    "expected_gain_per_trigger": ev_gain_per_trigger,
                    "delivered_quality_upgrade": upgraded_steal,
                    "actual_value_gain": actual_hextech_value_gain,
                } if steal_effect_id else None,
            },
        )

        if steal_effect_id:
            self._log_hextech_change(
                "steal_fish",
                thief_id,
                steal_effect_id,
                {
                    "effective_chance": effective_chance,
                    "expected_gain_per_trigger": ev_gain_per_trigger,
                    "cooldown_reduction": cooldown_reduction,
                    "cooldown_seconds": cooldown_seconds,
                    "fish_id": stolen_fish_item.fish_id,
                    "delivered_quality": delivered_quality,
                    "transfer_value": transfer_value,
                    "actual_value_gain": actual_hextech_value_gain,
                },
            )

        return {
            "success": True,
            "message": f"✅ 成功从【{victim.nickname}】的鱼塘里偷到了一条{stolen_fish_template.rarity}★【{stolen_fish_template.name}】{quality_info}！价值 {transfer_value} 金币{shield_recovery_msg}{hextech_message}",
            "thief_nickname": thief.nickname or thief.user_id,
            "victim_notification": {
                "stolen_fish_name": stolen_fish_template.name,
                "rarity": stolen_fish_template.rarity,
                "quality_level": stolen_fish_item.quality_level,
                "value": victim_loss_value,
            },
            "hextech_effect_id": steal_effect_id,
            "hextech_effect_chance": effective_chance,
            "hextech_bonus_value": actual_hextech_value_gain,
            "notification_events": notification_events,
        }

    # ============================================================
    # ==================== 新增功能：电鱼 开始 ====================
    # ============================================================
    def _consume_electric_fish_success_boost(self, user_id: str) -> Dict[str, Any]:
        """原子消耗一次电鱼成功率 Buff，返回本次实际生效的加成。"""
        result = {
            "bonus_rate": 0.0,
            "max_rate": 1.0,
            "fish_count_multiplier": 1.0,
            "consumed": False,
        }
        buff = self.buff_repo.get_active_by_user_and_type(
            user_id, "ELECTRIC_FISH_SUCCESS_BOOST"
        )
        if not buff:
            return result

        try:
            payload = json.loads(buff.payload or "{}")
            bonus_rate = float(payload.get("bonus_rate", 0.0))
            max_rate = float(payload.get("max_rate", 1.0))
            fish_count_multiplier = float(
                payload.get("fish_count_multiplier", 1.0)
            )
        except (TypeError, ValueError, json.JSONDecodeError):
            return result

        if bonus_rate <= 0 or fish_count_multiplier < 1.0:
            return result

        bonus_rate = min(1.0, bonus_rate)
        max_rate = min(1.0, max(0.0, max_rate))
        fish_count_multiplier = max(1.0, fish_count_multiplier)

        consumed = self.buff_repo.consume_charge_if_match(
            buff.id, buff.payload, None
        )
        if consumed:
            result.update(
                {
                    "bonus_rate": bonus_rate,
                    "max_rate": max_rate,
                    "fish_count_multiplier": fish_count_multiplier,
                    "consumed": True,
                }
            )
        return result

    def electric_fish(self, thief_id: str, victim_id: str) -> Dict[str, Any]:
        """
        处理"电鱼"的逻辑。
        - 基础成功率，受多种因素影响
        - 失败会扣除金币作为设备损坏费
        - 成功有三个档次：大成功、普通成功、小成功
        - 对鱼塘内鱼数>=100的目标随机偷取
        - 其中最多只能包含一条5星及以上的鱼
        """
        if thief_id == victim_id:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="electric_fish",
                success=False,
                details={"reason": "self_target"},
            )
            return {"success": False, "message": "不能电自己的鱼！"}
    
        thief = self.user_repo.get_by_id(thief_id)
        if not thief:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="electric_fish",
                success=False,
                details={"reason": "user_not_found"},
            )
            return {"success": False, "message": "使用者用户不存在"}
    
        victim = self.user_repo.get_by_id(victim_id)
        if not victim:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="electric_fish",
                success=False,
                details={"reason": "victim_not_found"},
            )
            return {"success": False, "message": "目标用户不存在"}
    
        # 0. 检查电鱼CD
        cooldown_seconds = self.config.get("electric_fish", {}).get("cooldown_seconds", 7200) # 默认2小时
        now = get_now()
    
        last_electric_fish_time = thief.last_electric_fish_time
        if last_electric_fish_time and last_electric_fish_time.tzinfo is None and now.tzinfo is not None:
            now = now.replace(tzinfo=None)
        elif last_electric_fish_time and last_electric_fish_time.tzinfo is not None and now.tzinfo is None:
            now = now.replace(tzinfo=last_electric_fish_time.tzinfo)
    
        if last_electric_fish_time and (now - last_electric_fish_time).total_seconds() < cooldown_seconds:
            remaining = math.ceil(cooldown_seconds - (now - last_electric_fish_time).total_seconds())
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="electric_fish",
                success=False,
                details={"reason": "cooldown", "remaining_seconds": remaining},
            )
            return {"success": False, "message": f"电鱼冷却中，请等待 {format_remaining_time(remaining)}后再试"}
    
        # ========== 守护海灵破盾机制（三段式）==========
        notification_events = []
        protection_buff = self.buff_repo.get_active_by_user_and_type(
            victim_id, "STEAL_PROTECTION_BUFF"
        )
        
        penetration_buff = self.buff_repo.get_active_by_user_and_type(
            thief_id, "STEAL_PENETRATION_BUFF"
        )
        shadow_cloak_buff = self.buff_repo.get_active_by_user_and_type(
            thief_id, "SHADOW_CLOAK_BUFF"
        )
        
        if protection_buff:
            prot_payload = json.loads(protection_buff.payload or "{}")
            current_layers = prot_payload.get("layers", 1)
            max_layers = prot_payload.get("max_layers", 2)
            resist_chance = prot_payload.get("resist_chance", 0.05)
            break_threshold = prot_payload.get("break_threshold", 3)
            broken_steals = prot_payload.get("broken_steals", 0)
            old_payload_str = protection_buff.payload  # 乐观锁用
            
            if current_layers > 0:
                # Phase 1: 盾还在，需要穿透才能减层（但电不到鱼）
                if not penetration_buff and not shadow_cloak_buff:
                    self._add_statistics_log(
                        user_id=thief_id,
                        target_id=victim_id,
                        action_type="electric_fish",
                        success=False,
                        details={"reason": "protected", "layers": current_layers},
                    )
                    return {"success": False, "message": f"❌ 无法电鱼，【{victim.nickname}】的鱼塘被守护海灵保护着！"}
                
                # 抵抗判定
                if random.random() < resist_chance:
                    # 抵抗成功，暗影斗篷消耗1次
                    msg = f"🛡️ 守护海灵抵抗了你的穿透！（目标还剩 {current_layers} 层守护）"
                    if shadow_cloak_buff:
                        sc_payload = json.loads(shadow_cloak_buff.payload or "{}")
                        sc_charges = sc_payload.get("charges", 1) - 1
                        if sc_charges <= 0:
                            self.buff_repo.delete(shadow_cloak_buff.id)
                            msg += "\n🌑 暗影斗篷消耗了最后 1 次反制机会，已消失。"
                        else:
                            shadow_cloak_buff.payload = json.dumps({"charges": sc_charges})
                            self.buff_repo.update(shadow_cloak_buff)
                            msg += f"\n🌑 暗影斗篷消耗了 1 次反制机会（剩余 {sc_charges} 次）。"
                    self._add_statistics_log(
                        user_id=thief_id,
                        target_id=victim_id,
                        action_type="electric_fish",
                        success=False,
                        details={"reason": "protection_resisted", "layers": current_layers},
                    )
                    return {"success": False, "message": msg}
                
                # 穿透成功：减层但仍挡电
                old_layers = current_layers
                current_layers -= 1
                
                if current_layers > 0:
                    # 盾还在
                    new_payload = json.dumps({
                        "layers": current_layers,
                        "max_layers": max_layers,
                        "resist_chance": resist_chance,
                        "break_threshold": break_threshold,
                        "broken_steals": broken_steals,
                    })
                    updated = self.buff_repo.update_payload_if_match(
                        protection_buff.id, old_payload_str, new_payload, protection_buff.expires_at
                    )
                    if not updated:
                        self._add_statistics_log(
                            user_id=thief_id,
                            target_id=victim_id,
                            action_type="electric_fish",
                            success=False,
                            details={"reason": "conflict"},
                        )
                        return {"success": False, "message": "⚠️ 操作冲突，请重试。"}
                    
                    # 消耗暗影斗篷
                    if shadow_cloak_buff:
                        sc_payload = json.loads(shadow_cloak_buff.payload or "{}")
                        sc_charges = sc_payload.get("charges", 1) - 1
                        if sc_charges <= 0:
                            self.buff_repo.delete(shadow_cloak_buff.id)
                        else:
                            shadow_cloak_buff.payload = json.dumps({"charges": sc_charges})
                            self.buff_repo.update(shadow_cloak_buff)
                    
                    counter_msg = "⚡ 破灵符的力量穿透了海灵守护！" if penetration_buff else "🌑 暗影斗篷让你在阴影中行动！"
                    notification_events.append(
                        {
                            "type": "protection_damaged",
                            "details": {
                                "old_layers": old_layers,
                                "new_layers": current_layers,
                                "layers_lost": old_layers - current_layers,
                            },
                        }
                    )
                    self._add_statistics_log(
                        user_id=thief_id,
                        target_id=victim_id,
                        action_type="electric_fish",
                        success=False,
                        details={"reason": "shield_blocked", "remaining_layers": current_layers},
                    )
                    return {
                        "success": False,
                        "message": f"{counter_msg}\n但守护海灵挡住了你的电鱼！（目标还剩 {current_layers} 层守护）",
                        "notification_events": notification_events,
                    }
                else:
                    # 盾破了！
                    shield_broken = True
                    new_payload = json.dumps({
                        "layers": 0,
                        "max_layers": max_layers,
                        "resist_chance": resist_chance,
                        "break_threshold": break_threshold,
                        "broken_steals": 0,
                    })
                    updated = self.buff_repo.update_payload_if_match(
                        protection_buff.id, old_payload_str, new_payload, protection_buff.expires_at
                    )
                    if not updated:
                        self._add_statistics_log(
                            user_id=thief_id,
                            target_id=victim_id,
                            action_type="electric_fish",
                            success=False,
                            details={"reason": "conflict"},
                        )
                        return {"success": False, "message": "⚠️ 操作冲突，请重试。"}
                    
                    # 消耗暗影斗篷
                    if shadow_cloak_buff:
                        sc_payload = json.loads(shadow_cloak_buff.payload or "{}")
                        sc_charges = sc_payload.get("charges", 1) - 1
                        if sc_charges <= 0:
                            self.buff_repo.delete(shadow_cloak_buff.id)
                        else:
                            shadow_cloak_buff.payload = json.dumps({"charges": sc_charges})
                            self.buff_repo.update(shadow_cloak_buff)
                    
                    counter_msg = "⚡ 破灵符的力量穿透了海灵守护！" if penetration_buff else "🌑 暗影斗篷让你在阴影中行动！"
                    notification_events.append(
                        {
                            "type": "protection_broken",
                            "details": {
                                "old_layers": old_layers,
                                "new_layers": 0,
                                "layers_lost": old_layers,
                            },
                        }
                    )
                    self._add_statistics_log(
                        user_id=thief_id,
                        target_id=victim_id,
                        action_type="electric_fish",
                        success=False,
                        details={"reason": "shield_broken"},
                    )
                    return {
                        "success": False,
                        "message": f"{counter_msg}\n💥 守护海灵的护盾破碎了！鱼塘现在毫无防备！",
                        "notification_events": notification_events,
                    }
            else:
                # Phase 2: 盾已破（layers == 0），可以电鱼
                pass  # 继续往下走到电鱼逻辑
        
        # ========== 守护海灵机制结束 ==========

        # 2. 检查受害者鱼塘数量是否达标
        victim_inventory = self.inventory_repo.get_fish_inventory(victim_id)
        if not victim_inventory:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="electric_fish",
                success=False,
                details={"reason": "empty_pond"},
            )
            return {"success": False, "message": f"目标用户【{victim.nickname}】的鱼塘是空的！"}
        
        total_fish_count = sum(item.quantity for item in victim_inventory)
        if total_fish_count < 100:
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="electric_fish",
                success=False,
                details={"reason": "not_enough_fish", "fish_count": total_fish_count},
            )
            return {"success": False, "message": f"目标用户【{victim.nickname}】的鱼塘里鱼太少了（{total_fish_count}/100），电不到什么好东西，还是放过他吧。"}

        fish_templates = None
        victim_coins_chance = None
        electric_population = []
        electric_unit_values = {}

        # 3. 计算成功率并进行判定
        # 道具只在通过所有前置检查、即将进行有效随机判定时消耗。
        try:
            base_success_rate = float(
                self.config.get("electric_fish", {}).get(
                    "base_success_rate", 0.6
                )
            )
        except (TypeError, ValueError):
            base_success_rate = 0.6
        base_success_rate = min(1.0, max(0.0, base_success_rate))
        boost = self._consume_electric_fish_success_boost(thief_id)
        final_success_rate = min(
            boost["max_rate"],
            max(0.0, base_success_rate + boost["bonus_rate"]),
        )
        boost_message = (
            f"（电鱼道具：成功率 +{boost['bonus_rate'] * 100:.1f}%"
            f"，鱼量 ×{boost['fish_count_multiplier']:.2f}）"
            if boost["consumed"]
            else ""
        )

        electric_card = self._get_selected_hextech_card(thief_id)
        electric_effect = get_first_hextech_effect(
            electric_card, ("C24", "C25", "C26", "S12", "G12", "P12")
        )
        electric_effect_id = electric_effect.get("id") if electric_effect else None
        electric_params = get_hextech_effect_params(electric_effect)
        electric_budget = self._hextech_budget(electric_card, electric_params)
        electric_chance = self._hextech_chance_ceiling(electric_params)
        electric_boost_multiplier = boost["fish_count_multiplier"] if boost["consumed"] else 1.0
        if electric_effect_id:
            fish_templates = {
                item.fish_id: self.item_template_repo.get_fish_by_id(item.fish_id)
                for item in victim_inventory
            }
            victim_coins_chance = get_user_coins_chance_by_repo(
                self.inventory_repo, self.item_template_repo, victim_id
            )
            electric_population, electric_unit_values = self._electric_fish_population(
                victim_inventory, fish_templates, victim_coins_chance
            )
            expected_by_quality = expected_electric_success_values(
                electric_population, total_fish_count, electric_boost_multiplier
            )
        else:
            expected_by_quality = {"great": 0.0, "normal": 0.0, "small": 0.0}
        expected_success_value = (
            0.3 * expected_by_quality["great"]
            + 0.4 * expected_by_quality["normal"]
            + 0.3 * expected_by_quality["small"]
        )
        electric_config = self.config.get("electric_fish", {})
        try:
            max_penalty_rate = max(0.0, float(electric_config.get("failure_penalty_max_rate", 0.5)))
        except (TypeError, ValueError):
            max_penalty_rate = 0.5
        expected_failure_penalty = max(0, thief.coins) * max_penalty_rate / 2.0
        electric_absolute_flow = (
            final_success_rate * expected_success_value
            + (1.0 - final_success_rate) * expected_failure_penalty
        )

        electric_proc_chance = 0.0
        electric_effect_fraction = 0.0
        electric_bonus_chance = 0.0
        if electric_effect_id == "C24":
            retry_gain_per_proc = (
                (1.0 - final_success_rate)
                * final_success_rate
                * (expected_success_value + expected_failure_penalty)
            )
            electric_proc_chance = budgeted_chance(
                electric_absolute_flow,
                retry_gain_per_proc,
                electric_budget,
                electric_chance,
            )
        elif electric_effect_id == "C25":
            requested_fraction = clamp_hextech_value(electric_params.get("fraction", 0.0))
            expected_penalty_flow = (1.0 - final_success_rate) * expected_failure_penalty
            allowed_fraction = (
                electric_budget * electric_absolute_flow / expected_penalty_flow
                if expected_penalty_flow > 0 else 0.0
            )
            electric_effect_fraction = min(requested_fraction, allowed_fraction)
        elif electric_effect_id == "C26":
            electric_bonus_chance = electric_chance
            requested_fraction = clamp_hextech_value(
                electric_params.get("fraction", electric_params.get("price_fraction", 0.0))
            )
            expected_reward_flow = final_success_rate * expected_success_value
            allowed_fraction = (
                electric_budget * electric_absolute_flow / expected_reward_flow
                if expected_reward_flow > 0 else 0.0
            )
            electric_effect_fraction = min(requested_fraction, allowed_fraction)
        elif electric_effect_id in ("S12", "P12"):
            if electric_effect_id == "S12":
                gain_per_proc = (
                    final_success_rate * 0.3
                    * max(0.0, expected_by_quality["normal"] - expected_by_quality["small"])
                )
            else:
                gain_per_proc = final_success_rate * (
                    0.3 * max(0.0, expected_by_quality["normal"] - expected_by_quality["small"])
                    + 0.4 * max(0.0, expected_by_quality["great"] - expected_by_quality["normal"])
                )
            electric_proc_chance = budgeted_chance(
                electric_absolute_flow, gain_per_proc, electric_budget, electric_chance
            )
        
        # 进行随机判定
        roll = random.random()
        electric_hextech_retry = False
        electric_hextech_retry_attempted = False
        if (
            electric_effect_id == "C24"
            and (final_success_rate <= 0.0 or roll > final_success_rate)
            and electric_proc_chance > 0
            and random.random() < electric_proc_chance
        ):
            electric_hextech_retry_attempted = True
            retry_roll = random.random()
            if retry_roll <= final_success_rate:
                roll = retry_roll
                electric_hextech_retry = True
        
        # 失败处理
        if final_success_rate <= 0.0 or roll > final_success_rate:
            # 使用正态分布计算天罚百分比（0-max_rate之间）
            # 正态分布，均值在中间（max_rate/2），标准差使得95%的值在0到max_rate之间
            mean = max_penalty_rate / 2
            std_dev = max_penalty_rate / 4  # 约95%的值在[0, max_rate]之间
            
            # 使用random.gauss生成正态分布的惩罚比例，并限制在[0, max_rate]范围内
            penalty_rate = random.gauss(mean, std_dev)
            penalty_rate = max(0.0, min(max_penalty_rate, penalty_rate))
            
            # 计算实际扣除的金币
            raw_penalty_coins = int(thief.coins * penalty_rate)
            penalty_reduction = 0
            if electric_effect_id == "C25" and electric_effect_fraction > 0:
                penalty_reduction = min(
                    raw_penalty_coins,
                    int(raw_penalty_coins * electric_effect_fraction),
                )
            penalty_coins = raw_penalty_coins - penalty_reduction
            
            thief.coins -= penalty_coins
            thief.last_electric_fish_time = now  # 失败也要更新CD
            self.user_repo.update(thief)
            
            # 根据惩罚程度显示不同的消息（动态基于配置的最大天罚）
            # 轻微: 0-20%的max, 中度: 20-50%的max, 严重: 50-80%的max, 毁灭性: 80-100%的max
            relative_penalty = penalty_rate / max_penalty_rate if max_penalty_rate > 0 else 0
            if relative_penalty < 0.2:
                severity = "⚡ 轻微天罚"
            elif relative_penalty < 0.5:
                severity = "⚡⚡ 中度天罚"
            elif relative_penalty < 0.8:
                severity = "⚡⚡⚡ 严重天罚"
            else:
                severity = "⚡⚡⚡⚡ 毁灭性天罚"
            
            # 写入电鱼失败统计日志
            self._add_statistics_log(
                user_id=thief_id,
                target_id=victim_id,
                action_type="electric_fish",
                success=False,
                fish_count=0,
                details={
                    "reason": "random_failed",
                    "penalty_rate": penalty_rate,
                    "penalty_coins": penalty_coins,
                    "base_success_rate": base_success_rate,
                    "bonus_success_rate": boost["bonus_rate"],
                    "fish_count_multiplier": boost["fish_count_multiplier"],
                    "boost_consumed": boost["consumed"],
                    "success_rate": final_success_rate,
                    "hextech_effect_id": electric_effect_id,
                    "hextech_retry_attempted": electric_hextech_retry_attempted,
                    "hextech_retry_saved": electric_hextech_retry,
                    "hextech_penalty_reduction": penalty_reduction,
                    "hextech_effect_chance": electric_proc_chance,
                    "hextech_effect_fraction": electric_effect_fraction,
                },
            )

            if electric_effect_id and (electric_hextech_retry or penalty_reduction > 0):
                self._log_hextech_change(
                    "electric_fish",
                    thief_id,
                    electric_effect_id,
                    {
                        "retry_attempted": electric_hextech_retry_attempted,
                        "retry_saved": electric_hextech_retry,
                        "retry_chance": electric_proc_chance,
                        "raw_penalty": raw_penalty_coins,
                        "penalty_reduction": penalty_reduction,
                        "final_penalty": penalty_coins,
                        "fraction": electric_effect_fraction,
                    },
                )

            return {
                "success": False,
                "message": f"❌ 电鱼失败！{severity}降临，雷电击中了你，损失了 {penalty_coins} 金币（{penalty_rate*100:.1f}%）！\n💡 本次成功率为 {final_success_rate*100:.1f}%{boost_message}"
                + (f"\n🎴 海克斯重新判定后仍失败。" if electric_hextech_retry_attempted else "")
                + (f"\n🎴 海克斯减免天罚 {penalty_reduction} 金币。" if penalty_reduction > 0 else ""),
                "hextech_effect_id": electric_effect_id,
                "hextech_retry_saved": electric_hextech_retry,
                "hextech_penalty_reduction": penalty_reduction,
                "hextech_effect_chance": electric_proc_chance,
            }

        # 4. 成功了！根据成功度（roll值）决定收益档次
        # roll越接近0表示越幸运，获得的收益越高
        success_quality = roll / final_success_rate  # 归一化到0-1之间
        electric_hextech_grade_upgraded = False
        if electric_effect_id in ("S12", "P12") and electric_proc_chance > 0:
            if (
                (electric_effect_id == "S12" and success_quality > 0.7)
                or (electric_effect_id == "P12" and success_quality > 0.3)
            ) and random.random() < electric_proc_chance:
                success_quality = 0.5 if success_quality > 0.7 else 0.15
                electric_hextech_grade_upgraded = True
        
        # 分段式收益：
        # - 大成功（0-0.3）：15%-20%的鱼
        # - 普通成功（0.3-0.7）：10%-15%的鱼
        # - 小成功（0.7-1.0）：5%-10%的鱼
        success_type = ""
        multiplier_range = (0, 0)
        
        if success_quality <= 0.3:
            success_type = "⭐大成功"
            multiplier_range = (0.15, 0.20)
        elif success_quality <= 0.7:
            success_type = "✅普通成功"
            multiplier_range = (0.10, 0.15)
        else:
            success_type = "🔹小成功"
            multiplier_range = (0.05, 0.10)
        
        # 5. 准备抽取数据。无海克斯卡时保持原有成功结算的读取路径。
        if fish_templates is None:
            fish_templates = {
                item.fish_id: self.item_template_repo.get_fish_by_id(item.fish_id)
                for item in victim_inventory
            }
        if victim_coins_chance is None:
            victim_coins_chance = get_user_coins_chance_by_repo(
                self.inventory_repo, self.item_template_repo, victim_id
            )
        all_fish_in_pond = []
        for item in victim_inventory:
            all_fish_in_pond.extend([(item.fish_id, item.quality_level, int(getattr(item, "unit_value", 0) or 0))] * item.quantity)

        # 6. 决定偷取数量并进行初次完全随机抽样
        num_to_steal = 0
        if total_fish_count > 400:
            # 如果鱼数大于400，按成功档次的百分比计算
            lower_bound = max(1, int(total_fish_count * multiplier_range[0]))
            upper_bound = max(lower_bound, int(total_fish_count * multiplier_range[1]))
            num_to_steal = random.randint(lower_bound, upper_bound)
        else:
            # 鱼数较少时，使用固定数量区间
            if success_quality <= 0.3:
                num_to_steal = random.randint(20, 30)  # 大成功
            elif success_quality <= 0.7:
                num_to_steal = random.randint(10, 20)  # 普通成功
            else:
                num_to_steal = random.randint(5, 10)   # 小成功

        if boost["consumed"]:
            num_to_steal = max(
                1, int(num_to_steal * boost["fish_count_multiplier"])
            )

        actual_num_to_steal = min(num_to_steal, len(all_fish_in_pond))
        initial_catch = random.sample(all_fish_in_pond, actual_num_to_steal)

        # 7. 检查并修正高星鱼数量（保留品质）
        high_rarity_caught = []
        low_rarity_caught = []
        for fish_tuple in initial_catch:
            fish_id, q_level, _unit_value = fish_tuple
            template = fish_templates.get(fish_id)
            if template and template.rarity >= 5:
                high_rarity_caught.append(fish_tuple)
            else:
                low_rarity_caught.append(fish_tuple)

        final_stolen_fish = []
        if len(high_rarity_caught) <= 1:
            final_stolen_fish = initial_catch
        else:
            random.shuffle(high_rarity_caught)
            final_stolen_fish.append(high_rarity_caught.pop(0))
            final_stolen_fish.extend(low_rarity_caught)

            num_to_replace = len(high_rarity_caught)

            pond_counts = Counter(all_fish_in_pond)
            initial_catch_counts = Counter(initial_catch)
            pond_counts.subtract(initial_catch_counts)

            replacement_pool = []
            for fish_tuple, count in pond_counts.items():
                if count > 0:
                    template = fish_templates.get(fish_tuple[0])
                    if template and template.rarity < 5:
                        replacement_pool.extend([fish_tuple] * count)

            if replacement_pool:
                num_can_replace = min(num_to_replace, len(replacement_pool))
                replacements = random.sample(replacement_pool, num_can_replace)
                final_stolen_fish.extend(replacements)

        # G12只替换一条鱼，不增加数量；候选来自目标鱼塘的剩余库存，
        # 且最终批次仍遵守每批最多一条5星及以上鱼。
        g12_bonus_value = 0.0
        if electric_effect_id == "G12" and final_stolen_fish:
            current_counts = Counter(final_stolen_fish)
            remaining_counts = Counter(all_fish_in_pond)
            remaining_counts.subtract(current_counts)
            caught_high_count = sum(
                count for (fish_id, _quality, _unit_value), count in current_counts.items()
                if fish_templates.get(fish_id)
                and getattr(fish_templates[fish_id], "rarity", 0) >= 5
            )
            candidates = []
            for fish_tuple, count in remaining_counts.items():
                if count <= 0:
                    continue
                template = fish_templates.get(fish_tuple[0])
                is_high = bool(template and getattr(template, "rarity", 0) >= 5)
                if caught_high_count >= 1 and is_high:
                    continue
                candidates.extend([fish_tuple] * count)
            actual_values = list(electric_unit_values.values())
            if candidates and actual_values:
                minimum_value = min(
                    electric_unit_values.get(fish_tuple, 0.0)
                    for fish_tuple in final_stolen_fish
                )
                maximum_pool_value = max(actual_values)
                maximum_gain = max(0.0, maximum_pool_value - min(actual_values))
                g12_proc_chance = budgeted_chance(
                    electric_absolute_flow,
                    final_success_rate * maximum_gain,
                    electric_budget,
                    electric_chance,
                )
                if g12_proc_chance > 0 and random.random() < g12_proc_chance:
                    replacement = random.choice(candidates)
                    replacement_value = electric_unit_values.get(replacement, 0.0)
                    if replacement_value > minimum_value:
                        cheapest_index = min(
                            range(len(final_stolen_fish)),
                            key=lambda index: electric_unit_values.get(final_stolen_fish[index], 0.0),
                        )
                        old_fish = final_stolen_fish[cheapest_index]
                        final_stolen_fish[cheapest_index] = replacement
                        g12_bonus_value = replacement_value - electric_unit_values.get(old_fish, 0.0)
            else:
                g12_proc_chance = 0.0
        else:
            g12_proc_chance = 0.0

        # 6. 按鱼种、品质、原入塘单价聚合，避免混淆不同价格的库存。
        stolen_fish_counts = Counter(final_stolen_fish)

        stolen_summary = []
        total_value_thief = 0
        total_value_victim = 0

        for (fish_id, quality_level, stored_unit_value), count in stolen_fish_counts.items():
            self.inventory_repo.update_fish_quantity(victim_id, fish_id, delta=-count, quality_level=quality_level, unit_value=stored_unit_value)

            template = fish_templates.get(fish_id)
            if template:
                q_label = "✨高品质" if quality_level == 1 else ""
                name_str = f"【{q_label}{template.name}】" if q_label else f"【{template.name}】"
                stolen_summary.append(f"{name_str}x{count}")

                transfer_unit_val = calculate_fish_unit_value(
                    template.base_value, quality_level, victim_coins_chance
                )
                self.inventory_repo.add_fish_to_inventory(
                    thief_id,
                    fish_id,
                    quantity=count,
                    quality_level=quality_level,
                    unit_value=transfer_unit_val,
                )
                total_value_thief += transfer_unit_val * count
                total_value_victim += transfer_unit_val * count

        electric_bonus_coins = 0
        if (
            electric_effect_id == "C26"
            and electric_effect_fraction > 0
            and electric_bonus_chance > 0
            and random.random() < electric_bonus_chance
        ):
            bonus_cap = max(0, int(electric_params.get("bonus_cap", 0) or 0))
            electric_bonus_coins = min(
                int(total_value_thief * electric_effect_fraction), bonus_cap
            )
            if electric_bonus_coins > 0:
                thief.coins += electric_bonus_coins

        # 10. 更新电鱼的CD时间并保存
        thief.last_electric_fish_time = now
        self.user_repo.update(thief)

        # ========== 电鱼成功后守护海灵立即恢复 ==========
        shield_recovery_msg = ""
        if protection_buff:
            prot_payload = json.loads(protection_buff.payload or "{}")
            current_layers = prot_payload.get("layers", 0)

            if current_layers == 0:
                # 电鱼成功后直接恢复满层，不累计配额
                max_layers = prot_payload.get("max_layers", 2)
                resist_chance = prot_payload.get("resist_chance", 0.05)
                break_threshold = prot_payload.get("break_threshold", 3)
                new_payload = json.dumps({
                    "layers": max_layers,
                    "max_layers": max_layers,
                    "resist_chance": resist_chance,
                    "break_threshold": break_threshold,
                    "broken_steals": 0,
                })
                old_payload_str = protection_buff.payload
                updated = self.buff_repo.update_payload_if_match(
                    protection_buff.id, old_payload_str, new_payload, protection_buff.expires_at
                )
                if not updated:
                    # 并发冲突，退化为普通更新（数据最终一致）
                    protection_buff.payload = new_payload
                    self.buff_repo.update(protection_buff)
                shield_recovery_msg = "\n🛡️ 守护海灵护盾立即恢复！"
                notification_events.append(
                    {
                        "type": "protection_restored",
                        "details": {
                            "layers_restored": max_layers,
                            "new_layers": max_layers,
                        },
                    }
                )
        # ========== 电鱼后守护海灵恢复结束 ==========

        # 11. 生成成功消息
        stolen_details = "、".join(stolen_summary)
        actual_stolen_count = len(final_stolen_fish)

        # 计算收益占比
        steal_percentage = (actual_stolen_count / total_fish_count) * 100

        # 写入电鱼成功统计日志
        self._add_statistics_log(
            user_id=thief_id,
            target_id=victim_id,
            action_type="electric_fish",
            success=True,
            fish_count=actual_stolen_count,
            coin_amount=total_value_thief,
            details={
                "success_type": success_type,
                "stolen_summary": stolen_summary,
                "total_value": total_value_thief,
                "victim_total_value": total_value_victim,
                "base_success_rate": base_success_rate,
                "bonus_success_rate": boost["bonus_rate"],
                "fish_count_multiplier": boost["fish_count_multiplier"],
                "boost_consumed": boost["consumed"],
                "success_rate": final_success_rate,
                "hextech_effect_id": electric_effect_id,
                "hextech_retry_saved": electric_hextech_retry,
                "hextech_grade_upgraded": electric_hextech_grade_upgraded,
                "hextech_effect_chance": electric_proc_chance if electric_effect_id != "G12" else g12_proc_chance,
                "hextech_effect_fraction": electric_effect_fraction,
                "hextech_bonus_chance": electric_bonus_chance,
                "hextech_bonus_coins": electric_bonus_coins,
                "hextech_value_gain": g12_bonus_value,
            },
        )

        electric_hextech_messages = []
        if electric_hextech_retry:
            electric_hextech_messages.append("失败判定后重判成功")
        if electric_hextech_grade_upgraded:
            electric_hextech_messages.append("成功档次提升")
        if g12_bonus_value > 0:
            electric_hextech_messages.append(f"择优换鱼，渔获价值增加 {int(g12_bonus_value)} 金币")
        if electric_bonus_coins > 0:
            electric_hextech_messages.append(f"系统赏金 {electric_bonus_coins} 金币")
        electric_hextech_message = (
            "\n🎴 海克斯生效：" + "；".join(electric_hextech_messages) + "。"
            if electric_hextech_messages else ""
        )
        if electric_effect_id and electric_hextech_messages:
            self._log_hextech_change(
                "electric_fish",
                thief_id,
                electric_effect_id,
                {
                    "retry_saved": electric_hextech_retry,
                    "grade_upgraded": electric_hextech_grade_upgraded,
                    "effective_chance": electric_proc_chance if electric_effect_id != "G12" else g12_proc_chance,
                    "value_gain": g12_bonus_value,
                    "bonus_coins": electric_bonus_coins,
                    "bonus_chance": electric_bonus_chance,
                    "success_value_ev": expected_success_value,
                    "absolute_flow": electric_absolute_flow,
                },
            )

        return {
            "success": True,
            "message": f"{success_type}！成功对【{victim.nickname}】的鱼塘进行了电击，捕获了{actual_stolen_count}条鱼（占其总数的{steal_percentage:.1f}%），总价值 {total_value_thief} 金币！\n分别是：{stolen_details}。\n💡 本次成功率为 {final_success_rate*100:.1f}%{boost_message}{shield_recovery_msg}{electric_hextech_message}",
            "thief_nickname": thief.nickname or thief.user_id,
            "thief_total_value": total_value_thief,
            "hextech_effect_id": electric_effect_id,
            "hextech_retry_saved": electric_hextech_retry,
            "hextech_retry_attempted": electric_hextech_retry_attempted,
            "hextech_grade_upgraded": electric_hextech_grade_upgraded,
            "hextech_effect_chance": electric_proc_chance if electric_effect_id != "G12" else g12_proc_chance,
            "hextech_value_gain": g12_bonus_value,
            "hextech_bonus_coins": electric_bonus_coins,
            "hextech_bonus_chance": electric_bonus_chance,
            "victim_notification": {
                "stolen_count": actual_stolen_count,
                "stolen_summary": stolen_summary,
                "total_value": total_value_victim,
                "steal_percentage": steal_percentage,
            },
            "notification_events": notification_events,
        }
    # ============================================================
    # ===================== 新增功能：电鱼 结束 =====================
    # ============================================================

    def dispel_steal_protection(self, target_id: str) -> Dict[str, Any]:
        """
        破除目标的海灵守护（三段式机制：破盾→偷鱼配额→配额用完恢复，不再直接删除）
        """
        target = self.user_repo.get_by_id(target_id)
        if not target:
            return {"success": False, "message": "目标用户不存在"}

        protection_buff = self.buff_repo.get_active_by_user_and_type(
            target_id, "STEAL_PROTECTION_BUFF"
        )
        
        if not protection_buff:
            return {"success": False, "message": f"【{target.nickname}】没有海灵守护效果"}
        
        # 读取当前 payload
        prot_payload = json.loads(protection_buff.payload or "{}")
        current_layers = prot_payload.get("layers", 0)
        max_layers = prot_payload.get("max_layers", 2)
        resist_chance = prot_payload.get("resist_chance", 0.05)
        break_threshold = prot_payload.get("break_threshold", 3)
        
        if current_layers == 0:
            return {"success": False, "message": f"【{target.nickname}】的海灵守护已经被击破，无需再驱散！"}
        
        # 破盾：将 layers 设为 0，重置 broken_steals，后续由偷鱼配额机制接管
        old_payload_str = protection_buff.payload
        new_payload = json.dumps({
            "layers": 0,
            "max_layers": max_layers,
            "resist_chance": resist_chance,
            "break_threshold": break_threshold,
            "broken_steals": 0,
        })
        updated = self.buff_repo.update_payload_if_match(
            protection_buff.id, old_payload_str, new_payload, protection_buff.expires_at
        )
        if not updated:
            # 并发冲突，退化为普通更新
            protection_buff.payload = new_payload
            self.buff_repo.update(protection_buff)
        
        return {
            "success": True,
            "message": (
                f"💥 成功击破了【{target.nickname}】的守护海灵！"
                f"\n盾破后鱼塘可被偷 {break_threshold} 次，之后海灵会自动恢复。"
            ),
            "notification_events": [
                {
                    "type": "protection_dispelled",
                    "details": {
                        "old_layers": current_layers,
                        "new_layers": 0,
                        "layers_lost": current_layers,
                        "max_layers": max_layers,
                    },
                }
            ],
        }

    def check_steal_protection(self, target_id: str) -> Dict[str, Any]:
        """
        检查目标是否有海灵守护效果
        """
        target = self.user_repo.get_by_id(target_id)
        if not target:
            return {"has_protection": False, "target_name": "未知用户", "message": "目标用户不存在"}

        protection_buff = self.buff_repo.get_active_by_user_and_type(
            target_id, "STEAL_PROTECTION_BUFF"
        )
        
        return {
            "has_protection": protection_buff is not None,
            "target_name": target.nickname,
            "message": f"【{target.nickname}】{'有' if protection_buff else '没有'}海灵守护效果"
        }

    def calculate_sell_price(self, item_type: str, rarity: int, refine_level: int) -> int:
        """
        计算物品的系统售价。

        Args:
            item_type: 物品类型 ('rod', 'accessory')
            rarity: 物品稀有度
            refine_level: 物品精炼等级

        Returns:
            计算出的售价。
        """
        sell_price_config = self.config.get("sell_prices", {})
        
        base_prices = sell_price_config.get(item_type, {})
        base_price = base_prices.get(str(rarity), 0)

        # 如果配置中没有该稀有度的基础价格，使用基于稀有度的公式计算默认值
        # 公式：基础价 = 100 * (2.5 ^ (rarity - 1))，确保高稀有度物品有合理的价格
        if base_price <= 0:
            # 使用指数增长公式：1星=100, 2星≈250, 3星≈625, 4星≈1562, 5星≈3906, 6星≈9765, 7星≈24414, 8星≈61035, 9星≈152587, 10星≈381469
            base_price = int(100 * (2.5 ** (rarity - 1)))
            # 确保最低价格为 100
            base_price = max(100, base_price)

        refine_multipliers = sell_price_config.get("refine_multiplier", {})
        refine_multiplier = refine_multipliers.get(str(refine_level), 1.0)

        final_price = int(base_price * refine_multiplier)

        # 确保最终价格至少为 30 金币（防止计算错误导致负值或零值）
        if final_price <= 0:
            return 30  # 默认最低价格

        return final_price

    # ============================================================
    # ==================== 新增功能：骰宝 (大小) 开始 ====================
    # ============================================================
    def play_sicbo(self, user_id: str, bet_type: str, amount: int) -> Dict[str, Any]:
        """处理骰宝（押大小）游戏的核心逻辑"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "❌ 用户不存在。"}

        # 1. 冷却时间检查 (例如：5秒)
        cooldown_seconds = 5
        now = get_now()
        if user.last_sicbo_time and (now - user.last_sicbo_time).total_seconds() < cooldown_seconds:
            remaining = int(cooldown_seconds - (now - user.last_sicbo_time).total_seconds())
            return {"success": False, "message": f"⏳ 操作太快了，请等待 {remaining} 秒后再试。"}

        # 2. 验证下注
        valid_bets = ['大', '小']
        if bet_type not in valid_bets:
            return {"success": False, "message": "❌ 押注类型错误！只能押 `大` 或 `小`。"}
        if amount <= 0:
            return {"success": False, "message": "❌ 押注金额必须大于0！"}
        if not user.can_afford(amount):
            return {"success": False, "message": f"💰 你的金币不足！当前拥有 {user.coins:,} 金币。"}

        # 3. 扣除押金并开始游戏
        user.coins -= amount
        
        # 4. 投掷三个骰子
        dice = [random.randint(1, 6) for _ in range(3)]
        total = sum(dice)
        
        # 5. 判断结果
        is_triple = (dice[0] == dice[1] == dice[2])
        
        if 4 <= total <= 10:
            result_type = '小'
        elif 11 <= total <= 17:
            result_type = '大'
        else: # 只有豹子会落到这个区间外
            result_type = '豹子'

        # 6. 判断输赢
        # 规则：如果开出豹子，庄家通吃
        win = False
        if not is_triple and bet_type == result_type:
            win = True

        # 7. 结算
        profit = 0
        if win:
            winnings = amount * 2 # 1:1赔率，返还本金+1倍奖金
            profit = amount
            user.coins += winnings
        else:
            profit = -amount # 输了，损失本金

        # 8. 更新用户状态并保存
        user.last_sicbo_time = now
        self.user_repo.update(user)

        # 9. 返回详细的游戏结果
        return {
            "success": True,
            "win": win,
            "dice": dice,
            "total": total,
            "result_type": result_type,
            "is_triple": is_triple,
            "profit": profit,
            "new_balance": user.coins
        }
