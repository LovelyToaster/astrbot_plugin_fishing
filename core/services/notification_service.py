"""统一的玩家通知写入与近期同类通知聚合。"""

import json
from typing import Any, Dict, Optional


class NotificationService:
    """为人工操作和 AI 操作提供一致的通知入口。"""

    AGGREGATE_WINDOW_SECONDS = 300
    DEFENSE_TYPES = {
        "protection_dispelled",
        "protection_damaged",
        "protection_broken",
        "protection_restored",
    }

    def __init__(self, notification_repo):
        self.notification_repo = notification_repo

    @staticmethod
    def _key(*parts: Any) -> str:
        return json.dumps(parts, ensure_ascii=False, sort_keys=True, default=str)

    def notify_social_result(
        self,
        *,
        action_type: str,
        recipient_id: str,
        sender_id: str,
        sender_nickname: str,
        result: Optional[Dict[str, Any]],
    ) -> None:
        """写入偷鱼/电鱼成功通知和护盾状态变化通知。"""
        if not isinstance(result, dict):
            return

        if result.get("success") and result.get("victim_notification"):
            details = dict(result["victim_notification"])
            if action_type == "steal":
                details.setdefault("stolen_count", 1)
                details.setdefault(
                    "stolen_entries",
                    [
                        {
                            "name": details.get("stolen_fish_name", "未知"),
                            "rarity": details.get("rarity", 0),
                            "quality_level": details.get("quality_level", 0),
                            "value": details.get("value", 0),
                        }
                    ],
                )
                key = self._key(
                    "steal",
                    sender_id,
                    recipient_id,
                )
                self.notification_repo.add_notification(
                    recipient_id=recipient_id,
                    sender_nickname=sender_nickname,
                    noti_type="steal",
                    details=details,
                    aggregate_key=key,
                    aggregate_window_seconds=self.AGGREGATE_WINDOW_SECONDS,
                    merge_fields=["stolen_count", "value", "stolen_entries"],
                )
            elif action_type == "electric_fish":
                key = self._key(
                    "electric_fish",
                    sender_id,
                    recipient_id,
                )
                self.notification_repo.add_notification(
                    recipient_id=recipient_id,
                    sender_nickname=sender_nickname,
                    noti_type="electric_fish",
                    details=details,
                    aggregate_key=key,
                    aggregate_window_seconds=self.AGGREGATE_WINDOW_SECONDS,
                    merge_fields=["stolen_count", "total_value", "stolen_summary"],
                )

        for event in result.get("notification_events", []) or []:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type", ""))
            if event_type not in self.DEFENSE_TYPES:
                continue
            details = dict(event.get("details") or {})
            details.setdefault("action_type", action_type)
            details.setdefault("_event_count", 1)
            key = self._key(
                event_type,
                sender_id,
                action_type,
                details.get("old_layers"),
                details.get("new_layers"),
            )
            self.notification_repo.add_notification(
                recipient_id=recipient_id,
                sender_nickname=sender_nickname,
                noti_type=event_type,
                details=details,
                aggregate_key=key,
                aggregate_window_seconds=self.AGGREGATE_WINDOW_SECONDS,
                merge_fields=["layers_lost", "_event_count"],
            )

    def notify_defense_result(
        self,
        *,
        recipient_id: str,
        sender_id: str,
        sender_nickname: str,
        result: Optional[Dict[str, Any]],
        action_type: str = "dispel_protection",
    ) -> None:
        """写入驱灵香等直接改变他人防御状态的通知。"""
        if not isinstance(result, dict):
            return
        self.notify_social_result(
            action_type=action_type,
            recipient_id=recipient_id,
            sender_id=sender_id,
            sender_nickname=sender_nickname,
            result=result,
        )
