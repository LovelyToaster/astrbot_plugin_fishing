"""
拉杆机(Slot Machine)游戏处理器
处理所有拉杆机相关的命令
"""

from astrbot.api.event import AstrMessageEvent
from astrbot.api import logger
from typing import TYPE_CHECKING
from ..draw.slot import (
    draw_slot_result, draw_slot_multi_result, draw_slot_jackpot_info,
    draw_slot_history, draw_slot_help, save_image_to_temp
)


if TYPE_CHECKING:
    from ..main import FishingPlugin


async def slot_spin(plugin: "FishingPlugin", event: AstrMessageEvent):
    """拉杆命令 - 单次拉杆"""
    if not plugin.is_game_enabled(event, "slot"):
        yield event.plain_result("❌ 拉杆机功能已被管理员在本群关闭")
        return
    try:
        user_id = plugin._get_effective_user_id(event)

        # 检查是否有逾期借款
        is_overdue, overdue_msg = plugin.loan_service.check_user_overdue_status(user_id)
        if is_overdue:
            yield event.plain_result(overdue_msg)
            return

        args = event.message_str.split()
        tier_name = "铜"  # 默认铜桌
        if len(args) >= 2:
            tier_name = args[1]

        result = plugin.slot_service.spin(user_id, tier_name)

        if not result["success"]:
            yield event.plain_result(result["message"])
            return

        if plugin.slot_service.is_image_mode():
            rd = result["result"]
            image = draw_slot_result(
                symbols=rd["symbols"],
                tier_name=result["tier"],
                cost=result["cost"],
                payout=result["payout"],
                net=result["net"],
                match_type=rd["match_type"],
                match_desc=rd["match_desc"],
                balance=result["balance"],
                remaining=result["remaining_spins"],
                daily_limit=result["daily_limit"],
                jackpot_pool=result["jackpot_pool"],
                jackpot_win=rd.get("jackpot_win", 0),
                is_lucky_hour=result.get("is_lucky_hour", False),
                symbol_labels=rd.get("symbol_labels"),
            )
            image_path = save_image_to_temp(image, "slot_spin", plugin.data_dir)
            yield event.image_result(image_path)
        else:
            yield event.plain_result(result["message"])

    except Exception as e:
        logger.error(f"拉杆失败: {e}")
        yield event.plain_result(f"❌ 拉杆失败：{str(e)}")


async def slot_multi_spin(plugin: "FishingPlugin", event: AstrMessageEvent):
    """连转命令 - 连续拉杆多次"""
    if not plugin.is_game_enabled(event, "slot"):
        yield event.plain_result("❌ 拉杆机功能已被管理员在本群关闭")
        return
    try:
        user_id = plugin._get_effective_user_id(event)

        # 检查是否有逾期借款
        is_overdue, overdue_msg = plugin.loan_service.check_user_overdue_status(user_id)
        if is_overdue:
            yield event.plain_result(overdue_msg)
            return

        args = event.message_str.split()
        tier_name = "铜"
        count = 5  # 默认5次

        if len(args) >= 2:
            tier_name = args[1]
        if len(args) >= 3:
            try:
                count = int(args[2])
            except ValueError:
                yield event.plain_result("❌ 次数请输入数字，例如：/连转 金 5")
                return

        result = plugin.slot_service.multi_spin(user_id, tier_name, count)

        if not result["success"]:
            yield event.plain_result(result["message"])
            return

        if plugin.slot_service.is_image_mode():
            image = draw_slot_multi_result(
                results=result["results"],
                tier_name=result["tier"],
                total_cost=result["total_cost"],
                total_payout=result["total_payout"],
                total_net=result["total_net"],
                balance=result["balance"],
                remaining=result["remaining_spins"],
                daily_limit=result["daily_limit"],
                jackpot_pool=result["jackpot_pool"],
            )
            image_path = save_image_to_temp(image, "slot_multi", plugin.data_dir)
            yield event.image_result(image_path)
        else:
            yield event.plain_result(result["message"])

    except Exception as e:
        logger.error(f"连转失败: {e}")
        yield event.plain_result(f"❌ 连转失败：{str(e)}")


async def slot_jackpot(plugin: "FishingPlugin", event: AstrMessageEvent):
    """查看奖池信息"""
    try:
        info = plugin.slot_service.get_jackpot_info()

        if plugin.slot_service.is_image_mode():
            image = draw_slot_jackpot_info(
                jackpot_pool=info["jackpot_pool"],
                lucky_hour_info=info["lucky_hour_info"],
                is_lucky_hour=info["is_lucky_hour"],
                tiers=info["tiers"],
            )
            image_path = save_image_to_temp(image, "slot_jackpot", plugin.data_dir)
            yield event.image_result(image_path)
        else:
            lines = [
                f"🏆 拉杆机累积奖池",
                f"💰 奖池金额：{info['jackpot_pool']:,} 金币",
                "",
            ]
            if info["is_lucky_hour"]:
                lines.append(f"🍀 幸运时段进行中！({info['lucky_hour_info']})")
            else:
                lines.append(f"⏰ 今日幸运时段：{info['lucky_hour_info']}")
            lines.append("")
            lines.append("📋 档位一览：")
            for key, t in info["tiers"].items():
                lines.append(f"  {t['name']}：{t['cost']:,}/次  JP:{t['jackpot_chance']}  Mini:{t['mini_chance']}")
            yield event.plain_result("\n".join(lines))

    except Exception as e:
        logger.error(f"查看奖池失败: {e}")
        yield event.plain_result(f"❌ 查看奖池失败：{str(e)}")


