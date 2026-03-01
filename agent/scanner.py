import os
import json
import asyncio
import logging
from groq import Groq
from telegram import Bot
import requests
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID           = os.environ.get("CHAT_ID")
TASK              = os.environ.get("TASK", "morning_scan")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY")
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
}

# רשימת המניות לסריקה
WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "AMD",  "NFLX", "CRM",
    "SHOP", "SQ",   "COIN", "PLTR", "UBER",
    "SNAP", "SPOT", "ZM",   "RBLX", "PYPL"
]


def get_stock_bars(symbol: str) -> list:
    """שולף נתוני מניה מ-Alpaca"""
    start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
    url        = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    params     = {"timeframe": "1Day", "limit": 30, "start": start_date}
    response   = requests.get(url, headers=HEADERS, params=params)
    data       = response.json()
    return data.get("bars", [])


def calculate_rsi(closes: list, period: int = 14) -> float:
    if len(closes) < period + 1:
        return 50.0
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(diff, 0))
        losses.append(max(-diff, 0))
    avg_gain = sum(gains[-period:]) / period
    avg_loss = sum(losses[-period:]) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def scan_stock(symbol: str) -> dict:
    """סורק מניה אחת ומחזיר ציון"""
    try:
        bars = get_stock_bars(symbol)
        if len(bars) < 10:
            return None

        closes        = [bar["c"] for bar in bars]
        volumes       = [bar["v"] for bar in bars]
        rsi           = calculate_rsi(closes)
        ma7           = sum(closes[-7:])  / min(7,  len(closes))
        ma20          = sum(closes[-20:]) / min(20, len(closes))
        current_price = closes[-1]
        prev_price    = closes[-2]
        change_pct    = ((current_price - prev_price) / prev_price) * 100
        avg_volume    = sum(volumes[-10:]) / 10
        curr_volume   = volumes[-1]
        volume_ratio  = curr_volume / avg_volume if avg_volume > 0 else 1

        # ציון הזדמנות (0-100)
        score = 0

        # RSI בין 35-50 = הזדמנות קנייה טובה
        if 35 <= rsi <= 50:
            score += 30
        elif 30 <= rsi <= 35:
            score += 20

        # MA7 מעל MA20 = מגמה חיובית
        if ma7 > ma20:
            score += 25

        # נפח גבוה = עניין בשוק
        if volume_ratio > 1.5:
            score += 20

        # שינוי חיובי קטן = מומנטום
        if 0 < change_pct < 3:
            score += 25

        return {
            "symbol":       symbol,
            "price":        round(current_price, 2),
            "change_pct":   round(change_pct, 2),
            "rsi":          round(rsi, 2),
            "ma7":          round(ma7, 2),
            "ma20":         round(ma20, 2),
            "volume_ratio": round(volume_ratio, 2),
            "score":        score
        }
    except Exception as e:
        logger.warning(f"שגיאה בסריקת {symbol}: {e}")
        return None


def get_current_positions() -> list:
    """מחזיר פוזיציות פתוחות"""
    url      = f"{ALPACA_BASE_URL}/v2/positions"
    response = requests.get(url, headers=HEADERS)
    return response.json()


def check_evening_positions(positions: list) -> list:
    """בודק אילו פוזיציות צריך למכור"""
    to_sell = []
    for pos in positions:
        symbol  = pos.get("symbol")
        pl_pct  = float(pos.get("unrealized_plpc", 0)) * 100
        qty     = pos.get("qty")

        # מכור אם רווח > 15% או הפסד > 10%
        if pl_pct >= 15:
            to_sell.append({"symbol": symbol, "qty": qty, "reason": f"רווח {pl_pct:.1f}% 🎯"})
        elif pl_pct <= -10:
            to_sell.append({"symbol": symbol, "qty": qty, "reason": f"Stop Loss {pl_pct:.1f}% 🛑"})

    return to_sell



def is_market_bullish() -> bool:
    """בודק אם השוק במגמה חיובית לפי SPY"""
    try:
        start_date = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
        url        = "https://data.alpaca.markets/v2/stocks/SPY/bars"
        params     = {"timeframe": "1Day", "limit": 25, "start": start_date}
        response   = requests.get(url, headers=HEADERS, params=params)
        bars       = response.json().get("bars", [])
        if len(bars) < 20:
            return True
        closes  = [bar["c"] for bar in bars]
        ma20    = sum(closes[-20:]) / 20
        current = closes[-1]
        return current > ma20
    except:
        return True


