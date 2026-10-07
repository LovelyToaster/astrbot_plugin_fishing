"""Persist daily Hextech offers, rerolls, and the selected card."""


def up(cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS hextech_daily_choices (
            actor_id TEXT NOT NULL,
            game_day TEXT NOT NULL,
            tier TEXT NOT NULL CHECK (tier IN ('silver', 'gold', 'prismatic')),
            offers_json TEXT NOT NULL,
            reroll_count INTEGER NOT NULL DEFAULT 0 CHECK (reroll_count BETWEEN 0 AND 2),
            selected_index INTEGER CHECK (selected_index IS NULL OR selected_index BETWEEN 0 AND 2),
            created_at TEXT NOT NULL,
            selected_at TEXT,
            PRIMARY KEY (actor_id, game_day)
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_hextech_daily_game_day
        ON hextech_daily_choices(game_day)
        """
    )


def down(cursor):
    raise NotImplementedError("Daily Hextech selections are gameplay history and cannot be rolled back safely")
