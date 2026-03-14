#!/usr/bin/env python3
"""
Prague Flat Hunter Bot
Telegram bot na monitorovanie ponúk bytov v Prahe.
"""

import asyncio
import logging
import sys
from datetime import datetime

import aiohttp
from telegram import Update, Bot
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
)

from config import config
from database import Database, Listing
from scrapers import ALL_SCRAPERS

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot")

# Database
db = Database(config.db_path)


# ─── Telegram message formatting ───────────────────────────────

def format_listing_message(listing: Listing) -> str:
    """Format a listing for Telegram notification."""
    price_fmt = f"{listing.price:,.0f}".replace(",", " ")

    area_str = f"📐 {listing.area_m2:.0f} m²\n" if listing.area_m2 else ""
    district_str = f"📍 {listing.district}\n" if listing.district else ""

    msg = (
        f"🏠 *{_escape_md(listing.title)}*\n\n"
        f"💰 *{price_fmt} Kč*\n"
        f"🏠 {listing.rooms}\n"
        f"{area_str}"
        f"{district_str}"
        f"📌 {_escape_md(listing.address)}\n"
        f"🔗 [{listing.source}]({listing.url})\n"
    )
    return msg


def _escape_md(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    if not text:
        return ""
    chars = r"_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


# ─── Scraping logic ────────────────────────────────────────────

async def run_scrape_cycle() -> list[Listing]:
    """Run all scrapers and return new (unseen) listings."""
    new_listings = []

    async with aiohttp.ClientSession() as session:
        for ScraperClass in ALL_SCRAPERS:
            scraper = ScraperClass(
                min_price=config.min_price,
                max_price=config.max_price,
                rooms=config.rooms,
            )

            try:
                found = await scraper.safe_scrape(session)
                new_count = 0

                for listing in found:
                    if not db.is_seen(listing):
                        if db.save_listing(listing):
                            new_listings.append(listing)
                            new_count += 1

                db.log_scrape(scraper.name, "ok", len(found), new_count)
                logger.info(f"  {scraper.name}: {len(found)} nájdených, {new_count} nových")

            except Exception as e:
                logger.error(f"  {scraper.name} error: {e}")
                db.log_scrape(scraper.name, "error", error=str(e))

    return new_listings


async def send_listing_notification(bot: Bot, listing: Listing):
    """Send a single listing notification to Telegram."""
    try:
        message = format_listing_message(listing)

        if listing.image_url:
            try:
                await bot.send_photo(
                    chat_id=config.chat_id,
                    photo=listing.image_url,
                    caption=message,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                return
            except Exception:
                pass  # Fallback to text if image fails

        await bot.send_message(
            chat_id=config.chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=False,
        )
    except Exception as e:
        # Fallback: send without formatting
        try:
            plain = (
                f"🏠 {listing.title}\n"
                f"💰 {listing.price:,} Kč\n"
                f"🏠 {listing.rooms}\n"
                f"📍 {listing.address}\n"
                f"🔗 {listing.url}"
            )
            await bot.send_message(chat_id=config.chat_id, text=plain)
        except Exception as e2:
            logger.error(f"Failed to send notification: {e2}")


# ─── Periodic scraping job ──────────────────────────────────────

async def periodic_scrape(context: ContextTypes.DEFAULT_TYPE):
    """Job that runs every X minutes to check for new listings."""
    if config.paused:
        return

    logger.info("🔄 Spúšťam scrape cyklus...")
    new_listings = await run_scrape_cycle()

    if new_listings:
        logger.info(f"📬 Posielam {len(new_listings)} nových ponúk")
        for listing in new_listings:
            await send_listing_notification(context.bot, listing)
            await asyncio.sleep(1)  # Rate limiting
    else:
        logger.info("ℹ️ Žiadne nové ponuky")


# ─── Telegram command handlers ──────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command."""
    await update.message.reply_text(
        f"🏠 *Prague Flat Hunter Bot*\n\n"
        f"Bot monitoruje realitné portály a posiela ti nové ponuky\\.\n\n"
        f"{_escape_md(config.format_filters())}\n\n"
        f"Príkazy: /help",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command."""
    await update.message.reply_text(
        "📋 *Príkazy:*\n\n"
        "/start \\- Info o botovi\n"
        "/status \\- Štatistiky\n"
        "/filter \\- Aktuálne filtre\n"
        "/setprice MIN MAX \\- Zmeniť cenu\n"
        "/setrooms 2\\+kk,2\\+1 \\- Zmeniť dispozíciu\n"
        "/pause \\- Pozastaviť\n"
        "/resume \\- Obnoviť\n"
        "/search \\- Okamžitý check\n"
        "/latest \\- Posledných 5 ponúk",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /status command."""
    stats = db.get_stats()
    by_source_lines = "\n".join(
        f"  • {src}: {cnt}" for src, cnt in stats["by_source"].items()
    )
    await update.message.reply_text(
        f"📊 Štatistiky:\n\n"
        f"Celkom ponúk: {stats['total']}\n"
        f"Za posledných 24h: {stats['last_24h']}\n\n"
        f"Podľa zdroja:\n{by_source_lines}"
    )


async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /filter command."""
    await update.message.reply_text(config.format_filters())


async def cmd_setprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setprice MIN MAX command."""
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Použitie: /setprice 4000000 8000000")
        return

    try:
        config.min_price = int(args[0])
        config.max_price = int(args[1])
        await update.message.reply_text(
            f"✅ Cenový rozsah zmenený na {config.min_price:,} – {config.max_price:,} Kč"
        )
    except ValueError:
        await update.message.reply_text("❌ Zadaj čísla, napr. /setprice 4000000 8000000")


async def cmd_setrooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /setrooms 2+kk,2+1 command."""
    args = context.args
    if not args:
        await update.message.reply_text("Použitie: /setrooms 2+kk,2+1,3+kk")
        return

    rooms = args[0].split(",")
    config.rooms = [r.strip() for r in rooms]
    await update.message.reply_text(f"✅ Dispozícia zmenená na: {', '.join(config.rooms)}")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /pause command."""
    config.paused = True
    await update.message.reply_text("⏸ Monitoring pozastavený. /resume na obnovenie.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /resume command."""
    config.paused = False
    await update.message.reply_text("▶️ Monitoring obnovený!")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /search - immediate manual check."""
    await update.message.reply_text("🔍 Spúšťam manuálny check...")

    new_listings = await run_scrape_cycle()

    if new_listings:
        await update.message.reply_text(f"📬 Nájdených {len(new_listings)} nových ponúk, posielam...")
        for listing in new_listings:
            await send_listing_notification(context.bot, listing)
            await asyncio.sleep(1)
    else:
        await update.message.reply_text("ℹ️ Žiadne nové ponuky od posledného checku.")


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /latest - show last 5 listings."""
    latest = db.get_latest(5)
    if not latest:
        await update.message.reply_text("Zatiaľ žiadne ponuky v databáze.")
        return

    msg = "📋 *Posledných 5 ponúk:*\n\n"
    for i, l in enumerate(latest, 1):
        price_fmt = f"{l['price']:,.0f}".replace(",", " ")
        msg += (
            f"{i}\\. {_escape_md(l['title'][:60])}\n"
            f"   💰 {price_fmt} Kč \\| {l['rooms']} \\| {_escape_md(l['district'])}\n"
            f"   🔗 [{l['source']}]({l['url']})\n\n"
        )

    await update.message.reply_text(msg, parse_mode=ParseMode.MARKDOWN_V2, disable_web_page_preview=True)


# ─── Main ───────────────────────────────────────────────────────

def main():
    if not config.validate():
        sys.exit(1)

    logger.info("🚀 Štartujem Prague Flat Hunter Bot")
    logger.info(config.format_filters())

    app = Application.builder().token(config.bot_token).build()

    # Register commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("filter", cmd_filter))
    app.add_handler(CommandHandler("setprice", cmd_setprice))
    app.add_handler(CommandHandler("setrooms", cmd_setrooms))
    app.add_handler(CommandHandler("pause", cmd_pause))
    app.add_handler(CommandHandler("resume", cmd_resume))
    app.add_handler(CommandHandler("search", cmd_search))
    app.add_handler(CommandHandler("latest", cmd_latest))

    # Schedule periodic scraping
    job_queue = app.job_queue
    job_queue.run_repeating(
        periodic_scrape,
        interval=config.check_interval_minutes * 60,
        first=10,  # First run 10 seconds after start
        name="scrape_job",
    )

    logger.info(f"⏱ Scrape interval: {config.check_interval_minutes} minút")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
