import os
import re
import json
import uuid
import asyncio
import logging
from groq import Groq
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
import redis
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

# כשהמשתמש לוחץ "אשר" בטלגרם, ה-Brain מפעיל את הסוכן מחדש עם מזהה ההזמנה הממתינה
CONFIRMED_ORDER_ID = os.environ.get("CONFIRMED_ORDER_ID")

MAX_ORDER_QTY       = int(os.environ.get("MAX_ORDER_QTY", "100"))  # תקרת בטיחות לכמות בפקודה אחת
PENDING_TTL_SECONDS = 300                                         # כמה זמן אפשר לאשר (5 דקות)

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY,
    "Content-Type": "application/json"
}

redis_client = redis.Redis(host="redis-service", port=6379, decode_responses=True)


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
        max_tokens=50,
        temperature=0
    )
    raw = response.choices[0].message.content.strip()
    # מודלים לפעמים עוטפים את ה-JSON ב-```json ... ``` — מחלצים רק את האובייקט
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"תשובה לא תקינה מהמודל: {raw[:100]}")
    return json.loads(match.group(0))


def validate_order(symbol: str, qty) -> str | None:
    """בודק שהפקודה הגיונית לפני שמציגים אותה לאישור. מחזיר הודעת שגיאה או None."""
    if not re.fullmatch(r"[A-Z]{1,5}(\.[A-Z])?", symbol or ""):
        return f"סימול לא תקין: {symbol!r}"
    try:
        qty = int(qty)
    except (TypeError, ValueError):
        return f"כמות לא תקינה: {qty!r}"
    if qty <= 0:
        return "הכמות חייבת להיות חיובית"
    if qty > MAX_ORDER_QTY:
        return f"כמות {qty} חורגת מהתקרה ({MAX_ORDER_QTY}). אפשר לשנות דרך MAX_ORDER_QTY."
    resp = requests.get(f"{ALPACA_BASE_URL}/v2/assets/{symbol}", headers=HEADERS, timeout=15)
    if resp.status_code != 200:
        return f"המניה {symbol} לא נמצאה ב-Alpaca"
    if not resp.json().get("tradable"):
        return f"המניה {symbol} לא סחירה ב-Alpaca"
    return None


def place_order(symbol: str, qty: int, side: str) -> dict:
    """שולח פקודת שוק ל-Alpaca"""
    url  = f"{ALPACA_BASE_URL}/v2/orders"
    body = {
        "symbol":        symbol,
        "qty":           str(qty),
        "side":          side,
        "type":          "market",
        "time_in_force": "day"
    }
    response = requests.post(url, headers=HEADERS, json=body, timeout=15)
    return response.json()


def get_positions() -> list:
    """מחזיר את כל הפוזיציות הפתוחות"""
    url      = f"{ALPACA_BASE_URL}/v2/positions"
    response = requests.get(url, headers=HEADERS, timeout=15)
    return response.json()


def get_portfolio() -> dict:
    """מחזיר מידע על החשבון"""
    url      = f"{ALPACA_BASE_URL}/v2/account"
    response = requests.get(url, headers=HEADERS, timeout=15)
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


async def request_confirmation(bot: Bot, action: str, symbol: str, qty: int):
    """שומר את הפקודה ב-Redis ושולח למשתמש כפתורי אישור/ביטול. שום דבר לא נשלח ל-Alpaca עדיין."""
    order_id = uuid.uuid4().hex[:10]
    redis_client.setex(
        f"pending_order:{order_id}",
        PENDING_TTL_SECONDS,
        json.dumps({"action": action, "symbol": symbol, "qty": qty, "chat_id": str(CHAT_ID)})
    )
    verb     = "קנייה" if action == "buy" else "מכירה"
    emoji    = "📈" if action == "buy" else "📉"
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ אשר", callback_data=f"confirm:{order_id}"),
        InlineKeyboardButton("❌ בטל", callback_data=f"cancel:{order_id}"),
    ]])
    await bot.send_message(
        chat_id=CHAT_ID,
        text=f"{emoji} *אישור {verb}*\n\n{symbol} — {qty} מניות, במחיר שוק.\n\n⏳ תוקף האישור: 5 דקות.",
        parse_mode="Markdown",
        reply_markup=keyboard
    )


def execute_confirmed_order(order_id: str) -> str:
    """מבצע פקודה שהמשתמש אישר. getdel מבטיח שאותה פקודה לא תבוצע פעמיים."""
    raw = redis_client.getdel(f"pending_order:{order_id}")
    if not raw:
        return "⌛ הפקודה פגה או שכבר טופלה — לא בוצע דבר."
    order = json.loads(raw)
    if order["chat_id"] != str(CHAT_ID):
        return "⛔ הפקודה לא שייכת לצ'אט הזה."

    action, symbol, qty = order["action"], order["symbol"], int(order["qty"])
    result = place_order(symbol, qty, action)
    verb   = "קנייה" if action == "buy" else "מכירה"
    emoji  = "📈" if action == "buy" else "📉"
    if "id" in result:
        return (f"✅ *פקודת {verb} נשלחה!*\n\n{emoji} {symbol}\n🔢 כמות: {qty} מניות\n"
                f"📋 מספר הזמנה: `{result['id'][:8]}...`\n\n⏳ הפקודה תבוצע במחיר השוק.")
    return f"❌ שגיאה ב{verb}: {result.get('message', str(result))}"


async def run():
    logger.info(f"Trader agent התעורר למשימה: {TASK}")
    bot = Bot(token=TELEGRAM_TOKEN)

    try:
        if CONFIRMED_ORDER_ID:
            message = execute_confirmed_order(CONFIRMED_ORDER_ID)
        else:
            intent = parse_trade_intent(TASK)
            action = intent.get("action")
            logger.info(f"Intent: {intent}")

            if action in ("buy", "sell"):
                symbol = str(intent.get("symbol", "")).upper().strip()
                qty    = intent.get("qty", 1)
                error  = validate_order(symbol, qty)
                if error:
                    message = f"❌ {error}"
                else:
                    await request_confirmation(bot, action, symbol, int(qty))
                    return

            elif action == "positions":
                positions = get_positions()
                message   = format_positions(positions)

            elif action == "portfolio":
                account    = get_portfolio()
                cash       = float(account.get("cash", 0))
                equity     = float(account.get("equity", 0))
                buying_pwr = float(account.get("buying_power", 0))
                pl_today   = equity - float(account.get("last_equity", equity))
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
