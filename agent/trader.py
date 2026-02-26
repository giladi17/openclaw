import os
import json
import asyncio
import logging
from groq import Groq
from telegram import Bot
import requests

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID           = os.environ.get("CHAT_ID")
TASK              = os.environ.get("TASK")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY")
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "Content-Type": "application/json"
}


def parse_trade_intent(task: str) -> dict:
    """
    משתמש ב-Groq כדי להבין מה המשתמש רוצה.
    מחזיר JSON עם action, symbol, qty
    """
    groq_client = Groq(api_key=GROQ_API_KEY)
    response = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {
                "role": "system",
                "content": """You are a trading intent parser. Extract trading intent from text and return ONLY a JSON object.

Possible actions: buy, sell, positions, portfolio

Return format:
{"action": "buy", "symbol": "AAPL", "qty": 5}
{"action": "sell", "symbol": "TSLA", "qty": 3}
{"action": "positions"}
{"action": "portfolio"}

If qty is not specified for buy/sell, use 1.
Return ONLY the JSON, nothing else."""
            },
            {"role": "user", "content": task}
        ],
        max_tokens=50
    )
    raw = response.choices[0].message.content.strip()
    return json.loads(raw)


def buy_stock(symbol: str, qty: int) -> dict:
    """קונה מניה דרך Alpaca"""
    url  = f"{ALPACA_BASE_URL}/v2/orders"
    body = {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          "buy",
        "type":          "market",
        "time_in_force": "day"
    }
    response = requests.post(url, headers=HEADERS, json=body)
    return response.json()


def sell_stock(symbol: str, qty: int) -> dict:
    """מוכר מניה דרך Alpaca"""
    url  = f"{ALPACA_BASE_URL}/v2/orders"
    body = {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          "sell",
        "type":          "market",
        "time_in_force": "day"
    }
    response = requests.post(url, headers=HEADERS, json=body)
    return response.json()


def get_positions() -> list:
    """מחזיר את כל הפוזיציות הפתוחות"""
    url      = f"{ALPACA_BASE_URL}/v2/positions"
    response = requests.get(url, headers=HEADERS)
    return response.json()


def get_portfolio() -> dict:
    """מחזיר מידע על החשבון"""
    url      = f"{ALPACA_BASE_URL}/v2/account"
    response = requests.get(url, headers=HEADERS)
    return response.json()


def format_positions(positions: list) -> str:
    """מעצב את רשימת הפוזיציות להצגה"""
    if not positions:
        return "📭 אין פוזיציות פתוחות כרגע."

    lines = ["📋 *הפוזיציות שלך:*\n"]
    for pos in positions:
        symbol    = pos.get("symbol", "")
        qty       = pos.get("qty", "0")
        avg_price = float(pos.get("avg_entry_price", 0))
        curr      = float(pos.get("current_price", 0))
        pl        = float(pos.get("unrealized_pl", 0))
        pl_pct    = float(pos.get("unrealized_plpc", 0)) * 100
        emoji     = "🟢" if pl >= 0 else "🔴"

        lines.append(
            f"{emoji} *{symbol}*: {qty} מניות\n"
            f"   קנייה: ${avg_price:.2f} | עכשיו: ${curr:.2f}\n"
            f"   P&L: ${pl:.2f} ({pl_pct:.1f}%)\n"
        )
    return "\n".join(lines)


async def run():
    logger.info(f"Trader agent התעורר למשימה: {TASK}")
    bot = Bot(token=TELEGRAM_TOKEN)

    try:
        intent = parse_trade_intent(TASK)
        action = intent.get("action")
        logger.info(f"Intent: {intent}")

        if action == "buy":
            symbol = intent.get("symbol", "").upper()
            qty    = int(intent.get("qty", 1))
            result = buy_stock(symbol, qty)

            if "id" in result:
                message = f"✅ *פקודת קנייה בוצעה!*\n\n📈 {symbol}\n🔢 כמות: {qty} מניות\n📋 מספר הזמנה: `{result['id'][:8]}...`\n\n⏳ הפקודה תבוצע במחיר השוק."
            else:
                error = result.get("message", str(result))
                message = f"❌ שגיאה בקנייה: {error}"

        elif action == "sell":
            symbol = intent.get("symbol", "").upper()
            qty    = int(intent.get("qty", 1))
            result = sell_stock(symbol, qty)

            if "id" in result:
                message = f"✅ *פקודת מכירה בוצעה!*\n\n📉 {symbol}\n🔢 כמות: {qty} מניות\n📋 מספר הזמנה: `{result['id'][:8]}...`\n\n⏳ הפקודה תבוצע במחיר השוק."
            else:
                error = result.get("message", str(result))
                message = f"❌ שגיאה במכירה: {error}"

        elif action == "positions":
            positions = get_positions()
            message   = format_positions(positions)

        elif action == "portfolio":
            account    = get_portfolio()
            cash       = float(account.get("cash", 0))
            equity     = float(account.get("equity", 0))
            buying_pwr = float(account.get("buying_power", 0))
            pl_today   = float(account.get("equity", 0)) - float(account.get("last_equity", equity))
            emoji      = "🟢" if pl_today >= 0 else "🔴"

            message = f"""💼 *התיק שלך:*

💰 שווי כולל: ${equity:,.2f}
💵 מזומן: ${cash:,.2f}
🛒 כוח קנייה: ${buying_pwr:,.2f}
{emoji} רווח/הפסד היום: ${pl_today:,.2f}"""

        else:
            message = "❓ לא הבנתי את הפקודה. נסה: 'קנה 5 מניות AAPL' או 'מה הפוזיציות שלי?'"

    except Exception as e:
        logger.error(f"שגיאה: {e}", exc_info=True)
        message = f"❌ שגיאה: {str(e)[:200]}"

    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
    logger.info("תשובת trader נשלחה!")


if __name__ == "__main__":
    asyncio.run(run())