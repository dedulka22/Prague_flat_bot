import sqlite3
import os
from datetime import datetime
from dataclasses import dataclass


@dataclass
class Listing:
    source: str          # sreality, bezrealitky, idnes, bazos
    external_id: str     # unique ID from the source
    title: str
    price: int
    rooms: str           # e.g. "2+kk"
    area_m2: float | None
    district: str        # e.g. "Praha 4"
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
        self.conn = sqlite3.connect(db_path)
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
                notified_at TIMESTAMP,
                UNIQUE(source, external_id)
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

    def is_seen(self, listing: Listing) -> bool:
        cursor = self.conn.execute(
            "SELECT 1 FROM listings WHERE source = ? AND external_id = ?",
            (listing.source, listing.external_id)
        )
        return cursor.fetchone() is not None

    def save_listing(self, listing: Listing) -> bool:
        """Save listing. Returns True if new (not duplicate)."""
        try:
            self.conn.execute(
                """INSERT INTO listings (source, external_id, title, price, rooms, area_m2,
                   district, address, url, image_url, description, notified_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (listing.source, listing.external_id, listing.title, listing.price,
                 listing.rooms, listing.area_m2, listing.district, listing.address,
                 listing.url, listing.image_url, listing.description, datetime.now())
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def log_scrape(self, source: str, status: str, found: int = 0, new: int = 0, error: str | None = None):
        self.conn.execute(
            """INSERT INTO scrape_log (source, status, listings_found, new_listings, error_message)
               VALUES (?, ?, ?, ?, ?)""",
            (source, status, found, new, error)
        )
        self.conn.commit()

    def get_stats(self) -> dict:
        cursor = self.conn.execute("SELECT COUNT(*) FROM listings")
        total = cursor.fetchone()[0]

        cursor = self.conn.execute(
            "SELECT source, COUNT(*) FROM listings GROUP BY source"
        )
        by_source = dict(cursor.fetchall())

        cursor = self.conn.execute(
            "SELECT COUNT(*) FROM listings WHERE created_at > datetime('now', '-1 day')"
        )
        last_24h = cursor.fetchone()[0]

        return {"total": total, "by_source": by_source, "last_24h": last_24h}

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
