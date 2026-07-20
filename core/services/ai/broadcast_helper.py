"""
AI 玩家广播帮助器。

集中管理所有 AI 动作对外的广播文案与发送逻辑，
便于统一调整措辞、开关控制或后续国际化。
"""

from typing import Callable, Optional, List, Dict, Any

from astrbot.api import logger


class BroadcastHelper:
    """封装广播回调 + 文案模板。"""

    def __init__(
        self,
        ai_nickname: str,
        callback: Optional[Callable[[str], None]] = None,
    ):
        self.ai_nickname = ai_nickname
        self._callback = callback

    # ---------- 底层 ----------

    def send(self, message: str) -> None:
        """发送任意消息，回调为空或抛异常时静默。"""
        if self._callback is None:
            return
        try:
            self._callback(message)
        except Exception:
            logger.debug("[AI] 广播消息失败", exc_info=True)

    # ---------- 生命周期 ----------

    def online(self) -> None:
        self.send(f"🤖 AI 玩家「{self.ai_nickname}」已上线，开始搅动这片渔场！")

    # ---------- 卖鱼/装备 ----------

    def sold_fish(self, value: str) -> None:
        self.send(f"💰 {self.ai_nickname} 卖光了鱼塘，获得 {value} 金币")

    def sold_equipment(self, total_count: int, total_value: int) -> None:
        if total_count <= 0:
            return
        self.send(
            f"💎 {self.ai_nickname} 卖出了 {total_count} 件多余装备，获得 {total_value} 金币"
        )

    def equipped_rod(self, name: str, rarity: int) -> None:
        stars = "⭐" * rarity if rarity else ""
        label = f"{stars}「{name}」" if stars else f"「{name}」"
        self.send(f"🎣 {self.ai_nickname} 换上了新鱼竿 {label}")

    def equipped_accessory(self, name: str, rarity: int) -> None:
        stars = "⭐" * rarity if rarity else ""
        label = f"{stars}「{name}」" if stars else f"「{name}」"
        self.send(f"💍 {self.ai_nickname} 换上了新饰品 {label}")

    def repaired(self, rod_name: str, new_durability) -> None:
        self.send(
            f"🔧 {self.ai_nickname} 修复了「{rod_name}」，耐久恢复至 {new_durability}"
        )

    def refined(self, item_name: str, new_level: int) -> None:
        self.send(
            f"🔨 {self.ai_nickname} 精炼了「{item_name}」至 Lv.{new_level}"
        )

    # ---------- 偷/电 ----------

    @staticmethod
    def _victim_display(target_nickname: Optional[str], target_id: str) -> str:
        return target_nickname or f"**{target_id[-4:]}"

    def steal_success(
        self,
        target_id: str,
        target_nickname: Optional[str],
        fish_count: Any,
        value: Any,
    ) -> None:
        victim = self._victim_display(target_nickname, target_id)
        self.send(
            f"🎣 {self.ai_nickname} 偷了 @{victim} 的 {fish_count} 条鱼"
            f"（价值 {value} 金币）"
        )

    def steal_failure(
        self, target_id: str, target_nickname: Optional[str], err_msg: str
    ) -> None:
        victim = self._victim_display(target_nickname, target_id)
        self.send(
            f"💨 {self.ai_nickname} 试图偷 @{victim}，但失败了：{err_msg}"
        )

    def electric_success(
        self,
        target_id: str,
        target_nickname: Optional[str],
        fish_count: Any,
        value: Any,
    ) -> None:
        victim = self._victim_display(target_nickname, target_id)
        self.send(
            f"⚡ {self.ai_nickname} 电了 @{victim} 的鱼塘，"
            f"收获 {fish_count} 条鱼（价值 {value} 金币）"
        )

    def electric_failure(
        self, target_id: str, target_nickname: Optional[str], err_msg: str
    ) -> None:
        victim = self._victim_display(target_nickname, target_id)
        self.send(
            f"💨 {self.ai_nickname} 对 @{victim} 的鱼塘放电，但没成功：{err_msg}"
        )

    # ---------- 抽卡 ----------

    @staticmethod
    def _format_gacha_item(item: Dict[str, Any]) -> Optional[str]:
        """把单个抽卡结果格式化为文案片段；无法识别则返回 None。"""
        item_type = item.get("type")
        if item_type == "coins":
            return f"{item.get('quantity', 0)} 金币"
        if item_type == "title":
            return f"称号「{item.get('name', '未知')}」"

        # 其他类型（rod / accessory / bait / item）
        name = item.get("name", "未知")
        rarity = item.get("rarity", 0)
        quantity = item.get("quantity", 1) or 1
        stars = "⭐" * rarity if rarity else ""
        base = f"{stars}「{name}」" if stars else f"「{name}」"
        return f"{base}×{quantity}" if quantity > 1 else base

    def gacha_result(
        self, pool_name: str, results: List[Dict[str, Any]]
    ) -> None:
        """把一次抽卡的所有结果合并为一条消息广播。"""
        if not results:
            return

        parts: List[str] = []
        for item in results:
            if not isinstance(item, dict):
                continue
            text = self._format_gacha_item(item)
            if text:
                parts.append(text)

        if not parts:
            return

        summary = "、".join(parts)
        self.send(f"🎉 {self.ai_nickname} 在「{pool_name}」抽到：{summary}")
