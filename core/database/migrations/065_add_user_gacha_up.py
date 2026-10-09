"""Persist each user's personal UP choice for each gacha pool."""

import sqlite3


def up(cursor: sqlite3.Cursor):
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_gacha_up (
            user_id TEXT NOT NULL,
            gacha_pool_id INTEGER NOT NULL,
            up_pool_item_id INTEGER NOT NULL,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, gacha_pool_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (gacha_pool_id) REFERENCES gacha_pools(gacha_pool_id) ON DELETE CASCADE,
            FOREIGN KEY (up_pool_item_id) REFERENCES gacha_pool_items(gacha_pool_item_id) ON DELETE CASCADE
        )
        """
    )
    cursor.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_user_gacha_up_item
        ON user_gacha_up(up_pool_item_id)
        """
    )
    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS user_gacha_up_invalidations (
            user_id TEXT NOT NULL,
            gacha_pool_id INTEGER NOT NULL,
            reason TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (user_id, gacha_pool_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (gacha_pool_id) REFERENCES gacha_pools(gacha_pool_id) ON DELETE CASCADE
        )
        """
    )


def down(cursor: sqlite3.Cursor):
    raise NotImplementedError("Personal gacha UP choices are saved user preferences")
