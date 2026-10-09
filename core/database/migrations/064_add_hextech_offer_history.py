"""Persist effect exposure for recent Hextech offer generation."""


def up(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS hextech_offer_history (
            actor_id TEXT NOT NULL,
            game_day TEXT NOT NULL,
            effect_id TEXT NOT NULL,
            shown_count INTEGER NOT NULL DEFAULT 1 CHECK (shown_count > 0),
            last_shown_at TEXT NOT NULL,
            PRIMARY KEY (actor_id, game_day, effect_id)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hextech_offer_history_actor_day
        ON hextech_offer_history(actor_id, game_day)
        """
    )


def down(cursor):
    raise NotImplementedError("Displayed Hextech offers are gameplay history")
