import sqlite3

from astrbot.api import logger


def _rebuild_fish_table(cursor: sqlite3.Cursor, table_name: str, old_table_name: str, include_added_at: bool) -> None:
    """Add unit_value to a fish container while preserving existing rows."""
    cursor.execute(f"ALTER TABLE {table_name} RENAME TO {old_table_name}")

    no_sell_column_definition = "no_sell_until DATETIME," if not include_added_at else ""
    added_at_column = ", added_at DATETIME DEFAULT CURRENT_TIMESTAMP" if include_added_at else ""
    added_at_select = ", old.added_at" if include_added_at else ""
    added_at_insert = ", added_at" if include_added_at else ""
    no_sell_select = ", old.no_sell_until" if not include_added_at else ""
    no_sell_insert = ", no_sell_until" if not include_added_at else ""

    cursor.execute(
        f"""
        CREATE TABLE {table_name} (
            user_id TEXT NOT NULL,
            fish_id INTEGER NOT NULL,
            quality_level INTEGER DEFAULT 0 CHECK (quality_level IN (0, 1)),
            unit_value INTEGER NOT NULL CHECK (unit_value >= 0),
            quantity INTEGER DEFAULT 0 CHECK (quantity >= 0),
            {no_sell_column_definition[:-1] if no_sell_column_definition else ''}{added_at_column.lstrip(', ')},
            PRIMARY KEY (user_id, fish_id, quality_level, unit_value),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (fish_id) REFERENCES fish(fish_id) ON DELETE CASCADE
        )
        """
    )

    cursor.execute(
        f"""
        INSERT INTO {table_name} (
            user_id, fish_id, quality_level, unit_value, quantity{no_sell_insert}{added_at_insert}
        )
        SELECT
            old.user_id,
            old.fish_id,
            COALESCE(old.quality_level, 0),
            CAST(f.base_value * (1 + COALESCE(old.quality_level, 0)) AS INTEGER),
            old.quantity{no_sell_select}{added_at_select}
        FROM {old_table_name} old
        JOIN fish f ON f.fish_id = old.fish_id
        WHERE old.quantity > 0
        """
    )

    cursor.execute(f"DROP TABLE {old_table_name}")


def up(cursor: sqlite3.Cursor):
    """Persist the exact fish settlement price across pond/aquarium transfers."""
    logger.info("正在执行 061_add_fish_unit_value_snapshot: 保存鱼的结算单价快照...")

    _rebuild_fish_table(
        cursor,
        "user_fish_inventory",
        "user_fish_inventory_old_061",
        include_added_at=False,
    )
    _rebuild_fish_table(
        cursor,
        "user_aquarium",
        "user_aquarium_old_061",
        include_added_at=True,
    )

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_fish_inventory_user ON user_fish_inventory(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_fish_inventory_fish ON user_fish_inventory(fish_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_aquarium_user ON user_aquarium(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_user_aquarium_fish ON user_aquarium(fish_id)")

    cursor.execute("PRAGMA table_info(market)")
    market_columns = {row[1] for row in cursor.fetchall()}
    if "unit_value" not in market_columns:
        cursor.execute("ALTER TABLE market ADD COLUMN unit_value INTEGER")

    cursor.execute(
        """
        UPDATE market
        SET unit_value = (
            SELECT CAST(f.base_value * (1 + COALESCE(market.quality_level, 0)) AS INTEGER)
            FROM fish f
            WHERE f.fish_id = market.item_id
        )
        WHERE item_type = 'fish' AND unit_value IS NULL
        """
    )


def down(cursor: sqlite3.Cursor):
    """Rollback is intentionally omitted; unit values are gameplay data."""
    raise NotImplementedError("061_add_fish_unit_value_snapshot cannot be rolled back safely")
