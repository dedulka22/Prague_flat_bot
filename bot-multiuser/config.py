import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Telegram – len token, chat_id už nepotrebuješ
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")

    # Globálny rozsah pre scraping (čo najširší, aby bot videl všetky ponuky)
    # Každý user má vlastné filtre uložené v databáze
    min_price: int = int(os.getenv("GLOBAL_MIN_PRICE", "1000000"))
    max_price: int = int(os.getenv("GLOBAL_MAX_PRICE", "20000000"))
    rooms: list[str] = field(default_factory=lambda: os.getenv(
        "GLOBAL_ROOMS", "1+kk,1+1,2+kk,2+1,3+kk,3+1,4+kk,4+1"
    ).split(","))
    city: str = os.getenv("CITY", "praha")

    check_interval_minutes: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))
    db_path: str = os.getenv("DB_PATH", "data/listings.db")

    # paused tu už nie je – každý user má vlastný stav v DB

    def validate(self) -> bool:
        if not self.bot_token or self.bot_token == "your_bot_token_here":
            print("❌ TELEGRAM_BOT_TOKEN nie je nastavený!")
            return False
        return True


config = Config()
