import sqlite3


def up(cursor: sqlite3.Cursor):
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cats (
            cat_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            icon_url TEXT,
            base_hunger INTEGER NOT NULL DEFAULT 100,
            base_mood INTEGER NOT NULL DEFAULT 100,
            base_health INTEGER NOT NULL DEFAULT 100,
            fishing_bonus REAL NOT NULL DEFAULT 0.0,
            rare_bonus REAL NOT NULL DEFAULT 0.0,
            coin_bonus REAL NOT NULL DEFAULT 0.0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_cat_instances (
            cat_instance_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            cat_id INTEGER NOT NULL,
            nickname TEXT,
            obtained_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            hunger INTEGER NOT NULL DEFAULT 100,
            mood INTEGER NOT NULL DEFAULT 100,
            health INTEGER NOT NULL DEFAULT 100,
            level INTEGER NOT NULL DEFAULT 1,
            exp INTEGER NOT NULL DEFAULT 0,
            star INTEGER NOT NULL DEFAULT 1,
            rare_bonus_extra REAL NOT NULL DEFAULT 0.0,
            coin_bonus_extra REAL NOT NULL DEFAULT 0.0,
            last_feed_time TEXT,
            last_play_time TEXT,
            color TEXT,
            pattern TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (cat_id) REFERENCES cats(cat_id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cat_diseases (
            disease_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            symptom TEXT,
            min_health_threshold INTEGER NOT NULL DEFAULT 0,
            min_hunger_threshold INTEGER NOT NULL DEFAULT 0,
            min_mood_threshold INTEGER NOT NULL DEFAULT 0,
            onset_chance REAL NOT NULL DEFAULT 0.0,
            treatment_cost INTEGER NOT NULL DEFAULT 0,
            health_decay_per_hour REAL NOT NULL DEFAULT 0.0,
            fishing_bonus_modifier REAL NOT NULL DEFAULT 0.0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_cat_diseases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            cat_instance_id INTEGER NOT NULL,
            disease_id INTEGER,
            disease_name TEXT NOT NULL,
            started_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            is_treated INTEGER NOT NULL DEFAULT 0 CHECK (is_treated IN (0, 1)),
            treatment_start TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (cat_instance_id) REFERENCES user_cat_instances(cat_instance_id) ON DELETE CASCADE,
            FOREIGN KEY (disease_id) REFERENCES cat_diseases(disease_id) ON DELETE SET NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS user_cat_events (
            record_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            cat_instance_id INTEGER NOT NULL,
            event_id INTEGER,
            event_name TEXT NOT NULL,
            event_type TEXT NOT NULL,
            description TEXT,
            reward_info TEXT,
            triggered_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime')),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (cat_instance_id) REFERENCES user_cat_instances(cat_instance_id) ON DELETE CASCADE
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cats_rarity
        ON cats(rarity)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_cat_instances_user
        ON user_cat_instances(user_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_cat_instances_cat
        ON user_cat_instances(cat_id)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_cat_instances_user_cat
        ON user_cat_instances(user_id, cat_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_cat_diseases_name
        ON cat_diseases(name)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_cat_diseases_user_treated
        ON user_cat_diseases(user_id, is_treated)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_cat_diseases_cat_treated
        ON user_cat_diseases(cat_instance_id, is_treated)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_cat_diseases_disease
        ON user_cat_diseases(disease_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_cat_events_user_time
        ON user_cat_events(user_id, triggered_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_cat_events_cat_time
        ON user_cat_events(cat_instance_id, triggered_at)
    """)
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_cat_events_event_type
        ON user_cat_events(event_type)
    """)


def down(cursor: sqlite3.Cursor):
    cursor.execute("DROP INDEX IF EXISTS idx_user_cat_events_event_type")
    cursor.execute("DROP INDEX IF EXISTS idx_user_cat_events_cat_time")
    cursor.execute("DROP INDEX IF EXISTS idx_user_cat_events_user_time")

    cursor.execute("DROP INDEX IF EXISTS idx_user_cat_diseases_disease")
    cursor.execute("DROP INDEX IF EXISTS idx_user_cat_diseases_cat_treated")
    cursor.execute("DROP INDEX IF EXISTS idx_user_cat_diseases_user_treated")

    cursor.execute("DROP INDEX IF EXISTS idx_cat_diseases_name")

    cursor.execute("DROP INDEX IF EXISTS idx_user_cat_instances_user_cat")
    cursor.execute("DROP INDEX IF EXISTS idx_user_cat_instances_cat")
    cursor.execute("DROP INDEX IF EXISTS idx_user_cat_instances_user")

    cursor.execute("DROP INDEX IF EXISTS idx_cats_rarity")

    cursor.execute("DROP TABLE IF EXISTS user_cat_events")
    cursor.execute("DROP TABLE IF EXISTS user_cat_diseases")
    cursor.execute("DROP TABLE IF EXISTS cat_diseases")
    cursor.execute("DROP TABLE IF EXISTS user_cat_instances")
    cursor.execute("DROP TABLE IF EXISTS cats")
