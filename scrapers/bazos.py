import logging
import re

import aiohttp
from bs4 import BeautifulSoup

from database import Listing
from .base import BaseScraper, HEADERS

logger = logging.getLogger(__name__)

BASE_URL = "https://reality.bazos.cz"


class BazosScraper(BaseScraper):
    name = "bazos"

    def _build_url(self) -> str:
        # Opravená URL – Bazos zmenil štruktúru
        return (
            f"{BASE_URL}/byty/prodam/praha/"
            f"?cena_od={self.min_price}&cena_do={self.max_price}"
        )

    async def scrape(self, session: aiohttp.ClientSession) -> list[Listing]:
        url = self._build_url()
        try:
            async with session.get(url, headers=HEADERS, allow_redirects=True) as resp:
                if resp.status != 200:
                    logger.warning(f"Bazos HTTP {resp.status} (url: {url})")
                    return []
                html = await resp.text()
                return self._parse_html(html)
        except Exception as e:
            logger.warning(f"Bazos error: {e}")
            return []

    def _parse_html(self, html: str) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        # Bazos listing containers
        items = soup.select(".inzeraty .inzerat")
        if not items:
            items = soup.select(".inzerat")
        if not items:
            # Fallback – hľadáme podľa štruktúry
            items = soup.select("div[class*='inzer']")

        for item in items:
            try:
                listing = self._parse_item(item)
                if listing:
                    if listing.rooms and not self.matches_rooms(listing.rooms):
                        continue
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"Bazos parse error: {e}")

        return listings

    def _parse_item(self, item) -> Listing | None:
        link_el = item.select_one("a.nadpis, h2 a, h3 a, a[href*='/inzerat/']")
        if not link_el:
            link_el = item.select_one("a")
        if not link_el:
            return None

        href = link_el.get("href", "")
        if not href:
            return None
        if not href.startswith("http"):
            href = f"{BASE_URL}{href}"

        title = link_el.get_text(strip=True)

        id_match = re.search(r"/inzerat/(\d+)", href)
        external_id = id_match.group(1) if id_match else str(hash(href))

        price = 0
        price_el = item.select_one(".inzeratycena, [class*='cena']")
        if price_el:
            price = self._parse_price(price_el.get_text(strip=True)) or 0

        if price and (price < self.min_price or price > self.max_price):
            return None

        desc_el = item.select_one(".inzeratypopis, [class*='popis']")
        description = desc_el.get_text(strip=True) if desc_el else ""

        rooms = self._extract_rooms(title) or self._extract_rooms(description)

        img_el = item.select_one("img")
        image_url = img_el.get("src", "") if img_el else None
        if image_url and not image_url.startswith("http"):
            image_url = f"https://reality.bazos.cz{image_url}"

        locality_el = item.select_one(".inzeratylok, [class*='lokalit']")
        address = locality_el.get_text(strip=True) if locality_el else ""

        district = ""
        full_text = f"{title} {address} {description}"
        praha_match = re.search(r"Praha\s*\d*", full_text)
        if praha_match:
            district = praha_match.group(0)

        area = None
        area_match = re.search(r"(\d+)\s*m[²2]", full_text)
        if area_match:
            area = float(area_match.group(1))

        return Listing(
            source="bazos",
            external_id=external_id,
            title=title,
            price=price,
            rooms=rooms,
            area_m2=area,
            district=district,
            address=address,
            url=href,
            image_url=image_url,
            description=description[:500] if description else None,
        )

    @staticmethod
    def _extract_rooms(text: str) -> str:
        if not text:
            return ""
        text_lower = text.lower()
        for pattern in ["5+1", "5+kk", "4+1", "4+kk", "3+1", "3+kk", "2+1", "2+kk", "1+1", "1+kk"]:
            if pattern in text_lower:
                return pattern
        return ""

    @staticmethod
    def _parse_price(text: str) -> int | None:
        if not text:
            return None
        cleaned = re.sub(r"[^\d]", "", text)
        try:
            return int(cleaned) if cleaned else None
        except ValueError:
            return None
