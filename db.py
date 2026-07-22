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
    task_type TEXT NOT NULL DEFAULT 'main',
    deadline_at TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS task_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'delivered',
    submission_chat_id INTEGER,
    submission_message_id INTEGER,
    submitted_at TEXT,
    reviewed_at TEXT,
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

            # Safe migration for task review on existing Railway databases.
            cur = await db.execute("PRAGMA table_info(task_deliveries)")
            delivery_columns = {row[1] for row in await cur.fetchall()}
            delivery_migrations = {
                "status": "ALTER TABLE task_deliveries ADD COLUMN status TEXT NOT NULL DEFAULT 'delivered'",
                "submission_chat_id": "ALTER TABLE task_deliveries ADD COLUMN submission_chat_id INTEGER",
                "submission_message_id": "ALTER TABLE task_deliveries ADD COLUMN submission_message_id INTEGER",
                "submitted_at": "ALTER TABLE task_deliveries ADD COLUMN submitted_at TEXT",
                "reviewed_at": "ALTER TABLE task_deliveries ADD COLUMN reviewed_at TEXT",
            }

            for column, sql in delivery_migrations.items():
                if column not in delivery_columns:
                    await db.execute(sql)

            # Safe migration for task types and individual deadlines.
            cur = await db.execute("PRAGMA table_info(tasks)")
            task_columns = {row[1] for row in await cur.fetchall()}
            task_migrations = {
                "task_type": "ALTER TABLE tasks ADD COLUMN task_type TEXT NOT NULL DEFAULT 'main'",
                "deadline_at": "ALTER TABLE tasks ADD COLUMN deadline_at TEXT",
            }

            for column, sql in task_migrations.items():
                if column not in task_columns:
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

    async def public_players(self, exclude_tg_user_id: int, limit: int = 100):
        """Return only fields that are allowed in the public players section."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT tg_user_id, first_name, occupation, photo_file_id,
                       points, current_day
                FROM players
                WHERE profile_complete=1 AND tg_user_id<>?
                ORDER BY first_name COLLATE NOCASE ASC, created_at ASC
                LIMIT ?
                """,
                (exclude_tg_user_id, limit),
            )
            return await cur.fetchall()

    async def get_public_player(self, tg_user_id: int):
        """Return one completed player without private onboarding answers."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT tg_user_id, first_name, occupation, photo_file_id,
                       points, current_day
                FROM players
                WHERE tg_user_id=? AND profile_complete=1
                """,
                (tg_user_id,),
            )
            return await cur.fetchone()

    async def create_task(
        self,
        title: str,
        description: str,
        points: int,
        created_by: int,
        task_type: str = "main",
        deadline_at: str | None = None,
    ):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                INSERT INTO tasks (
                    title, description, points, created_by, task_type, deadline_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (title, description, points, created_by, task_type, deadline_at),
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

    async def latest_task_for_player(self, tg_user_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT td.id AS delivery_id, td.status,
                       t.id AS task_id, t.title, t.description, t.points,
                       t.task_type, t.deadline_at
                FROM task_deliveries td
                JOIN tasks t ON t.id=td.task_id
                JOIN players p ON p.id=td.player_id
                WHERE p.tg_user_id=?
                ORDER BY t.id DESC
                LIMIT 1
                """,
                (tg_user_id,),
            )
            return await cur.fetchone()

    async def active_tasks_for_player(self, tg_user_id: int):
        """Return all delivered tasks whose individual deadline has not passed."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT td.id AS delivery_id, td.status,
                       t.id AS task_id, t.title, t.description, t.points,
                       t.task_type, t.deadline_at
                FROM task_deliveries td
                JOIN tasks t ON t.id=td.task_id
                JOIN players p ON p.id=td.player_id
                WHERE p.tg_user_id=?
                  AND t.is_active=1
                  AND (t.deadline_at IS NULL OR t.deadline_at > CURRENT_TIMESTAMP)
                ORDER BY
                    CASE t.task_type
                        WHEN 'main' THEN 1
                        WHEN 'media' THEN 2
                        ELSE 3
                    END,
                    t.deadline_at ASC,
                    t.id ASC
                """,
                (tg_user_id,),
            )
            return await cur.fetchall()

    async def get_task_delivery(self, task_id: int, tg_user_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT td.id AS delivery_id, td.status,
                       t.id AS task_id, t.title, t.description, t.points,
                       t.task_type, t.deadline_at,
                       p.tg_user_id, p.first_name, p.topic_id
                FROM task_deliveries td
                JOIN tasks t ON t.id=td.task_id
                JOIN players p ON p.id=td.player_id
                WHERE t.id=? AND p.tg_user_id=?
                """,
                (task_id, tg_user_id),
            )
            return await cur.fetchone()

    async def mark_task_submitted(
        self,
        delivery_id: int,
        tg_user_id: int,
        submission_chat_id: int,
        submission_message_id: int,
    ):
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                UPDATE task_deliveries
                SET status='submitted',
                    submission_chat_id=?,
                    submission_message_id=?,
                    submitted_at=CURRENT_TIMESTAMP,
                    reviewed_at=NULL
                WHERE id=?
                  AND player_id=(SELECT id FROM players WHERE tg_user_id=?)
                  AND status IN ('delivered', 'revision')
                  AND EXISTS (
                      SELECT 1
                      FROM tasks t
                      WHERE t.id=task_deliveries.task_id
                        AND (t.deadline_at IS NULL OR t.deadline_at > CURRENT_TIMESTAMP)
                  )
                """,
                (submission_chat_id, submission_message_id, delivery_id, tg_user_id),
            )
            await db.commit()
            return cur.rowcount == 1

    async def restore_task_submission(
        self,
        delivery_id: int,
        tg_user_id: int,
        previous_status: str,
        submission_chat_id: int,
        submission_message_id: int,
    ):
        """Unlock a submission only when forwarding it to the host failed."""
        if previous_status not in {"delivered", "revision"}:
            return False
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                """
                UPDATE task_deliveries
                SET status=?, submission_chat_id=NULL, submission_message_id=NULL,
                    submitted_at=NULL, reviewed_at=NULL
                WHERE id=?
                  AND player_id=(SELECT id FROM players WHERE tg_user_id=?)
                  AND status='submitted'
                  AND submission_chat_id=?
                  AND submission_message_id=?
                """,
                (
                    previous_status,
                    delivery_id,
                    tg_user_id,
                    submission_chat_id,
                    submission_message_id,
                ),
            )
            await db.commit()
            return cur.rowcount == 1

    async def get_task_submission(self, delivery_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                """
                SELECT td.id AS delivery_id, td.status,
                       td.submission_chat_id, td.submission_message_id,
                       t.title, t.points,
                       p.tg_user_id, p.first_name, p.topic_id, p.points AS current_points
                FROM task_deliveries td
                JOIN tasks t ON t.id=td.task_id
                JOIN players p ON p.id=td.player_id
                WHERE td.id=?
                """,
                (delivery_id,),
            )
            return await cur.fetchone()

    async def accept_task_submission(self, delivery_id: int):
        """Atomically accept one submission and add its points exactly once."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                """
                SELECT td.status, t.title, t.points AS task_points,
                       p.id AS player_id, p.tg_user_id, p.first_name,
                       p.points AS current_points
                FROM task_deliveries td
                JOIN tasks t ON t.id=td.task_id
                JOIN players p ON p.id=td.player_id
                WHERE td.id=?
                """,
                (delivery_id,),
            )
            row = await cur.fetchone()
            if not row:
                await db.rollback()
                return None
            if row["status"] != "submitted":
                await db.rollback()
                return {"status": row["status"]}

            total = row["current_points"] + row["task_points"]
            await db.execute(
                "UPDATE players SET points=? WHERE id=?",
                (total, row["player_id"]),
            )
            await db.execute(
                "INSERT INTO point_events (player_id, delta, reason) VALUES (?, ?, ?)",
                (row["player_id"], row["task_points"], f"Задание: {row['title']}"),
            )
            await db.execute(
                """
                UPDATE task_deliveries
                SET status='accepted', reviewed_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (delivery_id,),
            )
            await db.commit()
            return {
                "status": "accepted",
                "title": row["title"],
                "points": row["task_points"],
                "total": total,
                "tg_user_id": row["tg_user_id"],
                "first_name": row["first_name"],
            }

    async def return_task_for_revision(self, delivery_id: int):
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            await db.execute("BEGIN IMMEDIATE")
            cur = await db.execute(
                """
                SELECT td.status, t.title, p.tg_user_id, p.first_name,
                       CASE
                           WHEN t.deadline_at IS NOT NULL
                                AND t.deadline_at <= CURRENT_TIMESTAMP
                           THEN 1 ELSE 0
                       END AS deadline_expired
                FROM task_deliveries td
                JOIN tasks t ON t.id=td.task_id
                JOIN players p ON p.id=td.player_id
                WHERE td.id=?
                """,
                (delivery_id,),
            )
            row = await cur.fetchone()
            if not row:
                await db.rollback()
                return None
            if row["status"] != "submitted":
                await db.rollback()
                return {"status": row["status"]}
            if row["deadline_expired"]:
                await db.rollback()
                return {"status": "expired"}

            await db.execute(
                """
                UPDATE task_deliveries
                SET status='revision', reviewed_at=CURRENT_TIMESTAMP
                WHERE id=?
                """,
                (delivery_id,),
            )
            await db.commit()
            return {
                "status": "revision",
                "title": row["title"],
                "tg_user_id": row["tg_user_id"],
                "first_name": row["first_name"],
            }

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

    async def delete_player(self, tg_user_id: int):
        """
        Deletes a player and all game data linked to that player.
        Returns the deleted player's topic_id for optional topic cleanup.
        """
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(
                "SELECT id, topic_id FROM players WHERE tg_user_id=?",
                (tg_user_id,),
            )
            player = await cur.fetchone()
            if not player:
                return None

            player_id = player["id"]
            topic_id = player["topic_id"]

            await db.execute("DELETE FROM task_deliveries WHERE player_id=?", (player_id,))
            await db.execute("DELETE FROM point_events WHERE player_id=?", (player_id,))
            await db.execute("DELETE FROM secret_missions WHERE player_id=?", (player_id,))
            await db.execute("DELETE FROM player_achievements WHERE player_id=?", (player_id,))
            await db.execute("DELETE FROM players WHERE id=?", (player_id,))
            await db.commit()
            return topic_id

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
