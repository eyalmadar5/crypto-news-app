# -*- coding: utf-8 -*-
"""
תצורה מרכזית: אילו מטבעות עוקבים אחריהם, אילו מילות מפתח מזהות אותם בכתבה,
ומאילו מקורות (RSS) שואבים חדשות.

כדי להוסיף מטבע חדש: הוסף שורה ל-COINS.
כדי להוסיף/להסיר מקור: ערוך את NEWS_SOURCES או OFFICIAL_SOURCES.
"""

# --- המטבעות שעוקבים אחריהם ---
# key = הסימול שיוצג באתר, value = מילות מפתח לזיהוי הכתבה (case-insensitive)
COINS = {
    "XRP":  {"name": "XRP (Ripple)",     "coingecko_id": "ripple",              "keywords": ["xrp", "ripple"]},
    "ALGO": {"name": "Algorand",         "coingecko_id": "algorand",            "keywords": ["algo", "algorand"]},
    "HBAR": {"name": "Hedera",           "coingecko_id": "hedera-hashgraph",    "keywords": ["hbar", "hedera"]},
    "XDC":  {"name": "XDC Network",      "coingecko_id": "xdce-crowd-sale",     "keywords": ["xdc", "xinfin", "xdc network"]},
    "XLM":  {"name": "Stellar",          "coingecko_id": "stellar",             "keywords": ["xlm", "stellar"]},
}

# --- מקורות חדשות כלליים ואיכותיים (RSS) ---
# אלה אתרי חדשות קריפטו בינלאומיים ומוכרים. כל כתבה מהם תסונן לפי מילות המפתח מלמעלה.
NEWS_SOURCES = {
    "CoinDesk":      "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Cointelegraph": "https://cointelegraph.com/rss",
    "Decrypt":       "https://decrypt.co/feed",
    "CryptoSlate":   "https://cryptoslate.com/feed/",
    "The Daily Hodl":"https://dailyhodl.com/feed/",
}

# --- הודעות/בלוגים רשמיים של הפרויקטים עצמם ---
# הערה: פרויקטים משנים כתובות RSS מדי פעם ולא לכולם יש RSS יציב -
# הרשימה הזו היא נקודת פתיחה ומומלץ לוודא/לעדכן אותה בעצמך מדי פעם.
OFFICIAL_SOURCES = {
    "XRP Ledger Foundation (Blog)": "https://xrpl.org/blog/feed.rss",
    "Stellar Blog":                 "https://stellar.org/blog/rss.xml",
    "Algorand Blog":                "https://algorand.co/blog/rss.xml",
    "Hedera Blog":                  "https://hedera.com/blog/rss.xml",
}

# איחוד לרשימה אחת עם תיוג "news" / "official" לשימוש הפנימי של ה-fetcher
ALL_SOURCES = (
    [{"name": n, "url": u, "kind": "news"} for n, u in NEWS_SOURCES.items()]
    + [{"name": n, "url": u, "kind": "official"} for n, u in OFFICIAL_SOURCES.items()]
)
