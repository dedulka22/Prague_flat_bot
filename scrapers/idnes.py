import logging
import re

import aiohttp
from bs4 import BeautifulSoup

from database import Listing
from .base import BaseScraper, HEADERS

logger = logging.getLogger(__name__)

BASE_URL = "https://reality.idnes.cz"

# Aktuálne URL slugy pre iDnes (opravené 2026)
ROOM_SLUGS = {
    "1+kk": "1-kk",
    "1+1": "1-1",
    "2+kk": "2-kk",
    "2+1": "2-1",
    "3+kk": "3-kk",
    "3+1": "3-1",
    "4+kk": "4-kk",
    "4+1": "4-1",
}


class IdnesScraper(BaseScraper):
    name = "idnes"

    def _build_url(self, room_slug: str) -> str:
        # Nový formát URL: /s/prodej/byty/praha/?velikost=2-kk&cena-od=X&cena-do=Y
        return (
            f"{BASE_URL}/s/prodej/byty/praha/"
            f"?velikost={room_slug}"
            f"&cena-od={self.min_price}&cena-do={self.max_price}"
        )

    async def scrape(self, session: aiohttp.ClientSession) -> list[Listing]:
        listings = []

        for room in self.rooms:
            room_key = room.strip().lower()
            slug = ROOM_SLUGS.get(room_key)
            if not slug:
                continue

            url = self._build_url(slug)
            try:
                async with session.get(url, headers=HEADERS, allow_redirects=True) as resp:
                    if resp.status != 200:
                        logger.warning(f"Idnes HTTP {resp.status} for {room_key} (url: {url})")
                        continue
                    html = await resp.text()
                    parsed = self._parse_html(html, room_key)
                    listings.extend(parsed)
            except Exception as e:
                logger.warning(f"Idnes error for {room_key}: {e}")

        return listings

    def _parse_html(self, html: str, rooms: str) -> list[Listing]:
        soup = BeautifulSoup(html, "html.parser")
        listings = []

        # iDnes používa rôzne selektory – skúsime viacero
        items = soup.select(".c-products__item")
        if not items:
            items = soup.select("article.b-reality-item")
        if not items:
            items = soup.select("[class*='product']")

        for item in items:
            try:
                listing = self._parse_item(item, rooms)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"Idnes item parse error: {e}")

        return listings

    def _parse_item(self, item, rooms: str) -> Listing | None:
        link_el = item.select_one("a[href*='/detail/']")
        if not link_el:
            link_el = item.select_one("a")
        if not link_el:
            return None

        href = link_el.get("href", "")
        if not href.startswith("http"):
            href = f"{BASE_URL}{href}"

        title_el = item.select_one("h2, h3, .c-products__title, [class*='title']")
        title = title_el.get_text(strip=True) if title_el else link_el.get_text(strip=True)

        external_id_match = re.search(r"/detail/([^/?]+)", href)
        external_id = external_id_match.group(1) if external_id_match else str(hash(href))

        price_el = item.select_one(".c-products__price, [class*='price'], [class*='cena']")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = self._parse_price(price_text) or 0

        if price and (price < self.min_price or price > self.max_price):
            return None

        img_el = item.select_one("img")
        image_url = img_el.get("src", "") if img_el else None
        if image_url and not image_url.startswith("http"):
            image_url = f"https:{image_url}"

        locality_el = item.select_one("[class*='locality'], [class*='address'], [class*='location']")
        address = locality_el.get_text(strip=True) if locality_el else ""

        district = ""
        if "Praha" in address:
            match = re.search(r"Praha\s*\d*", address)
            district = match.group(0) if match else "Praha"

        area = None
        area_match = re.search(r"(\d+)\s*m[²2]", title + " " + address)
        if area_match:
            area = float(area_match.group(1))

        return Listing(
            source="idnes",
            external_id=external_id,
            title=title,
            price=price,
            rooms=rooms,
            area_m2=area,
            district=district,
            address=address,
            url=href,
            image_url=image_url,
        )

    @staticmethod
    def _parse_price(text: str) -> int | None:
        if not text:
            return None
        cleaned = re.sub(r"[^\d]", "", text)
        try:
            return int(cleaned) if cleaned else None
        except ValueError:
            return None