async def slot_history(plugin: "FishingPlugin", event: AstrMessageEvent):
    """查看拉杆记录"""
    try:
        user_id = plugin._get_effective_user_id(event)
        user = plugin.user_repo.get_by_id(user_id)
        username = user.nickname if user and user.nickname else "未知玩家"

        args = event.message_str.split()
        limit = 10
        if len(args) >= 2:
            try:
                limit = max(1, min(int(args[1]), 50))
            except ValueError:
                pass

        records = plugin.slot_service.get_user_history(user_id, limit)

        if plugin.slot_service.is_image_mode():
            image = draw_slot_history(records, username)
            image_path = save_image_to_temp(image, "slot_history", plugin.data_dir)
            yield event.image_result(image_path)
        else:
            if not records:
                yield event.plain_result("📋 暂无拉杆记录")
                return
            lines = [f"📋 {username} 的最近 {len(records)} 条拉杆记录\n"]
            for i, rec in enumerate(reversed(records), 1):
                syms = " ".join(rec.get("symbols", []))
                net = rec.get("net", 0)
                net_str = f"+{net:,}" if net > 0 else f"{net:,}"
                desc = rec.get("match_desc", "")
                lines.append(f"{i}. [{rec.get('tier', '')}] {syms}  {desc}  {net_str}")
            yield event.plain_result("\n".join(lines))

    except Exception as e:
        logger.error(f"查看记录失败: {e}")
        yield event.plain_result(f"❌ 查看记录失败：{str(e)}")


async def slot_help(plugin: "FishingPlugin", event: AstrMessageEvent):
    """拉杆机帮助"""
    try:
        if plugin.slot_service.is_image_mode():
            image = draw_slot_help(
                daily_limit=plugin.slot_service.daily_limit,
                tiers_info={},
                max_multi_spin=plugin.slot_service.max_multi_spin,
            )
            image_path = save_image_to_temp(image, "slot_help", plugin.data_dir)
            yield event.image_result(image_path)
        else:
            help_text = f"""🎰 拉杆机帮助

【游戏规则】
• 投入金币拉杆，3个转轮随机停止
• 三同 → 高倍奖金 | 两同 → 小额奖金
• 每日限 {plugin.slot_service.daily_limit} 次

【赔率表】
三海星 ×250 | 三宝石 ×120 | 三鲸鱼 ×60
三鲨鱼 ×30  | 三章鱼 ×15  | 三螃蟹 ×8
三小鱼 ×5
两海星 ×5   | 两宝石 ×3 | 两鲸鱼 ×2 | 其余两同 ×1

【档位】
铜桌 1万/次 | 银桌 10万/次
金桌 100万/次 | 至尊桌 500万/次
金桌/至尊桌可触发 Jackpot 累积奖池

【特殊机制】
🍀 幸运时段：每日随机2小时，高级符号概率UP
🛡️ 保底：连续{plugin.slot_service.streak_protection}次未中奖 → 保底两同
🏆 Jackpot：金桌/至尊桌有概率独得全部累积奖池

【命令】
/拉杆 [档位] - 单次拉杆（默认铜桌）
/连转 [档位] [次数] - 连续拉杆（最多{plugin.slot_service.max_multi_spin}次）
/奖池 - 查看累积奖池
/拉杆记录 - 查看最近记录
/拉杆帮助 - 查看本帮助

祝您好运！🍀"""
            yield event.plain_result(help_text)

    except Exception as e:
        logger.error(f"获取帮助失败: {e}")
        yield event.plain_result(f"❌ 获取帮助失败：{str(e)}")


async def set_slot_mode(plugin: "FishingPlugin", event: AstrMessageEvent):
    """[管理员] 设置拉杆机消息模式"""
    args = event.message_str.split()

    if len(args) < 2:
        current_mode = plugin.slot_service.get_message_mode()
        mode_name = "图片模式" if current_mode == "image" else "文本模式"
        yield event.plain_result(f"📱 当前拉杆机消息模式：{mode_name}\n用法：/拉杆模式 <image|text>")
        return

    try:
        mode = args[1].lower()
        if mode in ("图片", "图片模式", "img"):
            mode = "image"
        elif mode in ("文本", "文字", "文本模式", "txt"):
            mode = "text"

        result = plugin.slot_service.set_message_mode(mode)
        yield event.plain_result(result["message"])
    except Exception as e:
        yield event.plain_result(f"❌ 设置失败：{str(e)}")
