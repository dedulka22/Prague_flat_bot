# 🏠 Prague Flat Hunter Bot

Telegram bot na monitorovanie ponúk bytov na predaj v Prahe z hlavných realitných portálov.

## Monitorované portály

| Portál | Metóda | Spoľahlivosť |
|--------|--------|---------------|
| **Sreality.cz** | Public REST API | ⭐⭐⭐ Najspoľahlivejšia |
| **Bezrealitky.cz** | GraphQL API | ⭐⭐⭐ Veľmi spoľahlivá |
| **Reality.idnes.cz** | Web scraping | ⭐⭐ Stredná |
| **Bazoš.cz** | Web scraping | ⭐⭐ Stredná |

## Funkcie

- 🔄 Automatický check každých 10 minút
- 🔍 Filtrovanie: cena, dispozícia, mestská časť
- 📱 Telegram notifikácie s fotkou, cenou, popisom, odkazom
- 🗄️ SQLite databáza – žiadne duplikáty
- ⚙️ Telegram príkazy na zmenu filtrov za behu
- 🐳 Docker Compose ready

## Setup

### 1. Vytvor Telegram bota

1. Otvor [@BotFather](https://t.me/BotFather) v Telegrame
2. Pošli `/newbot` a nasleduj inštrukcie
3. Skopíruj **API token**
4. Pošli `/start` tvojmu novému botovi
5. Otvor `https://api.telegram.org/bot<TOKEN>/getUpdates` a nájdi tvoje **chat_id**

### 2. Konfigurácia

```bash
cp .env.example .env
# Vyplň TELEGRAM_BOT_TOKEN a TELEGRAM_CHAT_ID
```

### 3. Spustenie cez Docker

```bash
docker-compose up -d
```

### 4. Spustenie lokálne

```bash
pip install -r requirements.txt
python bot.py
```

## Telegram príkazy

| Príkaz | Popis |
|--------|-------|
| `/start` | Spustí bota, zobrazí aktuálne filtre |
| `/status` | Štatistiky – koľko ponúk bolo nájdených |
| `/filter` | Zobrazí aktuálne filtre |
| `/setprice 4000000 8000000` | Zmení cenový rozsah |
| `/setrooms 2+kk,2+1,3+kk` | Zmení dispozície |
| `/pause` | Pozastaví monitoring |
| `/resume` | Obnoví monitoring |
| `/search` | Okamžitý manuálny check |
| `/latest` | Zobrazí posledných 5 ponúk |
