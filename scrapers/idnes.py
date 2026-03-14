import logging
import re

import aiohttp
from bs4 import BeautifulSoup

from database import Listing
from .base import BaseScraper, HEADERS

logger = logging.getLogger(__name__)

# Reality.idnes.cz URL patterns
BASE_URL = "https://reality.idnes.cz"

# Room type slug mapping for idnes URL
ROOM_SLUGS = {
    "1+kk": "1-plus-kk",
    "1+1": "1-plus-1",
    "2+kk": "2-plus-kk",
    "2+1": "2-plus-1",
    "3+kk": "3-plus-kk",
    "3+1": "3-plus-1",
    "4+kk": "4-plus-kk",
    "4+1": "4-plus-1",
}


class IdnesScraper(BaseScraper):
    name = "idnes"

    def _build_url(self, room: str, page: int = 1) -> str:
        slug = ROOM_SLUGS.get(room.strip().lower(), "")
        # Format: /s/prodej/byty/2-plus-kk/praha/cena-od-X-do-Y/
        url = f"{BASE_URL}/s/prodej/byty/{slug}/praha/"
        url += f"cena-od-{self.min_price}-do-{self.max_price}/"
        if page > 1:
            url += f"?page={page}"
        return url

    async def scrape(self, session: aiohttp.ClientSession) -> list[Listing]:
        listings = []

        for room in self.rooms:
            room_key = room.strip().lower()
            if room_key not in ROOM_SLUGS:
                continue

            url = self._build_url(room_key)

            try:
                async with session.get(url, headers=HEADERS) as resp:
                    if resp.status != 200:
                        logger.warning(f"Idnes HTTP {resp.status} for {room_key}")
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

        # idnes uses .c-products__item for each listing
        items = soup.select(".c-products__item, .c-list-products__item, article[class*='product']")

        for item in items:
            try:
                listing = self._parse_item(item, rooms)
                if listing:
                    listings.append(listing)
            except Exception as e:
                logger.debug(f"Idnes item parse error: {e}")

        return listings

    def _parse_item(self, item, rooms: str) -> Listing | None:
        # Title and link
        link_el = item.select_one("a[href*='/detail/']")
        if not link_el:
            link_el = item.select_one("a")
        if not link_el:
            return None

        href = link_el.get("href", "")
        if not href.startswith("http"):
            href = f"{BASE_URL}{href}"

        title = link_el.get_text(strip=True)
        if not title:
            title_el = item.select_one("h2, h3, .c-products__title")
            title = title_el.get_text(strip=True) if title_el else ""

        # Extract ID from URL
        external_id = re.search(r"/detail/(\d+)", href)
        if not external_id:
            # Use hash of URL as fallback
            external_id = str(hash(href))
        else:
            external_id = external_id.group(1)

        # Price
        price_el = item.select_one(".c-products__price, [class*='price']")
        price_text = price_el.get_text(strip=True) if price_el else ""
        price = self._parse_price(price_text)

        if price and (price < self.min_price or price > self.max_price):
            return None

        # Image
        img_el = item.select_one("img")
        image_url = img_el.get("src", "") if img_el else None
        if image_url and not image_url.startswith("http"):
            image_url = f"https:{image_url}"

        # Location
        locality_el = item.select_one(".c-products__info, [class*='locality']")
        address = locality_el.get_text(strip=True) if locality_el else ""

        district = ""
        if "Praha" in address:
            match = re.search(r"Praha\s*\d*", address)
            district = match.group(0) if match else "Praha"

        # Area
        area = None
        area_match = re.search(r"(\d+)\s*m[²2]", title + " " + address)
        if area_match:
            area = float(area_match.group(1))

        return Listing(
            source="idnes",
            external_id=external_id,
            title=title,
            price=price or 0,
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
        # Remove currency symbols and spaces: "5 490 000 Kč" → 5490000
        cleaned = re.sub(r"[^\d]", "", text)
        try:
            return int(cleaned) if cleaned else None
        except ValueError:
            return None
