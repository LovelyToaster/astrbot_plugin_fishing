from astrbot.api.event import filter, AstrMessageEvent
from ..utils import parse_target_user_id, to_percentage, safe_datetime_handler
from typing import TYPE_CHECKING
from ..core.services.hextech_effects import EFFECTS

if TYPE_CHECKING:
    from ..main import FishingPlugin


def _reward_quantity_text(item):
    quantity = int(item.get("quantity", 1) or 1)
    return f" × {quantity}" if item.get("type") in ("bait", "item") and quantity > 1 else ""


def _hextech_gacha_summary(result):
    effect = result.get("hextech_effect") or {}
    effect_id = effect.get("id")
    definition = EFFECTS.get(effect_id, {})
    name = definition.get("name", "海克斯")
    refund = int(result.get("hextech_refund_coins", 0) or 0)
    bonus = int(effect.get("bonus_coins_total", 0) or 0)
    count = int(effect.get("triggered_count", 0) or 0)
    if refund:
        return f"\n✨ {name}：返还 {refund:,} 金币。"
    if bonus:
        return f"\n✨ {name}：额外获得 {bonus:,} 金币（已计入奖励）。"
    if count:
        return f"\n✨ {name}：本次触发 {count} 次。"
    if effect_id == "G13" and effect.get("weight_multiplier", 1) > 1:
        return f"\n✨ {name}已生效。"
    return ""


def _get_field(obj, key, default=None):
    """统一读取字段，兼容 dataclass 模型实现了 __getitem__ 但没有 dict.get 的情况。"""
    try:
        # 优先尝试下标访问（GachaPool 实现了 __getitem__）
        return obj[key]
    except Exception:
        # 若是 dict 支持 get；否则回退 getattr
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)


def _format_pool_details(
    pool, probabilities, pity_threshold=0, personal_up=None, up_warning=None,
    current_hextech_effect_id=None,
):
    message = "【🎰 卡池详情】\n\n"
    message += f"ID: {pool['gacha_pool_id']} - {pool['name']}\n"
    message += f"描述: {pool['description']}\n"
    # 限时开放信息展示（安全检查字段）
    is_limited_time = bool(_get_field(pool, "is_limited_time"))
    open_until = _get_field(pool, "open_until")
    if is_limited_time and open_until:
        display_time = str(open_until).replace("T", " ").replace("-", "/")
        if len(display_time) > 16:
            display_time = display_time[:16]
        message += f"限时开放 至: {display_time}\n"
    if _get_field(pool, "cost_premium_currency"):
        message += f"花费: {pool['cost_premium_currency']} 高级货币 / 次\n\n"
    else:
        message += f"花费: {pool['cost_coins']} 金币 / 次\n\n"
    if pity_threshold > 0:
        message += f"【🎯 保底规则】连续 {pity_threshold} 抽未出本卡池最稀有物品时，下一抽必出\n\n"
    message += "【📋 基础权重单抽概率】\n"
    message += "个人概率已计入你的UP；基础概率未启用UP。两者均不含保底长期影响。\n"
    if current_hextech_effect_id:
        effect_name = EFFECTS.get(current_hextech_effect_id, {}).get("name", "海克斯")
        message += (
            f"当前海克斯列按{effect_name}计算（非硬保底状态）；"
            "只改变数量或货币的效果不会改变物品命中概率。\n"
        )
    if any(item.get("hard_pity_probability") is not None for item in probabilities):
        message += "硬保底列表示下一抽处于硬保底时的条件概率。\n"
    if personal_up:
        message += (
            f"你的个人UP：{personal_up['item_name']}（{personal_up['rarity']}星，"
            f"奖品条目ID {personal_up['entry_id']}）；最终抽到该星级时，UP命中率为50%。\n"
        )
    else:
        message += "你的个人UP：关闭\n"
    if up_warning:
        message += f"⚠️ {up_warning}\n"
    if probabilities:
        for item in probabilities:
            probability_text = (
                f"个人: {to_percentage(item['probability'])}；"
                f"基础: {to_percentage(item['base_probability'])}"
            )
            if item.get("current_hextech_probability") is not None:
                probability_text += (
                    f"；当前海克斯: {to_percentage(item['current_hextech_probability'])}"
                )
            if item.get("hard_pity_probability") is not None:
                probability_text += (
                    f"；硬保底: {to_percentage(item['hard_pity_probability'])}"
                )
            message += (
                f" - 条目 {item['gacha_pool_item_id']} "
                f"{'🎯UP ' if item.get('is_personal_up') else ''}"
                f"{'⭐' * item.get('item_rarity', 0)} {item['item_name']} "
                f"({probability_text})\n"
            )
    message += (
        f"\n设置：/卡池 {pool['gacha_pool_id']} UP <奖品条目ID>\n"
        f"关闭：/卡池 {pool['gacha_pool_id']} UP 关闭"
    )
    return message


