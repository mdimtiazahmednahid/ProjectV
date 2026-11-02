import sqlite3
import os
import logging
from typing import List, Optional
from app.models.share_profile import ShareProfile
from app.models.collection_session import CollectionSession

logger = logging.getLogger(__name__)

class DatabaseRepository:
    def __init__(self, db_path: str = "data/facebook_shares.sqlite"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_db()

    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS collection_sessions (
                        id TEXT PRIMARY KEY,
                        start_time TEXT,
                        end_time TEXT,
                        status TEXT,
                        total_profiles INTEGER,
                        total_scrolls INTEGER
                    )
                """)
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS profiles (
                        id TEXT PRIMARY KEY,
                        name TEXT,
                        profile_url TEXT,
                        share_url TEXT,
                        source TEXT,
                        confidence REAL,
                        first_seen_at TEXT,
                        last_seen_at TEXT,
                        session_id TEXT,
                        scroll_index INTEGER,
                        content TEXT,
                        reactions TEXT,
                        comments TEXT,
                        action_type TEXT DEFAULT 'share',
                        avatar_hash TEXT,
                        avatar_path TEXT,
                        FOREIGN KEY(session_id) REFERENCES collection_sessions(id)
                    )
                """)
                
                # Dynamic column addition for backward compatibility
                cursor.execute("PRAGMA table_info(profiles)")
                columns = [info[1] for info in cursor.fetchall()]
                if 'content' not in columns:
                    cursor.execute("ALTER TABLE profiles ADD COLUMN content TEXT")
                if 'reactions' not in columns:
                    cursor.execute("ALTER TABLE profiles ADD COLUMN reactions TEXT")
                if 'comments' not in columns:
                    cursor.execute("ALTER TABLE profiles ADD COLUMN comments TEXT")
                if 'action_type' not in columns:
                    cursor.execute("ALTER TABLE profiles ADD COLUMN action_type TEXT DEFAULT 'share'")
                if 'avatar_hash' not in columns:
                    cursor.execute("ALTER TABLE profiles ADD COLUMN avatar_hash TEXT")
                if 'avatar_path' not in columns:
                    cursor.execute("ALTER TABLE profiles ADD COLUMN avatar_path TEXT")
                
                # Create indexes to speed up deduplication searches
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_profiles_url ON profiles(profile_url)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_profiles_name ON profiles(name)")
                cursor.execute("CREATE INDEX IF NOT EXISTS idx_profiles_avatar ON profiles(avatar_hash)")
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Database initialization failed: {e}")

    def create_session(self, session: CollectionSession):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO collection_sessions (id, start_time, end_time, status, total_profiles, total_scrolls) VALUES (?, ?, ?, ?, ?, ?)",
                    (session.id, session.start_time, session.end_time, session.status, session.total_profiles, session.total_scrolls)
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to create session in db: {e}")

    def update_session(self, session: CollectionSession):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "UPDATE collection_sessions SET end_time = ?, status = ?, total_profiles = ?, total_scrolls = ? WHERE id = ?",
                    (session.end_time, session.status, session.total_profiles, session.total_scrolls, session.id)
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to update session in db: {e}")

    def save_profile(self, profile: ShareProfile):
        self.save_profiles_batch([profile])

    def save_profiles_batch(self, profiles: List[ShareProfile]):
        if not profiles:
            return
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.executemany(
                    """
                    INSERT OR REPLACE INTO profiles (
                        id, name, profile_url, share_url, source, confidence,
                        first_seen_at, last_seen_at, session_id, scroll_index,
                        content, reactions, comments, action_type, avatar_hash, avatar_path
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            p.id, p.name, p.profile_url, p.share_url, p.source, p.confidence,
                            p.first_seen_at, p.last_seen_at, p.session_id, p.scroll_index,
                            p.content, p.reactions, p.comments,
                            getattr(p, 'action_type', 'share'),
                            getattr(p, 'avatar_hash', None),
                            getattr(p, 'avatar_path', None),
                        )
                        for p in profiles
                    ]
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to batch save profiles in db: {e}")

    def update_profile_last_seen(self, profile_id: str, last_seen_at: str):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("UPDATE profiles SET last_seen_at = ? WHERE id = ?", (last_seen_at, profile_id))
                conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to update profile last_seen in db: {e}")

    def get_all_profiles_for_session(self, session_id: str) -> List[ShareProfile]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM profiles WHERE session_id = ?", (session_id,))
                rows = cursor.fetchall()
                
                # Fetch column names to build dictionary dynamically
                column_names = [description[0] for description in cursor.description]
                
                profiles = []
                for row in rows:
                    row_dict = dict(zip(column_names, row))
                    profiles.append(ShareProfile(
                        id=row_dict.get('id'), 
                        name=row_dict.get('name'), 
                        profile_url=row_dict.get('profile_url'), 
                        share_url=row_dict.get('share_url'),
                        source=row_dict.get('source'), 
                        confidence=row_dict.get('confidence'), 
                        first_seen_at=row_dict.get('first_seen_at'),
                        last_seen_at=row_dict.get('last_seen_at'), 
                        session_id=row_dict.get('session_id'), 
                        scroll_index=row_dict.get('scroll_index', 0),
                        content=row_dict.get('content', None),
                        reactions=row_dict.get('reactions', None),
                        comments=row_dict.get('comments', None),
                        action_type=row_dict.get('action_type') or 'share',
                        avatar_hash=row_dict.get('avatar_hash', None),
                        avatar_path=row_dict.get('avatar_path', None)
                    ))
                return profiles
        except sqlite3.Error as e:
            logger.error(f"Failed to get profiles for session: {e}")
            return []

    def get_sessions(self) -> List[CollectionSession]:
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM collection_sessions ORDER BY start_time DESC")
                rows = cursor.fetchall()
                sessions = []
                for row in rows:
                    sessions.append(CollectionSession(
                        id=row[0], start_time=row[1], end_time=row[2], status=row[3],
                        total_profiles=row[4], total_scrolls=row[5]
                    ))
                return sessions
        except sqlite3.Error as e:
            logger.error(f"Failed to get sessions: {e}")
            return []
