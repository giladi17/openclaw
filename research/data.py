"""
נתונים יומיים מ-Alpaca לבדיקות היסטוריות, עם cache מקומי ב-research/data/.

- feed=sip: כל הבורסות (ל-IEX אין נתונים לפני ~2020, והנפח שלו חלקי)
- adjustment=all: מותאם לפיצולים ודיבידנדים, כדי שתשואות יהיו נכונות
- המפתחות נלקחים מ-.env בשורש הפרויקט
"""
from pathlib import Path

import pandas as pd
import requests

ROOT      = Path(__file__).resolve().parent.parent
CACHE_DIR = Path(__file__).resolve().parent / "data"
START     = "2015-01-01"   # ב-feed של SIP הנתונים מתחילים בפועל ב-2016-01-04
BARS_URL  = "https://data.alpaca.markets/v2/stocks/bars"

# שמות שהשתנו: הנתונים ההיסטוריים נמצאים תחת השם החדש
RENAMED = {"SQ": "XYZ"}

UNIVERSES = {
    # רשימת המעקב של הבוט — נבחרה בדיעבד (מניות צמיחה שעלו), לכן תוצאות עליה מנופחות
    "watchlist": ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA", "AMD", "NFLX", "CRM",
                  "SHOP", "SQ", "COIN", "PLTR", "UBER", "SNAP", "SPOT", "ZM", "RBLX", "PYPL"],
    # ETF-ים: 11 סקטורים של S&P 500 + מדדים, חו"ל, אג"ח, זהב ופיקדון (BIL). אין כאן "בחירה בדיעבד" של מניות
    "etf": ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",
            "SPY", "QQQ", "IWM", "EFA", "EEM", "TLT", "IEF", "GLD", "BIL"],
    # S&P 100 לפי ההרכב הנוכחי — רחב יותר, אבל עדיין עם survivorship bias (מי שנפל מהמדד לא כאן)
    "sp100": ["AAPL", "ABBV", "ABT", "ACN", "ADBE", "AIG", "AMD", "AMGN", "AMT", "AMZN", "AVGO", "AXP",
              "BA", "BAC", "BK", "BKNG", "BLK", "BMY", "BRK.B", "C", "CAT", "CHTR", "CL", "CMCSA", "COF",
              "COP", "COST", "CRM", "CSCO", "CVS", "CVX", "DE", "DHR", "DIS", "DUK", "EMR", "F", "FDX",
              "GD", "GE", "GILD", "GM", "GOOGL", "GS", "HD", "HON", "IBM", "INTC", "INTU", "ISRG", "JNJ",
              "JPM", "KO", "LIN", "LLY", "LMT", "LOW", "MA", "MCD", "MDLZ", "MDT", "MET", "META", "MMM",
              "MO", "MRK", "MS", "MSFT", "NEE", "NFLX", "NKE", "NOW", "NVDA", "ORCL", "PEP", "PFE", "PG",
              "PLTR", "PM", "PYPL", "QCOM", "RTX", "SBUX", "SCHW", "SO", "SPG", "T", "TGT", "TMO", "TMUS",
              "TSLA", "TXN", "UBER", "UNH", "UNP", "UPS", "USB", "V", "VZ", "WFC", "WMT", "XOM"],
}


def _headers() -> dict:
    env = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            env[key.strip()] = value.strip()
    return {"APCA-API-KEY-ID": env["ALPACA_API_KEY"], "APCA-API-SECRET-KEY": env["ALPACA_SECRET_KEY"]}


def _download(symbols: list[str], end: str) -> dict[str, pd.DataFrame]:
    headers = _headers()
    params  = {"symbols": ",".join(symbols), "timeframe": "1Day", "start": START, "end": end,
               "adjustment": "all", "feed": "sip", "limit": 10000}
    rows: dict[str, list] = {}
    while True:
        resp = requests.get(BARS_URL, headers=headers, params=params, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        for sym, bars in (body.get("bars") or {}).items():
            rows.setdefault(sym, []).extend(bars)
        if not body.get("next_page_token"):
            break
        params["page_token"] = body["next_page_token"]

    frames = {}
    for sym, bars in rows.items():
        df = pd.DataFrame(bars).rename(columns={"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"})
        df.index = pd.to_datetime(df["t"]).dt.tz_convert("America/New_York").dt.normalize().dt.tz_localize(None)
        frames[sym] = df[["open", "high", "low", "close", "volume"]].sort_index()
    return frames


def load(symbols: list[str], refresh: bool = False) -> dict[str, pd.DataFrame]:
    """מחזיר {סימבול: DataFrame יומי}. מוריד רק מה שחסר ב-cache (או הכל עם refresh)."""
    CACHE_DIR.mkdir(exist_ok=True)
    end     = (pd.Timestamp.now(tz="America/New_York").normalize() - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    wanted  = {sym: RENAMED.get(sym, sym) for sym in symbols}
    missing = [src for sym, src in wanted.items()
               if refresh or not (CACHE_DIR / f"{src}.csv").exists()]

    for i in range(0, len(missing), 50):
        for src, df in _download(missing[i:i + 50], end).items():
            df.to_csv(CACHE_DIR / f"{src}.csv")

    out = {}
    for sym, src in wanted.items():
        path = CACHE_DIR / f"{src}.csv"
        if path.exists():
            out[sym] = pd.read_csv(path, index_col=0, parse_dates=True)
    return out
