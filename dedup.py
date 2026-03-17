"""
Cross-portal deduplication.
Matches listings across portals by normalized address + rooms + area.
Keeps only the cheapest version of each unique flat.
"""

import re
import logging
from dataclasses import dataclass

from database import Listing

logger = logging.getLogger(__name__)

# Words to strip when normalizing addresses
STRIP_WORDS = [
    "prodej", "bytu", "byt", "praha", "ulice", "ul.", "č.p.",
    "česká republika", "česko", "cz",
]


def normalize_address(address: str) -> str:
    """Normalize address for comparison across portals."""
    if not address:
        return ""
    text = address.lower().strip()

    # Remove diacritics-insensitive common words
    for word in STRIP_WORDS:
        text = text.replace(word, "")

    # Remove postal codes (e.g. 120 00)
    text = re.sub(r"\b\d{3}\s?\d{2}\b", "", text)

    # Remove all non-alphanumeric except spaces
    text = re.sub(r"[^a-záčďéěíňóřšťúůýž0-9\s]", "", text)

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def normalize_district(district: str) -> str:
    """Extract Praha district number."""
    if not district:
        return ""
    match = re.search(r"praha\s*(\d+)", district.lower())
    return f"praha{match.group(1)}" if match else district.lower().strip()


def make_fingerprint(listing: Listing) -> str:
    """
    Create a fingerprint for a listing to detect cross-portal duplicates.
    Uses: normalized address + rooms + rounded area.
    """
    addr = normalize_address(listing.address)
    district = normalize_district(listing.district)
    rooms = listing.rooms.lower().strip() if listing.rooms else ""

    # Round area to nearest 5 m² to handle slight differences
    area_bucket = ""
    if listing.area_m2 and listing.area_m2 > 0:
        area_bucket = str(round(listing.area_m2 / 5) * 5)

    # Build fingerprint from available data
    parts = [p for p in [district, rooms, area_bucket, addr] if p]
    fingerprint = "|".join(parts)

    return fingerprint


def deduplicate_listings(listings: list[Listing]) -> list[Listing]:
    """
    Remove cross-portal duplicates. Keeps the cheapest version of each flat.

    Strategy:
    1. Group listings by fingerprint (address + rooms + area)
    2. For each group, keep the listing with the lowest price
    3. Return deduplicated list
    """
    if not listings:
        return []

    # Group by fingerprint
    groups: dict[str, list[Listing]] = {}
    no_fingerprint: list[Listing] = []

    for listing in listings:
        fp = make_fingerprint(listing)

        # If fingerprint is too short / empty, can't deduplicate reliably
        if len(fp) < 10:
            no_fingerprint.append(listing)
            continue

        if fp not in groups:
            groups[fp] = []
        groups[fp].append(listing)

    # Pick cheapest from each group
    result: list[Listing] = []

    for fp, group in groups.items():
        if len(group) == 1:
            result.append(group[0])
        else:
            # Sort by price, pick cheapest
            group.sort(key=lambda l: l.price if l.price > 0 else float("inf"))
            cheapest = group[0]

            sources = [l.source for l in group]
            prices = [f"{l.price:,} Kč ({l.source})" for l in group]
            logger.info(
                f"🔄 Duplicita: {cheapest.title[:50]} | "
                f"Portály: {', '.join(sources)} | "
                f"Ceny: {', '.join(prices)} | "
                f"Vybraná: {cheapest.price:,} Kč z {cheapest.source}"
            )

            # Add info about other portals to the cheapest listing
            other_sources = [l.source for l in group if l.source != cheapest.source]
            if other_sources:
                cheapest.description = (
                    f"📊 Nájdené aj na: {', '.join(other_sources)} | "
                    f"Najnižšia cena: {cheapest.price:,} Kč ({cheapest.source})"
                )

            result.append(cheapest)

    result.extend(no_fingerprint)

    deduped_count = len(listings) - len(result)
    if deduped_count > 0:
        logger.info(f"🧹 Deduplikácia: {len(listings)} → {len(result)} (odstránených {deduped_count} duplicít)")

    return result