async def morning_scan(bot: Bot):
    """סריקת בוקר — מוצא הזדמנויות וקונה"""
    logger.info("🌅 סריקת בוקר מתחילה...")

    # בדוק אם השוק חיובי
    market_ok = is_market_bullish()
    market_msg = "🟢 השוק במגמה חיובית" if market_ok else "🔴 השוק במגמה שלילית — לא קונה היום"

    await bot.send_message(
        chat_id=CHAT_ID,
        text=f"🌅 *סריקת בוקר מתחילה...*\n{market_msg}\nסורק 20 מניות, זה ייקח כדקה.",
        parse_mode="Markdown"
    )

    if not market_ok:
        positions = get_current_positions()
        if positions and isinstance(positions, list) and len(positions) > 0:
            lines = ["📋 *מצב התיק הנוכחי:*
"]
            total_pl = 0
            for pos in positions:
                pl     = float(pos.get("unrealized_pl", 0))
                pl_pct = float(pos.get("unrealized_plpc", 0)) * 100
                emoji  = "🟢" if pl >= 0 else "🔴"
                total_pl += pl
                lines.append(f"{emoji} {pos.get('symbol')}: ${pl:.2f} ({pl_pct:.1f}%)")
            total_emoji = "🟢" if total_pl >= 0 else "🔴"
            lines.append(f"
{total_emoji} *סה\"כ P&L: ${total_pl:.2f}*")
            await bot.send_message(chat_id=CHAT_ID, text="
".join(lines), parse_mode="Markdown")
        else:
            await bot.send_message(chat_id=CHAT_ID, text="📭 אין פוזיציות פתוחות כרגע.")
        return

    # סריקת כל המניות
    results = []
    for symbol in WATCHLIST:
        result = scan_stock(symbol)
        if result:
            results.append(result)

    # מיון לפי ציון
    results.sort(key=lambda x: x["score"], reverse=True)
    top_picks = results[:5]  # 5 הטובות ביותר

    if not top_picks:
        await bot.send_message(chat_id=CHAT_ID, text="😴 לא נמצאו הזדמנויות טובות הבוקר.")
        return

    # בניית הודעת סיכום
    lines = ["📊 *סריקת בוקר — תוצאות:*\n"]
    for i, stock in enumerate(top_picks, 1):
        lines.append(
            f"{i}. *{stock['symbol']}* — ציון: {stock['score']}/100\n"
            f"   💰 ${stock['price']} | RSI: {stock['rsi']} | שינוי: {stock['change_pct']}%\n"
        )

    await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines), parse_mode="Markdown")

    # קנייה אוטומטית של Top 3
    bought = []
    for stock in top_picks[:3]:
        if stock["score"] >= 50:  # קנה רק אם ציון גבוה מספיק
            try:
                url  = f"{ALPACA_BASE_URL}/v2/orders"
                body = {
                    "symbol":        stock["symbol"],
                    "qty":           "2",
                    "side":          "buy",
                    "type":          "market",
                    "time_in_force": "day"
                }
                response = requests.post(url, headers={**HEADERS, "Content-Type": "application/json"}, json=body)
                result   = response.json()
                if "id" in result:
                    bought.append(stock["symbol"])
            except Exception as e:
                logger.error(f"שגיאה בקנייה של {stock['symbol']}: {e}")

    if bought:
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"✅ *קניתי אוטומטית:* {', '.join(bought)}\n2 מניות מכל אחת במחיר שוק.",
            parse_mode="Markdown"
        )


async def evening_scan(bot: Bot):
    """סריקת ערב — בודק פוזיציות ומוכר לפי הצורך"""
    logger.info("🌆 סריקת ערב מתחילה...")

    positions = get_current_positions()

    if not positions:
        await bot.send_message(chat_id=CHAT_ID, text="🌆 *סריקת ערב:* אין פוזיציות פתוחות.", parse_mode="Markdown")
        return

    to_sell = check_evening_positions(positions)

    # מכירה אוטומטית
    sold = []
    for item in to_sell:
        try:
            url  = f"{ALPACA_BASE_URL}/v2/orders"
            body = {
                "symbol":        item["symbol"],
                "qty":           item["qty"],
                "side":          "sell",
                "type":          "market",
                "time_in_force": "day"
            }
            response = requests.post(url, headers={**HEADERS, "Content-Type": "application/json"}, json=body)
            result   = response.json()
            if "id" in result:
                sold.append(f"{item['symbol']} ({item['reason']})")
        except Exception as e:
            logger.error(f"שגיאה במכירה של {item['symbol']}: {e}")

    # דוח ערב
    lines = ["🌆 *דוח ערב:*\n"]
    total_pl = 0
    for pos in positions:
        symbol  = pos.get("symbol")
        pl      = float(pos.get("unrealized_pl", 0))
        pl_pct  = float(pos.get("unrealized_plpc", 0)) * 100
        emoji   = "🟢" if pl >= 0 else "🔴"
        total_pl += pl
        lines.append(f"{emoji} {symbol}: ${pl:.2f} ({pl_pct:.1f}%)")

    total_emoji = "🟢" if total_pl >= 0 else "🔴"
    lines.append(f"\n{total_emoji} *סה\"כ P&L: ${total_pl:.2f}*")

    if sold:
        lines.append(f"\n🔄 *מכרתי:* {', '.join(sold)}")

    await bot.send_message(chat_id=CHAT_ID, text="\n".join(lines), parse_mode="Markdown")


async def run():
    logger.info(f"Scanner agent התעורר | task={TASK}")
    bot = Bot(token=TELEGRAM_TOKEN)

    if TASK == "morning_scan":
        await morning_scan(bot)
    elif TASK == "evening_scan":
        await evening_scan(bot)
    else:
        await bot.send_message(chat_id=CHAT_ID, text=f"❓ TASK לא מוכר: {TASK}")


if __name__ == "__main__":
    asyncio.run(run())