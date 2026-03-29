from astrbot.api.event import AstrMessageEvent
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..main import FishingPlugin


class CatHandlers:
    def __init__(self, plugin: "FishingPlugin"):
        self.plugin = plugin
        self.cat_service = plugin.cat_service
        self.item_template_repo = plugin.item_template_repo

    def _calc_exp_needed(self, level: int, star: int) -> int:
        return int(100 * star * (1 + 0.5 * (level - 1)))

    def _resolve_cat_template(self, cat_id: int):
        if not hasattr(self.cat_service, "cat_repo"):
            return None
        cat_repo = self.cat_service.cat_repo
        if hasattr(cat_repo, "get_cat_by_id"):
            return cat_repo.get_cat_by_id(cat_id)
        if hasattr(cat_repo, "get_all_cats"):
            all_cats = cat_repo.get_all_cats()
            return next((c for c in all_cats if c.cat_id == cat_id), None)
        return None

    async def cat_help(self, event: AstrMessageEvent):
        message = """【养猫系统帮助】：

领养猫咪后，猫咪会为你提供钓鱼加成
每只猫咪都有饱食度、心情、健康三个状态
需要定期喂食和互动来维持状态
如果忽视猫咪，它们可能会生病

星级系统：初始为1星，喂食高星级鱼有概率升星
等级满10级自动升星，每次升星后等级重置为1
每升一星，升级所需经验增加

可用命令：
• /领养猫咪 [名字] - 花费500金币领养一只猫咪
• /我的猫咪 - 查看你拥有的所有猫咪
• /猫咪状态 [编号] - 查看指定猫咪的详细状态
• /喂猫 [编号] [鱼ID] - 用鱼喂猫（高星级鱼可能触发升星）
• /逗猫 [编号] - 陪猫咪玩耍恢复心情
• /一键喂猫 - 自动用最高星鱼喂所有猫咪
• /一键逗猫 - 逗所有猫咪恢复心情
• /治疗猫咪 [编号] - 治疗生病的猫咪
• /猫咪改名 [编号] [新名字] - 给猫咪改名
• /放生猫咪 [编号] - 放生猫咪（不可恢复）
• /养猫帮助 - 显示此帮助信息

喂鱼效果（消耗1条鱼）：
饱食度: 8 + 鱼稀有度*2
经验: 鱼稀有度
心情: 4星以上开始有

使用「鱼塘」命令查看鱼ID"""
        yield event.plain_result(message)

    async def adopt_cat(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        args = event.message_str.split()

        nickname = args[1] if len(args) > 1 else None
        result = self.cat_service.adopt_cat(user_id, nickname)

        if not result["success"]:
            yield event.plain_result(f"❌ {result['message']}")
            return

        cat = result["cat"]
        cat_tpl = result["cat_template"]

        msg = f"""【领养猫咪】

恭喜！您领养了一只 {cat_tpl.name}

名字: {cat.nickname}
星级: {cat.star}星
健康值: {cat.health}
饱食度: {cat.hunger}
心情值: {cat.mood}

钓鱼稀有概率 +{cat.rare_bonus_extra * 100:.1f}%
金币加成 +{cat.coin_bonus_extra * 100:.1f}%"""

        yield event.plain_result(msg)

    async def my_cats(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        cats = self.cat_service.list_user_cats(user_id)

        if not cats:
            yield event.plain_result("【我的猫咪】\n\n您还没有领养猫咪，使用「领养猫咪」开始吧")
            return

        msg = "【我的猫咪】\n\n"
        for i, cat in enumerate(cats, 1):
            cat_tpl = self._resolve_cat_template(cat.cat_id)

            disease_emoji = ""
            try:
                status_result = self.cat_service.get_cat_status(user_id, cat.cat_instance_id)
                if status_result.get("success") and status_result.get("disease"):
                    disease_emoji = f" 😿{status_result['disease']['name']}中"
            except Exception:
                disease_emoji = ""

            msg += f"{i}. {cat.nickname} | {cat.star}星 Lv.{cat.level}\n"
            msg += f"   健康 {cat.health} | 饱食 {cat.hunger} | 心情 {cat.mood}{disease_emoji}\n\n"

        msg += f"共 {len(cats)} 只猫咪\n"
        msg += "使用「猫咪状态 编号」查看详细信息"

        yield event.plain_result(msg)

    async def cat_status(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        args = event.message_str.split()

        if len(args) < 2:
            yield event.plain_result("请指定猫咪编号，使用「我的猫咪」查看编号")
            return

        try:
            cat_index = int(args[1]) - 1
        except ValueError:
            yield event.plain_result("编号必须是数字")
            return

        cats = self.cat_service.list_user_cats(user_id)
        if cat_index < 0 or cat_index >= len(cats):
            yield event.plain_result("猫咪编号不存在")
            return

        cat = cats[cat_index]
        result = self.cat_service.get_cat_status(user_id, cat.cat_instance_id)

        if not result["success"]:
            yield event.plain_result(f"❌ {result['message']}")
            return

        cat_tpl = result["cat_template"]
        disease_info = result.get("disease")
        description = cat_tpl.description if getattr(cat_tpl, "description", None) else ""

        msg = f"""【猫咪状态】{cat.nickname}

{cat.star}星 Lv.{cat.level} 经验 {cat.exp}/{self._calc_exp_needed(cat.level, cat.star)}
品种: {cat.color} {cat.pattern}
{description}

健康值: {cat.health}/100
饱食度: {cat.hunger}/100 {"⚠️ 饿了" if cat.hunger < 50 else ""}
心情值: {cat.mood}/100 {"⚠️ 无聊" if cat.mood < 50 else ""}"""

        if disease_info:
            msg += f"""

生病中: {disease_info['name']}
症状: {disease_info['symptom']}
治疗: 需要对应药物或 {disease_info['treatment_cost']} 金币"""

        rare_bonus = result.get("fishing_bonus", 0)
        coin_bonus = result.get("coin_bonus", 0)
        
        msg += f"""

钓鱼稀有概率: {rare_bonus * 100:+.1f}%
金币加成: {coin_bonus * 100:+.1f}%"""

        events = result.get("recent_events", [])
        if events:
            msg += "\n\n最近事件:"
            for ev in events:
                emoji = "🎁" if ev.event_type == "positive" else ("😿" if ev.event_type == "negative" else "💬")
                time_str = ev.triggered_at.strftime("%m-%d %H:%M")
                msg += f"\n{time_str} {emoji} {ev.event_name}"

        yield event.plain_result(msg)

    async def feed_cat(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        args = event.message_str.split()

        if len(args) < 2:
            yield event.plain_result("请指定猫咪编号，使用「我的猫咪」查看编号")
            return

        try:
            cat_index = int(args[1]) - 1
        except ValueError:
            yield event.plain_result("编号必须是数字")
            return

        if len(args) < 3:
            yield event.plain_result("请指定要喂的鱼ID，使用「鱼塘」命令查看鱼ID")
            return

        try:
            fish_id_str = args[2].lower()
            quality_level = 0
            if fish_id_str.startswith('f'):
                if fish_id_str.endswith('h'):
                    quality_level = 1
                    fish_id = int(fish_id_str[1:-1])
                else:
                    fish_id = int(fish_id_str[1:])
            else:
                fish_id = int(fish_id_str)
        except ValueError:
            yield event.plain_result("鱼类ID格式错误")
            return

        cats = self.cat_service.list_user_cats(user_id)
        if cat_index < 0 or cat_index >= len(cats):
            yield event.plain_result("猫咪编号不存在")
            return

        cat = cats[cat_index]

        result = self.cat_service.feed_cat(user_id, cat.cat_instance_id, fish_id, quality_level)

        if not result["success"]:
            yield event.plain_result(f"❌ {result['message']}")
            return

        msg = f"""【喂猫】{cat.nickname}

喂食: {result['fish_name']} ({result['rarity']}星)
饱食度: {result['old_hunger']} → {result['new_hunger']} ({result['hunger_change']:+.0f})
心情: {result['old_mood']} → {result['new_mood']} ({result['mood_change']:+.0f})
经验: +{result['exp_gain']} ({result['star']}星 Lv.{cat.level})"""

        if result.get("star_up"):
            su = result["star_up"]
            msg += f"\n🎉 升星了！{su['old_star']}星 → {su['new_star']}星！"

        if result.get("level_up"):
            msg += f"\n升级了，现在是 Lv.{result['new_level']}"

        if result.get("event"):
            ev = result["event"]
            emoji = "🎁" if ev["event_type"] == "positive" else ("😿" if ev["event_type"] == "negative" else "💬")
            msg += f"\n\n{emoji} 触发事件: {ev['name']}\n{ev['description']}"
            if ev.get("reward_type") == "item":
                item_tpl = self.item_template_repo.get_item_by_id(ev["reward_item_id"])
                item_name = item_tpl.name if item_tpl else ev["reward_item_id"]
                msg += f"\n获得 {item_name} x{ev.get('reward_value', 1)}"
            elif ev.get("reward_type") == "coins":
                msg += f"\n获得 {ev['reward_value']} 金币"

        if result.get("disease"):
            d = result["disease"]
            msg += f"\n\n猫咪生病了: {d['name']}\n症状: {d['symptom']}"

        yield event.plain_result(msg)

    async def play_with_cat(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        args = event.message_str.split()

        if len(args) < 2:
            yield event.plain_result("请指定猫咪编号，使用「我的猫咪」查看编号")
            return

        try:
            cat_index = int(args[1]) - 1
        except ValueError:
            yield event.plain_result("编号必须是数字")
            return

        cats = self.cat_service.list_user_cats(user_id)
        if cat_index < 0 or cat_index >= len(cats):
            yield event.plain_result("猫咪编号不存在")
            return

        cat = cats[cat_index]
        result = self.cat_service.play_with_cat(user_id, cat.cat_instance_id)

        if not result["success"]:
            yield event.plain_result(f"❌ {result['message']}")
            return

        msg = f"""【逗猫】{cat.nickname}

心情: {result['old_mood']} → {result['new_mood']} ({result['mood_change']:+.0f})
经验: +{result['exp_gain']}"""

        if result.get("level_up"):
            msg += f"\n升级了，现在是 Lv.{result['new_level']}"

        if result.get("event"):
            ev = result["event"]
            emoji = "🎁" if ev["event_type"] == "positive" else ("😿" if ev["event_type"] == "negative" else "💬")
            msg += f"\n\n{emoji} 触发事件: {ev['name']}\n{ev['description']}"
            if ev.get("reward_type") == "coins":
                msg += f"\n获得 {ev['reward_value']} 金币"

        yield event.plain_result(msg)

    async def treat_cat(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        args = event.message_str.split()

        if len(args) < 2:
            yield event.plain_result("请指定猫咪编号，使用「我的猫咪」查看编号")
            return

        try:
            cat_index = int(args[1]) - 1
        except ValueError:
            yield event.plain_result("编号必须是数字")
            return

        cats = self.cat_service.list_user_cats(user_id)
        if cat_index < 0 or cat_index >= len(cats):
            yield event.plain_result("猫咪编号不存在")
            return

        cat = cats[cat_index]
        result = self.cat_service.treat_cat(user_id, cat.cat_instance_id)

        if not result["success"]:
            yield event.plain_result(f"❌ {result['message']}")
            return

        yield event.plain_result(f"✨ {result['message']}")

    async def rename_cat(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        args = event.message_str.split()

        if len(args) < 3:
            yield event.plain_result("请输入「猫咪改名 编号 新名字」")
            return

        try:
            cat_index = int(args[1]) - 1
        except ValueError:
            yield event.plain_result("编号必须是数字")
            return

        new_name = args[2]
        if len(new_name) > 10:
            yield event.plain_result("名字太长，最多10个字符")
            return

        cats = self.cat_service.list_user_cats(user_id)
        if cat_index < 0 or cat_index >= len(cats):
            yield event.plain_result("猫咪编号不存在")
            return

        cat = cats[cat_index]
        cat.nickname = new_name
        self.cat_service.cat_repo.update_cat_instance(cat)

        yield event.plain_result(f"✨ 您的猫咪改名为「{new_name}」了")

    async def release_cat(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        args = event.message_str.split()

        if len(args) < 2:
            yield event.plain_result("请指定要放生的猫咪编号，使用「我的猫咪」查看编号")
            return

        try:
            cat_index = int(args[1]) - 1
        except ValueError:
            yield event.plain_result("编号必须是数字")
            return

        cats = self.cat_service.list_user_cats(user_id)
        if cat_index < 0 or cat_index >= len(cats):
            yield event.plain_result("猫咪编号不存在")
            return

        cat = cats[cat_index]
        self.cat_service.cat_repo.remove_cat_instance(cat.cat_instance_id)

        yield event.plain_result(f"您放生了「{cat.nickname}」，愿它找到好的归宿")

    async def batch_play_with_cats(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        result = self.cat_service.batch_play_with_cats(user_id)

        if not result["success"]:
            yield event.plain_result(f"❌ {result['message']}")
            return

        msg = f"""【一键逗猫】

共 {result['total_cats']} 只猫咪
成功逗猫: {result['success_count']} 只
冷却跳过: {result['skip_count']} 只
心情已满跳过: {result.get('skip_mood_full', 0)} 只

"""
        for detail in result["details"]:
            if detail["status"] == "success":
                msg += f"✓ {detail['cat_name']}\n"
                msg += f"  ↳ 心情 {detail['old_mood']}→{detail['new_mood']}(+{detail['mood_gain']})\n"
                msg += f"  ↳ 经验 +{detail['exp_gain']}\n"
                if detail.get("level_up"):
                    msg += f"  ↳ 升级 Lv.{detail['level_up']}\n"
                if detail.get("star_up"):
                    msg += f"  ↳ ⭐ 升星! {detail['star_up']['old_star']}→{detail['star_up']['new_star']}★\n"
                if detail.get("event"):
                    emoji = "🎁" if detail.get("event_type") == "positive" else "😿"
                    msg += f"  ↳ {emoji} 【{detail['event']}】{detail.get('event_desc', '')}\n"
                if detail.get("disease"):
                    msg += f"  ↳ 生病: {detail['disease']}\n"
            else:
                msg += f"✗ {detail['cat_name']}: {detail['reason']}\n"

        msg += f"\n总计: 心情 +{result['total_mood_gain']}, 经验 +{result['total_exp_gain']}"

        yield event.plain_result(msg)

    async def batch_feed_cats(self, event: AstrMessageEvent):
        user_id = self.plugin._get_effective_user_id(event)
        result = self.cat_service.batch_feed_cats(user_id)

        if not result["success"]:
            yield event.plain_result(f"❌ {result['message']}")
            return

        msg = f"""【一键喂猫】

共 {result['total_cats']} 只猫咪
成功喂食: {result['success_count']} 只
冷却跳过: {result['skip_cooldown']} 只
无鱼跳过: {result['skip_no_fish']} 只
饱食已满跳过: {result.get('skip_hunger_full', 0)} 只
使用鱼类: {result['used_fish_count']} 条

"""
        for detail in result["details"]:
            if detail["status"] == "success":
                msg += f"✓ {detail['cat_name']}: 喂{detail['fish_name']}({detail['rarity']}星)\n"
                msg += f"  ↳ 饱食 {detail['old_hunger']}→{detail['new_hunger']}(+{detail['hunger_gain']})\n"
                msg += f"  ↳ 心情 {detail['old_mood']}→{detail['new_mood']}(+{detail['mood_gain']})\n"
                msg += f"  ↳ 经验 +{detail['exp_gain']}\n"
                if detail.get("star_up"):
                    msg += f"  ↳ ⭐ 升星! {detail['star_up']['old_star']}→{detail['star_up']['new_star']}★\n"
                if detail.get("level_up"):
                    msg += f"  ↳ 升级 Lv.{detail['level_up']}\n"
                if detail.get("event"):
                    emoji = "🎁" if detail.get("event_type") == "positive" else "😿"
                    msg += f"  ↳ {emoji} 【{detail['event']}】{detail.get('event_desc', '')}\n"
                if detail.get("disease"):
                    msg += f"  ↳ 生病: {detail['disease']}\n"
            else:
                msg += f"✗ {detail['cat_name']}: {detail['reason']}\n"

        msg += f"\n总计: 饱食 +{result['total_hunger_gain']}, 心情 +{result['total_mood_gain']}, 经验 +{result['total_exp_gain']}"

        yield event.plain_result(msg)
