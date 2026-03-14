import logging

import aiohttp

from database import Listing
from .base import BaseScraper, HEADERS

logger = logging.getLogger(__name__)

# Sreality API constants
SREALITY_API = "https://www.sreality.cz/api/cs/v2/estates"

# Category: 1 = byt, Type: 1 = prodej
CATEGORY_BYT = 1
TYPE_PRODEJ = 1

# Sreality room type IDs
ROOM_MAP = {
    "1+kk": "2",
    "1+1": "3",
    "2+kk": "4",
    "2+1": "5",
    "3+kk": "6",
    "3+1": "7",
    "4+kk": "8",
    "4+1": "9",
    "5+kk": "10",
    "5+1": "11",
}

# Sreality locality: Praha = region 10
REGION_PRAHA = 10


class SrealityScraper(BaseScraper):
    name = "sreality"

    async def scrape(self, session: aiohttp.ClientSession) -> list[Listing]:
        listings = []

        # Map room filters to sreality sub-type IDs
        sub_types = []
        for room in self.rooms:
            room_key = room.strip().lower()
            if room_key in ROOM_MAP:
                sub_types.append(ROOM_MAP[room_key])

        params = {
            "category_main_cb": CATEGORY_BYT,
            "category_type_cb": TYPE_PRODEJ,
            "czk_price_summary_order2": f"{self.min_price}|{self.max_price}",
            "locality_region_id": REGION_PRAHA,
            "per_page": 60,
            "page": 1,
            "tms": 1,
        }

        if sub_types:
            params["category_sub_cb"] = "|".join(sub_types)

        # Fetch up to 3 pages
        for page in range(1, 4):
            params["page"] = page

            async with session.get(SREALITY_API, params=params, headers=HEADERS) as resp:
                if resp.status != 200:
                    logger.warning(f"Sreality HTTP {resp.status}")
                    break

                data = await resp.json()
                estates = data.get("_embedded", {}).get("estates", [])

                if not estates:
                    break

                for estate in estates:
                    try:
                        listing = self._parse_estate(estate)
                        if listing:
                            listings.append(listing)
                    except Exception as e:
                        logger.debug(f"Sreality parse error: {e}")

        return listings

    def _parse_estate(self, estate: dict) -> Listing | None:
        estate_id = str(estate.get("hash_id", ""))
        if not estate_id:
            return None

        name = estate.get("name", "")
        locality = estate.get("locality", "")
        price = estate.get("price", 0)

        # Skip out of range (API sometimes returns edge cases)
        if price < self.min_price or price > self.max_price:
            return None

        # Extract room info from name (e.g. "Prodej bytu 2+kk 54 m²")
        rooms = ""
        for r in ROOM_MAP:
            if r in name.lower():
                rooms = r
                break

        # Extract area
        area = None
        seo = estate.get("seo", {})
        if "m2" in name:
            try:
                parts = name.split("m²")[0].split()
                area = float(parts[-1].replace(",", "."))
            except (ValueError, IndexError):
                pass

        # Image
        image_url = None
        images = estate.get("_links", {}).get("images", [])
        if images:
            image_url = images[0].get("href", "")
            if image_url and not image_url.startswith("http"):
                image_url = f"https:{image_url}"

        # Build URL
        seo_locality = seo.get("locality", "praha")
        url = f"https://www.sreality.cz/detail/prodej/byt/{rooms.replace('+', '%2B')}/{seo_locality}/{estate_id}"

        # District from locality (e.g. "Praha 4 - Nusle")
        district = ""
        if "Praha" in locality:
            parts = locality.split("-")
            district = parts[0].strip()

        return Listing(
            source="sreality",
            external_id=estate_id,
            title=name,
            price=price,
            rooms=rooms,
            area_m2=area,
            district=district,
            address=locality,
            url=url,
            image_url=image_url,
        )
