# -*- coding: utf-8 -*-
"""
שרת מקומי/מרוחק (FastAPI) שמגיש:
1. API לחדשות, מחירים, גרפים, ניהול מטבעות וסיכומים
2. את הפרונטאנד (index.html)
3. מתזמן פנימי שמרענן חדשות+מחירים אוטומטית ברקע (כל עוד השרת "ער")
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from apscheduler.schedulers.background import BackgroundScheduler

import fetcher
from sources import COINS as DEFAULT_COINS

app = FastAPI(title="Crypto News Dashboard")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"
scheduler = BackgroundScheduler()


@app.on_event("startup")
def startup():
    fetcher.init_db()
    # רענון אוטומטי כל 60 דקות. הערה: בטייר החינמי של Render השרת נרדם אחרי
    # 15 דקות חוסר פעילות - אז זה ירוץ אוטומטית כשהשרת ער, אבל לא באופן קבוע
    # לגמרי אם אין תנועה לאתר. סיכומים ונתונים תמיד מחושבים-על-הדרישה בכל מקרה.
    scheduler.add_job(fetcher.refresh_all, "interval", minutes=60, id="auto_refresh")
    scheduler.start()


@app.on_event("shutdown")
def shutdown():
    scheduler.shutdown(wait=False)


# --- מטבעות ---

@app.get("/api/coins")
def get_coins():
    coins = fetcher.get_active_coins()
    return {sym: {"name": info["name"], "custom": sym not in DEFAULT_COINS} for sym, info in coins.items()}


@app.get("/api/coins/search")
def search_coins(q: str):
    return fetcher.search_coingecko(q)


class AddCoinRequest(BaseModel):
    symbol: str
    name: str
    coingecko_id: str
    keywords: list[str]


@app.post("/api/coins")
def add_coin(req: AddCoinRequest):
    result = fetcher.add_custom_coin(req.symbol, req.name, req.coingecko_id, req.keywords)
    return JSONResponse(result)


@app.delete("/api/coins/{symbol}")
def delete_coin(symbol: str):
    result = fetcher.remove_custom_coin(symbol)
    return JSONResponse(result)


# --- מחירים וגרפים ---

@app.get("/api/prices")
def get_prices():
    conn = fetcher.get_db()
    rows = conn.execute("SELECT * FROM prices").fetchall()
    conn.close()
    return [dict(r) for r in rows]


@app.get("/api/chart")
def get_chart(coin: str, range: str = "7d"):
    return fetcher.fetch_chart(coin, range)


# --- חדשות ---

@app.get("/api/news")
def get_news(coin: str = None, limit: int = 50):
    conn = fetcher.get_db()
    if coin:
        rows = conn.execute(
            "SELECT * FROM articles WHERE ',' || coins || ',' LIKE ? "
            "ORDER BY fetched_at DESC LIMIT ?",
            (f"%,{coin},%", limit),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM articles ORDER BY fetched_at DESC LIMIT ?", (limit,)
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# --- סיכומים ---

@app.get("/api/summary")
def get_summary(coin: str, period: str = "daily"):
    return fetcher.get_summary(coin, period)


# --- רענון ידני ---

@app.post("/api/refresh")
def refresh():
    result = fetcher.refresh_all()
    return JSONResponse(result)


# --- הגשת הפרונטאנד ---
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))
