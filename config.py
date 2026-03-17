import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    # Telegram
    bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")

    # Filters
    min_price: int = int(os.getenv("MIN_PRICE", "4000000"))
    max_price: int = int(os.getenv("MAX_PRICE", "8000000"))
    rooms: list[str] = field(default_factory=lambda: os.getenv("ROOMS", "2+kk,2+1").split(","))
    city: str = os.getenv("CITY", "praha")

    # Scraping
    check_interval_minutes: int = int(os.getenv("CHECK_INTERVAL_MINUTES", "10"))

    # Database
    db_path: str = os.getenv("DB_PATH", "data/listings.db")

    # State
    paused: bool = False

    def validate(self) -> bool:
        if not self.bot_token or self.bot_token == "your_bot_token_here":
            print("❌ TELEGRAM_BOT_TOKEN nie je nastavený!")
            return False
        if not self.chat_id or self.chat_id == "your_chat_id_here":
            print("❌ TELEGRAM_CHAT_ID nie je nastavený!")
            return False
        return True

    def format_filters(self) -> str:
        return (
            f"🔍 *Aktuálne filtre:*\n"
            f"💰 Cena: {self.min_price:,} – {self.max_price:,} Kč\n"
            f"🏠 Dispozícia: {', '.join(self.rooms)}\n"
            f"📍 Mesto: {self.city.title()}\n"
            f"⏱ Interval: každých {self.check_interval_minutes} min\n"
            f"{'⏸ POZASTAVENÉ' if self.paused else '▶️ Aktívne'}"
        )


config = Config()
