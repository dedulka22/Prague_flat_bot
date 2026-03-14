from .sreality import SrealityScraper
from .bezrealitky import BezrealitkyScraper
from .idnes import IdnesScraper
from .bazos import BazosScraper

ALL_SCRAPERS = [
    SrealityScraper,
    BezrealitkyScraper,
    IdnesScraper,
    BazosScraper,
]

__all__ = ["ALL_SCRAPERS", "SrealityScraper", "BezrealitkyScraper", "IdnesScraper", "BazosScraper"]
