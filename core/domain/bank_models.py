"""
银行系统领域模型
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from enum import Enum


class DepositType(Enum):
    """存款类型"""
    CURRENT = "current"  # 活期存款
    FIXED = "fixed"  # 定期存款


@dataclass
class BankAccount:
    """银行账户模型"""
    user_id: str = ""  # 用户 ID
    current_balance: int = 0  # 活期余额（含已结算利息，实现复利）
    fixed_balance: int = 0  # 定期余额
    total_interest: int = 0  # 累计利息（已废弃，保留兼容性）
    last_interest_date: Optional[datetime] = None  # 上次结息日期（游戏日）
    created_at: Optional[datetime] = None  # 开户时间
    updated_at: Optional[datetime] = None  # 更新时间


@dataclass
class DepositRecord:
    """存款记录模型"""
    record_id: Optional[int] = None  # 记录 ID（数据库自增）
    user_id: str = ""  # 用户 ID
    deposit_type: DepositType = DepositType.FIXED  # 存款类型（仅定期使用）
    amount: int = 0  # 存款金额
    interest_rate: float = 0.0  # 利率
    term_days: Optional[int] = None  # 存款期限（游戏日），仅定期存款有效
    start_date: Optional[datetime] = None  # 存款开始时间
    end_date: Optional[datetime] = None  # 存款结束时间，仅定期存款有效
    interest_earned: int = 0  # 已获得利息
    status: str = "active"  # 状态：active(进行中), completed(已完成), withdrawn(已取出)
    created_at: Optional[datetime] = None  # 创建时间
    updated_at: Optional[datetime] = None  # 更新时间

    def is_matured(self) -> bool:
        """是否到期（仅定期存款）"""
        if self.deposit_type == DepositType.FIXED and self.end_date:
            # 确保两个 datetime 都是 naive 再比较
            end_date = self.end_date
            if end_date.tzinfo is not None:
                end_date = end_date.replace(tzinfo=None)
            return datetime.now() >= end_date
        return False
