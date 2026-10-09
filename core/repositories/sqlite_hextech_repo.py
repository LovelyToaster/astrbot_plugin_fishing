"""SQLite persistence for daily Hextech card selections."""

import json
import sqlite3
import threading
from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple


class SqliteHextechRepository:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._local = threading.local()

    def _get_connection(self) -> sqlite3.Connection:
        conn = getattr(self._local, "connection", None)
        if conn is None:
            conn = sqlite3.connect(self.db_path, timeout=30)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA busy_timeout = 30000")
            self._local.connection = conn
        return conn

    @staticmethod
    def _row_to_state(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
        if row is None:
            return None
        return {
            "actor_id": row["actor_id"],
            "game_day": row["game_day"],
            "tier": row["tier"],  # Legacy compatibility: first offer's tier, not a shared tier.
            "offers": json.loads(row["offers_json"]),
            "reroll_count": row["reroll_count"],
            "selected_index": row["selected_index"],
            "created_at": row["created_at"],
            "selected_at": row["selected_at"],
        }

    def get_daily_state(self, actor_id: str, game_day: str) -> Optional[Dict[str, Any]]:
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM hextech_daily_choices WHERE actor_id = ? AND game_day = ?",
                (str(actor_id), game_day),
            ).fetchone()
        return self._row_to_state(row)

    def get_latest_daily_state(self, actor_id: str, game_day: str) -> Optional[Dict[str, Any]]:
        """The newest offer set is a barrier even when no card was selected."""
        with self._get_connection() as conn:
            row = conn.execute(
                """SELECT * FROM hextech_daily_choices
                WHERE actor_id = ? AND game_day <= ?
                ORDER BY game_day DESC LIMIT 1""",
                (str(actor_id), game_day),
            ).fetchone()
        return self._row_to_state(row)

    @staticmethod
    def _has_history_table(conn: sqlite3.Connection) -> bool:
        return conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='hextech_offer_history'"
        ).fetchone() is not None

    def get_offer_history_weights(
        self,
        actor_id: str,
        game_day: str,
        window_days: int = 7,
        same_day_weight: float = 0.15,
        recent_weight: float = 0.5,
    ) -> Dict[str, float]:
        """Return the most recent exposure weight for each effect in the window."""
        try:
            end_day = date.fromisoformat(str(game_day))
            window_days = int(window_days)
        except (TypeError, ValueError):
            return {}
        if window_days <= 0:
            return {}
        start_day = (end_day - timedelta(days=window_days - 1)).isoformat()
        with self._get_connection() as conn:
            if not self._has_history_table(conn):
                return {}
            rows = conn.execute(
                """SELECT DISTINCT effect_id, game_day FROM hextech_offer_history
                WHERE actor_id = ? AND game_day BETWEEN ? AND ?""",
                (str(actor_id), start_day, end_day.isoformat()),
            ).fetchall()
        weights: Dict[str, float] = {}
        for row in rows:
            weight = (
                same_day_weight
                if row["game_day"] == end_day.isoformat()
                else recent_weight
            )
            effect_id = str(row["effect_id"])
            weights[effect_id] = min(weights.get(effect_id, 1.0), float(weight))
        return weights

    @staticmethod
    def _record_offer_history(
        conn: sqlite3.Connection,
        actor_id: str,
        game_day: str,
        shown_effect_counts: Optional[Dict[str, int]],
        shown_at: str,
    ) -> None:
        if not shown_effect_counts or not SqliteHextechRepository._has_history_table(conn):
            return
        for effect_id, raw_count in shown_effect_counts.items():
            count = int(raw_count)
            if count <= 0:
                continue
            conn.execute(
                """INSERT INTO hextech_offer_history
                    (actor_id, game_day, effect_id, shown_count, last_shown_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(actor_id, game_day, effect_id) DO UPDATE SET
                    shown_count = shown_count + excluded.shown_count,
                    last_shown_at = excluded.last_shown_at""",
                (str(actor_id), str(game_day), str(effect_id), count, str(shown_at)),
            )

    @staticmethod
    def _prune_offer_history(
        conn: sqlite3.Connection,
        actor_id: str,
        game_day: str,
        window_days: int,
    ) -> None:
        if not SqliteHextechRepository._has_history_table(conn):
            return
        try:
            end_day = date.fromisoformat(str(game_day))
            window_days = int(window_days)
        except (TypeError, ValueError):
            return
        if window_days <= 0:
            return
        cutoff = (end_day - timedelta(days=window_days - 1)).isoformat()
        conn.execute(
            "DELETE FROM hextech_offer_history WHERE actor_id = ? AND game_day < ?",
            (str(actor_id), cutoff),
        )

    def create_daily_state(
        self,
        actor_id: str,
        game_day: str,
        tier: str,
        offers: list,
        created_at: str,
        shown_effect_counts: Optional[Dict[str, int]] = None,
        history_window_days: int = 7,
    ) -> Tuple[Dict[str, Any], bool]:
        """Insert once under concurrent requests and return the persisted winner."""
        conn = self._get_connection()
        with conn:
            cursor = conn.execute(
                """
                INSERT OR IGNORE INTO hextech_daily_choices
                    (actor_id, game_day, tier, offers_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    str(actor_id),
                    game_day,
                    tier,
                    json.dumps(offers, ensure_ascii=False, separators=(",", ":")),
                    created_at,
                ),
            )
            created = cursor.rowcount == 1
            if created:
                self._record_offer_history(
                    conn, actor_id, game_day, shown_effect_counts, created_at
                )
                self._prune_offer_history(conn, actor_id, game_day, history_window_days)
            row = conn.execute(
                "SELECT * FROM hextech_daily_choices WHERE actor_id = ? AND game_day = ?",
                (str(actor_id), game_day),
            ).fetchone()
        state = self._row_to_state(row)
        if state is None:
            raise RuntimeError("failed to persist daily Hextech state")
        return state, created

    def reroll_daily_offers(
        self,
        actor_id: str,
        game_day: str,
        offers: list,
        shown_effect_counts: Optional[Dict[str, int]] = None,
        shown_at: Optional[str] = None,
        history_window_days: int = 7,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Atomically replace all offers, enforcing the daily limit and selection lock."""
        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM hextech_daily_choices WHERE actor_id = ? AND game_day = ?",
                (str(actor_id), game_day),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None, "missing"
            if row["selected_index"] is not None:
                conn.rollback()
                return self._row_to_state(row), "selected"
            if row["reroll_count"] >= 2:
                conn.rollback()
                return self._row_to_state(row), "limit_reached"

            conn.execute(
                """
                UPDATE hextech_daily_choices
                SET offers_json = ?, tier = ?, reroll_count = reroll_count + 1
                WHERE actor_id = ? AND game_day = ?
                """,
                (
                    json.dumps(offers, ensure_ascii=False, separators=(",", ":")),
                    offers[0]["tier"],
                    str(actor_id),
                    game_day,
                ),
            )
            self._record_offer_history(
                conn,
                actor_id,
                game_day,
                shown_effect_counts,
                shown_at or "",
            )
            self._prune_offer_history(conn, actor_id, game_day, history_window_days)
            updated = conn.execute(
                "SELECT * FROM hextech_daily_choices WHERE actor_id = ? AND game_day = ?",
                (str(actor_id), game_day),
            ).fetchone()
            conn.commit()
            return self._row_to_state(updated), "rerolled"
        except Exception:
            conn.rollback()
            raise

    def select_daily_card(
        self,
        actor_id: str,
        game_day: str,
        selected_index: int,
        selected_at: str,
    ) -> Tuple[Optional[Dict[str, Any]], str]:
        """Atomically lock one of the three offers as today's card."""
        if selected_index not in (0, 1, 2):
            return None, "invalid_index"

        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            row = conn.execute(
                "SELECT * FROM hextech_daily_choices WHERE actor_id = ? AND game_day = ?",
                (str(actor_id), game_day),
            ).fetchone()
            if row is None:
                conn.rollback()
                return None, "missing"
            if row["selected_index"] is not None:
                conn.rollback()
                return self._row_to_state(row), "already_selected"

            conn.execute(
                """
                UPDATE hextech_daily_choices
                SET selected_index = ?, selected_at = ?
                WHERE actor_id = ? AND game_day = ? AND selected_index IS NULL
                """,
                (selected_index, selected_at, str(actor_id), game_day),
            )
            updated = conn.execute(
                "SELECT * FROM hextech_daily_choices WHERE actor_id = ? AND game_day = ?",
                (str(actor_id), game_day),
            ).fetchone()
            conn.commit()
            return self._row_to_state(updated), "selected"
        except Exception:
            conn.rollback()
            raise

    def reset_all_users(self) -> Dict[str, int]:
        """Clear all offer history so carried cards cannot reappear after reset.

        The wheel snapshot is also a Hextech effect; clear it while preserving
        the player's round, stake, prize and progress. Everything commits once.
        """
        conn = self._get_connection()
        conn.execute("BEGIN IMMEDIATE")
        try:
            actors = {row[0] for row in conn.execute(
                "SELECT DISTINCT actor_id FROM hextech_daily_choices"
            )}
            records = conn.execute("DELETE FROM hextech_daily_choices").rowcount
            if self._has_history_table(conn):
                actors.update(row[0] for row in conn.execute(
                    "SELECT DISTINCT actor_id FROM hextech_offer_history"
                ))
                conn.execute("DELETE FROM hextech_offer_history")
            snapshots = 0
            columns = {row[1] for row in conn.execute("PRAGMA table_info(users)")}
            if "wof_hextech_snapshot" in columns:
                actors.update(row[0] for row in conn.execute(
                    "SELECT user_id FROM users WHERE wof_hextech_snapshot IS NOT NULL"
                ))
                snapshots = conn.execute(
                    "UPDATE users SET wof_hextech_snapshot = NULL WHERE wof_hextech_snapshot IS NOT NULL"
                ).rowcount
            conn.commit()
            return {"users": len(actors), "records": records, "wheel_snapshots": snapshots}
        except Exception:
            conn.rollback()
            raise
