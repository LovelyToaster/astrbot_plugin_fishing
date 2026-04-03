from astrbot.api.event import filter, AstrMessageEvent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main import FishingPlugin


async def deep_sea_start(self: "FishingPlugin", event: AstrMessageEvent):
    """开始深海探险"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split(" ")

    if len(args) < 2:
        zone = None
    else:
        zone = args[1]

    if not zone:
        message = """🌊【深海探险】🌊

请选择要探索的区域：

1️⃣ 浅海区
💰 入场费: 8000-12000 金币
📊 深度: 1-10m

2️⃣ 深海区
💰 入场费: 44000-66000 金币
📊 深度: 11-20m

3️⃣ 深渊区
💰 入场费: 80000-120000 金币
📊 深度: 21-30m

💡 使用「深海 浅海区」/「深海 深海区」/「深海 深渊区」开始探险！

⚠️ 风险提示：深海探险高风险高收益，请谨慎入场！"""

        yield event.plain_result(message)
        return

    result = self.deep_sea_service.start_adventure(user_id, zone)
    if not result["success"]:
        yield event.plain_result(result["message"])
        return
    yield event.plain_result(result["message"])


async def deep_sea_move_down(self: "FishingPlugin", event: AstrMessageEvent):
    """下潜"""
    user_id = self._get_effective_user_id(event)
    result = self.deep_sea_service.move(user_id, "下潜")
    yield event.plain_result(result["message"])


async def deep_sea_move_up(self: "FishingPlugin", event: AstrMessageEvent):
    """上浮"""
    user_id = self._get_effective_user_id(event)
    result = self.deep_sea_service.move(user_id, "上浮")
    yield event.plain_result(result["message"])


async def deep_sea_move_left(self: "FishingPlugin", event: AstrMessageEvent):
    """左游"""
    user_id = self._get_effective_user_id(event)
    result = self.deep_sea_service.move(user_id, "左游")
    yield event.plain_result(result["message"])


async def deep_sea_move_right(self: "FishingPlugin", event: AstrMessageEvent):
    """右游"""
    user_id = self._get_effective_user_id(event)
    result = self.deep_sea_service.move(user_id, "右游")
    yield event.plain_result(result["message"])


async def deep_sea_retreat(self: "FishingPlugin", event: AstrMessageEvent):
    """回头，结束探险"""
    user_id = self._get_effective_user_id(event)
    result = self.deep_sea_service.retreat(user_id)
    yield event.plain_result(result["message"])


async def deep_sea_status(self: "FishingPlugin", event: AstrMessageEvent):
    """查看深海探险状态"""
    user_id = self._get_effective_user_id(event)
    result = self.deep_sea_service.get_status(user_id)
    yield event.plain_result(result["message"])
