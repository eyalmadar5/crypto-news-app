# -*- coding: utf-8 -*-
"""
שרת מקומי (FastAPI) שמגיש:
1. API לחדשות ומחירים (מתוך ה-DB המקומי)
2. את הפרונטאנד (index.html) בכתובת http://localhost:8000
"""
from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import fetcher
from sources import COINS

app = FastAPI(title="Crypto News Dashboard")

FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.on_event("startup")
def startup():
    fetcher.init_db()


@app.get("/api/coins")
def get_coins():
    return {sym: info["name"] for sym, info in COINS.items()}


@app.get("/api/prices")
def get_prices():
    conn = fetcher.get_db()
    rows = conn.execute("SELECT * FROM prices").fetchall()
    conn.close()
    return [dict(r) for r in rows]


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


@app.post("/api/refresh")
def refresh():
    result = fetcher.refresh_all()
    return JSONResponse(result)


# --- הגשת הפרונטאנד ---
app.mount("/static", StaticFiles(directory=str(FRONTEND_DIR)), name="static")


@app.get("/")
def index():
    return FileResponse(str(FRONTEND_DIR / "index.html"))
