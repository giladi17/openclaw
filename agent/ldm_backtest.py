"""
LDM — Leveraged Dual Momentum backtest

הכלל:
  בסוף כל חודש בודקים את QQQ מול הממוצע הנע של 200 יום (SMA200).
  QQQ מעל SMA200  → מחזיקים QLD (נאסד"ק x2) בחודש הבא
  QQQ מתחת SMA200 → מחזיקים BIL (אג"ח קצר מועד, "מזומן")

אין הצצה לעתיד: ההחלטה מתקבלת על מחיר הסגירה של היום האחרון בחודש,
והתשואה נספרת רק מהיום שאחריו. משווים מול קנה-והחזק של QQQ ושל QLD.
"""
import os
import json
import asyncio
import logging
from datetime import datetime, timedelta
import requests
from groq import Groq
from telegram import Bot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID           = os.environ.get("CHAT_ID")
GROQ_API_KEY      = os.environ.get("GROQ_API_KEY")
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
}

SIGNAL      = "QQQ"
RISK_ON     = "QLD"
RISK_OFF    = "BIL"
SMA_DAYS    = 200
YEARS       = 3
COST_PCT    = 0.10   # עלות משוערת (עמלה + slippage) לכל החלפה, באחוזים


def get_daily_closes(symbol: str, start: str, end: str) -> dict:
    """
    מחזיר {תאריך: מחיר סגירה מתואם} עם דפדוף (next_page_token).
    adjustment=all — מתאם לספליטים ודיבידנדים, אחרת התשואות של QLD/BIL שגויות.
    מנסה קודם SIP (נתונים מלאים; בחשבון חינמי מותר להיסטוריה שמסתיימת לפני 15 דק'), ואז IEX.
    """
    for feed in ("sip", "iex"):
        closes, token = {}, None
        try:
            while True:
                params = {"timeframe": "1Day", "start": start, "end": end, "limit": 10000,
                          "adjustment": "all", "feed": feed}
                if token:
                    params["page_token"] = token
                resp = requests.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                                    headers=HEADERS, params=params, timeout=30)
                resp.raise_for_status()
                data = resp.json()
                for bar in data.get("bars") or []:
                    closes[bar["t"][:10]] = bar["c"]
                token = data.get("next_page_token")
                if not token:
                    break
            if closes:
                return closes
        except Exception as e:
            logger.warning(f"{symbol} feed={feed} נכשל: {e}")
    return {}


def max_drawdown(values: list) -> float:
    peak, mdd = values[0], 0.0
    for v in values:
        peak = max(peak, v)
        mdd  = max(mdd, (peak - v) / peak * 100)
    return mdd


def cagr(start_val: float, end_val: float, days: int) -> float:
    years = days / 365.25
    return ((end_val / start_val) ** (1 / years) - 1) * 100 if years > 0 else 0.0


