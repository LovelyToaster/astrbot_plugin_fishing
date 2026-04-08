"""
银行系统服务层
"""

import asyncio
from datetime import datetime, timedelta
from typing import List, Tuple, Optional
import threading

from astrbot.api import logger

from ..repositories.sqlite_bank_repo import SqliteBankRepository
from ..repositories.sqlite_user_repo import SqliteUserRepository
from ..domain.bank_models import BankAccount, DepositRecord, DepositType
from ..domain.models import TaxRecord
from ..repositories.abstract_repository import AbstractLogRepository
from ..utils import get_now


class BankService:
    """银行业务逻辑服务"""

    def __init__(
        self,
        bank_repo: SqliteBankRepository,
        user_repo: SqliteUserRepository,
        log_repo: AbstractLogRepository = None,  # 日志仓储，用于记录税收
        # 活期利率配置
        current_interest_rate: float = 0.001,  # 活期基础利率，默认 0.1%
        min_interest_rate: float = 0.0008,  # 最低活期利率，默认 0.08%
        max_interest_rate: float = 0.005,  # 最高活期利率，默认 0.5%
        rate_volatility: float = 0.0003,  # 利率波动幅度，默认 0.03%
        # 定期利率配置
        base_fixed_rate: float = 0.003,  # 基础定期利率，默认 0.3%
        max_fixed_rate: float = 0.15,  # 最高定期利率，默认 15%
        # 资金池影响参数
        pool_base_amount: int = 10000000,  # 资金池基准值，默认 1000 万
        pool_exponent: float = 0.3,  # 资金池影响指数，默认 0.3
        pool_factor_min: float = 0.7,  # 资金池因子最小值，默认 0.7
        # 游戏时间配置
        game_day_hours: float = 1.0,  # 1 游戏日的小时数，默认 1 小时
        daily_reset_hour: int = 0,  # 每日刷新时间点（小时）
        # 税收配置（统一使用税收系统的配置）
        tax_config: dict = None,  # 税收配置字典，包含开关、起征点、税率等
    ):
        self.bank_repo = bank_repo
        self.user_repo = user_repo
        self.log_repo = log_repo  # 日志仓储
        self.base_interest_rate = current_interest_rate  # 基础活期利率
        self.game_day_hours = game_day_hours  # 1 游戏日的小时数
        self.daily_reset_hour = daily_reset_hour  # 每日刷新时间点
        
        # 银行税收配置（使用税收系统统一配置）
        if tax_config is None:
            tax_config = {}
        self.tax_config = tax_config
        self.bank_tax_enabled = tax_config.get("is_tax", True)  # 是否启用税收
        self.bank_tax_threshold = tax_config.get("threshold", 1000000)  # 直接使用税收系统的起征点
        self.bank_tax_rate = tax_config.get("min_rate", 0.001)  # 直接使用税收系统的起点税率

        # 动态利率配置
        self.min_interest_rate = min_interest_rate  # 最低利率
        self.max_interest_rate = max_interest_rate  # 最高利率
        # 利率变化间隔 = 1 游戏日（与利息结算同步）
        self.rate_change_interval = int(self.game_day_hours * 3600)  # 利率变化间隔（秒）
        self.last_rate_update = datetime.now()  # 上次利率更新时间
        self.current_interest_rate = self.base_interest_rate  # 当前实际利率

        # 利率波动幅度（随机因子）
        self.rate_volatility = rate_volatility  # 每次变化的最大波动幅度

        # 资金池影响参数
        self.pool_base_amount = pool_base_amount  # 资金池基准值
        self.pool_exponent = pool_exponent  # 资金池影响指数
        self.pool_factor_min = pool_factor_min  # 资金池因子最小值

        # 定期利率配置（动态计算）
        # 新的定期利率采用动态计算：利率 = min(基础利率 + 天数奖励，最高 15%)
        # 使用单调递增公式，存期越长利率越高
        self.max_fixed_rate = max_fixed_rate  # 最高定期利率
        self.base_fixed_rate = base_fixed_rate  # 基础定期利率
        # 分段利率配置：(天数阈值，该段每增加 1 天的利率增量)
        # 计算示例：
        #   1 天：0.3% + 1×0.10% = 0.4%
        #  15 天：0.3% + 15×0.10% = 1.8%
        #  30 天：0.3% + 30×0.10% = 3.3%
        #  50 天：0.3% + 30×0.10% + 20×0.12% = 5.7%
        #  72 天：0.3% + 30×0.10% + 42×0.12% = 8.34%
        #  96 天：0.3% + 30×0.10% + 42×0.12% + 24×0.15% = 11.94%
        # 120 天：0.3% + 30×0.10% + 42×0.12% + 24×0.15% + 24×0.13% = 15.06% → 封顶 15%
        # 150 天：封顶 15%
        self.tiered_rates = [
            (30, 0.0010),      # 1-30 天：每天 0.10%
            (72, 0.0012),      # 31-72 天：每天 0.12%
            (96, 0.0015),      # 73-96 天：每天 0.15%
            (120, 0.0013),     # 97-120 天：每天 0.13%
        ]

        # 线程锁，用于保护利率更新
        self._rate_lock = threading.Lock()

    def _ensure_naive(self, dt: datetime) -> datetime:
        """
        确保 datetime 是时区无知的（naive）

        Args:
            dt: 输入的 datetime 对象

        Returns:
            时区无知的 datetime 对象
        """
        if dt is None:
            return None
        if dt.tzinfo is not None:
            # 如果是时区感知的，移除时区信息（直接丢弃时区）
            return dt.replace(tzinfo=None)
        return dt

    def _get_game_day(self, dt: datetime = None) -> datetime:
        """
        获取指定时间对应的游戏日日期

        游戏日定义：从指定的刷新时间点（daily_reset_hour）开始到下一个刷新时间点之前

        Args:
            dt: 指定时间，默认为当前时间

        Returns:
            游戏日的开始时间点（时区无知）
        """
        if dt is None:
            dt = datetime.now()
        else:
            # 确保输入是时区无知的
            dt = self._ensure_naive(dt)

        # 创建今天的刷新时间点
        today_reset = dt.replace(
            hour=self.daily_reset_hour,
            minute=0,
            second=0,
            microsecond=0
        )

        # 如果当前时间已经过了今天的刷新时间点，返回今天的刷新时间点
        if dt >= today_reset:
            return today_reset
        else:
            # 否则返回昨天的刷新时间点
            return today_reset - timedelta(days=1)

    def _get_game_days_elapsed(self, start_date: datetime) -> int:
        """
        计算从指定时间到现在经过的游戏日数

        游戏日按 game_day_hours 计算，例如 game_day_hours=1 时，
        现实 1 小时 = 1 游戏日

        Args:
            start_date: 开始时间

        Returns:
            经过的游戏日数（整数）
        """
        if start_date is None:
            return 0

        # 确保 start_date 是 naive
        start_date_naive = self._ensure_naive(start_date)

        # 计算经过的现实时间（小时）
        now = datetime.now()
        hours_elapsed = (now - start_date_naive).total_seconds() / 3600

        # 转换为游戏日：现实小时数 / game_day_hours = 游戏日数
        # 例如：经过 24 现实小时，game_day_hours=1 时，= 24 游戏日
        game_days = int(hours_elapsed / self.game_day_hours)

        return max(0, game_days)

    def get_or_create_account(self, user_id: str) -> BankAccount:
        """获取或创建银行账户"""
        account = self.bank_repo.get_account(user_id)
        if not account:
            account = self.bank_repo.create_account(user_id)
        return account

    def get_fixed_interest_rate(self, days: int) -> float:
        """
        获取指定天数的定期利率（动态计算，单调递增）

        利率计算公式：采用分段累进利率
        - 存期越长，利率越高
        - 72-96 天达到较高利率区间
        - 最高不超过 15%

        Args:
            days: 存款天数（游戏日）

        Returns:
            定期利率（小数形式，如 0.05 表示 5%）
        """
        if days <= 0:
            return 0.0

        # 分段累进计算
        rate = self.base_fixed_rate
        prev_tier_day = 0

        for tier_days, rate_per_day in self.tiered_rates:
            if days > tier_days:
                # 当前段已满，累加完整区间的利率
                rate += (tier_days - prev_tier_day) * rate_per_day
                prev_tier_day = tier_days
            else:
                # 在当前段内，按比例计算
                rate += (days - prev_tier_day) * rate_per_day
                break

        # 限制在最高利率以内
        return min(rate, self.max_fixed_rate)

    def calculate_dynamic_interest_rate(self) -> float:
        """计算动态活期利率（基于时间和资金池）"""
        import random

        with self._rate_lock:
            now = datetime.now()
            # 确保两个 datetime 都是时区无知的
            now = self._ensure_naive(now)
            last_rate_update = self._ensure_naive(self.last_rate_update)
            time_since_last_update = (now - last_rate_update).total_seconds()

            if time_since_last_update >= self.rate_change_interval:
                total_current_balance = self._get_total_current_balance()

                if total_current_balance > 0:
                    pool_factor = max(
                        self.pool_factor_min,
                        1.0 - (total_current_balance / self.pool_base_amount) ** self.pool_exponent
                    )
                else:
                    pool_factor = 1.0

                time_factor = random.uniform(-self.rate_volatility, self.rate_volatility)
                new_rate = self.base_interest_rate * pool_factor + time_factor
                new_rate = max(self.min_interest_rate, min(self.max_interest_rate, new_rate))

                self.current_interest_rate = new_rate
                self.last_rate_update = now

                logger.info(f"活期利率更新：{new_rate*100:.3f}% (资金池：{total_current_balance:,})")

        return self.current_interest_rate

    def _get_total_current_balance(self) -> int:
        """获取所有用户的活期存款总额"""
        try:
            conn = self.bank_repo._get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT SUM(current_balance) FROM bank_accounts")
            result = cursor.fetchone()
            return result[0] if result[0] else 0
        except Exception as e:
            logger.error(f"获取活期存款总额失败：{e}")
            return 0

    def _get_settlement_countdown(self) -> str:
        """
        计算下次利息结算的倒计时

        Returns:
            倒计时字符串，如"30 分钟"或"0.5 游戏日"
        """
        now = datetime.now()
        game_day_seconds = int(self.game_day_hours * 3600)

        # 计算下一个结算时间点
        seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second
        next_boundary_seconds = ((seconds_since_midnight // game_day_seconds) + 1) * game_day_seconds

        # 如果超出当天，等到明天
        if next_boundary_seconds >= 24 * 3600:
            next_boundary_seconds = next_boundary_seconds - (24 * 3600)
            next_settlement = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        else:
            next_settlement = now.replace(microsecond=0)
            next_settlement = next_settlement.replace(
                hour=next_boundary_seconds // 3600,
                minute=(next_boundary_seconds % 3600) // 60,
                second=next_boundary_seconds % 60
            )

        remaining_seconds = (next_settlement - now).total_seconds()
        remaining_minutes = int(remaining_seconds / 60)

        if remaining_minutes < 60:
            return f"{remaining_minutes} 分钟"
        elif remaining_minutes < 1440:
            return f"{remaining_minutes / 60:.1f} 小时"
        else:
            return f"{remaining_minutes / 1440:.1f} 游戏日"

    def get_interest_rate_info(self) -> str:
        """获取当前利率信息"""
        current_rate = self.calculate_dynamic_interest_rate()
        rate_percent = current_rate * 100

        if current_rate > self.base_interest_rate:
            trend = "📈 上升"
        elif current_rate < self.base_interest_rate:
            trend = "📉 下降"
        else:
            trend = "➡️ 平稳"

        total_balance = self._get_total_current_balance()

        # 计算几个典型天数的定期利率示例
        rate_examples = []
        for days in [1, 7, 15, 30, 60]:
            r = self.get_fixed_interest_rate(days)
            rate_examples.append(f"{days}天 {r*100:.2f}%")

        return (
            f"📊 活期利率信息\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 当前利率：{rate_percent:.3f}% {trend}\n"
            f"📦 基础利率：{self.base_interest_rate*100:.3f}%\n"
            f"💵 银行资金池：{total_balance:,} 金币\n"
            f"📅 下次更新：{(self.last_rate_update + timedelta(seconds=self.rate_change_interval)).strftime('%H:%M:%S')}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💡 提示：资金池越大，利率越低；资金池越小，利率越高\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"📈 定期利率参考：{', '.join(rate_examples)}\n"
            f"💎 最高利率：{self.max_fixed_rate*100:.1f}%"
        )

    def deposit_current(self, user_id: str, amount: int) -> Tuple[bool, str, Optional[DepositRecord]]:
        """
        活期存款

        返回：(成功标志，消息，存款记录)
        """
        if amount <= 0:
            return False, "❌ 存款金额必须大于 0", None

        user = self.user_repo.get_by_id(user_id)
        if not user:
            return False, "❌ 用户不存在", None

        if user.coins < amount:
            return False, f"❌ 金币不足，当前金币：{user.coins:,}", None

        account = self.get_or_create_account(user_id)

        try:
            # 扣除用户金币
            user.coins -= amount
            self.user_repo.update(user)

            # 更新账户活期余额
            account.current_balance += amount
            self.bank_repo.update_account(account)

            # 创建活期存款记录（仅用于记录，不参与实际业务）
            record = DepositRecord(
                user_id=user_id,
                deposit_type=DepositType.CURRENT,
                amount=amount,
                interest_rate=self.current_interest_rate,
                term_days=None,
                start_date=datetime.now(),
                end_date=None,
                interest_earned=0,
                status="completed"
            )
            self.bank_repo.create_deposit_record(record)

            logger.info(f"用户 {user_id} 活期存款 {amount} 金币")
            return True, (
                f"✅ 活期存款成功！\n"
                f"💰 存款金额：{amount:,} 金币\n"
                f"📈 当前利率：{self.current_interest_rate*100:.2f}%\n"
                f"📊 活期余额：{account.current_balance:,} 金币\n"
                f"💡 提示：利息按游戏日自动结算并加入本金，实现复利收益"
            ), record
        except Exception as e:
            logger.error(f"活期存款失败：{e}")
            return False, f"❌ 存款失败：{str(e)}", None

    def deposit_fixed(self, user_id: str, amount: int, days: int) -> Tuple[bool, str, Optional[DepositRecord]]:
        """
        定期存款

        返回：(成功标志，消息，存款记录)
        """
        if amount <= 0:
            return False, "❌ 存款金额必须大于 0", None

        if days <= 0:
            return False, "❌ 存款天数必须大于 0", None

        user = self.user_repo.get_by_id(user_id)
        if not user:
            return False, "❌ 用户不存在", None

        if user.coins < amount:
            return False, f"❌ 金币不足，当前金币：{user.coins:,}", None

        account = self.get_or_create_account(user_id)
        interest_rate = self.get_fixed_interest_rate(days)

        # 计算到期时间（使用游戏日小时数）
        # 定期存款的 days 是游戏日，需要转换为现实小时
        actual_hours = days * self.game_day_hours
        end_date = datetime.now() + timedelta(hours=actual_hours)

        record = DepositRecord(
            user_id=user_id,
            deposit_type=DepositType.FIXED,
            amount=amount,
            interest_rate=interest_rate,
            term_days=days,
            start_date=datetime.now(),
            end_date=end_date,
            interest_earned=0,
            status="active"
        )

        try:
            user.coins -= amount
            self.user_repo.update(user)

            account.fixed_balance += amount
            self.bank_repo.update_account(account)

            record_id = self.bank_repo.create_deposit_record(record)
            record.record_id = record_id

            # 计算预计利息
            estimated_interest = round(amount * interest_rate)

            logger.info(f"用户 {user_id} 定期存款 {amount} 金币，{days} 游戏日")
            return True, (
                f"✅ 定期存款成功！\n"
                f"💰 存款金额：{amount:,} 金币\n"
                f"📅 存款天数：{days} 游戏日\n"
                f"🕐 到期时间：{self.game_day_hours * days:.1f} 现实小时\n"
                f"📈 执行利率：{interest_rate*100:.2f}%\n"
                f"🎁 预计利息：{estimated_interest:,} 金币\n"
                f"🔖 存款 ID: #{record_id}\n"
                f"📊 定期余额：{account.fixed_balance:,} 金币"
            ), record
        except Exception as e:
            logger.error(f"定期存款失败：{e}")
            return False, f"❌ 存款失败：{str(e)}", None

    def withdraw_current(self, user_id: str, amount: int) -> Tuple[bool, str]:
        """
        活期取款

        返回：(成功标志，消息)
        """
        if amount <= 0:
            return False, "❌ 取款金额必须大于 0"

        account = self.get_or_create_account(user_id)
        if not account:
            return False, "❌ 银行账户不存在"

        if account.current_balance < amount:
            return False, f"❌ 余额不足，当前余额：{account.current_balance:,} 金币"

        try:
            # 更新账户
            account.current_balance -= amount
            self.bank_repo.update_account(account)

            # 增加用户金币
            user = self.user_repo.get_by_id(user_id)
            if user:
                user.coins += amount
                self.user_repo.update(user)

            logger.info(f"用户 {user_id} 活期取款 {amount} 金币")

            # 计算下次结算倒计时
            settlement_countdown = self._get_settlement_countdown()

            msg = (
                f"✅ 活期取款成功！\n"
                f"💰 取款金额：{amount:,} 金币\n"
                f"📊 活期余额：{account.current_balance:,} 金币\n"
                f"⏰ 下次利息结算：{settlement_countdown}\n"
                f"💡 提示：利息按游戏日自动结算并加入本金，实现复利收益"
            )

            return True, msg
        except Exception as e:
            logger.error(f"活期取款失败：{e}")
            return False, f"❌ 取款失败：{str(e)}"

    def withdraw_all_matured_fixed(self, user_id: str) -> Tuple[bool, str]:
        """
        取出所有已到期的定期存款

        返回：(成功标志，消息)
        """
        # 获取所有进行中的定期存款
        fixed_records = self.bank_repo.get_deposit_records_by_user(
            user_id, DepositType.FIXED, "active"
        )

        if not fixed_records:
            return False, "❌ 您没有定期存款"

        # 找出已到期的存款
        matured_records = [r for r in fixed_records if r.is_matured()]

        if not matured_records:
            # 没有到期的，显示最近 5 条快到期的
            sorted_records = sorted(fixed_records, key=lambda r: r.end_date or datetime.now())[:5]
            message = "💡 您的定期存款尚未到期\n\n📅 最近到期的定期存款:\n"
            for i, record in enumerate(sorted_records, 1):
                if record.end_date:
                    # 确保两个 datetime 都是时区无知的再相减
                    end_date_naive = self._ensure_naive(record.end_date)
                    now_naive = self._ensure_naive(datetime.now())
                    remaining = end_date_naive - now_naive
                    hours_left = remaining.total_seconds() / 3600
                    message += f"  {i}. #{record.record_id} - {record.amount:,} 金币，{record.term_days}游戏日\n"
                    message += f"     💰 利率：{record.interest_rate*100:.2f}%\n"
                    message += f"     ⏰ 剩余：{hours_left:.1f} 小时\n\n"
            return False, message

        # 取出所有到期的存款
        total_withdrawal = 0
        total_interest = 0
        total_tax = 0
        withdrawal_details = []

        for record in matured_records:
            # 计算利息
            # 配置的利率是游戏日利率，直接乘以本金即可
            # 例如：1 天定期利率 0.5%，存 1 游戏日，利息 = 本金 × 0.005
            interest = round(record.amount * record.interest_rate)
            
            # 税收计算：检查是否启用税收且存款本金达到起征点
            tax_amount = 0
            if self.bank_tax_enabled and record.amount >= self.bank_tax_threshold:
                tax_amount = round(interest * self.bank_tax_rate)
            
            # 税后利息
            actual_interest = interest - tax_amount
            total_tax += tax_amount
            
            total_withdrawal += record.amount + actual_interest
            total_interest += actual_interest
            
            tax_info = f" (税收 {tax_amount:,})" if tax_amount > 0 else ""
            withdrawal_details.append(f"#{record.record_id}: {record.amount:,} 金币 (+{actual_interest:,} 利息{tax_info})")

            # 记录税收日志
            if tax_amount > 0 and self.log_repo:
                tax_record = TaxRecord(
                    tax_id=0,
                    user_id=user_id,
                    tax_amount=tax_amount,
                    tax_rate=self.bank_tax_rate,
                    original_amount=interest,
                    balance_after=record.amount + actual_interest,
                    timestamp=get_now(),
                    tax_type=f"定期利息税（本金 {record.amount:,}）"
                )
                self.log_repo.add_tax_record(tax_record)

            # 更新记录
            record.status = "withdrawn"
            record.interest_earned = actual_interest
            self.bank_repo.update_deposit_record(record)

        # 更新账户
        account = self.get_or_create_account(user_id)
        total_fixed_amount = sum(r.amount for r in matured_records)

        # 防御性检查
        if account.fixed_balance < total_fixed_amount:
            logger.error(f"定期余额不足：{account.fixed_balance} < {total_fixed_amount}")
            return False, "❌ 系统错误：定期余额不足"

        account.fixed_balance -= total_fixed_amount
        self.bank_repo.update_account(account)

        # 增加用户金币
        user = self.user_repo.get_by_id(user_id)
        if user:
            user.coins += total_withdrawal
            self.user_repo.update(user)

        logger.info(f"用户 {user_id} 批量取出 {len(matured_records)} 笔定期存款，共计 {total_withdrawal:,} 金币（税收 {total_tax:,}）")

        details_text = "\n".join(withdrawal_details)
        tax_info = f"\n💸 利息税收：{total_tax:,} 金币" if total_tax > 0 else ""
        return True, (
            f"✅ 定期取款成功！\n"
            f"📦 取出笔数：{len(matured_records)} 笔\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"{details_text}\n"
            f"━━━━━━━━━━━━━━━━━━\n"
            f"💰 总取款：{total_withdrawal:,} 金币{tax_info}\n"
            f"📊 定期余额：{account.fixed_balance:,} 金币"
        )

    def get_deposit_details(self, user_id: str) -> Tuple[bool, str]:
        """
        获取存款详情

        返回：(成功标志，消息)
        """
        # 获取银行账户
        account = self.bank_repo.get_account(user_id)
        if not account:
            return False, "❌ 银行账户不存在，请先进行存款操作开户"

        # 活期存款余额（含已结算利息）
        current_balance = account.current_balance

        # 获取定期存款记录
        fixed_records = self.bank_repo.get_deposit_records_by_user(
            user_id, DepositType.FIXED, "active"
        )
        fixed_total_principal = sum(r.amount for r in fixed_records)

        # 计算总本金
        total_principal = current_balance + fixed_total_principal

        # 构建消息
        message = "📊 存款详情\n"
        message += "━━━━━━━━━━━━━━━━━━\n\n"

        message += "💰 活期存款:\n"
        message += f"  • 当前余额：{current_balance:,} 金币\n"
        message += "  • 说明：利息自动结算并滚入本金，实现复利收益\n"
        message += "\n"

        message += "💎 定期存款:\n"
        message += f"  • 存入本金：{fixed_total_principal:,} 金币\n"
        if fixed_records:
            message += f"  • 存款笔数：{len(fixed_records)} 笔\n"
            # 显示每笔定期的详细信息
            message += "\n  存款明细:\n"
            for i, record in enumerate(fixed_records[:5], 1):  # 只显示最近 5 笔
                status_icon = "⚠️" if record.is_matured() else "🔒"
                message += f"    {i}. {status_icon} #{record.record_id} - {record.amount:,} 金币 "
                message += f"({record.term_days}天，利率{record.interest_rate*100:.1f}%)\n"
            if len(fixed_records) > 5:
                message += f"    ... 还有 {len(fixed_records) - 5} 笔\n"

        message += f"\n━━━━━━━━━━━━━━━━━━\n"
        message += f"📊 总资产：{total_principal:,} 金币"

        return True, message

    def get_account_info(self, user_id: str) -> Tuple[bool, str]:
        """
        获取银行账户信息

        Args:
            user_id: 用户 ID

        Returns:
            (成功标志，消息文本)
        """
        account = self.bank_repo.get_account(user_id)
        if not account:
            return False, "❌ 银行账户不存在，请先进行存款操作开户"

        fixed_records = self.bank_repo.get_deposit_records_by_user(
            user_id, DepositType.FIXED, "active"
        )

        matured_count = sum(1 for r in fixed_records if r.is_matured())
        settlement_countdown = self._get_settlement_countdown()

        # 构建消息
        message = "🏦 银行账户信息\n"
        message += "━━━━━━━━━━━━━━━━━━\n"
        message += f"💰 活期余额：{account.current_balance:,} 金币\n"
        
        if account.fixed_balance > 0:
            message += f"💎 定期余额：{account.fixed_balance:,} 金币\n"
            if matured_count > 0:
                message += f"⚠️ 提示：{matured_count} 笔定期存款已到期，请及时取出！\n"
        
        message += f"📊 总资产：{account.current_balance + account.fixed_balance:,} 金币\n"
        message += "━━━━━━━━━━━━━━━━━━\n"
        message += f"⏰ 下次结息：{settlement_countdown}\n"
        message += f"📈 活期利率：{self.current_interest_rate*100:.3f}%\n"
        
        # 显示定期利率参考
        rate_examples = []
        for days in [7, 15, 30, 60, 96]:
            r = self.get_fixed_interest_rate(days)
            rate_examples.append(f"{days}天{r*100:.1f}%")
        message += f"📅 定期利率：{', '.join(rate_examples)}\n"
        message += f"💎 最高利率：{self.max_fixed_rate*100:.1f}%\n"
        message += "━━━━━━━━━━━━━━━━━━\n"
        message += "💡 说明:\n"
        message += "• 活期利息按游戏日自动结算并滚入本金，实现复利收益\n"
        message += "• 定期存款利率随存期增长，最高可达 15%\n"
        message += "• 利率根据银行资金池动态调整"

        return True, message

    def start_interest_settlement_task(self):
        """
        启动后台利息结算任务

        每隔一个游戏日自动为所有账户结算活期利息
        """
        import asyncio

        self._settlement_task = asyncio.create_task(self._settlement_loop())
        logger.info("🏦 银行利息结算任务已启动")

    async def _settlement_loop(self):
        """利息结算循环 - 每隔一个游戏日结算一次"""
        while True:
            try:
                now = datetime.now()
                game_day_seconds = int(self.game_day_hours * 3600)  # 转换为整数秒数
                seconds_per_day = 24 * 3600

                # 计算从当日 00:00:00 起经过的秒数
                seconds_since_midnight = now.hour * 3600 + now.minute * 60 + now.second

                # 计算下一个游戏日边界时间（秒数）
                # 游戏日边界：0, game_day_seconds, 2*game_day_seconds, ...
                # 使用取模运算直接计算到下一个边界的剩余秒数
                seconds_to_next_boundary = (game_day_seconds - (seconds_since_midnight % game_day_seconds)) % seconds_per_day

                # 如果计算结果为 0，说明当前正好是边界，需要等待下一个游戏日
                if seconds_to_next_boundary == 0:
                    seconds_to_next_boundary = game_day_seconds

                # 构建下一个结算时间点
                next_settlement = now.replace(microsecond=0) + timedelta(seconds=seconds_to_next_boundary)

                sleep_seconds = seconds_to_next_boundary

                logger.info(f"🏦 下次利息结算时间：{next_settlement.strftime('%Y-%m-%d %H:%M:%S')}，等待 {sleep_seconds:.0f} 秒")
                await asyncio.sleep(sleep_seconds)

                # 执行利息结算
                logger.info("🏦 开始执行活期利息结算任务...")
                
                # 强制触发一次利率更新
                self.calculate_dynamic_interest_rate()
                conn = self.bank_repo._get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT user_id FROM bank_accounts WHERE current_balance > 0")
                accounts = cursor.fetchall()

                total_settled = 0
                total_interest = 0

                for row in accounts:
                    try:
                        user_id = row[0]
                        account = self.get_or_create_account(user_id)

                        # 计算利息：余额 × 利率 × 1 游戏日
                        interest = round(account.current_balance * self.current_interest_rate)

                        if interest > 0:
                            # 税收计算：检查是否启用税收且达到起征点
                            tax_amount = 0
                            if self.bank_tax_enabled and account.current_balance >= self.bank_tax_threshold:
                                tax_amount = round(interest * self.bank_tax_rate)
                            
                            # 税后利息
                            actual_interest = interest - tax_amount
                            
                            # 记录税收日志
                            if tax_amount > 0 and self.log_repo:
                                tax_record = TaxRecord(
                                    tax_id=0,
                                    user_id=user_id,
                                    tax_amount=tax_amount,
                                    tax_rate=self.bank_tax_rate,
                                    original_amount=interest,
                                    balance_after=account.current_balance + actual_interest,
                                    timestamp=get_now(),
                                    tax_type=f"活期利息税（余额 {account.current_balance:,}）"
                                )
                                self.log_repo.add_tax_record(tax_record)
                            
                            # 税后利息直接加入本金，实现复利效果
                            account.current_balance += actual_interest
                            account.last_interest_date = datetime.now()
                            self.bank_repo.update_account(account)
                            total_settled += 1
                            total_interest += actual_interest
                            
                            tax_info = f" (税收 {tax_amount:,})" if tax_amount > 0 else ""
                            logger.info(f"  - 用户 {user_id}: 结算 {actual_interest} 金币{tax_info} (新余额：{account.current_balance:,})")
                    except Exception as e:
                        logger.error(f"处理用户 {user_id} 账户时出错：{e}")
                        continue

                logger.info(f"🏦 利息结算完成：{total_settled} 个账户，共计 {total_interest:,} 金币")

            except asyncio.CancelledError:
                logger.info("🏦 银行利息结算任务已取消")
                break
            except Exception as e:
                logger.error(f"🏦 银行利息结算任务出错：{e}")
                await asyncio.sleep(60)  # 出错后等待 1 分钟重试

    def stop_interest_settlement_task(self):
        """停止利息结算任务"""
        if hasattr(self, '_settlement_task') and self._settlement_task:
            self._settlement_task.cancel()
            logger.info("🏦 银行利息结算任务已停止")
