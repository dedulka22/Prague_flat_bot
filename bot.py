#!/usr/bin/env python3
"""
Prague Flat Hunter Bot – multi-user verzia
Každý používateľ má vlastné nastavenia a dostáva notifikácie nezávisle.
"""

import asyncio
import logging
import sys

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
from dedup import deduplicate_listings
from scrapers import ALL_SCRAPERS
from scrapers.base import HEADERS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("bot")

db = Database(config.db_path)


# ─── Filter: Družstevné byty a anuita ─────────────────────────

DRUZSTVO_KEYWORDS = [
    "družstevní", "družstevn", "družstvo", "členský podíl", "členský podil",
    "převod členských práv", "bytové družstvo", "bytove druzstvo",
    "podíl v družstvu", "podil v druzstvu",
]

ANUITA_KEYWORDS = [
    "anuita", "anuitní", "zástavní právo", "zástavní právo", "záložní právo",
    "zalozni pravo", "věcné břemeno", "vecne bremeno",
    "hypoteční zástavní", "exekuce", "exekuční", "insolvence", "insolvenční",
    "dražba", "předkupní právo zástavního",
]


def is_unwanted_listing(listing: Listing) -> tuple[bool, str]:
    """Vráti (True, dôvod) ak je byt družstevný alebo má anuitu/záložné právo."""
    check_text = " ".join(filter(None, [
        listing.title,
        listing.description,
        listing.address,
    ])).lower()

    for kw in DRUZSTVO_KEYWORDS:
        if kw.lower() in check_text:
            return True, f"družstevní ({kw})"

    for kw in ANUITA_KEYWORDS:
        if kw.lower() in check_text:
            return True, f"anuita/záložní právo ({kw})"

    return False, ""


# ─── Formatting ────────────────────────────────────────────────

def format_listing_message(listing: Listing) -> str:
    price_fmt = f"{listing.price:,.0f}".replace(",", " ")
    area_str = f"📐 {listing.area_m2:.0f} m²\n" if listing.area_m2 else ""
    district_str = f"📍 {listing.district}\n" if listing.district else ""
    dedup_str = ""
    if listing.description and "Nájdené aj na:" in listing.description:
        dedup_str = f"📊 {_escape_md(listing.description)}\n"

    return (
        f"🏠 *{_escape_md(listing.title)}*\n\n"
        f"💰 *{price_fmt} Kč*\n"
        f"🏠 {listing.rooms}\n"
        f"{area_str}"
        f"{district_str}"
        f"📌 {_escape_md(listing.address)}\n"
        f"{dedup_str}"
        f"🔗 [{listing.source}]({listing.url})\n"
    )


def _escape_md(text: str) -> str:
    if not text:
        return ""
    chars = r"_*[]()~`>#+-=|{}.!"
    for ch in chars:
        text = text.replace(ch, f"\\{ch}")
    return text


def format_user_filters(settings: dict) -> str:
    rooms_str = ", ".join(settings["rooms"])
    return (
        f"🔍 *Tvoje filtre:*\n"
        f"💰 Cena: {settings['min_price']:,} – {settings['max_price']:,} Kč\n"
        f"🏠 Dispozícia: {rooms_str}\n"
        f"📍 Mesto: {settings['city'].title()}\n"
        f"{'⏸ POZASTAVENÉ' if settings['paused'] else '▶️ Aktívne'}"
    )


# ─── Detail fetching ───────────────────────────────────────────

async def fetch_listing_detail_text(session: aiohttp.ClientSession, url: str) -> str:
    """Stiahne detail stránku inzerátu a vráti čistý text na kontrolu kľúčových slov."""
    try:
        async with session.get(url, headers=HEADERS, timeout=aiohttp.ClientTimeout(total=10)) as resp:
            if resp.status != 200:
                return ""
            html = await resp.text()
            # Odstráňme HTML tagy — chceme len text
            import re as _re
            text = _re.sub(r"<[^>]+>", " ", html)
            text = _re.sub(r"\s+", " ", text)
            return text.lower()
    except Exception as e:
        logger.debug(f"Detail fetch error ({url}): {e}")
        return ""


