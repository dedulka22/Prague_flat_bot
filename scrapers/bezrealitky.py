import json
import logging

import aiohttp

from database import Listing
from .base import BaseScraper, HEADERS

logger = logging.getLogger(__name__)

# Bezrealitky zmenilo endpoint – nový je s lomkou na konci
BEZREALITKY_API = "https://api.bezrealitky.cz/graphql/"

DISPOSITION_MAP = {
    "1+kk": "DISPOSITION_1_KK",
    "1+1": "DISPOSITION_1_1",
    "2+kk": "DISPOSITION_2_KK",
    "2+1": "DISPOSITION_2_1",
    "3+kk": "DISPOSITION_3_KK",
    "3+1": "DISPOSITION_3_1",
    "4+kk": "DISPOSITION_4_KK",
    "4+1": "DISPOSITION_4_1",
    "5+kk": "DISPOSITION_5_KK",
    "5+1": "DISPOSITION_5_1",
}

GRAPHQL_QUERY = """
query ListAdverts($input: AdvertListInput!) {
  listAdverts(input: $input) {
    list {
      id
      uri
      headline
      price
      surface
      disposition
      address
      publicImages {
        url
      }
    }
    totalCount
  }
}
"""


class BezrealitkyScraper(BaseScraper):
    name = "bezrealitky"

    async def scrape(self, session: aiohttp.ClientSession) -> list[Listing]:
        listings = []

        dispositions = []
        for room in self.rooms:
            key = room.strip().lower()
            if key in DISPOSITION_MAP:
                dispositions.append(DISPOSITION_MAP[key])

        variables = {
            "input": {
                "offerType": "PRODEJ",
                "estateType": "BYT",
                "disposition": dispositions if dispositions else None,
                "priceTo": self.max_price,
                "priceFrom": self.min_price,
                "regionOsmIds": ["R435514"],  # Praha
                "order": "TIMEORDER_DESC",
                "limit": 50,
                "offset": 0,
            }
        }

        headers = {
            **HEADERS,
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Origin": "https://www.bezrealitky.cz",
            "Referer": "https://www.bezrealitky.cz/",
        }

        payload = {"query": GRAPHQL_QUERY, "variables": variables}

        async with session.post(BEZREALITKY_API, json=payload, headers=headers) as resp:
            if resp.status != 200:
                logger.warning(f"Bezrealitky HTTP {resp.status}")
                return []

            data = await resp.json(content_type=None)
            adverts = (
                data.get("data", {})
                .get("listAdverts", {})
                .get("list", [])
            )

            for advert in adverts:
                try:
                    listing = self._parse_advert(advert)
                    if listing:
                        listings.append(listing)
                except Exception as e:
                    logger.debug(f"Bezrealitky parse error: {e}")

        return listings

    def _parse_advert(self, advert: dict) -> Listing | None:
        advert_id = str(advert.get("id", ""))
        if not advert_id:
            return None

        price = advert.get("price", 0) or 0
        if price < self.min_price or price > self.max_price:
            return None

        disposition = advert.get("disposition", "")
        rooms = ""
        for readable, api_val in DISPOSITION_MAP.items():
            if api_val == disposition:
                rooms = readable
                break

        image_url = None
        images = advert.get("publicImages", [])
        if images and images[0].get("url"):
            image_url = images[0]["url"]

        uri = advert.get("uri", "")
        url = f"https://www.bezrealitky.cz/nemovitosti-byty-domy/{uri}" if uri else ""

        address = advert.get("address", "") or ""
        district = ""
        if "Praha" in address:
            for part in address.split(","):
                if "Praha" in part:
                    district = part.strip()
                    break

        return Listing(
            source="bezrealitky",
            external_id=advert_id,
            title=advert.get("headline", "") or "",
            price=price,
            rooms=rooms,
            area_m2=advert.get("surface"),
            district=district,
            address=address,
            url=url,
            image_url=image_url,
        )
