from pathlib import Path
import aiosqlite

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tg_user_id INTEGER UNIQUE NOT NULL,
    username TEXT,
    first_name TEXT,
    last_name TEXT,
    topic_id INTEGER UNIQUE,
    points INTEGER NOT NULL DEFAULT 0,
    streak INTEGER NOT NULL DEFAULT 0,
    max_streak INTEGER NOT NULL DEFAULT 0,
    current_day INTEGER NOT NULL DEFAULT 1,
    occupation TEXT,
    point_a TEXT,
    goal_21 TEXT,
    photo_file_id TEXT,
    profile_complete INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    points INTEGER NOT NULL,
    created_by INTEGER,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    delivered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(task_id, player_id)
);

CREATE TABLE IF NOT EXISTS point_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    delta INTEGER NOT NULL,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS secret_missions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    points INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    image_key TEXT
);

CREATE TABLE IF NOT EXISTS player_achievements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    achievement_id INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(player_id, achievement_id)
);
"""

class Database:
    def __init__(self, path: str):
        self.path = path

    async def init(self):
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(SCHEMA)

            # Безопасная миграция для уже существующей базы.
            cur = await db.execute("PRAGMA table_info(players)")
            columns = {row[1] for row in await cur.fetchall()}

            migrations = {
                "occupation": "ALTER TABLE players ADD COLUMN occupation TEXT",
                "point_a": "ALTER TABLE players ADD COLUMN point_a TEXT",
                "goal_21": "ALTER TABLE players ADD COLUMN goal_21 TEXT",
                "photo_file_id": "ALTER TABLE players ADD COLUMN photo_file_id TEXT",
                "profile_complete": "ALTER TABLE players ADD COLUMN profile_complete INTEGER NOT NULL DEFAULT 0",
            }

            for column, sql in migrations.items():
                if column not in columns:
                    await db.execute(sql)

            await db.commit()

    async def upsert_player(self, user):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO players (tg_user_id, username, first_name, last_name)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(tg_user_id) DO UPDATE SET
                    username=excluded.username,
                    first_name=excluded.first_name,
                    last_name=excluded.last_name
                """,
                (user.id, user.username, user.first_name, user.last_name),
            )
            await db.commit()
        return await self.get_player(user.id)

    async def get_player(self, tg_user_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM players WHERE tg_user_id=?",
                (tg_user_id,),
            )
            return await cur.fetchone()

    async def player_exists(self, tg_user_id: int) -> bool:
        player = await self.get_player(tg_user_id)
        return player is not None

    async def get_or_create_player(self, user):
        """
        Telegram user_id is the permanent identity key.
        Existing progress/profile/topic are never reset here.
        """
        existing = await self.get_player(user.id)
        if existing:
            # Only refresh public Telegram identity fields.
            async with aiosqlite.connect(self.path) as db:
                await db.execute(
                    """
                    UPDATE players
                    SET username=?, first_name=COALESCE(NULLIF(first_name, ''), ?), last_name=?
                    WHERE tg_user_id=?
                    """,
                    (user.username, user.first_name, user.last_name, user.id),
                )
                await db.commit()
            return await self.get_player(user.id)

        return await self.upsert_player(user)

    async def get_player_by_topic(self, topic_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT * FROM players WHERE topic_id=?",
                (topic_id,),
            )
            return await cur.fetchone()

    async def set_topic(self, tg_user_id: int, topic_id: int):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE players SET topic_id=? WHERE tg_user_id=?",
                (topic_id, tg_user_id),
            )
            await db.commit()

    async def all_players(self):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT * FROM players ORDER BY created_at ASC")
            return await cur.fetchall()

    async def create_task(self, title: str, description: str, points: int, created_by: int):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO tasks (title, description, points, created_by)
                VALUES (?, ?, ?, ?)
                """,
                (title, description, points, created_by),
            )
            await db.commit()
            return cur.lastrowid

    async def mark_task_delivered(self, task_id: int, tg_user_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT id FROM players WHERE tg_user_id=?", (tg_user_id,))
            player = await cur.fetchone()
            if not player:
                return
            await db.execute(
                "INSERT OR IGNORE INTO task_deliveries (task_id, player_id) VALUES (?, ?)",
                (task_id, player["id"]),
            )
            await db.commit()

    async def add_points(self, tg_user_id: int, delta: int, reason: str):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, points FROM players WHERE tg_user_id=?",
                (tg_user_id,),
            )
            player = await cur.fetchone()
            if not player:
                raise ValueError("Игрок не найден")

            total = player["points"] + delta
            await db.execute("UPDATE players SET points=? WHERE id=?", (total, player["id"]))
            await db.execute(
                "INSERT INTO point_events (player_id, delta, reason) VALUES (?, ?, ?)",
                (player["id"], delta, reason),
            )
            await db.commit()
            return total

    async def save_player_profile(
        self,
        tg_user_id: int,
        first_name: str,
        occupation: str,
        point_a: str,
        goal_21: str,
        photo_file_id: str,
    ):
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                UPDATE players
                SET first_name=?,
                    occupation=?,
                    point_a=?,
                    goal_21=?,
                    photo_file_id=?,
                    profile_complete=1
                WHERE tg_user_id=?
                """,
                (first_name, occupation, point_a, goal_21, photo_file_id, tg_user_id),
            )
            await db.commit()

    async def leaderboard(self, limit: int = 20):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT tg_user_id, first_name, username, points, streak, current_day
                FROM players
                ORDER BY points DESC, created_at ASC
                LIMIT ?
                """,
                (limit,),
            )
            return await cur.fetchall()

    async def create_secret_mission(self, tg_user_id: int, title: str, description: str, points: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute("SELECT id FROM players WHERE tg_user_id=?", (tg_user_id,))
            player = await cur.fetchone()
            if not player:
                raise ValueError("Игрок не найден")
            await db.execute(
                """
                INSERT INTO secret_missions (player_id, title, description, points)
                VALUES (?, ?, ?, ?)
                """,
                (player["id"], title, description, points),
            )
            await db.commit()