async def enrich_and_filter(session: aiohttp.ClientSession, listing: Listing) -> tuple[Listing | None, str]:
    """
    Stiahne detail inzerátu, skontroluje kľúčové slová.
    Vráti (listing, "") ak je OK, alebo (None, dôvod) ak má byť filtrovaný.
    """
    # Najprv skontroluj to čo už máme (rýchle)
    unwanted, reason = is_unwanted_listing(listing)
    if unwanted:
        return None, reason

    # Stiahni detail a skontroluj celý text stránky
    detail_text = await fetch_listing_detail_text(session, listing.url)
    if detail_text:
        # Pridaj detail text do dočasného objektu na kontrolu
        enriched = Listing(
            source=listing.source,
            external_id=listing.external_id,
            title=listing.title,
            price=listing.price,
            rooms=listing.rooms,
            area_m2=listing.area_m2,
            district=listing.district,
            address=listing.address,
            url=listing.url,
            image_url=listing.image_url,
            description=detail_text[:2000],  # prvých 2000 znakov stačí
        )
        unwanted, reason = is_unwanted_listing(enriched)
        if unwanted:
            return None, reason

    return listing, ""


# ─── Scraping ──────────────────────────────────────────────────

DETAIL_SEMAPHORE = asyncio.Semaphore(5)  # max 5 paralelných detail fetchov


async def enrich_with_semaphore(session, listing):
    async with DETAIL_SEMAPHORE:
        result = await enrich_and_filter(session, listing)
        await asyncio.sleep(0.3)  # jemný rate limit
        return result


async def run_scrape_cycle() -> list[Listing]:
    """Scrape all portals, fetch details, filter unwanted, save globally."""
    all_new = []

    async with aiohttp.ClientSession() as session:
        for ScraperClass in ALL_SCRAPERS:
            scraper = ScraperClass(
                min_price=config.min_price,
                max_price=config.max_price,
                rooms=config.rooms,
            )
            try:
                found = await scraper.safe_scrape(session)

                # Filtruj len nové (ešte neuložené) inzeráty — detail fetchujeme len pre ne
                candidates = [l for l in found if not db.listing_exists(l)]

                if candidates:
                    logger.info(f"  {scraper.name}: {len(candidates)} nových kandidátov, sťahujem detaily...")
                    tasks = [enrich_with_semaphore(session, l) for l in candidates]
                    results = await asyncio.gather(*tasks)
                else:
                    results = []

                new_count = 0
                filtered_count = 0
                for result, reason in results:
                    if result is None:
                        logger.info(f"  🚫 Filtrovaný [{scraper.name}]: {reason}")
                        filtered_count += 1
                        continue
                    if db.save_listing(result):
                        all_new.append(result)
                        new_count += 1

                db.log_scrape(scraper.name, "ok", len(found), new_count)
                filter_note = f", 🚫 {filtered_count} filtrovaných" if filtered_count else ""
                logger.info(f"  {scraper.name}: {len(found)} nájdených, {new_count} nových{filter_note}")
            except Exception as e:
                logger.error(f"  {scraper.name} error: {e}")
                db.log_scrape(scraper.name, "error", error=str(e))

    if all_new:
        before = len(all_new)
        all_new = deduplicate_listings(all_new)
        if before != len(all_new):
            logger.info(f"🧹 Deduplikácia: {before} → {len(all_new)}")

    return all_new


async def send_listing_to_user(bot: Bot, chat_id: int, listing: Listing):
    try:
        message = format_listing_message(listing)
        if listing.image_url:
            try:
                await bot.send_photo(
                    chat_id=chat_id,
                    photo=listing.image_url,
                    caption=message,
                    parse_mode=ParseMode.MARKDOWN_V2,
                )
                return
            except Exception:
                pass
        await bot.send_message(
            chat_id=chat_id,
            text=message,
            parse_mode=ParseMode.MARKDOWN_V2,
            disable_web_page_preview=False,
        )
    except Exception as e:
        try:
            plain = (
                f"🏠 {listing.title}\n"
                f"💰 {listing.price:,} Kč\n"
                f"🏠 {listing.rooms}\n"
                f"📍 {listing.address}\n"
                f"🔗 {listing.url}"
            )
            await bot.send_message(chat_id=chat_id, text=plain)
        except Exception as e2:
            logger.error(f"Failed to send to {chat_id}: {e2}")


# ─── Periodic job ───────────────────────────────────────────────

async def periodic_scrape(context: ContextTypes.DEFAULT_TYPE):
    logger.info("🔄 Spúšťam scrape cyklus...")
    new_listings = await run_scrape_cycle()

    if not new_listings:
        logger.info("ℹ️ Žiadne nové ponuky")
        return

    logger.info(f"📬 {len(new_listings)} nových ponúk, distribuujem používateľom...")

    # Send each listing to every active user whose filters match
    active_users = db.get_all_active_users()
    for user_id in active_users:
        settings = db.get_user_settings(user_id)
        for listing in new_listings:
            if db.is_seen_by_user(user_id, listing):
                continue
            if not db.listing_matches_user(listing, settings):
                continue
            await send_listing_to_user(context.bot, user_id, listing)
            db.mark_seen_by_user(user_id, listing)
            await asyncio.sleep(0.5)


