import os
import asyncio
from typing import TYPE_CHECKING
from astrbot.api.event import AstrMessageEvent
from astrbot.core.message.components import At
from astrbot.api import logger

if TYPE_CHECKING:
    from ..main import FishingPlugin


async def showcase(plugin: "FishingPlugin", event: AstrMessageEvent):
    """
    查看展示柜命令：
    - `/展示柜` / `/我的展示柜`: 查看自己的展示柜
    - `/查看展示柜 @用户`: 查看指定用户的展示柜
    """
    effective_user_id = plugin._get_effective_user_id(event)
    target_id = None

    # 尝试从消息组件查找 At 目标
    message_obj = event.message_obj
    if hasattr(message_obj, "message"):
        for comp in message_obj.message:
            if isinstance(comp, At):
                if comp.qq != getattr(message_obj, "self_id", None):
                    target_id = str(comp.qq)
                    break

    # 若未找到 At，检查命令参数
    if not target_id:
        args = event.message_str.strip().split()
        if len(args) >= 2:
            potential_id = args[1].strip()
            if potential_id and not (potential_id.startswith("签名") or potential_id.startswith("放入") or potential_id.startswith("取出")):
                target_id = potential_id

    # 默认为自己
    target_user_id = target_id or effective_user_id

    # 获取数据
    data = plugin.showcase_service.get_showcase_data(target_user_id)
    if not data.get("success"):
        yield event.plain_result(f"❌ {data.get('message', '获取展示柜信息失败')}")
        return

    try:
        from ..draw.showcase import draw_showcase_image
        from ..draw.utils import get_user_avatar

        # 异步获取头像
        avatar_img = None
        try:
            avatar_config = getattr(plugin, 'game_config', {}).get("avatar_config", {})
            avatar_img = await get_user_avatar(target_user_id, plugin.data_dir, 80, avatar_config)
        except Exception as e:
            logger.warning(f"获取展示柜用户头像失败: {e}")

        # 绘制图片
        image = draw_showcase_image(data, avatar_img=avatar_img)
        image_path = os.path.join(plugin.tmp_dir, f"showcase_{target_user_id}.png")
        image.save(image_path)

        yield event.image_result(image_path)

    except Exception as e:
        logger.error(f"生成展示柜图片失败: {e}", exc_info=True)
        yield event.plain_result(f"❌ 生成展示柜图片失败: {e}")


async def put_in_showcase(plugin: "FishingPlugin", event: AstrMessageEvent):
    """将鱼竿/饰品移入展示柜"""
    user_id = plugin._get_effective_user_id(event)
    args = event.message_str.strip().split()

    if len(args) < 2:
        yield event.plain_result("❌ 用法：/放入展示柜 <装备短码>\n💡 示例：/放入展示柜 R1 或 /放入展示柜 A2\n说明：使用 /背包 查看装备短码。")
        return

    token = args[1].strip()
    result = plugin.showcase_service.put_in_showcase(user_id, token)

    if result.get("success"):
        yield event.plain_result(f"✅ {result['message']}")
    else:
        yield event.plain_result(f"❌ {result['message']}")


async def take_out_showcase(plugin: "FishingPlugin", event: AstrMessageEvent):
    """将装备从展示柜移回背包"""
    user_id = plugin._get_effective_user_id(event)
    args = event.message_str.strip().split()

    if len(args) < 2:
        yield event.plain_result("❌ 用法：/取出展示柜 <装备短码>\n💡 示例：/取出展示柜 R1 或 /取出展示柜 A2")
        return

    token = args[1].strip()
    result = plugin.showcase_service.take_out_showcase(user_id, token)

    if result.get("success"):
        yield event.plain_result(f"✅ {result['message']}")
    else:
        yield event.plain_result(f"❌ {result['message']}")


async def set_showcase_signature(plugin: "FishingPlugin", event: AstrMessageEvent):
    """修改展示柜个性宣言"""
    user_id = plugin._get_effective_user_id(event)
    args = event.message_str.strip().split(maxsplit=1)

    if len(args) < 2:
        yield event.plain_result("❌ 用法：/展示柜签名 <签名内容>\n💡 示例：/展示柜签名 全服第一钓客！")
        return

    signature = args[1].strip()
    result = plugin.showcase_service.set_signature(user_id, signature)

    if result.get("success"):
        yield event.plain_result(f"✅ {result['message']}")
    else:
        yield event.plain_result(f"❌ {result['message']}")
