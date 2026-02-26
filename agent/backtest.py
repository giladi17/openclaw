import os
import json
import asyncio
import logging
import requests
from datetime import datetime, timedelta
from groq import Groq
from telegram import Bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID           = os.environ.get("CHAT_ID")
TASK              = os.environ.get("TASK", "backtest")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY")
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
}

WATCHLIST = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA",
    "META", "TSLA", "AMD",  "NFLX", "CRM",
    "SHOP", "SQ",   "COIN", "PLTR", "UBER",
    "SNAP", "SPOT", "ZM",   "RBLX", "PYPL"
]


def get_historical_bars(symbol: str, start: str, end: str) -> list:
    """שולף נתונים היסטוריים מ-Alpaca"""
    url    = f"https://data.alpaca.markets/v2/stocks/{symbol}/bars"
    params = {"timeframe": "1Day", "start": start, "end": end, "limit": 1000, "feed": "iex"}
    response = requests.get(url, headers=HEADERS, params=params)
    data     = response.json()
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


def score_stock(closes: list, volumes: list) -> int:
    """מחשב ציון הזדמנות — אותה לוגיקה כמו Scanner"""
    if len(closes) < 20:
        return 0

    rsi    = calculate_rsi(closes)
    ma7    = sum(closes[-7:])  / 7
    ma20   = sum(closes[-20:]) / 20
    change = ((closes[-1] - closes[-2]) / closes[-2]) * 100
    avg_vol = sum(volumes[-10:]) / 10
    vol_ratio = volumes[-1] / avg_vol if avg_vol > 0 else 1

    score = 0
    if 35 <= rsi <= 50:
        score += 30
    elif 30 <= rsi <= 35:
        score += 20
    if ma7 > ma20:
        score += 25
    if vol_ratio > 1.5:
        score += 20
    if 0 < change < 3:
        score += 25

    return score



def is_market_bullish_on_date(all_spy_bars: list, date_str: str) -> bool:
    """בודק אם השוק היה חיובי בתאריך מסוים"""
    bars_until = [b for b in all_spy_bars if b["t"][:10] <= date_str]
    if len(bars_until) < 20:
        return True
    closes  = [b["c"] for b in bars_until]
    ma20    = sum(closes[-20:]) / 20
    current = closes[-1]
    return current > ma20


def run_backtest(start_date: str, end_date: str, initial_capital: float = 100000) -> dict:
    """
    מריץ backtest על כל ה-watchlist בין start_date ל-end_date
    """
    logger.info(f"מריץ backtest: {start_date} → {end_date}")

    # טעינת נתוני SPY לפילטר שוק
    spy_bars = get_historical_bars("SPY", start_date, end_date)

    # שלב 1: הורדת כל הנתונים
    all_data = {}
    for symbol in WATCHLIST:
        bars = get_historical_bars(symbol, start_date, end_date)
        if len(bars) >= 30:
            all_data[symbol] = bars

    if not all_data:
        return {"error": "לא נמצאו נתונים"}

    # שלב 2: סימולציה יום אחרי יום
    capital       = initial_capital
    positions     = {}   # symbol → {qty, buy_price, buy_date}
    trades        = []   # היסטוריית עסקאות
    daily_capital = []   # לגרף

    # מוצאים את כל התאריכים הייחודיים
    all_dates = set()
    for bars in all_data.values():
        for bar in bars:
            all_dates.add(bar["t"][:10])
    all_dates = sorted(all_dates)

    for date_str in all_dates:
        # בנה snapshot של נתונים עד היום הזה
        day_data = {}
        for symbol, bars in all_data.items():
            bars_until_today = [b for b in bars if b["t"][:10] <= date_str]
            if len(bars_until_today) >= 20:
                day_data[symbol] = bars_until_today

        # בדוק פוזיציות קיימות — מכור אם צריך
        for symbol in list(positions.keys()):
            if symbol not in day_data:
                continue
            current_price = day_data[symbol][-1]["c"]
            buy_price     = positions[symbol]["buy_price"]
            pl_pct        = ((current_price - buy_price) / buy_price) * 100
            days_held     = (datetime.strptime(date_str, "%Y-%m-%d") -
                             datetime.strptime(positions[symbol]["buy_date"], "%Y-%m-%d")).days

            # מכור: רווח > 15% או הפסד > 10% או החזקה > 10 ימים
            should_sell = pl_pct >= 15 or pl_pct <= -10 or days_held >= 10

            if should_sell:
                qty        = positions[symbol]["qty"]
                sell_value = qty * current_price
                capital   += sell_value
                reason     = "take_profit" if pl_pct >= 15 else ("stop_loss" if pl_pct <= -10 else "timeout")

                trades.append({
                    "symbol":     symbol,
                    "buy_date":   positions[symbol]["buy_date"],
                    "sell_date":  date_str,
                    "buy_price":  round(buy_price, 2),
                    "sell_price": round(current_price, 2),
                    "pl_pct":     round(pl_pct, 2),
                    "reason":     reason
                })
                del positions[symbol]

        # סרוק הזדמנויות חדשות (רק אם יש מספיק הון והשוק חיובי)
        market_ok = is_market_bullish_on_date(spy_bars, date_str)
        if market_ok and capital > initial_capital * 0.1 and len(positions) < 5:
            candidates = []
            for symbol, bars in day_data.items():
                if symbol in positions:
                    continue
                closes  = [b["c"] for b in bars]
                volumes = [b["v"] for b in bars]
                score   = score_stock(closes, volumes)
                if score >= 50:
                    candidates.append((symbol, score, closes[-1]))

            candidates.sort(key=lambda x: x[1], reverse=True)

            for symbol, score, price in candidates[:2]:
                invest = min(capital * 0.15, capital / 3)
                qty    = int(invest / price)
                if qty > 0:
                    cost     = qty * price
                    capital -= cost
                    positions[symbol] = {
                        "qty":       qty,
                        "buy_price": price,
                        "buy_date":  date_str
                    }

        # חשב שווי יומי
        portfolio_value = capital
        for symbol, pos in positions.items():
            if symbol in day_data:
                portfolio_value += pos["qty"] * day_data[symbol][-1]["c"]
        daily_capital.append(portfolio_value)

    # חשב סטטיסטיקות
    if not trades:
        return {"error": "לא בוצעו עסקאות"}

    winning_trades = [t for t in trades if t["pl_pct"] > 0]
    losing_trades  = [t for t in trades if t["pl_pct"] <= 0]
    win_rate       = len(winning_trades) / len(trades) * 100
    avg_win        = sum(t["pl_pct"] for t in winning_trades) / len(winning_trades) if winning_trades else 0
    avg_loss       = sum(t["pl_pct"] for t in losing_trades)  / len(losing_trades)  if losing_trades  else 0

    final_value    = daily_capital[-1] if daily_capital else initial_capital
    total_return   = ((final_value - initial_capital) / initial_capital) * 100

    # Max Drawdown
    peak     = initial_capital
    max_dd   = 0
    for val in daily_capital:
        if val > peak:
            peak = val
        dd = ((peak - val) / peak) * 100
        if dd > max_dd:
            max_dd = dd

    best_trade  = max(trades, key=lambda x: x["pl_pct"])
    worst_trade = min(trades, key=lambda x: x["pl_pct"])

    return {
        "start_date":     start_date,
        "end_date":       end_date,
        "initial_capital": initial_capital,
        "final_value":    round(final_value, 2),
        "total_return":   round(total_return, 2),
        "total_trades":   len(trades),
        "win_rate":       round(win_rate, 1),
        "avg_win":        round(avg_win, 2),
        "avg_loss":       round(avg_loss, 2),
        "max_drawdown":   round(max_dd, 2),
        "best_trade":     best_trade,
        "worst_trade":    worst_trade,
        "winning_trades": len(winning_trades),
        "losing_trades":  len(losing_trades)
    }


