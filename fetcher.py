# -*- coding: utf-8 -*-
"""
לוגיקת האיסוף: שליפת RSS, סינון לפי מטבע, שליפת מחירים מ-CoinGecko, שמירה ב-SQLite.
"""
import sqlite3
import time
import hashlib
from datetime import datetime, timezone
import feedparser
import requests

from sources import COINS, ALL_SOURCES

DB_PATH = "crypto_news.db"
COINGECKO_URL = "https://api.coingecko.com/api/v3/simple/price"


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            link TEXT NOT NULL,
            source TEXT NOT NULL,
            kind TEXT NOT NULL,
            summary TEXT,
            published TEXT,
            fetched_at TEXT NOT NULL,
            coins TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS prices (
            coin TEXT PRIMARY KEY,
            usd REAL,
            usd_24h_change REAL,
            updated_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()


def _article_id(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8")).hexdigest()


def _match_coins(text: str):
    text_low = text.lower()
    matched = []
    for symbol, info in COINS.items():
        for kw in info["keywords"]:
            if kw.lower() in text_low:
                matched.append(symbol)
                break
    return matched


def fetch_news(verbose=True):
    """שולף את כל מקורות ה-RSS, מסנן לפי המטבעות שהוגדרו, ושומר כתבות חדשות ב-DB."""
    conn = get_db()
    new_count = 0
    errors = []

    for source in ALL_SOURCES:
        name, url, kind = source["name"], source["url"], source["kind"]
        try:
            feed = feedparser.parse(url)
            if feed.bozo and not feed.entries:
                errors.append(f"{name}: לא ניתן היה לפרסר את ה-RSS ({feed.bozo_exception})")
                continue
        except Exception as e:
            errors.append(f"{name}: שגיאת רשת - {e}")
            continue

        for entry in feed.entries:
            title = entry.get("title", "")
            summary = entry.get("summary", "") or entry.get("description", "")
            link = entry.get("link", "")
            if not link or not title:
                continue

            matched = _match_coins(f"{title} {summary}")
            if not matched:
                continue  # לא רלוונטי לאף אחד מהמטבעות שלנו

            aid = _article_id(link)
            published = entry.get("published", "") or entry.get("updated", "")

            row = conn.execute("SELECT id FROM articles WHERE id = ?", (aid,)).fetchone()
            if row:
                continue  # כבר קיים

            conn.execute(
                """INSERT INTO articles (id, title, link, source, kind, summary, published, fetched_at, coins)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    aid, title.strip(), link, name, kind,
                    (summary or "")[:500], published,
                    datetime.now(timezone.utc).isoformat(),
                    ",".join(matched),
                ),
            )
            new_count += 1

        if verbose:
            print(f"[fetcher] {name}: נסרק ({kind})")

    conn.commit()
    conn.close()
    return {"new_articles": new_count, "errors": errors}


def fetch_prices():
    """שולף מחירים עדכניים מ-CoinGecko לכל המטבעות המוגדרים ב-sources.py."""
    ids = ",".join(info["coingecko_id"] for info in COINS.values())
    params = {"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"}
    try:
        resp = requests.get(COINGECKO_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": str(e)}

    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    for symbol, info in COINS.items():
        cg_id = info["coingecko_id"]
        if cg_id in data:
            usd = data[cg_id].get("usd")
            change = data[cg_id].get("usd_24h_change")
            conn.execute(
                """INSERT INTO prices (coin, usd, usd_24h_change, updated_at)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(coin) DO UPDATE SET usd=excluded.usd,
                       usd_24h_change=excluded.usd_24h_change, updated_at=excluded.updated_at""",
                (symbol, usd, change, now),
            )
    conn.commit()
    conn.close()
    return {"updated": list(COINS.keys()), "at": now}


def refresh_all():
    """מרענן גם חדשות וגם מחירים - זו הפונקציה שנקראת בלחיצה על 'רענון' או ב-cron."""
    news_result = fetch_news()
    price_result = fetch_prices()
    return {"news": news_result, "prices": price_result}


if __name__ == "__main__":
    init_db()
    print(refresh_all())