async def gacha(self: "FishingPlugin", event: AstrMessageEvent):
    """抽卡"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split()
    if len(args) < 2:
        # 展示所有的抽奖池信息并显示帮助
        pools = self.gacha_service.get_all_pools()
        if not pools:
            yield event.plain_result("❌ 当前没有可用的抽奖池。")
            return
        message = "【🎰 抽奖池列表】\n\n"
        for pool in pools.get("pools", []):
            cost_text = f"💰 金币 {pool['cost_coins']} / 次"
            if pool["cost_premium_currency"]:
                cost_text = f"💎 高级货币 {pool['cost_premium_currency']} / 次"
            message += f"ID: {pool['gacha_pool_id']} - {pool['name']} - {pool['description']}\n {cost_text}\n\n"
        # 添加卡池详细信息
        message += "【📋 卡池详情】使用「查看卡池 ID」命令查看详细物品概率\n"
        message += "【🎯 个人UP】使用「卡池 ID UP」查询或设置自己的卡池UP\n"
        message += "【🎲 抽卡命令】使用「抽卡 ID」命令选择抽卡池进行单次抽卡\n"
        message += "【🎯 十连命令】使用「十连 ID [次数]」命令进行十连抽卡\n"
        message += "   - 单次十连：/十连 1\n"
        message += "   - 多次十连：/十连 1 5 (进行5次十连，合并统计)"
        yield event.plain_result(message)
        return
    pool_id = args[1]
    if not pool_id.isdigit():
        yield event.plain_result("❌ 抽奖池 ID 必须是数字，请检查后重试。")
        return
    pool_id = int(pool_id)
    if result := self.gacha_service.perform_draw(user_id, pool_id, num_draws=1):
        if result["success"]:
            items = result.get("results", [])
            message = f"🎉 抽卡成功！您抽到了 {len(items)} 件物品：\n"
            for item in items:
                if item.get("type") == "coins":
                    message += f"⭐ {item['quantity']} 金币！\n"
                else:
                    marker = " 🎯UP" if item.get("is_up") else ""
                    message += f"{'⭐' * item.get('rarity', 1)} {item['name']}{marker}{_reward_quantity_text(item)}\n"
            pity = result.get("pity", 0)
            pity_threshold = result.get("pity_threshold", 0)
            if pity_threshold > 0:
                remaining = max(0, pity_threshold - pity)
                message += f"\n🎯 距离保底还有 {remaining} 抽"
            up_hits = sum(1 for item in items if item.get("is_up"))
            if up_hits:
                message += f"\n✨ 本次命中个人UP {up_hits} 次"
            message += _hextech_gacha_summary(result)
            yield event.plain_result(message)
        else:
            yield event.plain_result(f"❌ 抽卡失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def ten_gacha(self: "FishingPlugin", event: AstrMessageEvent):
    """十连抽卡"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split()
    if len(args) < 2:
        yield event.plain_result("❌ 请指定要进行十连抽卡的抽奖池 ID，例如：/十连 1")
        return
    
    # 检查是否有次数参数
    times = 1
    if len(args) >= 3:
        if args[2].isdigit():
            times = int(args[2])
            if times <= 0:
                yield event.plain_result("❌ 抽卡次数必须大于0")
                return
            max_draws = int(getattr(self.gacha_service, "max_draws_per_request", 100))
            max_ten_batches = max_draws // 10
            if times > max_ten_batches:
                yield event.plain_result(f"❌ 当前单次最多抽 {max_draws} 张（{max_ten_batches} 次十连）")
                return
        else:
            yield event.plain_result("❌ 抽卡次数必须是数字")
            return
    
    pool_id = args[1]
    if not pool_id.isdigit():
        yield event.plain_result("❌ 抽奖池 ID 必须是数字，请检查后重试。")
        return
    pool_id = int(pool_id)
    
    # 如果是多次十连，使用合并统计功能
    if times > 1:
        async for result in multi_ten_gacha(self, event, pool_id, times):
            yield result
        return
    
    # 单次十连抽卡
    if result := self.gacha_service.perform_draw(user_id, pool_id, num_draws=10):
        if result["success"]:
            items = result.get("results", [])
            message = f"🎉 十连抽卡成功！您抽到了 {len(items)} 件物品：\n"
            for item in items:
                if item.get("type") == "coins":
                    message += f"⭐ {item['quantity']} 金币！\n"
                else:
                    marker = " 🎯UP" if item.get("is_up") else ""
                    message += f"{'⭐' * item.get('rarity', 1)} {item['name']}{marker}{_reward_quantity_text(item)}\n"
            pity = result.get("pity", 0)
            pity_threshold = result.get("pity_threshold", 0)
            if pity_threshold > 0:
                remaining = max(0, pity_threshold - pity)
                message += f"\n🎯 距离保底还有 {remaining} 抽"
            up_hits = sum(1 for item in items if item.get("is_up"))
            if up_hits:
                message += f"\n✨ 本次命中个人UP {up_hits} 次"
            message += _hextech_gacha_summary(result)
            yield event.plain_result(message)
        else:
            yield event.plain_result(f"❌ 抽卡失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def multi_ten_gacha(self: "FishingPlugin", event: AstrMessageEvent, pool_id: int, times: int):
    """多次十连抽卡，单次调用并合并统计"""
    user_id = self._get_effective_user_id(event)
    total_draws = times * 10
    max_draws = int(getattr(self.gacha_service, "max_draws_per_request", 100))
    if total_draws > max_draws:
        yield event.plain_result(f"❌ 单次最多只能抽 {max_draws} 张")
        return

    pool = self.gacha_service.gacha_repo.get_pool_by_id(pool_id)
    if not pool:
        yield event.plain_result("❌ 卡池不存在")
        return

    use_premium_currency = (getattr(pool, "cost_premium_currency", 0) or 0) > 0
    if use_premium_currency:
        total_cost = (pool.cost_premium_currency or 0) * total_draws
        cost_type = "高级货币"
        cost_unit = "点"
    else:
        total_cost = (pool.cost_coins or 0) * total_draws
        cost_type = "金币"
        cost_unit = ""

    result = self.gacha_service.perform_draw(user_id, pool_id, num_draws=total_draws)
    if not result or not result.get("success"):
        yield event.plain_result(f"❌ 抽卡失败：{result.get('message', '未知错误')}")
        return

    items = result.get("results", [])
    pity = result.get("pity", 0)
    pity_threshold = result.get("pity_threshold", 0)

    # 合并统计
    total_items = len(items)
    item_counts = {}
    rarity_counts = {i: 0 for i in range(1, 11)}
    coin_total = 0

    for item in items:
        if item.get("type") == "coins":
            coin_total += item['quantity']
        else:
            name = item['name']
            rarity = item.get('rarity', 1)
            quantity = int(item.get("quantity", 1) or 1) if item.get("type") in ("bait", "item") else 1
            item_counts[name] = item_counts.get(name, 0) + quantity
            r = rarity if rarity <= 10 else 10
            rarity_counts[r] = rarity_counts.get(r, 0) + 1

    message = f"🎉 {times}次十连抽卡完成！共获得 {total_items} 份奖励：\n\n"
    message += f"【💰 消耗统计】\n消耗{cost_type}：{total_cost:,}{cost_unit}\n\n"

    message += "【📊 稀有度统计】\n"
    for rarity in [10, 9, 8, 7, 6, 5, 4, 3, 2, 1]:
        count = rarity_counts.get(rarity, 0)
        if count > 0:
            message += f"{'⭐' * rarity} {count} 件\n"

    if coin_total > 0:
        message += f"\n💰 金币总计：{coin_total}\n"

    if item_counts:
        message += "\n【🎁 物品详情】\n"
        for name, count in sorted(item_counts.items()):
            message += f"{name} × {count}\n"

    if pity_threshold > 0:
        remaining = max(0, pity_threshold - pity)
        message += f"\n🎯 距离保底还有 {remaining} 抽"

    up_hits = int(result.get("up_hit_count", 0) or 0)
    if up_hits:
        message += f"\n✨ 本次命中个人UP {up_hits} 次"

    message += _hextech_gacha_summary(result)
    yield event.plain_result(message)


async def view_gacha_pool(self: "FishingPlugin", event: AstrMessageEvent):
    """查看卡池，并管理当前有效用户自己的个人UP。"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split()
    if len(args) < 2 or (len(args) == 2 and args[1].lower() == "list"):
        pools_result = self.gacha_service.get_all_pools()
        if not pools_result.get("success"):
            yield event.plain_result(f"❌ 查看卡池失败：{pools_result.get('message', '未知错误')}")
            return
        up_by_pool = {
            row["pool_id"]: row for row in self.gacha_service.get_user_up_overview(user_id)
        }
        message = "【🎰 卡池列表】\n"
        for pool in pools_result.get("pools", []):
            pool_id = int(_get_field(pool, "gacha_pool_id", 0) or 0)
            pool_name = _get_field(pool, "name", "未知卡池")
            choice = up_by_pool.get(pool_id, {}).get("up")
            if choice:
                up_text = f"个人UP：{choice['item_name']}（{choice['rarity']}星，条目ID {choice['entry_id']}）"
            else:
                up_text = "个人UP：关闭"
            message += f"\n{pool_id} - {pool_name}\n{up_text}\n"
            warning = up_by_pool.get(pool_id, {}).get("warning")
            if warning:
                message += f"⚠️ {warning}\n"
        message += (
            "\n查看奖品与概率：/卡池 <卡池ID>\n"
            "查询自己的UP：/卡池 <卡池ID> UP\n"
            "设置UP：/卡池 <卡池ID> UP <奖品条目ID>\n"
            "关闭UP：/卡池 <卡池ID> UP 关闭"
        )
        yield event.plain_result(message)
        return
    pool_id = args[1]
    if not pool_id.isdigit():
        yield event.plain_result("❌ 卡池 ID 必须是数字，请检查后重试。")
        return
    pool_id = int(pool_id)

    if len(args) >= 3 and args[2].lower() == "up":
        if len(args) == 3:
            result = self.gacha_service.get_user_up(user_id, pool_id)
            if not result.get("success"):
                yield event.plain_result(f"❌ 查询个人UP失败：{result['message']}")
                return
            up = result.get("up")
            if up:
                message = (
                    f"卡池「{result['pool'].name}」的个人UP：{up['item_name']}"
                    f"（{up['rarity']}星，奖品条目ID {up['entry_id']}）。\n"
                    f"最终抽到{up['rarity']}星时，UP命中率为50%。\n"
                )
            else:
                message = f"卡池 {pool_id} 当前没有个人UP。\n"
            if result.get("warning"):
                message += f"⚠️ {result['warning']}\n"
            message += (
                f"设置：/卡池 {pool_id} UP <奖品条目ID>\n"
                f"关闭：/卡池 {pool_id} UP 关闭"
            )
            yield event.plain_result(message)
            return
        if len(args) != 4:
            yield event.plain_result(
                f"用法：/卡池 {pool_id} UP <奖品条目ID> 或 /卡池 {pool_id} UP 关闭"
            )
            return
        if args[3].lower() == "关闭":
            result = self.gacha_service.close_user_up(user_id, pool_id)
        elif args[3].isdigit():
            result = self.gacha_service.set_user_up(user_id, pool_id, int(args[3]))
        else:
            yield event.plain_result(
                f"奖品条目ID必须是数字。用法：/卡池 {pool_id} UP <奖品条目ID> 或 /卡池 {pool_id} UP 关闭"
            )
            return
        if result.get("success"):
            yield event.plain_result(f"✅ {result['message']}")
        else:
            yield event.plain_result(f"❌ 设置个人UP失败：{result['message']}")
        return

    if len(args) != 2:
        yield event.plain_result(
            "❌ 参数格式错误。示例：/卡池 1、/卡池 1 UP、/卡池 1 UP 23、/卡池 1 UP 关闭"
        )
        return
    if result := self.gacha_service.get_pool_details(pool_id, user_id=user_id):
        if result["success"]:
            pool = result.get("pool", {})
            probabilities = result.get("probabilities", [])
            pity_threshold = getattr(self.gacha_service, "pity_threshold", 0)
            yield event.plain_result(_format_pool_details(
                pool, probabilities, pity_threshold,
                result.get("personal_up"), result.get("up_warning"),
                result.get("current_hextech_effect_id"),
            ))
        else:
            yield event.plain_result(f"❌ 查看卡池失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def gacha_history(self: "FishingPlugin", event: AstrMessageEvent):
    """查看抽卡记录"""
    user_id = self._get_effective_user_id(event)
    if result := self.gacha_service.get_user_gacha_history(user_id):
        if result["success"]:
            history = result.get("records", [])
            if not history:
                yield event.plain_result("📜 您还没有抽卡记录。")
                return
            total_count = len(history)
            message = f"【📜 抽卡记录】共 {total_count} 条\n\n"

            for record in history:
                message += f"物品名称: {record['item_name']} (稀有度: {'⭐' * record['rarity']})\n"
                message += f"时间: {safe_datetime_handler(record['timestamp'])}\n\n"

            yield event.plain_result(message)
        else:
            yield event.plain_result(f"❌ 查看抽卡记录失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def wipe_bomb(self: "FishingPlugin", event: AstrMessageEvent):
    """擦弹功能"""
    user_id = self._get_effective_user_id(event)
    
    # 检查是否有逾期借款
    is_overdue, overdue_msg = self.loan_service.check_user_overdue_status(user_id)
    if is_overdue:
        yield event.plain_result(overdue_msg)
        return
    
    args = event.message_str.split(" ")
    if len(args) < 2:
        yield event.plain_result("💸 请指定要擦弹的数量 ID，例如：/擦弹 123456789")
        return
    contribution_amount = args[1]
    if contribution_amount in ["allin", "halfin", "梭哈", "梭一半"]:
        # 查询用户当前金币数量
        if user := self.user_repo.get_by_id(user_id):
            coins = user.coins
        else:
            yield event.plain_result("❌ 您还没有注册，请先使用 /注册 命令注册。")
            return
        if contribution_amount in ("allin", "梭哈"):
            contribution_amount = coins
        elif contribution_amount in ("halfin", "梭一半"):
            contribution_amount = coins // 2
        contribution_amount = str(contribution_amount)
    # 判断是否为int或数字字符串
    if not contribution_amount.isdigit():
        yield event.plain_result("❌ 擦弹数量必须是数字，请检查后重试。")
        return
    if result := self.game_mechanics_service.perform_wipe_bomb(
        user_id, int(contribution_amount)
    ):
        if result["success"]:
            message = ""
            contribution = result["contribution"]
            multiplier = result["multiplier"]
            reward = result["reward"]
            profit = result["profit"]
            remaining_today = result["remaining_today"]

            # 格式化倍率，智能精度显示
            if multiplier < 0.01:
                # 当倍率小于0.01时，显示4位小数以避免混淆
                multiplier_formatted = f"{multiplier:.4f}"
            else:
                # 正常情况下保留两位小数
                multiplier_formatted = f"{multiplier:.2f}"

            if multiplier >= 3:
                message += f"🎰 大成功！你投入 {contribution} 金币，获得了 {multiplier_formatted} 倍奖励！\n 💰 奖励金额：{reward} 金币（盈利：+ {profit}）\n"
            elif multiplier >= 1:
                message += f"🎲 你投入 {contribution} 金币，获得了 {multiplier_formatted} 倍奖励！\n 💰 奖励金额：{reward} 金币（盈利：+ {profit}）\n"
            else:
                message += f"💥 你投入 {contribution} 金币，获得了 {multiplier_formatted} 倍奖励！\n 💰 奖励金额：{reward} 金币（亏损：- {abs(profit)})\n"
            message += f"剩余擦弹次数：{remaining_today} 次\n"
            hextech_bonus = int(result.get("hextech_bonus", 0) or 0)
            if hextech_bonus:
                effect_name = EFFECTS.get(result.get("hextech_effect_id"), {}).get("name", "海克斯")
                message += f"✨ {effect_name}：额外奖励 {hextech_bonus:,} 金币（已计入奖励金额）。\n"

            # 如果触发了抑制模式，添加通知信息
            if "suppression_notice" in result:
                message += f"\n{result['suppression_notice']}"

            yield event.plain_result(message)
        else:
            yield event.plain_result(f"⚠️ 擦弹失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def wipe_bomb_history(self: "FishingPlugin", event: AstrMessageEvent):
    """查看擦弹记录"""
    user_id = self._get_effective_user_id(event)
    if result := self.game_mechanics_service.get_wipe_bomb_history(user_id):
        if result["success"]:
            history = result.get("logs", [])
            if not history:
                yield event.plain_result("📜 您还没有擦弹记录。")
                return
            message = "【📜 擦弹记录】\n\n"
            for record in history:
                # 添加一点emoji
                message += f"⏱️ 时间: {safe_datetime_handler(record['timestamp'])}\n"
                message += f"💸 投入: {record['contribution']} 金币, 🎁 奖励: {record['reward']} 金币\n"
                # 计算盈亏
                profit = record["reward"] - record["contribution"]
                profit_text = f"盈利: +{profit}" if profit >= 0 else f"亏损: {profit}"
                profit_emoji = "📈" if profit >= 0 else "📉"

                if record["multiplier"] >= 3:
                    message += f"🔥 倍率: {record['multiplier']} ({profit_emoji} {profit_text})\n\n"
                elif record["multiplier"] >= 1:
                    message += f"✨ 倍率: {record['multiplier']} ({profit_emoji} {profit_text})\n\n"
                else:
                    message += f"💔 倍率: {record['multiplier']} ({profit_emoji} {profit_text})\n\n"
            yield event.plain_result(message)
        else:
            yield event.plain_result(f"❌ 查看擦弹记录失败：{result['message']}")
    else:
        yield event.plain_result("❌ 出错啦！请稍后再试。")


async def start_wheel_of_fate(self: "FishingPlugin", event: AstrMessageEvent):
    """处理开始命运之轮游戏的指令，并提供玩法说明。"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split(" ")

    if len(args) < 2:
        config = self.game_mechanics_service.WHEEL_OF_FATE_CONFIG
        min_fee = config.get("min_entry_fee", 500)
        max_fee = config.get("max_entry_fee", 50000)
        timeout = config.get("timeout_seconds", 60)
        help_message = "--- 🎲 命运之轮 玩法说明 ---\n\n"
        help_message += "这是一个挑战勇气与运气的游戏！你将面临连续的抉择，幸存得越久，奖励越丰厚，但失败将让你失去一切。\n\n"
        help_message += f"【玩法】\n使用 `/命运之轮 <金额>` 开始游戏。\n(金额需在 {min_fee} - {max_fee} 之间)\n\n"
        help_message += f"【规则】\n游戏共10层，每层机器人都会提示你当前的奖金和下一层的成功率。你需要在 {timeout} 秒内回复【继续】或【放弃】来决定你的命运！超时将自动放弃并结算当前奖金。\n\n"
        help_message += "【概率详情】\n"
        levels = config.get("levels", [])
        for i, level in enumerate(levels):
            rate = int(level.get("success_rate", 0) * 100)
            help_message += f" - 前往第 {i + 1} 层：{rate}% 成功率\n"
        help_message += "\n祝你好运，挑战者！"
        yield event.plain_result(help_message)
        return

    entry_fee_str = args[1]
    if not entry_fee_str.isdigit():
        yield event.plain_result("指令格式不正确哦！\n金额必须是纯数字。")
        return

    entry_fee = int(entry_fee_str)
    result = self.game_mechanics_service.start_wheel_of_fate(user_id, entry_fee)
    
    if result and result.get("message"):
        user = self.user_repo.get_by_id(user_id)
        user_nickname = user.nickname if user and user.nickname else user_id
        formatted_message = result["message"].replace(f"[CQ:at,qq={user_id}]", f"@{user_nickname}")
        yield event.plain_result(formatted_message)

async def continue_wheel_of_fate(self: "FishingPlugin", event: AstrMessageEvent):
    """处理命运之轮的“继续”指令"""
    user_id = self._get_effective_user_id(event)
    # 直接将请求交给 Service 层，它会处理所有逻辑
    result = self.game_mechanics_service.continue_wheel_of_fate(user_id)
    if result and result.get("message"):
        user = self.user_repo.get_by_id(user_id)
        user_nickname = user.nickname if user and user.nickname else user_id
        formatted_message = result["message"].replace(f"[CQ:at,qq={user_id}]", f"@{user_nickname}")
        yield event.plain_result(formatted_message)

async def stop_wheel_of_fate(self: "FishingPlugin", event: AstrMessageEvent):
    """处理命运之轮的“放弃”指令"""
    user_id = self._get_effective_user_id(event)
    # 直接将请求交给 Service 层，它会处理所有逻辑
    result = self.game_mechanics_service.cash_out_wheel_of_fate(user_id)
    if result and result.get("message"):
        user = self.user_repo.get_by_id(user_id)
        user_nickname = user.nickname if user and user.nickname else user_id
        formatted_message = result["message"].replace(f"[CQ:at,qq={user_id}]", f"@{user_nickname}")
        yield event.plain_result(formatted_message)

async def sicbo(self: "FishingPlugin", event: AstrMessageEvent):
    """处理骰宝游戏指令"""
    user_id = self._get_effective_user_id(event)
    args = event.message_str.split(" ")

    # 如果指令不完整，显示帮助信息
    if len(args) < 3:
        help_message = (
            "--- 🎲 骰子 (押大小) 玩法说明 ---\n\n"
            "【规则】\n"
            "系统将投掷三颗骰子，你可以选总点数是“大”还是“小”。\n"
            " - 🎯 小: 总点数 4 - 10\n"
            " - 🎯 大: 总点数 11 - 17\n"
            " - 🐅 豹子: 若三颗骰子点数相同 (例如 都在)，则庄家赢！\n"
            "奖金均为 1:1。\n\n"
            "【指令格式】\n"
            "`/骰子 <大或小> <金币>`\n"
            "例如: `/骰子 大 1000`"
        )
        yield event.plain_result(help_message)
        return

    bet_type = args[1]
    amount_str = args[2]

    if not amount_str.isdigit():
        yield event.plain_result("❌ 押注金额必须是纯数字！")
        return
    
    amount = int(amount_str)

    # 调用核心服务逻辑
    result = self.game_mechanics_service.play_sicbo(user_id, bet_type, amount)

    # 根据服务返回的结果，构建回复消息
    if not result["success"]:
        yield event.plain_result(result["message"])
        return

    dice_emojis = {1: '⚀', 2: '⚁', 3: '⚂', 4: '⚃', 5: '⚄', 6: '⚅'}
    dice_str = " ".join([dice_emojis.get(d, str(d)) for d in result["dice"]])
    
    message = f"🎲 开奖结果: {dice_str}  (总点数: {result['total']})\n"
    
    if result["is_triple"]:
        message += f"🐅 开出豹子！庄家通吃！\n"
    else:
        message += f"🎯 判定结果为: {result['result_type']}\n"

    if result["win"]:
        message += f"🎉 恭喜你，猜中了！\n"
        message += f"💰 你赢得了 {result['profit']:,} 金币！"
    else:
        message += f"😔 很遗憾，没猜中。\n"
        message += f"💸 你失去了 {abs(result['profit']):,} 金币。"

    message += f"\n余额: {result['new_balance']:,} 金币"
    
    yield event.plain_result(message)
