import asyncio
import logging
from abc import ABC, abstractmethod

import aiohttp

from database import Listing

logger = logging.getLogger(__name__)

# Common headers to avoid blocks
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "cs-CZ,cs;q=0.9,en;q=0.8",
    "Accept": "application/json, text/html, */*",
}


class BaseScraper(ABC):
    """Base class for all real estate scrapers."""

    name: str = "base"

    def __init__(self, min_price: int, max_price: int, rooms: list[str]):
        self.min_price = min_price
        self.max_price = max_price
        self.rooms = rooms

    @abstractmethod
    async def scrape(self, session: aiohttp.ClientSession) -> list[Listing]:
        """Fetch listings from the portal. Must be implemented by subclasses."""
        ...

    async def safe_scrape(self, session: aiohttp.ClientSession) -> list[Listing]:
        """Wraps scrape with error handling and retry."""
        for attempt in range(3):
            try:
                listings = await self.scrape(session)
                logger.info(f"✅ {self.name}: {len(listings)} ponúk nájdených")
                return listings
            except Exception as e:
                logger.warning(f"⚠️ {self.name} pokus {attempt + 1}/3 zlyhal: {e}")
                if attempt < 2:
                    await asyncio.sleep(5 * (attempt + 1))
        logger.error(f"❌ {self.name}: všetky pokusy zlyhali")
        return []

    @staticmethod
    def normalize_rooms(raw: str) -> str:
        """Normalize room layout string."""
        if not raw:
            return ""
        raw = raw.strip().lower().replace(" ", "")
        # Normalize common formats
        for pattern in ["2+kk", "2+1", "3+kk", "3+1", "1+kk", "1+1", "4+kk", "4+1", "5+kk", "5+1"]:
            if pattern in raw:
                return pattern
        return raw

    def matches_rooms(self, rooms_str: str) -> bool:
        """Check if a room layout matches our filter."""
        normalized = self.normalize_rooms(rooms_str)
        return any(self.normalize_rooms(r) == normalized for r in self.rooms)
