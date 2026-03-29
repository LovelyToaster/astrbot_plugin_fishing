import json
import random
from typing import Dict, Any, Optional, List, Tuple
from datetime import datetime
from dataclasses import dataclass, asdict
from astrbot.api import logger

from ..repositories.abstract_repository import (
    AbstractUserRepository,
    AbstractInventoryRepository,
    AbstractItemTemplateRepository,
    AbstractLogRepository,
    AbstractUserBuffRepository,
)
from ..domain.models import DeepSeaAdventure, UserBuff
from ..utils import get_now


class DeepSeaService:
    """深海探险服务层"""

    ZONES = {
        "浅海区": {"depth_range": (1, 10), "entry_fee_range": (500, 2000), "max_depth": 10, "fish_rarity_range": (1, 3)},
        "深海区": {"depth_range": (11, 20), "entry_fee_range": (2000, 8000), "max_depth": 20, "fish_rarity_range": (2, 4)},
        "深渊区": {"depth_range": (21, 30), "entry_fee_range": (8000, 20000), "max_depth": 30, "fish_rarity_range": (3, 5)},
    }

    ENCOUNTERS = {
        "fish_school": {"weight": 30, "name": "鱼群"},
        "treasure_chest": {"weight": 15, "name": "宝箱"},
        "current": {"weight": 15, "name": "暗流"},
        "shark": {"weight": 10, "name": "鲨鱼"},
        "giant_octopus": {"weight": 8, "name": "巨型章鱼"},
        "deep_lord": {"weight": 2, "name": "深海之主"},
        "mermaid": {"weight": 12, "name": "人鱼公主"},
        "volcano": {"weight": 8, "name": "海底火山"},
    }

    def __init__(
        self,
        user_repo: AbstractUserRepository,
        inventory_repo: AbstractInventoryRepository,
        item_template_repo: AbstractItemTemplateRepository,
        log_repo: AbstractLogRepository,
        buff_repo: AbstractUserBuffRepository,
        config: Dict[str, Any],
    ):
        self.user_repo = user_repo
        self.inventory_repo = inventory_repo
        self.item_template_repo = item_template_repo
        self.log_repo = log_repo
        self.buff_repo = buff_repo
        self.config = config
        self._adventures: Dict[str, DeepSeaAdventure] = {}

    def _get_all_fish_by_rarity(self, min_rarity: int, max_rarity: Optional[int] = None) -> List:
        """根据稀有度范围获取鱼类，max_rarity为None时不限制最大值"""
        all_fish = self.item_template_repo.get_all_fish()
        if max_rarity is None:
            return [f for f in all_fish if f.rarity >= min_rarity]
        return [f for f in all_fish if min_rarity <= f.rarity <= max_rarity]

    def _select_fish(self, min_rarity: int, max_rarity: Optional[int] = None) -> Optional[Any]:
        """根据稀有度范围选择一条鱼，max_rarity为None时查询该星级以上"""
        fishes = self._get_all_fish_by_rarity(min_rarity, max_rarity)
        if not fishes:
            fishes = self.item_template_repo.get_all_fish()
        if not fishes:
            return None
        return random.choice(fishes)

    def _select_encounter(self) -> str:
        """根据权重随机选择遭遇类型"""
        encounters = list(self.ENCOUNTERS.keys())
        weights = [self.ENCOUNTERS[e]["weight"] for e in encounters]
        return random.choices(encounters, weights=weights, k=1)[0]

    def _get_fish_by_depth(self, depth: int) -> Tuple[int, int]:
        """根据深度获取鱼类稀有度范围"""
        if depth <= 10:
            return (1, 3)
        elif depth <= 20:
            return (2, 4)
        else:
            return (3, 5)

    def _add_fish_and_format(self, user_id: str, fish: Any, adventure: DeepSeaAdventure) -> str:
        """获得鱼并格式化消息"""
        if not fish:
            return ""
        self.inventory_repo.add_fish_to_inventory(user_id, fish.fish_id, quantity=1, quality_level=0)
        adventure.current_reward += fish.base_value
        return f"🐟 获得: {fish.name} ⭐ {fish.rarity}星 💰 {fish.base_value} 金币"

    def _add_coins_and_format(self, user_id: str, amount: int, adventure: DeepSeaAdventure, is_loss: bool = False) -> str:
        """获得/损失金币并格式化消息"""
        if amount == 0:
            return ""
        user = self.user_repo.get_by_id(user_id)
        if is_loss:
            actual_amount = min(abs(amount), user.coins)
            user.coins -= actual_amount
            adventure.current_loss += actual_amount
            self.user_repo.update(user)
            return f"💸 损失: -{actual_amount} 金币"
        else:
            user.coins += amount
            adventure.current_reward += amount
            self.user_repo.update(user)
            return f"💰 获得: +{amount} 金币"

    def _process_encounter(self, encounter_type: str, user_id: str, adventure: DeepSeaAdventure) -> Tuple[List[str], Optional[Any]]:
        """处理单次遭遇并返回格式化消息"""
        message_lines = []
        fish_obtained = None

        if encounter_type == "fish_school":
            rarity_range = self._get_fish_by_depth(adventure.depth)
            fish = self._select_fish(*rarity_range)
            if fish:
                message_lines.append(f"🐟 你发现了一群 {fish.name}！")
                message_lines.append(self._add_fish_and_format(user_id, fish, adventure))
                fish_obtained = fish
            else:
                message_lines.append("🐟 鱼群游走了，什么都没钓到...")

        elif encounter_type == "treasure_chest":
            treasure_value = random.randint(50, 200) * adventure.depth
            message_lines.append(f"📦 发现宝箱！")
            message_lines.append(self._add_coins_and_format(user_id, treasure_value, adventure))

        elif encounter_type == "current":
            user = self.user_repo.get_by_id(user_id)
            loss = min(int(user.coins * 0.05), adventure.entry_fee * 2)
            message_lines.append(f"🌀 遭遇暗流！")
            message_lines.append(self._add_coins_and_format(user_id, -loss, adventure, is_loss=True))

        elif encounter_type == "shark":
            if random.random() < 0.5:
                user = self.user_repo.get_by_id(user_id)
                loss = min(int(user.coins * 0.03), adventure.entry_fee * 2)
                message_lines.append(f"🦈 遭遇鲨鱼！你转身逃跑")
                message_lines.append(self._add_coins_and_format(user_id, -loss, adventure, is_loss=True))
            else:
                if random.random() < 0.6:
                    reward = random.randint(200, 500) * adventure.depth
                    message_lines.append(f"🦈 遭遇鲨鱼！你选择搏斗")
                    message_lines.append(f"⚔️ 成功了！")
                    message_lines.append(self._add_coins_and_format(user_id, reward, adventure))
                else:
                    user = self.user_repo.get_by_id(user_id)
                    loss = min(int(user.coins * 0.10), adventure.entry_fee * 3)
                    message_lines.append(f"🦈 遭遇鲨鱼！你选择搏斗")
                    message_lines.append(f"⚔️ 被咬伤了！")
                    message_lines.append(self._add_coins_and_format(user_id, -loss, adventure, is_loss=True))

        elif encounter_type == "giant_octopus":
            user = self.user_repo.get_by_id(user_id)
            loss = min(int(user.coins * 0.08), adventure.entry_fee * 2)
            message_lines.append(f"🐙 遭遇巨型章鱼！")
            message_lines.append(f"💨 被章鱼缠绕")
            message_lines.append(self._add_coins_and_format(user_id, -loss, adventure, is_loss=True))

        elif encounter_type == "deep_lord":
            jackpot_multiplier = 30
            jackpot_base = adventure.entry_fee * jackpot_multiplier
            message_lines.append(f"🐉 遭遇【深海之主】！！！")
            message_lines.append(f"头奖！！！ 深海之主被你的勇气所震撼！")
            message_lines.append(self._add_coins_and_format(user_id, jackpot_base, adventure))

            fish_rarity_roll = random.random()
            if fish_rarity_roll < 0.01:
                fish = self._select_fish(6)
            elif fish_rarity_roll < 0.10:
                fish = self._select_fish(5, 5)
            else:
                fish = self._select_fish(4, 4)

            if fish:
                message_lines.append(self._add_fish_and_format(user_id, fish, adventure))

        elif encounter_type == "mermaid":
            if random.random() < 0.5:
                reward = random.randint(100, 300) * 3
                message_lines.append(f"🧜‍♀️ 人鱼公主向你微笑...")
                message_lines.append(f"💨 她赠送了你3倍好运")
                message_lines.append(self._add_coins_and_format(user_id, reward, adventure))
            else:
                rarity_range = self._get_fish_by_depth(adventure.depth)
                fish = self._select_fish(*rarity_range)
                if fish:
                    message_lines.append(f"🧜‍♀️ 人鱼公主赠予你一条珍贵的鱼！")
                    message_lines.append(self._add_fish_and_format(user_id, fish, adventure))
                    fish_obtained = fish
                else:
                    message_lines.append(f"🧜‍♀️ 人鱼公主说：这里没有鱼能配得上你...")
                    message_lines.append(self._add_coins_and_format(user_id, 100, adventure))

        elif encounter_type == "volcano":
            if random.random() < 0.30:
                fish_rarity_roll = random.random()
                if fish_rarity_roll < 0.01:
                    fish = self._select_fish(6)
                elif fish_rarity_roll < 0.10:
                    fish = self._select_fish(5, 5)
                else:
                    fish = self._select_fish(4, 4)

                message_lines.append(f"🌋 海底火山喷发！")
                if fish:
                    message_lines.append(self._add_fish_and_format(user_id, fish, adventure))
                    fish_obtained = fish
                else:
                    message_lines.append("💨 你躲避及时，没有损失...")
            else:
                user = self.user_repo.get_by_id(user_id)
                loss = min(int(user.coins * 0.15), adventure.entry_fee * 3)
                message_lines.append(f"🌋 海底火山喷发！")
                message_lines.append(self._add_coins_and_format(user_id, -loss, adventure, is_loss=True))

        return message_lines, fish_obtained

    def _save_adventure(self, adventure: DeepSeaAdventure) -> None:
        """保存探险状态到数据库（使用 user_buffs 表）"""
        buff_type = "DEEP_SEA_ADVENTURE"
        payload = json.dumps(asdict(adventure), default=str)
        expires_at = None

        existing = self.buff_repo.get_active_by_user_and_type(adventure.user_id, buff_type)
        if existing:
            existing.payload = payload
            self.buff_repo.update(existing)
        else:
            buff = UserBuff(
                id=0,
                user_id=adventure.user_id,
                buff_type=buff_type,
                payload=payload,
                started_at=get_now(),
                expires_at=expires_at,
            )
            self.buff_repo.add(buff)

    def _load_adventure(self, user_id: str) -> Optional[DeepSeaAdventure]:
        """从数据库加载探险状态"""
        buff_type = "DEEP_SEA_ADVENTURE"
        buff = self.buff_repo.get_active_by_user_and_type(user_id, buff_type)
        if buff and buff.payload:
            try:
                data = json.loads(buff.payload)
                data["started_at"] = datetime.fromisoformat(data["started_at"])
                return DeepSeaAdventure(**data)
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.error(f"加载深海探险状态失败: {e}")
        return None

    def _clear_adventure(self, user_id: str) -> None:
        """清除探险状态"""
        buff_type = "DEEP_SEA_ADVENTURE"
        existing = self.buff_repo.get_active_by_user_and_type(user_id, buff_type)
        if existing:
            self.buff_repo.delete(existing.id)

    def start_adventure(self, user_id: str, zone: str) -> Dict[str, Any]:
        """开始深海探险"""
        user = self.user_repo.get_by_id(user_id)
        if not user:
            return {"success": False, "message": "❌ 您还没有注册，请先使用 /注册 命令注册。"}

        if zone not in self.ZONES:
            return {"success": False, "message": "❌ 无效的区域，请选择：浅海区 / 深海区 / 深渊区"}

        zone_config = self.ZONES[zone]
        entry_fee = random.randint(*zone_config["entry_fee_range"])

        if user.coins < entry_fee:
            return {"success": False, "message": f"❌ 金币不足，需要 {entry_fee} 金币才能进入 {zone}。"}

        existing = self._load_adventure(user_id)
        if existing and existing.status == "active":
            return {"success": False, "message": "❌ 您已经在深海探险中了，请先使用「回头」命令结束当前探险。"}

        user.coins -= entry_fee
        self.user_repo.update(user)

        adventure = DeepSeaAdventure(
            user_id=user_id,
            zone=zone,
            entry_fee=entry_fee,
            depth=0,
            current_reward=0,
            current_loss=0,
            started_at=get_now(),
            max_depth=zone_config["max_depth"],
            status="active",
            position_x=0,
            position_y=0,
            moves=0,
        )
        self._save_adventure(adventure)

        zone_desc = {
            "浅海区": "阳光斑斓，小鱼成群结队，是新手练习的好去处。",
            "深海区": "光线渐暗，体型更大的鱼类出没其中。",
            "深渊区": "漆黑一片，传说中的深海之主沉睡于此...",
        }

        message = f"""🌊【{zone}探险开始】🌊

📍 区域: {zone}
💰 入场费: {entry_fee} 金币（已扣除）
⏱️ 开始时间: {adventure.started_at.strftime('%H:%M:%S')}

{zone_desc.get(zone, '')}

🏃 使用「下潜」「上浮」「左游」「右游」开始探索！

💡 提示: 每次移动都可能触发事件（鱼群/宝箱/暗流/鲨鱼/巨型章鱼/深海之主/人鱼公主/海底火山）"""

        return {"success": True, "message": message}

    def move(self, user_id: str, direction: str) -> Dict[str, Any]:
        """移动方向"""
        adventure = self._load_adventure(user_id)
        if not adventure or adventure.status != "active":
            return {"success": False, "message": "❌ 您还没有在进行深海探险，请先使用「深海」命令开始探险。"}

        if direction not in ["下潜", "上浮", "左游", "右游"]:
            return {"success": False, "message": "❌ 无效的移动方向，请使用：下潜 / 上浮 / 左游 / 右游"}

        old_depth = adventure.depth
        message_lines = []
        fish_obtained = None

        if direction in ["下潜", "上浮"]:
            remaining = adventure.max_depth - adventure.depth if direction == "下潜" else adventure.depth
            step = min(5, remaining)
            for i in range(step):
                if direction == "下潜":
                    adventure.depth += 1
                    adventure.position_y += 1
                else:
                    adventure.depth -= 1
                    adventure.position_y -= 1
                adventure.moves += 1

                encounter_type = self._select_encounter()
                encounter_messages, enc_fish = self._process_encounter(encounter_type, user_id, adventure)
                if enc_fish:
                    fish_obtained = enc_fish

                step_prefix = f"第{i+1}/{step}步 " if step > 1 else ""
                message_lines.append(f"{step_prefix}{direction}至 {adventure.depth}m")
                message_lines.extend(encounter_messages)
                message_lines.append("")

                if adventure.depth >= adventure.max_depth:
                    break
        else:
            if direction == "左游":
                adventure.position_x -= 1
            elif direction == "右游":
                adventure.position_x += 1

            adventure.moves += 1
            encounter_type = self._select_encounter()
            encounter_messages, enc_fish = self._process_encounter(encounter_type, user_id, adventure)
            if enc_fish:
                fish_obtained = enc_fish
            message_lines.extend(encounter_messages)

        header_msg = f"""🌊【深海探险 - 移动】🌊

📊 深度: {adventure.depth}m
"""

        if adventure.depth >= adventure.max_depth:
            adventure.status = "completed"
            net_profit = adventure.current_reward - adventure.current_loss
            user = self.user_repo.get_by_id(user_id)
            if net_profit > 0:
                user.coins += net_profit
                self.user_repo.update(user)

            message_lines.append(f"""🏆 恭喜！你到达了{adventure.zone}最深处！
总收益: +{adventure.current_reward} 金币
总损失: -{adventure.current_loss} 金币
净收益: {net_profit:+.0f} 金币""")
            self._clear_adventure(user_id)
        else:
            self._save_adventure(adventure)

        profit = adventure.current_reward - adventure.current_loss

        message_lines.append("")
        message_lines.append(f"""📊 探险状态:
收益: +{adventure.current_reward}
损失: -{adventure.current_loss}
净收益: {profit:+.0f}
剩余: {adventure.max_depth - adventure.depth}m""")

        return {
            "success": True,
            "message": header_msg + "\n".join(message_lines),
            "adventure": adventure,
            "fish_obtained": fish_obtained,
        }

    def retreat(self, user_id: str) -> Dict[str, Any]:
        """回头，结束探险"""
        adventure = self._load_adventure(user_id)
        if not adventure or adventure.status != "active":
            return {"success": False, "message": "❌ 您还没有在进行深海探险。"}

        net_profit = adventure.current_reward - adventure.current_loss

        user = self.user_repo.get_by_id(user_id)
        if net_profit > 0:
            user.coins += net_profit
        elif net_profit < 0:
            user.coins = max(0, user.coins + net_profit)

        self.user_repo.update(user)

        message = f"""🏃【深海探险 - 回头】🏃

💰 入场费: {adventure.entry_fee} 金币
📈 总收益: +{adventure.current_reward} 金币
📉 总损失: -{adventure.current_loss} 金币
💵 净收益: {net_profit:+.0f} 金币
⏱️ 探险时长: {(get_now() - adventure.started_at).total_seconds():.0f} 秒

结算完成，金币已从你的账户{("返还" if net_profit > 0 else "扣除")}！"""

        self._clear_adventure(user_id)

        return {"success": True, "message": message, "net_profit": net_profit}

    def get_status(self, user_id: str) -> Dict[str, Any]:
        """获取当前探险状态"""
        adventure = self._load_adventure(user_id)
        if not adventure or adventure.status != "active":
            return {"success": False, "message": "❌ 您还没有在进行深海探险，请先使用「深海」命令开始探险。"}

        profit = adventure.current_reward - adventure.current_loss

        zone_emoji = {"浅海区": "🌊", "深海区": "🌊🌊", "深渊区": "🌊🌊🌊"}

        message = f"""🌊【深海探险 - 状态】🌊

📍 区域: {zone_emoji.get(adventure.zone, '')} {adventure.zone}
📊 深度: {adventure.depth}m / {adventure.max_depth}m
💰 入场费: {adventure.entry_fee} 金币
📈 收益: +{adventure.current_reward} 金币
📉 损失: -{adventure.current_loss} 金币
💵 净收益: {profit:+.0f} 金币
⏱️ 开始时间: {adventure.started_at.strftime('%H:%M:%S')}

💡 使用「下潜」「上浮」「左游」「右游」继续探索，「回头」结束探险。"""

        return {"success": True, "message": message, "adventure": adventure}
