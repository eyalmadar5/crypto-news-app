# -*- coding: utf-8 -*-
"""
לוגיקת הליבה: שליפת RSS, סינון לפי מטבע, שליפת מחירים וגרפים מ-CoinGecko,
ניהול מטבעות שנוספו דינמית, ובניית סיכומים יומיים/שבועיים בעברית.
"""
import sqlite3
import hashlib
import json
import os
from datetime import datetime, timezone, timedelta
import feedparser
import requests

from sources import COINS as DEFAULT_COINS, ALL_SOURCES

DB_PATH = "crypto_news.db"
COINGECKO_SIMPLE_URL = "https://api.coingecko.com/api/v3/simple/price"
COINGECKO_SEARCH_URL = "https://api.coingecko.com/api/v3/search"
COINGECKO_CHART_URL = "https://api.coingecko.com/api/v3/coins/{id}/market_chart"

# אם מוגדר משתנה סביבה ANTHROPIC_API_KEY, נשתמש בו לסיכומים אמיתיים בעברית.
# אם לא - הסיכומים ייבנו אוטומטית מריכוז כותרות (חינמי, בלי קריאת API).
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")

RANGE_TO_DAYS = {"1d": 1, "7d": 7, "30d": 30, "1y": 365}
CHART_CACHE_TTL_MIN = {"1d": 15, "7d": 60, "30d": 180, "1y": 720}


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
        CREATE TABLE IF NOT EXISTS custom_coins (
            symbol TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            coingecko_id TEXT NOT NULL,
            keywords TEXT NOT NULL,
            added_at TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS chart_cache (
            coin TEXT NOT NULL,
            range_key TEXT NOT NULL,
            data TEXT NOT NULL,
            fetched_at TEXT NOT NULL,
            PRIMARY KEY (coin, range_key)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS summaries (
            coin TEXT NOT NULL,
            period TEXT NOT NULL,
            bucket TEXT NOT NULL,
            content TEXT NOT NULL,
            source TEXT NOT NULL,
            generated_at TEXT NOT NULL,
            PRIMARY KEY (coin, period, bucket)
        )
    """)
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# ניהול מטבעות (קבועים + מטבעות שנוספו ידנית ע"י המשתמש)
# ---------------------------------------------------------------------------

def get_active_coins():
    """מחזיר dict מאוחד: מטבעות ברירת המחדל + כל מטבע שנוסף דינמית דרך /api/coins."""
    coins = dict(DEFAULT_COINS)
    conn = get_db()
    for row in conn.execute("SELECT * FROM custom_coins").fetchall():
        coins[row["symbol"]] = {
            "name": row["name"],
            "coingecko_id": row["coingecko_id"],
            "keywords": row["keywords"].split(","),
        }
    conn.close()
    return coins


def search_coingecko(query: str):
    """מחפש מטבע ב-CoinGecko לפי שם/סימול, כדי לעזור למשתמש למצוא coingecko_id נכון."""
    try:
        resp = requests.get(COINGECKO_SEARCH_URL, params={"query": query}, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": str(e), "results": []}

    results = [
        {"id": c["id"], "symbol": c["symbol"].upper(), "name": c["name"]}
        for c in data.get("coins", [])[:8]
    ]
    return {"results": results}


def add_custom_coin(symbol: str, name: str, coingecko_id: str, keywords: list):
    symbol = symbol.strip().upper()
    active = get_active_coins()
    if symbol in active:
        return {"error": f"המטבע {symbol} כבר קיים במעקב"}

    conn = get_db()
    conn.execute(
        "INSERT INTO custom_coins (symbol, name, coingecko_id, keywords, added_at) VALUES (?, ?, ?, ?, ?)",
        (symbol, name, coingecko_id, ",".join(k.strip().lower() for k in keywords if k.strip()),
         datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()

    # שליפה מיידית של מחיר וחדשות עבור המטבע החדש, כדי שיופיע מיד בממשק
    fetch_prices()
    fetch_news()
    return {"added": symbol}


def remove_custom_coin(symbol: str):
    symbol = symbol.strip().upper()
    if symbol in DEFAULT_COINS:
        return {"error": "אי אפשר להסיר את אחד ממטבעות ברירת המחדל"}
    conn = get_db()
    conn.execute("DELETE FROM custom_coins WHERE symbol = ?", (symbol,))
    conn.commit()
    conn.close()
    return {"removed": symbol}


# ---------------------------------------------------------------------------
# חדשות (RSS)
# ---------------------------------------------------------------------------

def _article_id(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8")).hexdigest()


def _match_coins(text: str, coins: dict):
    text_low = text.lower()
    matched = []
    for symbol, info in coins.items():
        for kw in info["keywords"]:
            if kw.lower() in text_low:
                matched.append(symbol)
                break
    return matched


def fetch_news(verbose=True):
    """שולף את כל מקורות ה-RSS, מסנן לפי המטבעות הפעילים (כולל מטבעות שנוספו ידנית)."""
    coins = get_active_coins()
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

            matched = _match_coins(f"{title} {summary}", coins)
            if not matched:
                continue

            aid = _article_id(link)
            published = entry.get("published", "") or entry.get("updated", "")

            row = conn.execute("SELECT id FROM articles WHERE id = ?", (aid,)).fetchone()
            if row:
                continue

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


# ---------------------------------------------------------------------------
# מחירים וגרפים (CoinGecko)
# ---------------------------------------------------------------------------

def fetch_prices():
    """שולף מחירים עדכניים מ-CoinGecko לכל המטבעות הפעילים."""
    coins = get_active_coins()
    ids = ",".join(info["coingecko_id"] for info in coins.values())
    params = {"ids": ids, "vs_currencies": "usd", "include_24hr_change": "true"}
    try:
        resp = requests.get(COINGECKO_SIMPLE_URL, params=params, timeout=15)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        return {"error": str(e)}

    conn = get_db()
    now = datetime.now(timezone.utc).isoformat()
    for symbol, info in coins.items():
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
    return {"updated": list(coins.keys()), "at": now}


def fetch_chart(symbol: str, range_key: str):
    """מחזיר סדרת מחירים לגרף (יום/שבוע/חודש/שנה), עם קאש כדי לא להציף את CoinGecko."""
    coins = get_active_coins()
    symbol = symbol.upper()
    if symbol not in coins:
        return {"error": f"מטבע לא מוכר: {symbol}"}
    if range_key not in RANGE_TO_DAYS:
        return {"error": f"טווח לא נתמך: {range_key}"}

    conn = get_db()
    ttl_min = CHART_CACHE_TTL_MIN[range_key]
    cached = conn.execute(
        "SELECT data, fetched_at FROM chart_cache WHERE coin=? AND range_key=?", (symbol, range_key)
    ).fetchone()
    if cached:
        fetched_at = datetime.fromisoformat(cached["fetched_at"])
        if datetime.now(timezone.utc) - fetched_at < timedelta(minutes=ttl_min):
            conn.close()
            return {"coin": symbol, "range": range_key, "prices": json.loads(cached["data"]), "cached": True}

    cg_id = coins[symbol]["coingecko_id"]
    days = RANGE_TO_DAYS[range_key]
    try:
        resp = requests.get(
            COINGECKO_CHART_URL.format(id=cg_id),
            params={"vs_currency": "usd", "days": days},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        prices = data.get("prices", [])  # [[timestamp_ms, price], ...]
    except Exception as e:
        conn.close()
        return {"error": str(e)}

    conn.execute(
        """INSERT INTO chart_cache (coin, range_key, data, fetched_at) VALUES (?, ?, ?, ?)
           ON CONFLICT(coin, range_key) DO UPDATE SET data=excluded.data, fetched_at=excluded.fetched_at""",
        (symbol, range_key, json.dumps(prices), datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    conn.close()
    return {"coin": symbol, "range": range_key, "prices": prices, "cached": False}


# ---------------------------------------------------------------------------
# סיכומים יומיים/שבועיים בעברית
# ---------------------------------------------------------------------------

def _bucket_key(period: str) -> str:
    now = datetime.now(timezone.utc)
    if period == "daily":
        return now.strftime("%Y-%m-%d")
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _period_window(period: str):
    now = datetime.now(timezone.utc)
    if period == "daily":
        return now - timedelta(days=1)
    return now - timedelta(days=7)


def _extractive_digest(symbol: str, coin_name: str, articles: list) -> str:
    """סיכום 'חינמי' בלי AI: ריכוז ברור של הכותרות, ממוין וללא כפילויות מובהקות."""
    if not articles:
        return f"לא נמצאו כתבות חדשות על {coin_name} ({symbol}) בתקופה הזו."

    official = [a for a in articles if a["kind"] == "official"]
    news = [a for a in articles if a["kind"] != "official"]

    lines = [f"נמצאו {len(articles)} כתבות על {coin_name} ({symbol}):", ""]
    if official:
        lines.append("הודעות רשמיות:")
        for a in official[:6]:
            lines.append(f"• {a['title']} — {a['source']}")
        lines.append("")
    if news:
        lines.append("כיסוי בתקשורת:")
        for a in news[:8]:
            lines.append(f"• {a['title']} — {a['source']}")
    return "\n".join(lines)


def _ai_summary(symbol: str, coin_name: str, articles: list, period_label: str) -> str:
    """סיכום אמיתי בעברית באמצעות Claude, רק אם הוגדר ANTHROPIC_API_KEY."""
    import anthropic

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    headlines = "\n".join(f"- {a['title']} ({a['source']})" for a in articles[:20])
    prompt = (
        f"הנה כותרות חדשות {period_label} על המטבע {coin_name} ({symbol}):\n\n{headlines}\n\n"
        "כתוב סיכום קצר וענייני בעברית (3-5 משפטים) של האירועים והמגמות המרכזיים. "
        "התמקד בעובדות (שיתופי פעולה, חוזים, רגולציה, שינויים משמעותיים) ולא בניחושי מחיר. "
        "אם אין מספיק חדשות משמעותיות, ציין זאת בקצרה. החזר טקסט בלבד, בלי כותרות markdown."
    )
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=400,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in resp.content if block.type == "text").strip()


def get_summary(symbol: str, period: str):
    """מחזיר סיכום (מהקאש אם קיים לתקופה הנוכחית, אחרת בונה חדש ושומר)."""
    symbol = symbol.upper()
    coins = get_active_coins()
    if symbol not in coins:
        return {"error": f"מטבע לא מוכר: {symbol}"}
    if period not in ("daily", "weekly"):
        return {"error": "period חייב להיות daily או weekly"}

    bucket = _bucket_key(period)
    conn = get_db()
    cached = conn.execute(
        "SELECT content, source, generated_at FROM summaries WHERE coin=? AND period=? AND bucket=?",
        (symbol, period, bucket),
    ).fetchone()
    if cached:
        conn.close()
        return {"coin": symbol, "period": period, "content": cached["content"],
                "source": cached["source"], "generated_at": cached["generated_at"], "cached": True}

    since = _period_window(period).isoformat()
    rows = conn.execute(
        "SELECT title, source, kind, published, fetched_at FROM articles "
        "WHERE ',' || coins || ',' LIKE ? AND fetched_at >= ? ORDER BY fetched_at DESC",
        (f"%,{symbol},%", since),
    ).fetchall()
    articles = [dict(r) for r in rows]
    coin_name = coins[symbol]["name"]
    period_label = "מה-24 שעות האחרונות" if period == "daily" else "מהשבוע האחרון"

    source_used = "extractive"
    content = None
    if ANTHROPIC_API_KEY and articles:
        try:
            content = _ai_summary(symbol, coin_name, articles, period_label)
            source_used = "ai"
        except Exception as e:
            content = None  # ניפול חזרה לגרסה החינמית

    if content is None:
        content = _extractive_digest(symbol, coin_name, articles)

    now_iso = datetime.now(timezone.utc).isoformat()
    conn.execute(
        """INSERT INTO summaries (coin, period, bucket, content, source, generated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(coin, period, bucket) DO UPDATE SET content=excluded.content,
               source=excluded.source, generated_at=excluded.generated_at""",
        (symbol, period, bucket, content, source_used, now_iso),
    )
    conn.commit()
    conn.close()
    return {"coin": symbol, "period": period, "content": content, "source": source_used,
            "generated_at": now_iso, "cached": False}


def refresh_all():
    """מרענן חדשות ומחירים - נקרא בלחיצה על 'רענון' וגם אוטומטית ע"י המתזמן הפנימי."""
    news_result = fetch_news()
    price_result = fetch_prices()
    return {"news": news_result, "prices": price_result}


if __name__ == "__main__":
    init_db()
    print(refresh_all())
