import sqlite3
import os
from datetime import datetime
from dataclasses import dataclass


@dataclass
class Listing:
    source: str
    external_id: str
    title: str
    price: int
    rooms: str
    area_m2: float | None
    district: str
    address: str
    url: str
    image_url: str | None
    description: str | None = None

    @property
    def unique_key(self) -> str:
        return f"{self.source}:{self.external_id}"


class Database:
    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) if os.path.dirname(db_path) else ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self._create_tables()

    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS listings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                external_id TEXT NOT NULL,
                title TEXT NOT NULL,
                price INTEGER NOT NULL,
                rooms TEXT,
                area_m2 REAL,
                district TEXT,
                address TEXT,
                url TEXT NOT NULL,
                image_url TEXT,
                description TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(source, external_id)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_seen (
                user_id INTEGER NOT NULL,
                listing_source TEXT NOT NULL,
                listing_external_id TEXT NOT NULL,
                notified_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (user_id, listing_source, listing_external_id)
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                min_price INTEGER DEFAULT 4000000,
                max_price INTEGER DEFAULT 8000000,
                rooms TEXT DEFAULT '2+kk,2+1',
                city TEXT DEFAULT 'praha',
                paused INTEGER DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS scrape_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                status TEXT NOT NULL,
                listings_found INTEGER DEFAULT 0,
                new_listings INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self.conn.commit()

    # ─── User settings ──────────────────────────────────────────

    def get_user_settings(self, user_id: int) -> dict:
        cursor = self.conn.execute(
            "SELECT min_price, max_price, rooms, city, paused FROM user_settings WHERE user_id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
        if row:
            return {
                "min_price": row[0],
                "max_price": row[1],
                "rooms": row[2].split(","),
                "city": row[3],
                "paused": bool(row[4]),
            }
        defaults = {
            "min_price": 4000000,
            "max_price": 8000000,
            "rooms": ["2+kk", "2+1"],
            "city": "praha",
            "paused": False,
        }
        self._upsert_user_settings(user_id, defaults)
        return defaults

    def _upsert_user_settings(self, user_id: int, settings: dict):
        rooms_str = ",".join(settings["rooms"]) if isinstance(settings["rooms"], list) else settings["rooms"]
        self.conn.execute("""
            INSERT INTO user_settings (user_id, min_price, max_price, rooms, city, paused, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                min_price=excluded.min_price,
                max_price=excluded.max_price,
                rooms=excluded.rooms,
                city=excluded.city,
                paused=excluded.paused,
                updated_at=excluded.updated_at
        """, (user_id, settings["min_price"], settings["max_price"], rooms_str,
              settings["city"], int(settings["paused"]), datetime.now()))
        self.conn.commit()

    def set_user_price(self, user_id: int, min_price: int, max_price: int):
        s = self.get_user_settings(user_id)
        s["min_price"] = min_price
        s["max_price"] = max_price
        self._upsert_user_settings(user_id, s)

    def set_user_rooms(self, user_id: int, rooms: list[str]):
        s = self.get_user_settings(user_id)
        s["rooms"] = rooms
        self._upsert_user_settings(user_id, s)

    def set_user_paused(self, user_id: int, paused: bool):
        s = self.get_user_settings(user_id)
        s["paused"] = paused
        self._upsert_user_settings(user_id, s)

    def get_all_active_users(self) -> list[int]:
        cursor = self.conn.execute(
            "SELECT user_id FROM user_settings WHERE paused = 0"
        )
        return [row[0] for row in cursor.fetchall()]

    # ─── Listings ───────────────────────────────────────────────

    def listing_exists(self, listing: Listing) -> bool:
        """Skontroluje či inzerát už existuje v DB (bez uloženia)."""
        cursor = self.conn.execute(
            "SELECT 1 FROM listings WHERE source = ? AND external_id = ?",
            (listing.source, listing.external_id)
        )
        return cursor.fetchone() is not None

    def save_listing(self, listing: Listing) -> bool:
        try:
            self.conn.execute(
                """INSERT INTO listings (source, external_id, title, price, rooms, area_m2,
                   district, address, url, image_url, description)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (listing.source, listing.external_id, listing.title, listing.price,
                 listing.rooms, listing.area_m2, listing.district, listing.address,
                 listing.url, listing.image_url, listing.description)
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def is_seen_by_user(self, user_id: int, listing: Listing) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM user_seen WHERE user_id = ? AND listing_source = ? AND listing_external_id = ?",
            (user_id, listing.source, listing.external_id)
        )
        return cursor.fetchone() is not None

    def mark_seen_by_user(self, user_id: int, listing: Listing):
        try:
            self.conn.execute(
                """INSERT OR IGNORE INTO user_seen (user_id, listing_source, listing_external_id)
                   VALUES (?, ?, ?)""",
                (user_id, listing.source, listing.external_id)
            )
            self.conn.commit()
        except Exception:
            pass

    def get_all_listings(self) -> list["Listing"]:
        cursor = self.conn.execute(
            """SELECT source, external_id, title, price, rooms, area_m2,
               district, address, url, image_url, description
               FROM listings ORDER BY created_at DESC"""
        )
        results = []
        for row in cursor.fetchall():
            results.append(Listing(
                source=row[0], external_id=row[1], title=row[2], price=row[3],
                rooms=row[4], area_m2=row[5], district=row[6], address=row[7],
                url=row[8], image_url=row[9], description=row[10]
            ))
        return results

    def listing_matches_user(self, listing: "Listing", settings: dict) -> bool:
        if listing.price < settings["min_price"] or listing.price > settings["max_price"]:
            return False
        user_rooms = [r.lower().strip() for r in settings["rooms"]]
        if listing.rooms and listing.rooms.lower().strip() not in user_rooms:
            return False
        return True

    # ─── Logs & stats ───────────────────────────────────────────

    def log_scrape(self, source: str, status: str, found: int = 0, new: int = 0, error: str | None = None):
        self.conn.execute(
            """INSERT INTO scrape_log (source, status, listings_found, new_listings, error_message)
               VALUES (?, ?, ?, ?, ?)""",
            (source, status, found, new, error)
        )
        self.conn.commit()

    def get_stats(self, user_id: int | None = None) -> dict:
        cursor = self.conn.execute("SELECT COUNT(*) FROM listings")
        total = cursor.fetchone()[0]

        cursor = self.conn.execute("SELECT source, COUNT(*) FROM listings GROUP BY source")
        by_source = dict(cursor.fetchall())

        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM listings WHERE created_at > datetime('now', '-1 day')"
        )
        last_24h = cursor.fetchone()[0]

        seen_by_user = None
        if user_id is not None:
            cursor = self.conn.execute(
                "SELECT COUNT(*) FROM user_seen WHERE user_id = ?", (user_id,)
            )
            seen_by_user = cursor.fetchone()[0]

        return {"total": total, "by_source": by_source, "last_24h": last_24h, "seen_by_user": seen_by_user}

    def get_latest(self, limit: int = 5) -> list[dict]:
        cursor = self.conn.execute(
            """SELECT title, price, rooms, district, url, source, created_at
               FROM listings ORDER BY created_at DESC LIMIT ?""",
            (limit,)
        )
        columns = ["title", "price", "rooms", "district", "url", "source", "created_at"]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def close(self):
        self.conn.close()
