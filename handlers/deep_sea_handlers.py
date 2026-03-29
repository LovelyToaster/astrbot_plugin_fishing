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

============
1️⃣ 浅海区
   💰 入场费: 500-2000 金币
   📊 深度: 1-10m
   🐟 鱼类稀有度: 1-3星
   适合新手练习！

2️⃣ 深海区  
   💰 入场费: 2000-8000 金币
   📊 深度: 11-20m
   🐟 鱼类稀有度: 2-4星
   有机会遇到大型鱼类！

3️⃣ 深渊区
   💰 入场费: 8000-20000 金币
   📊 深度: 21-30m
   🐟 鱼类稀有度: 3-5星
   ⚠️ 传说中的深海之主出没！
============

💡 使用「深海 浅海区」/「深海 深海区」/「深海 深渊区」开始探险！"""

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