def run_ldm_backtest(years: int = YEARS) -> dict:
    end       = datetime.utcnow() - timedelta(days=1)
    start     = end - timedelta(days=int(years * 365.25))
    # צריך עוד ~300 ימים קלנדריים לפני ההתחלה כדי לחשב SMA200 מהיום הראשון
    warmup    = start - timedelta(days=SMA_DAYS * 1.5)
    end_s, start_s, warm_s = end.strftime("%Y-%m-%d"), start.strftime("%Y-%m-%d"), warmup.strftime("%Y-%m-%d")

    qqq = get_daily_closes(SIGNAL, warm_s, end_s)
    qld = get_daily_closes(RISK_ON, warm_s, end_s)
    bil = get_daily_closes(RISK_OFF, warm_s, end_s)
    if not (qqq and qld and bil):
        return {"error": "לא הצלחתי להוריד נתונים מ-Alpaca עבור QQQ/QLD/BIL"}

    all_dates = sorted(d for d in qqq if d in qld and d in bil)
    sim_dates = [d for d in all_dates if d >= start_s]
    if len(sim_dates) < 60:
        return {"error": f"מעט מדי ימי מסחר משותפים ({len(sim_dates)})"}

    qqq_dates = sorted(qqq)

    def signal_on(date: str) -> str:
        """מה להחזיק אחרי סגירת היום `date`, לפי QQQ מול SMA200 עד אותו יום (כולל)"""
        hist = [qqq[d] for d in qqq_dates if d <= date][-SMA_DAYS:]
        if len(hist) < SMA_DAYS:
            return RISK_OFF
        return RISK_ON if hist[-1] > sum(hist) / SMA_DAYS else RISK_OFF

    prices  = {RISK_ON: qld, RISK_OFF: bil}
    first   = all_dates.index(sim_dates[0])
    holding = signal_on(all_dates[max(first - 1, 0)])
    value   = 100_000.0
    values  = [value]
    switches, months_on, months_total = 0, 0, 0
    log = []

    for i in range(1, len(sim_dates)):
        prev, today = sim_dates[i - 1], sim_dates[i]
        # תשואה של היום לפי מה שהוחלט עד אתמול
        value *= prices[holding][today] / prices[holding][prev]
        values.append(value)

        # יום מסחר אחרון בחודש → בדיקה חודשית
        is_month_end = (i == len(sim_dates) - 1) or (sim_dates[i + 1][:7] != today[:7])
        if is_month_end:
            months_total += 1
            new_holding = signal_on(today)
            if new_holding == RISK_ON:
                months_on += 1
            if new_holding != holding:
                switches += 1
                value    *= (1 - COST_PCT / 100)
                values[-1] = value
                log.append(f"{today}: {holding} → {new_holding}")
                holding = new_holding

    days = (datetime.strptime(sim_dates[-1], "%Y-%m-%d") - datetime.strptime(sim_dates[0], "%Y-%m-%d")).days

    def buy_hold(series: dict) -> dict:
        vals = [series[d] for d in sim_dates]
        return {
            "total_return": round((vals[-1] / vals[0] - 1) * 100, 1),
            "cagr":         round(cagr(vals[0], vals[-1], days), 1),
            "max_drawdown": round(max_drawdown(vals), 1),
        }

    return {
        "start_date":   sim_dates[0],
        "end_date":     sim_dates[-1],
        "ldm": {
            "total_return": round((values[-1] / values[0] - 1) * 100, 1),
            "cagr":         round(cagr(values[0], values[-1], days), 1),
            "max_drawdown": round(max_drawdown(values), 1),
        },
        "qqq":          buy_hold(qqq),
        "qld":          buy_hold(qld),
        "switches":     switches,
        "pct_time_qld": round(months_on / months_total * 100) if months_total else 0,
        "holding_now":  holding,
        "recent_switches": log[-5:],
    }


async def run():
    logger.info("LDM backtest agent התעורר")
    bot = Bot(token=TELEGRAM_TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text=f"⏳ *מריץ LDM Backtest* על {YEARS} שנים אחורה...",
                           parse_mode="Markdown")

    r = await asyncio.to_thread(run_ldm_backtest)
    if "error" in r:
        await bot.send_message(chat_id=CHAT_ID, text=f"❌ {r['error']}")
        return

    def row(name, d):
        return f"{name}: {d['total_return']:+}% | CAGR {d['cagr']}% | DD -{d['max_drawdown']}%"

    switches = "\n".join(r["recent_switches"]) or "—"
    message = f"""🎯 *LDM — Leveraged Dual Momentum*
_{r['start_date']} → {r['end_date']}_

{row('🦾 LDM', r['ldm'])}
{row('📊 QQQ', r['qqq'])}
{row('⚡ QLD', r['qld'])}

🔄 החלפות: {r['switches']} | זמן ב-QLD: {r['pct_time_qld']}%
📌 אחזקה נוכחית לפי הכלל: *{r['holding_now']}*

החלפות אחרונות:
{switches}

_עלות משוערת {COST_PCT}% לכל החלפה. ביצועי עבר אינם מבטיחים תשואה עתידית._"""

    try:
        groq_client = Groq(api_key=GROQ_API_KEY)
        analysis = groq_client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {"role": "system", "content": "אתה אנליסט כמותי. נתח בקצרה (3 משפטים, בעברית) את תוצאות ה-backtest: תשואה מול סיכון, ומה החולשה העיקרית של האסטרטגיה."},
                {"role": "user", "content": json.dumps(r, ensure_ascii=False)}
            ],
            max_tokens=300
        )
        message += f"\n\n🤖 *ניתוח AI:*\n{analysis.choices[0].message.content}"
    except Exception as e:
        logger.warning(f"ניתוח AI נכשל: {e}")

    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
    logger.info("LDM backtest הושלם!")


if __name__ == "__main__":
    asyncio.run(run())
