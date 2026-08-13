"""
AI 玩家广播帮助器。

集中管理所有 AI 动作对外的广播文案与发送逻辑，
便于统一调整措辞、开关控制或后续国际化。
"""

import threading
from dataclasses import dataclass
from typing import Callable, Optional, List, Dict, Any, Tuple

from astrbot.api import logger


MENTION_TOKEN = "\uFFF0"


@dataclass(frozen=True)
class BroadcastEvent:
    """AI 广播事件；mention_ids 由发送层转换成真正的 At 组件。"""

    text: str
    mention_ids: Tuple[str, ...] = ()


class BroadcastHelper:
    """封装广播回调 + 文案模板。"""

    def __init__(
        self,
        ai_nickname: str,
        callback: Optional[Callable[[BroadcastEvent], None]] = None,
        aggregate_window_seconds: int = 10,
    ):
        self.ai_nickname = ai_nickname
        self._callback = callback
        self._aggregate_window_seconds = max(0, int(aggregate_window_seconds))
        self._pending: Dict[str, Tuple[BroadcastEvent, int, threading.Timer]] = {}
        self._lock = threading.RLock()

    # ---------- 底层 ----------

    def send(
        self,
        message: str,
        *,
        mention_ids: Optional[List[str]] = None,
        aggregate_key: Optional[str] = None,
    ) -> None:
        """发送任意消息；相同 aggregate_key 在短窗口内合并。"""
        if self._callback is None:
            return
        try:
            event = BroadcastEvent(
                text=message,
                mention_ids=tuple(str(value) for value in (mention_ids or []) if value),
            )
            if not aggregate_key or self._aggregate_window_seconds <= 0:
                self._callback(event)
                return
            with self._lock:
                previous = self._pending.get(aggregate_key)
                if previous:
                    _, count, timer = previous
                    timer.cancel()
                    count += 1
                else:
                    count = 1

                timer = threading.Timer(
                    self._aggregate_window_seconds,
                    self._flush_aggregate,
                    args=(aggregate_key,),
                )
                timer.daemon = True
                self._pending[aggregate_key] = (event, count, timer)
                timer.start()
        except Exception:
            logger.debug("[AI] 广播消息失败", exc_info=True)

    def _flush_aggregate(self, aggregate_key: str) -> None:
        with self._lock:
            pending = self._pending.pop(aggregate_key, None)
        if not pending or self._callback is None:
            return
        event, count, _ = pending
        if count > 1:
            event = BroadcastEvent(
                text=f"{event.text}（本窗口累计 {count} 次）",
                mention_ids=event.mention_ids,
            )
        try:
            self._callback(event)
        except Exception:
            logger.debug("[AI] 聚合广播消息失败", exc_info=True)

    def flush(self) -> None:
        """立即发送全部待发送广播，供停机和测试使用。"""
        with self._lock:
            keys = list(self._pending)
            for key in keys:
                pending = self._pending.pop(key, None)
                if pending:
                    pending[2].cancel()
                    event, count, _ = pending
                    if count > 1:
                        event = BroadcastEvent(
                            text=f"{event.text}（本窗口累计 {count} 次）",
                            mention_ids=event.mention_ids,
                        )
                    try:
                        if self._callback:
                            self._callback(event)
                    except Exception:
                        logger.debug("[AI] 刷新聚合广播失败", exc_info=True)

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

    def bait_used(self, name: str, rarity: int) -> None:
        self.send(
            f"🪱 {self.ai_nickname} 使用了{('⭐' * rarity) if rarity else ''}「{name}」",
            aggregate_key=f"bait:{name}:{rarity}",
        )

    def item_used(
        self,
        name: str,
        category: str,
        *,
        target_id: Optional[str] = None,
        target_nickname: Optional[str] = None,
    ) -> None:
        target = ""
        mention_ids: List[str] = []
        if target_id:
            mention_ids = [str(target_id)]
            target = f" 对 {MENTION_TOKEN}{target_id}{MENTION_TOKEN}"
        suffix = f"（{target_nickname}）" if target_nickname and not target_id else ""
        self.send(
            f"🎒 {self.ai_nickname} 使用了「{name}」{suffix}{target}",
            mention_ids=mention_ids,
            aggregate_key=f"item:{category}:{name}:{target_id or ''}",
        )

    def item_failed(self, name: str, message: str) -> None:
        self.send(f"⚠️ {self.ai_nickname} 使用「{name}」失败：{message}")

    def switched_zone(self, from_name: str, to_name: str) -> None:
        self.send(f"🗺️ {self.ai_nickname} 从「{from_name}」切换到了「{to_name}」")

    def action_failed(self, action_name: str, message: str) -> None:
        self.send(f"⚠️ {self.ai_nickname} 的{action_name}失败：{message}")

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
        self.send(
            f"🎣 {self.ai_nickname} 偷了 {MENTION_TOKEN}{target_id}{MENTION_TOKEN} 的 {fish_count} 条鱼"
            f"（价值 {value} 金币）",
            mention_ids=[target_id],
            aggregate_key=f"steal:{target_id}",
        )

    def steal_failure(
        self, target_id: str, target_nickname: Optional[str], err_msg: str
    ) -> None:
        self.send(
            f"💨 {self.ai_nickname} 试图偷 {MENTION_TOKEN}{target_id}{MENTION_TOKEN}，但失败了：{err_msg}",
            mention_ids=[target_id],
        )

    def electric_success(
        self,
        target_id: str,
        target_nickname: Optional[str],
        fish_count: Any,
        value: Any,
    ) -> None:
        self.send(
            f"⚡ {self.ai_nickname} 电了 {MENTION_TOKEN}{target_id}{MENTION_TOKEN} 的鱼塘，"
            f"收获 {fish_count} 条鱼（价值 {value} 金币）",
            mention_ids=[target_id],
            aggregate_key=f"electric_fish:{target_id}",
        )

    def electric_failure(
        self, target_id: str, target_nickname: Optional[str], err_msg: str
    ) -> None:
        self.send(
            f"💨 {self.ai_nickname} 对 {MENTION_TOKEN}{target_id}{MENTION_TOKEN} 的鱼塘放电，但没成功：{err_msg}",
            mention_ids=[target_id],
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