async def run():
    logger.info(f"Backtest agent התעורר | task={TASK}")
    bot = Bot(token=TELEGRAM_TOKEN)

    await bot.send_message(
        chat_id=CHAT_ID,
        text="⏳ *מריץ Backtest...*\nבודק את האסטרטגיה על 6 חודשים אחורה. זה ייקח 2-3 דקות.",
        parse_mode="Markdown"
    )

    # 6 חודשים אחורה
    end_date   = datetime.now().strftime("%Y-%m-%d")
    start_date = "2024-08-01"

    # בדיקת נתונים לפני הרצה
    test_bars = get_historical_bars("AAPL", start_date, end_date)
    import asyncio as _asyncio
    await bot.send_message(chat_id=CHAT_ID, text=f"🔍 בדיקה: AAPL החזיר {len(test_bars)} ימים מ-{start_date}")

    results = run_backtest(start_date, end_date)

    if "error" in results:
        await bot.send_message(chat_id=CHAT_ID, text=f"❌ {results['error']}")
        return

    return_emoji = "🟢" if results["total_return"] >= 0 else "🔴"
    best  = results["best_trade"]
    worst = results["worst_trade"]

    message = f"""📊 *תוצאות Backtest*
_{results['start_date']} → {results['end_date']}_

💰 הון התחלתי: ${results['initial_capital']:,.0f}
💼 שווי סופי: ${results['final_value']:,.0f}
{return_emoji} *תשואה כוללת: {results['total_return']}%*

📈 סה"כ עסקאות: {results['total_trades']}
✅ עסקאות מוצלחות: {results['winning_trades']}
❌ עסקאות כושלות: {results['losing_trades']}
🎯 Win Rate: {results['win_rate']}%

📊 ממוצע רווח לעסקה: +{results['avg_win']}%
📊 ממוצע הפסד לעסקה: {results['avg_loss']}%
📉 Max Drawdown: -{results['max_drawdown']}%

🏆 *עסקה הכי טובה:*
{best['symbol']}: +{best['pl_pct']}% ({best['buy_date']} → {best['sell_date']})

💸 *עסקה הכי גרועה:*
{worst['symbol']}: {worst['pl_pct']}% ({worst['buy_date']} → {worst['sell_date']})"""

    # ניתוח AI של התוצאות
    groq_client = Groq(api_key=GROQ_API_KEY)
    analysis    = groq_client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[
            {"role": "system", "content": "אתה אנליסט מסחר מומחה. נתח את תוצאות ה-backtest ותן המלצות לשיפור האסטרטגיה. ענה בעברית, 3-4 משפטים."},
            {"role": "user",   "content": f"תוצאות backtest: {json.dumps(results, ensure_ascii=False)}"}
        ],
        max_tokens=300
    )

    message += f"\n\n🤖 *ניתוח AI:*\n{analysis.choices[0].message.content}"

    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
    logger.info("Backtest הושלם!")


if __name__ == "__main__":
    asyncio.run(run())