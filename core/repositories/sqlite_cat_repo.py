import sqlite3
import json
import threading
from contextlib import contextmanager
from datetime import datetime
from typing import List, Optional, Any, Type, cast

from ..domain.models import (
    CatTemplate,
    UserCatInstance,
    CatDisease,
    UserCatDisease,
    CatEvent,
    UserCatEventRecord,
)

try:
    from .abstract_repository import AbstractCatRepository as _AbstractCatRepositoryBase
except ImportError:
    _AbstractCatRepositoryBase = object

from ..database.connection_manager import DatabaseConnectionManager
from ..utils import get_now


class SQLiteCatRepository(cast(Type[Any], _AbstractCatRepositoryBase)):
    def __init__(self, db_manager: DatabaseConnectionManager):
        self.db_manager = db_manager
        self._local = threading.local()

    @contextmanager
    def _get_connection(self):
        with self.db_manager.get_connection() as conn:
            conn.row_factory = sqlite3.Row
            self._local.connection = conn
            yield conn

    @staticmethod
    def _parse_dt(value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                return datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                    try:
                        return datetime.strptime(text, fmt)
                    except ValueError:
                        continue
        return None

    @staticmethod
    def _dt_to_db(value: Optional[datetime]) -> Optional[str]:
        return value.isoformat() if value else None

    @staticmethod
    def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
        cur = conn.cursor()
        cur.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ? LIMIT 1",
            (table_name,),
        )
        return cur.fetchone() is not None

    def _row_to_cat_template(self, row: sqlite3.Row) -> Optional[CatTemplate]:
        if not row:
            return None
        return CatTemplate(
            cat_id=row["cat_id"],
            name=row["name"],
            description=row["description"],
            icon_url=row["icon_url"],
            base_hunger=row["base_hunger"],
            base_mood=row["base_mood"],
            base_health=row["base_health"],
            fishing_bonus=row["fishing_bonus"],
            rare_bonus=row["rare_bonus"],
            coin_bonus=row["coin_bonus"],
        )

    def _row_to_user_cat_instance(self, row: sqlite3.Row) -> Optional[UserCatInstance]:
        if not row:
            return None
        return UserCatInstance(
            cat_instance_id=row["cat_instance_id"],
            user_id=row["user_id"],
            cat_id=row["cat_id"],
            nickname=row["nickname"] or "",
            obtained_at=self._parse_dt(row["obtained_at"]) or get_now(),
            hunger=row["hunger"],
            mood=row["mood"],
            health=row["health"],
            level=row["level"],
            exp=row["exp"],
            star=row["star"] if "star" in row.keys() and row["star"] is not None else 1,
            rare_bonus_extra=row["rare_bonus_extra"] if "rare_bonus_extra" in row.keys() and row["rare_bonus_extra"] is not None else 0.0,
            coin_bonus_extra=row["coin_bonus_extra"] if "coin_bonus_extra" in row.keys() and row["coin_bonus_extra"] is not None else 0.0,
            last_feed_time=self._parse_dt(row["last_feed_time"]),
            last_play_time=self._parse_dt(row["last_play_time"]),
            color=row["color"] or "橙色",
            pattern=row["pattern"] or "纯色",
        )

    def _row_to_disease(self, row: sqlite3.Row) -> Optional[CatDisease]:
        if not row:
            return None
        return CatDisease(
            disease_id=row["disease_id"],
            name=row["name"],
            description=row["description"] or "",
            symptom=row["symptom"] or "",
            min_health_threshold=row["min_health_threshold"],
            min_hunger_threshold=row["min_hunger_threshold"],
            min_mood_threshold=row["min_mood_threshold"],
            onset_chance=row["onset_chance"],
            treatment_cost=row["treatment_cost"],
            health_decay_per_hour=int(row["health_decay_per_hour"] or 0),
            fishing_bonus_modifier=row["fishing_bonus_modifier"],
        )

    def _row_to_user_disease(self, row: sqlite3.Row) -> Optional[UserCatDisease]:
        if not row:
            return None
        return UserCatDisease(
            id=row["id"],
            user_id=row["user_id"],
            cat_instance_id=row["cat_instance_id"],
            disease_id=row["disease_id"],
            disease_name=row["disease_name"],
            started_at=self._parse_dt(row["started_at"]) or get_now(),
            is_treated=bool(row["is_treated"]),
            treatment_start=self._parse_dt(row["treatment_start"]),
        )

    def _row_to_event_record(self, row: sqlite3.Row) -> Optional[UserCatEventRecord]:
        if not row:
            return None
        reward_info = row["reward_info"]
        if reward_info is not None and not isinstance(reward_info, str):
            reward_info = json.dumps(reward_info, ensure_ascii=False)
        return UserCatEventRecord(
            record_id=row["record_id"],
            user_id=row["user_id"],
            cat_instance_id=row["cat_instance_id"],
            event_id=row["event_id"] if row["event_id"] is not None else 0,
            event_name=row["event_name"],
            event_type=row["event_type"],
            description=row["description"] or "",
            triggered_at=self._parse_dt(row["triggered_at"]) or get_now(),
            reward_info=reward_info,
        )

    def get_all_cats(self) -> List[CatTemplate]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM cats ORDER BY cat_id ASC")
            result: List[CatTemplate] = []
            for row in cur.fetchall():
                item = self._row_to_cat_template(row)
                if item is not None:
                    result.append(item)
            return result

    def get_cat_by_id(self, cat_id: int) -> Optional[CatTemplate]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM cats WHERE cat_id = ?", (cat_id,))
            return self._row_to_cat_template(cur.fetchone())

    def get_user_cats(self, user_id: str) -> List[UserCatInstance]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                "SELECT * FROM user_cat_instances WHERE user_id = ? ORDER BY obtained_at DESC, cat_instance_id DESC",
                (user_id,),
            )
            result: List[UserCatInstance] = []
            for row in cur.fetchall():
                item = self._row_to_user_cat_instance(row)
                if item is not None:
                    result.append(item)
            return result

    def get_cat_instance(self, cat_instance_id: int) -> Optional[UserCatInstance]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM user_cat_instances WHERE cat_instance_id = ?", (cat_instance_id,))
            return self._row_to_user_cat_instance(cur.fetchone())

    def add_cat_instance(self, cat: UserCatInstance) -> UserCatInstance:
        with self._get_connection() as conn:
            cur = conn.cursor()
            if cat.cat_instance_id and cat.cat_instance_id > 0:
                cur.execute(
                    """
                    INSERT INTO user_cat_instances (
                        cat_instance_id, user_id, cat_id, nickname, obtained_at,
                        hunger, mood, health, level, exp, star, rare_bonus_extra, coin_bonus_extra,
                        last_feed_time, last_play_time, color, pattern
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cat.cat_instance_id,
                        cat.user_id,
                        cat.cat_id,
                        cat.nickname,
                        self._dt_to_db(cat.obtained_at),
                        cat.hunger,
                        cat.mood,
                        cat.health,
                        cat.level,
                        cat.exp,
                        cat.star,
                        cat.rare_bonus_extra,
                        cat.coin_bonus_extra,
                        self._dt_to_db(cat.last_feed_time),
                        self._dt_to_db(cat.last_play_time),
                        cat.color,
                        cat.pattern,
                    ),
                )
                new_id = cat.cat_instance_id
            else:
                cur.execute(
                    """
                    INSERT INTO user_cat_instances (
                        user_id, cat_id, nickname, obtained_at,
                        hunger, mood, health, level, exp, star, rare_bonus_extra, coin_bonus_extra,
                        last_feed_time, last_play_time, color, pattern
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        cat.user_id,
                        cat.cat_id,
                        cat.nickname,
                        self._dt_to_db(cat.obtained_at),
                        cat.hunger,
                        cat.mood,
                        cat.health,
                        cat.level,
                        cat.exp,
                        cat.star,
                        cat.rare_bonus_extra,
                        cat.coin_bonus_extra,
                        self._dt_to_db(cat.last_feed_time),
                        self._dt_to_db(cat.last_play_time),
                        cat.color,
                        cat.pattern,
                    ),
                )
                if cur.lastrowid is None:
                    raise RuntimeError("failed to create cat instance")
                new_id = int(cur.lastrowid)
            conn.commit()
            created = self.get_cat_instance(new_id)
            if created is None:
                raise RuntimeError("failed to fetch created cat instance")
            return created

    def update_cat_instance(self, cat: UserCatInstance) -> None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE user_cat_instances
                SET
                    user_id = ?,
                    cat_id = ?,
                    nickname = ?,
                    obtained_at = ?,
                    hunger = ?,
                    mood = ?,
                    health = ?,
                    level = ?,
                    exp = ?,
                    star = ?,
                    rare_bonus_extra = ?,
                    coin_bonus_extra = ?,
                    last_feed_time = ?,
                    last_play_time = ?,
                    color = ?,
                    pattern = ?
                WHERE cat_instance_id = ?
                """,
                (
                    cat.user_id,
                    cat.cat_id,
                    cat.nickname,
                    self._dt_to_db(cat.obtained_at),
                    cat.hunger,
                    cat.mood,
                    cat.health,
                    cat.level,
                    cat.exp,
                    cat.star,
                    cat.rare_bonus_extra,
                    cat.coin_bonus_extra,
                    self._dt_to_db(cat.last_feed_time),
                    self._dt_to_db(cat.last_play_time),
                    cat.color,
                    cat.pattern,
                    cat.cat_instance_id,
                ),
            )
            conn.commit()

    def remove_cat_instance(self, cat_instance_id: int) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_cat_instances WHERE cat_instance_id = ?", (cat_instance_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_user_cat_count(self, user_id: str) -> int:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) AS c FROM user_cat_instances WHERE user_id = ?", (user_id,))
            row = cur.fetchone()
            return int(row["c"] if row else 0)

    def get_all_cat_instances(self) -> List[UserCatInstance]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM user_cat_instances")
            result: List[UserCatInstance] = []
            for row in cur.fetchall():
                item = self._row_to_user_cat_instance(row)
                if item is not None:
                    result.append(item)
            return result

    def get_all_diseases(self) -> List[CatDisease]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM cat_diseases ORDER BY disease_id ASC")
            result: List[CatDisease] = []
            for row in cur.fetchall():
                item = self._row_to_disease(row)
                if item is not None:
                    result.append(item)
            return result

    def get_disease_by_id(self, disease_id: int) -> Optional[CatDisease]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM cat_diseases WHERE disease_id = ?", (disease_id,))
            return self._row_to_disease(cur.fetchone())

    def get_active_user_diseases(self, user_id: str) -> List[UserCatDisease]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM user_cat_diseases
                WHERE user_id = ? AND is_treated = 0
                ORDER BY started_at DESC, id DESC
                """,
                (user_id,),
            )
            result: List[UserCatDisease] = []
            for row in cur.fetchall():
                item = self._row_to_user_disease(row)
                if item is not None:
                    result.append(item)
            return result

    def get_cat_active_diseases(self, cat_instance_id: int) -> List[UserCatDisease]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM user_cat_diseases
                WHERE cat_instance_id = ? AND is_treated = 0
                ORDER BY started_at DESC, id DESC
                """,
                (cat_instance_id,),
            )
            result: List[UserCatDisease] = []
            for row in cur.fetchall():
                item = self._row_to_user_disease(row)
                if item is not None:
                    result.append(item)
            return result

    def add_user_disease(self, disease: UserCatDisease) -> UserCatDisease:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO user_cat_diseases (
                    user_id, cat_instance_id, disease_id, disease_name,
                    started_at, is_treated, treatment_start
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    disease.user_id,
                    disease.cat_instance_id,
                    disease.disease_id,
                    disease.disease_name,
                    self._dt_to_db(disease.started_at),
                    1 if disease.is_treated else 0,
                    self._dt_to_db(disease.treatment_start),
                ),
            )
            if cur.lastrowid is None:
                raise RuntimeError("failed to create user disease")
            new_id = int(cur.lastrowid)
            conn.commit()
            cur.execute("SELECT * FROM user_cat_diseases WHERE id = ?", (new_id,))
            created = self._row_to_user_disease(cur.fetchone())
            if created is None:
                raise RuntimeError("failed to fetch created user disease")
            return created

    def update_user_disease(self, disease: UserCatDisease) -> None:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE user_cat_diseases
                SET
                    user_id = ?,
                    cat_instance_id = ?,
                    disease_id = ?,
                    disease_name = ?,
                    started_at = ?,
                    is_treated = ?,
                    treatment_start = ?
                WHERE id = ?
                """,
                (
                    disease.user_id,
                    disease.cat_instance_id,
                    disease.disease_id,
                    disease.disease_name,
                    self._dt_to_db(disease.started_at),
                    1 if disease.is_treated else 0,
                    self._dt_to_db(disease.treatment_start),
                    disease.id,
                ),
            )
            conn.commit()

    def mark_disease_treated(self, user_disease_id: int, treatment_start: Optional[datetime] = None) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE user_cat_diseases
                SET is_treated = 1,
                    treatment_start = COALESCE(?, treatment_start)
                WHERE id = ?
                """,
                (self._dt_to_db(treatment_start), user_disease_id),
            )
            conn.commit()
            return cur.rowcount > 0

    def remove_user_disease(self, user_disease_id: int) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_cat_diseases WHERE id = ?", (user_disease_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_all_events(self) -> List[CatEvent]:
        with self._get_connection() as conn:
            if not self._table_exists(conn, "cat_events"):
                return []
            cur = conn.cursor()
            cur.execute("SELECT * FROM cat_events ORDER BY event_id ASC")
            rows = cur.fetchall()
            events: List[CatEvent] = []
            for row in rows:
                trigger_actions_raw = row["trigger_actions"] if "trigger_actions" in row.keys() else "[]"
                if isinstance(trigger_actions_raw, str):
                    try:
                        trigger_actions = json.loads(trigger_actions_raw) if trigger_actions_raw else []
                    except json.JSONDecodeError:
                        trigger_actions = []
                elif isinstance(trigger_actions_raw, list):
                    trigger_actions = trigger_actions_raw
                else:
                    trigger_actions = []

                events.append(
                    CatEvent(
                        event_id=row["event_id"],
                        name=row["name"],
                        description=row["description"] or "",
                        event_type=row["event_type"],
                        trigger_actions=trigger_actions,
                        weight=row["weight"],
                        reward_type=row["reward_type"] if "reward_type" in row.keys() else None,
                        reward_value=row["reward_value"] if "reward_value" in row.keys() else None,
                        reward_item_id=(
                            str(row["reward_item_id"]) if "reward_item_id" in row.keys() and row["reward_item_id"] is not None else None
                        ),
                        penalty_type=row["penalty_type"] if "penalty_type" in row.keys() else None,
                        penalty_value=row["penalty_value"] if "penalty_value" in row.keys() else None,
                        buff_type=row["buff_type"] if "buff_type" in row.keys() else None,
                        buff_duration_minutes=(row["buff_duration_minutes"] if "buff_duration_minutes" in row.keys() else None),
                        is_common=bool(row["is_common"]) if "is_common" in row.keys() else False,
                    )
                )
            return events

    def get_event_by_id(self, event_id: int) -> Optional[CatEvent]:
        events = self.get_all_events()
        for event in events:
            if event.event_id == event_id:
                return event
        return None

    def add_event_record(self, record: UserCatEventRecord) -> UserCatEventRecord:
        with self._get_connection() as conn:
            cur = conn.cursor()
            reward_info = record.reward_info
            if reward_info is not None and not isinstance(reward_info, str):
                reward_info = json.dumps(reward_info, ensure_ascii=False)

            cur.execute(
                """
                INSERT INTO user_cat_events (
                    user_id, cat_instance_id, event_id, event_name,
                    event_type, description, reward_info, triggered_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.user_id,
                    record.cat_instance_id,
                    record.event_id,
                    record.event_name,
                    record.event_type,
                    record.description,
                    reward_info,
                    self._dt_to_db(record.triggered_at),
                ),
            )
            new_id = cur.lastrowid
            conn.commit()
            cur.execute("SELECT * FROM user_cat_events WHERE record_id = ?", (new_id,))
            created = self._row_to_event_record(cur.fetchone())
            if created is None:
                raise RuntimeError("failed to fetch created event record")
            return created

    def get_user_event_records(self, user_id: str, limit: int = 50) -> List[UserCatEventRecord]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM user_cat_events
                WHERE user_id = ?
                ORDER BY triggered_at DESC, record_id DESC
                LIMIT ?
                """,
                (user_id, limit),
            )
            result: List[UserCatEventRecord] = []
            for row in cur.fetchall():
                item = self._row_to_event_record(row)
                if item is not None:
                    result.append(item)
            return result

    def get_cat_event_records(self, cat_instance_id: int, limit: int = 50) -> List[UserCatEventRecord]:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                SELECT * FROM user_cat_events
                WHERE cat_instance_id = ?
                ORDER BY triggered_at DESC, record_id DESC
                LIMIT ?
                """,
                (cat_instance_id, limit),
            )
            result: List[UserCatEventRecord] = []
            for row in cur.fetchall():
                item = self._row_to_event_record(row)
                if item is not None:
                    result.append(item)
            return result

    def remove_event_record(self, record_id: int) -> bool:
        with self._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM user_cat_events WHERE record_id = ?", (record_id,))
            conn.commit()
            return cur.rowcount > 0

    def get_active_disease(self, cat_instance_id: int) -> Optional[UserCatDisease]:
        diseases = self.get_cat_active_diseases(cat_instance_id)
        return diseases[0] if diseases else None

    def add_cat_disease(self, disease: UserCatDisease) -> None:
        self.add_user_disease(disease)

    def update_cat_disease(self, disease: UserCatDisease) -> None:
        self.update_user_disease(disease)

    def add_cat_event(self, event: UserCatEventRecord) -> None:
        self.add_event_record(event)

    def get_recent_events(self, user_id: str, cat_instance_id: int, limit: int = 5) -> List[UserCatEventRecord]:
        return self.get_cat_event_records(cat_instance_id, limit)