# ─── Commands ───────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = db.get_user_settings(user_id)
    filters_text = _escape_md(format_user_filters(settings))
    await update.message.reply_text(
        f"🏠 *Prague Flat Hunter Bot*\n\n"
        f"Bot monitoruje realitné portály a posiela ti nové ponuky\\.\n\n"
        f"{filters_text}\n\n"
        f"Príkazy: /help",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Príkazy:*\n\n"
        "/start \\- Info o botovi\n"
        "/status \\- Štatistiky\n"
        "/filter \\- Tvoje aktuálne filtre\n"
        "/setprice MIN MAX \\- Zmeniť cenu \\(napr\\. /setprice 4000000 8000000\\)\n"
        "/setrooms 2\\+kk,2\\+1 \\- Zmeniť dispozíciu\n"
        "/pause \\- Pozastaviť notifikácie\n"
        "/resume \\- Obnoviť notifikácie\n"
        "/search \\- Okamžitý check\n"
        "/latest \\- Posledných 5 ponúk",
        parse_mode=ParseMode.MARKDOWN_V2,
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    stats = db.get_stats(user_id=user_id)
    by_source_lines = "\n".join(
        f"  • {src}: {cnt}" for src, cnt in stats["by_source"].items()
    )
    seen_line = f"\nTy si videl/a: {stats['seen_by_user']}" if stats["seen_by_user"] is not None else ""
    await update.message.reply_text(
        f"📊 Štatistiky:\n\n"
        f"Celkom ponúk v DB: {stats['total']}\n"
        f"Za posledných 24h: {stats['last_24h']}"
        f"{seen_line}\n\n"
        f"Podľa zdroja:\n{by_source_lines}"
    )


async def cmd_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = db.get_user_settings(user_id)
    await update.message.reply_text(format_user_filters(settings))


async def cmd_setprice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if len(args) != 2:
        await update.message.reply_text("Použitie: /setprice 4000000 8000000")
        return
    try:
        min_p = int(args[0])
        max_p = int(args[1])
        db.set_user_price(user_id, min_p, max_p)
        await update.message.reply_text(
            f"✅ Tvoj cenový rozsah: {min_p:,} – {max_p:,} Kč"
        )
    except ValueError:
        await update.message.reply_text("❌ Zadaj čísla, napr. /setprice 4000000 8000000")


async def cmd_setrooms(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    args = context.args
    if not args:
        await update.message.reply_text("Použitie: /setrooms 2+kk,2+1,3+kk")
        return
    rooms = [r.strip() for r in args[0].split(",")]
    db.set_user_rooms(user_id, rooms)
    await update.message.reply_text(f"✅ Tvoja dispozícia: {', '.join(rooms)}")


async def cmd_pause(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.set_user_paused(user_id, True)
    await update.message.reply_text("⏸ Notifikácie pozastavené. /resume na obnovenie.")


async def cmd_resume(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    db.set_user_paused(user_id, False)
    await update.message.reply_text("▶️ Notifikácie obnovené!")


async def cmd_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    settings = db.get_user_settings(user_id)
    if settings["paused"]:
        await update.message.reply_text("⏸ Notifikácie sú pozastavené. Použi /resume.")
        return

    await update.message.reply_text("🔍 Spúšťam manuálny check...")
    new_listings = await run_scrape_cycle()

    sent = 0
    for listing in new_listings:
        if db.is_seen_by_user(user_id, listing):
            continue
        if not db.listing_matches_user(listing, settings):
            continue
        await send_listing_to_user(context.bot, user_id, listing)
        db.mark_seen_by_user(user_id, listing)
        sent += 1
        await asyncio.sleep(0.5)

    if sent:
        await update.message.reply_text(f"📬 Poslal som ti {sent} nových ponúk.")
    else:
        await update.message.reply_text("ℹ️ Žiadne nové ponuky zodpovedajúce tvojim filtrom.")


async def cmd_latest(update: Update, context: ContextTypes.DEFAULT_TYPE):
    latest = db.get_latest(5)
    if not latest:
        await update.message.reply_text("Zatiaľ žiadne ponuky v databáze.")
        return

    msg = "📋 *Posledných 5 ponúk \\(zo všetkých používateľov\\):*\n\n"
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

    logger.info("🚀 Štartujem Prague Flat Hunter Bot (multi-user)")

    app = Application.builder().token(config.bot_token).build()

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

    job_queue = app.job_queue
    job_queue.run_repeating(
        periodic_scrape,
        interval=config.check_interval_minutes * 60,
        first=10,
        name="scrape_job",
    )

    logger.info(f"⏱ Scrape interval: {config.check_interval_minutes} minút")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
