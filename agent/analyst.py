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
TASK              = os.environ.get("TASK")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY")
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")


def get_stock_data(symbol: str) -> dict:
    headers = {
        "APCA-API-KEY-ID": ALPACA_API_KEY,
        "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
    }
    # 30 הנרות האחרונים: sort=desc כדי לקבל את הימים העדכניים ולא את הישנים בטווח,
    # ואז הופכים חזרה לסדר כרונולוגי (ישן → חדש)
    start_date = (datetime.now() - timedelta(days=70)).strftime("%Y-%m-%d")

    url    = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    params = {"timeframe": "1Day", "start": start_date, "limit": 30,
              "sort": "desc", "feed": "iex"}

    response = requests.get(url, headers=headers, params=params, timeout=15)
    data     = response.json()
    bars     = list(reversed(data.get("bars") or []))

    if not bars:
        return {"error": f"לא נמצאו נתונים עבור {symbol}"}

    closes        = [bar["c"] for bar in bars]
    rsi           = calculate_rsi(closes)
    ma7           = sum(closes[-7:])  / min(7,  len(closes))
    ma20          = sum(closes[-20:]) / min(20, len(closes))
    current_price = closes[-1]
    prev_price    = closes[-2] if len(closes) > 1 else current_price
    change_pct    = ((current_price - prev_price) / prev_price) * 100

    return {
        "symbol":        symbol,
        "current_price": round(current_price, 2),
        "change_pct":    round(change_pct, 2),
        "rsi":           round(rsi, 2),
        "ma7":           round(ma7, 2),
        "ma20":          round(ma20, 2),
        "signal":        get_signal(rsi, ma7, ma20, current_price)
    }


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


def get_signal(rsi: float, ma7: float, ma20: float, price: float) -> str:
    if rsi < 30 and ma7 > ma20:
        return "BUY"
    elif rsi > 70 and ma7 < ma20:
        return "SELL"
    else:
        return "HOLD"


async def run():
    logger.info(f"Analyst agent התעורר למשימה: {TASK}")
    groq_client = Groq(api_key=GROQ_API_KEY)

    # חילוץ שם המניה
    extract_response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "Extract only the stock ticker symbol from the text. Return ONLY the ticker in uppercase, nothing else. Example: AAPL"},
            {"role": "user", "content": TASK}
        ],
        max_tokens=10
    )
    symbol = extract_response.choices[0].message.content.strip().upper()
    logger.info(f"מנתח מניה: {symbol}")

    stock_data = get_stock_data(symbol)

    if "error" in stock_data:
        message = f"❌ {stock_data['error']}"
    else:
        analysis_response = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "אתה אנליסט מניות מומחה. נתח את הנתונים ותן המלצה ברורה. ענה בעברית."},
                {"role": "user", "content": f"נתח את המניה {symbol} על בסיס הנתונים: {json.dumps(stock_data, ensure_ascii=False)}"}
            ],
            max_tokens=500
        )
        analysis      = analysis_response.choices[0].message.content
        signal_emoji  = {"BUY": "🟢", "SELL": "🔴", "HOLD": "🟡"}.get(stock_data["signal"], "⚪")

        message = f"""📊 *ניתוח {symbol}*

💰 מחיר: ${stock_data['current_price']}
📈 שינוי: {stock_data['change_pct']}%
📉 RSI: {stock_data['rsi']}
📊 MA7: ${stock_data['ma7']} | MA20: ${stock_data['ma20']}

{signal_emoji} *סיגנל: {stock_data['signal']}*

{analysis}"""

    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
    logger.info("ניתוח נשלח!")


if __name__ == "__main__":
    asyncio.run(run())