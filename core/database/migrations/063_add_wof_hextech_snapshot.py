"""Freeze the selected Hextech card for each wheel-of-fate game."""


def up(cursor):
    columns = {row[1] for row in cursor.execute("PRAGMA table_info(users)")}
    if "wof_hextech_snapshot" not in columns:
        cursor.execute("ALTER TABLE users ADD COLUMN wof_hextech_snapshot TEXT")


def down(cursor):
    raise NotImplementedError("Active wheel games must retain their card snapshots")
