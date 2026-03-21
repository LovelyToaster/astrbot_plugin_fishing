"""
银行系统处理器
"""

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger

from ..core.services.bank_service import BankService
from ..core.services.user_service import UserService
from ..core.domain.bank_models import DepositType


class BankHandlers:
    """银行命令处理器 - 仅负责消息格式化和用户检查"""

    def __init__(self, bank_service: BankService, user_service: UserService):
        self.bank_service = bank_service
        self.user_service = user_service

    async def bank_help(self, event: AstrMessageEvent):
        """查看银行帮助信息"""
        message = (
            "🏦 银行系统帮助\n"
            "━━━━━━━━━━━━━━━━━━\n"
            "📌 基础命令:\n"
            "  • 银行账户 - 查看你的银行账户总览（余额 + 利息）\n"
            "  • 利率信息 - 查看当前银行利率\n"
            "  • 存款详情 - 查看详细的存款统计信息\n"
            "\n💰 存款操作:\n"
            "  • 存款 活期 金额 - 存入金币到活期账户\n"
            "  • 存款 定期 金额 天数 - 存入金币到定期账户\n"
            "\n💸 取款操作:\n"
            "  • 取款 活期 金额 - 从活期账户取出金币\n"
            "  • 取款 定期 - 取出所有已到期的定期存款\n"
            "\n━━━━━━━━━━━━━━━━━━\n"
            "💡 提示:\n"
            "  • 活期存款按游戏日自动结算利息，利息滚入本金实现复利\n"
            "  • 定期存款利率更高，存期越长利率越高（最高 15%）\n"
            "  • 利率根据存期动态计算：存期越长，单利越高\n"
            "  • 定期利息在到期取款时一次性获得\n"
            "  • 活期利率根据银行资金池动态调整"
        )
        yield event.plain_result(message)

    async def bank_info(self, event: AstrMessageEvent):
        """查看银行账户信息"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        user = self.user_service.user_repo.get_by_id(user_id)
        if not user:
            yield event.plain_result("❌ 请先使用「注册」命令注册游戏账号")
            return

        # 获取账户信息
        success, message = self.bank_service.get_account_info(user_id)
        yield event.plain_result(message)

    async def interest_rate_info(self, event: AstrMessageEvent):
        """查看利率信息"""
        message = self.bank_service.get_interest_rate_info()
        yield event.plain_result(message)

    async def deposit(self, event: AstrMessageEvent):
        """存款操作（支持活期和定期）"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        user = self.user_service.user_repo.get_by_id(user_id)
        if not user:
            yield event.plain_result("❌ 请先使用「注册」命令注册游戏账号")
            return

        # 解析命令参数
        args = event.message_str.split()
        if len(args) < 3:
            yield event.plain_result("❌ 用法：\n• 存款 活期 金额\n• 存款 定期 金额 天数")
            return

        deposit_type_str = args[1].lower()

        try:
            if deposit_type_str == "活期":
                amount = int(args[2])
                success, message, _ = self.bank_service.deposit_current(user_id, amount)
                yield event.plain_result(message)

            elif deposit_type_str == "定期":
                if len(args) < 4:
                    yield event.plain_result("❌ 定期存款需要指定天数：存款 定期 金额 天数")
                    return
                amount = int(args[2])
                days = int(args[3])
                success, message, _ = self.bank_service.deposit_fixed(user_id, amount, days)
                yield event.plain_result(message)

            else:
                yield event.plain_result("❌ 存款类型必须是「活期」或「定期」")
        except ValueError:
            yield event.plain_result("❌ 金额和天数必须是整数")

    async def withdraw(self, event: AstrMessageEvent):
        """取款操作（支持活期和定期）"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        user = self.user_service.user_repo.get_by_id(user_id)
        if not user:
            yield event.plain_result("❌ 请先使用「注册」命令注册游戏账号")
            return

        # 解析命令参数
        args = event.message_str.split()
        if len(args) < 2:
            yield event.plain_result("❌ 用法：\n• 取款 活期 金额\n• 取款 定期")
            return

        withdraw_type_str = args[1].lower()

        try:
            if withdraw_type_str == "活期":
                if len(args) < 3:
                    yield event.plain_result("❌ 活期取款需要指定金额：取款 活期 金额")
                    return
                amount = int(args[2])
                success, message = self.bank_service.withdraw_current(user_id, amount)
                yield event.plain_result(message)

            elif withdraw_type_str == "定期":
                # 定期取款：检查所有到期存款，一起取出
                success, message = self.bank_service.withdraw_all_matured_fixed(user_id)
                yield event.plain_result(message)

            else:
                yield event.plain_result("❌ 取款类型必须是「活期」或「定期」")
        except ValueError:
            yield event.plain_result("❌ 金额必须是整数")

    async def deposit_details(self, event: AstrMessageEvent):
        """查看用户当前存款详情（包含本金、利息和平均利率）"""
        user_id = event.get_sender_id()

        # 检查用户是否注册
        user = self.user_service.user_repo.get_by_id(user_id)
        if not user:
            yield event.plain_result("❌ 请先使用「注册」命令注册游戏账号")
            return

        # 获取存款详情
        success, message = self.bank_service.get_deposit_details(user_id)
        yield event.plain_result(message)
