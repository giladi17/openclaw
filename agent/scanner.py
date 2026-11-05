"""
סבב סקטורים חודשי (Faber, Relative Strength) — האסטרטגיה שנבחרה במחקר (research/results/stage3.md).

כל חודש מחזיקים עד 3 ETF-ים של סקטורים ב-S&P 500 עם המומנטום הגבוה ביותר
(ממוצע התשואה של 3, 6 ו-12 חודשים) — רק אם הם מעל הממוצע של 200 יום. מקום שלא התמלא נשאר במזומן.

תזמון, כמו ב-backtest (research/strategies.py: SectorMomentum):
- יום המסחר האחרון בחודש, 15:45 — מוכרים סקטורים שיצאו מהרשימה
- יום המסחר הראשון בחודש, 9:35  — קונים סקטורים חדשים ברשימה, שליש מהתיק לכל אחד
- יום המסחר הראשון בשבוע — סקירה שבועית; שאר הבקרים — התראה רק אם התחזית לסבב השתנתה
- בכל ערב — דוח תיק
- מניות שאינן ETF של סקטור (למשל קנייה ידנית) — לא נוגעים בהן
"""
import os
import asyncio
import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import redis
import requests
from telegram import Bot
from tg import send

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN    = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID           = os.environ.get("CHAT_ID")
TASK              = os.environ.get("TASK", "morning_scan")
ALPACA_API_KEY    = os.environ.get("ALPACA_API_KEY")
ALPACA_SECRET_KEY = os.environ.get("ALPACA_SECRET_KEY")
ALPACA_BASE_URL   = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets")

HEADERS = {
    "APCA-API-KEY-ID": ALPACA_API_KEY,
    "APCA-API-SECRET-KEY": ALPACA_SECRET_KEY
}

NY            = ZoneInfo("America/New_York")
SECTORS       = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]
MAX_POSITIONS = 3
# תחילת הניסוי בחשבון ה-Paper — לחישוב "התיק מול SPY" בסקירה השבועית
EXPERIMENT_START = date.fromisoformat(os.environ.get("EXPERIMENT_START", "2026-11-02"))
START_EQUITY     = float(os.environ.get("START_EQUITY", "20000"))
LOOKBACKS     = (63, 126, 252)   # 3, 6, 12 חודשי מסחר
TREND_DAYS    = 200


def get_closes(symbol: str, include_today: bool) -> list[float]:
    """מחירי סגירה יומיים (מותאמים לדיבידנדים ופיצולים), מהישן לחדש"""
    start  = (date.today() - timedelta(days=450)).isoformat()
    params = {"timeframe": "1Day", "start": start, "limit": 10000, "adjustment": "all", "feed": "iex"}
    resp   = requests.get(f"https://data.alpaca.markets/v2/stocks/{symbol}/bars",
                          headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    bars = resp.json().get("bars") or []
    if not include_today:
        # בבוקר הנר של היום מכיל רק כמה דקות מסחר — מחשבים על ימים שלמים בלבד
        today = datetime.now(NY).date().isoformat()
        bars  = [b for b in bars if b["t"][:10] < today]
    return [b["c"] for b in bars]


def rank_sectors(include_today: bool) -> list[dict]:
    """מדרג את כל הסקטורים. אם חסרים נתונים לאחד מהם — זורק שגיאה, כדי לא לסחור על דירוג חלקי"""
    rows = []
    for symbol in SECTORS:
        closes = get_closes(symbol, include_today)
        if len(closes) <= max(LOOKBACKS):
            raise RuntimeError(f"{symbol}: רק {len(closes)} ימי נתונים")
        last = closes[-1]
        mom  = sum(last / closes[-1 - n] for n in LOOKBACKS) / len(LOOKBACKS) - 1
        rows.append({"symbol": symbol, "mom": mom, "above": last > sum(closes[-TREND_DAYS:]) / TREND_DAYS})
    rows.sort(key=lambda r: r["mom"], reverse=True)
    return rows


def pick_targets(rows: list[dict]) -> list[str]:
    return [r["symbol"] for r in rows[:MAX_POSITIONS] if r["above"]]


def trading_days(start: date, end: date) -> list[date]:
    params = {"start": start.isoformat(), "end": end.isoformat()}
    resp   = requests.get(f"{ALPACA_BASE_URL}/v2/calendar", headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    return [datetime.strptime(d["date"], "%Y-%m-%d").date() for d in resp.json()]


def next_rebalance(today: date) -> date:
    """יום המסחר האחרון בחודש הנוכחי — אז נבדק הסבב הבא"""
    days = [d for d in trading_days(today, today + timedelta(days=40)) if d.month == today.month]
    return days[-1] if days else today


def trading_day_type(today: date) -> str:
    """closed / first / last / first_and_last / regular — לפי לוח המסחר של Alpaca (כולל חגים)"""
    days = trading_days(today - timedelta(days=10), today + timedelta(days=10))
    if today not in days:
        return "closed"
    i     = days.index(today)
    first = i > 0 and days[i - 1].month != today.month
    last  = i + 1 < len(days) and days[i + 1].month != today.month
    return {(True, True): "first_and_last", (True, False): "first", (False, True): "last"}.get((first, last), "regular")


def get_positions() -> list:
    resp = requests.get(f"{ALPACA_BASE_URL}/v2/positions", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json()


def get_equity() -> float:
    resp = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    return float(resp.json()["equity"])


def sell_all(symbol: str) -> bool:
    """סוגר את כל הפוזיציה במחיר שוק (כולל שברי מניות)"""
    resp = requests.delete(f"{ALPACA_BASE_URL}/v2/positions/{symbol}", headers=HEADERS, timeout=15)
    if not resp.ok:
        logger.error(f"מכירת {symbol} נכשלה: {resp.status_code} {resp.text[:200]}")
    return resp.ok


def buy_notional(symbol: str, dollars: float) -> bool:
    body = {
        "symbol":        symbol,
        "notional":      f"{dollars:.2f}",
        "side":          "buy",
        "type":          "market",
        "time_in_force": "day",
        # מזהה קבוע ליום — אם הסריקה רצה פעמיים, Alpaca ידחה את הפקודה הכפולה
        "client_order_id": f"rot-{symbol}-{datetime.now(NY):%Y%m%d}",
    }
    resp = requests.post(f"{ALPACA_BASE_URL}/v2/orders", headers=HEADERS, json=body, timeout=15)
    if not resp.ok:
        logger.error(f"קניית {symbol} נכשלה: {resp.status_code} {resp.text[:200]}")
    return resp.ok


def ranking_lines(rows: list[dict], targets: list[str]) -> list[str]:
    lines = []
    for i, r in enumerate(rows, 1):
        mark  = "✅" if r["symbol"] in targets else ("⬇️" if not r["above"] else "▫️")
        lines.append(f"{mark} {i}. {r['symbol']}: {r['mom'] * 100:+.1f}%")
    return lines


def sell_non_targets(positions: list, targets: list[str]) -> list[str]:
    sold = []
    for pos in positions:
        symbol = pos["symbol"]
        if symbol in SECTORS and symbol not in targets and sell_all(symbol):
            sold.append(symbol)
    return sold


def index_line(symbol: str) -> str:
    c     = get_closes(symbol, include_today=False)
    chg   = c[-1] / c[-2] - 1
    trend = "מעל " if c[-1] > sum(c[-TREND_DAYS:]) / TREND_DAYS else "מתחת ל"
    dd    = c[-1] / max(c[-252:]) - 1
    return f"{'🟢' if chg >= 0 else '🔴'} {symbol}: {chg * 100:+.1f}% אתמול · {trend}ממוצע 200 · {dd * 100:.1f}% מהשיא השנתי"


def experiment_line() -> str:
    """התיק מול SPY מאז תחילת הניסוי: שניהם לפי הסגירה האחרונה (SPY נקנה בפתיחה של יום ההתחלה, כמו התיק)"""
    resp = requests.get(f"{ALPACA_BASE_URL}/v2/account", headers=HEADERS, timeout=15)
    resp.raise_for_status()
    port   = float(resp.json()["last_equity"]) / START_EQUITY - 1
    params = {"timeframe": "1Day", "start": EXPERIMENT_START.isoformat(), "adjustment": "all", "feed": "iex"}
    resp   = requests.get("https://data.alpaca.markets/v2/stocks/SPY/bars", headers=HEADERS, params=params, timeout=15)
    resp.raise_for_status()
    today = datetime.now(NY).date().isoformat()
    bars  = [b for b in resp.json().get("bars") or [] if b["t"][:10] < today]
    spy   = bars[-1]["c"] / bars[0]["o"] - 1
    diff  = (port - spy) * 100
    return (f"🧪 *הניסוי מאז {EXPERIMENT_START:%d.%m}:* התיק {port * 100:+.1f}% · SPY {spy * 100:+.1f}% "
            f"→ {'🟢' if diff >= 0 else '🔴'} {diff:+.1f} נק' מול SPY")


def outlook() -> tuple[list[dict], list[str], set[str], list[str], list[str]]:
    """הדירוג עכשיו, מול מה שבתיק: מה ייצא ומה ייכנס אם הדירוג יישאר כך עד הסבב"""
    rows     = rank_sectors(include_today=False)
    targets  = pick_targets(rows)
    held     = {p["symbol"] for p in get_positions()}
    leaving  = sorted(s for s in held & set(SECTORS) if s not in targets)
    entering = [s for s in targets if s not in held]
    return rows, targets, held, leaving, entering


def change_line(leaving: list[str], entering: list[str]) -> str:
    if leaving or entering:
        return f"⚠️ אם הדירוג יישאר כך — יימכרו: {', '.join(leaving) or 'כלום'} · ייקנו: {', '.join(entering) or 'כלום'}"
    return "✅ אם הדירוג יישאר כך — אין שינוי בתיק"


# המצב האחרון שדווח ("מה צפוי בסבב"), כדי לשלוח התראה רק כשהוא משתנה ולא כל בוקר מחדש
ALERT_KEY = "rotation:expected_change"


def swap_alert_state(state: str) -> str | None:
    """שומר את המצב החדש ומחזיר את הקודם. בלי Redis — מחזיר None (ואז נשלחת התראה אם יש שינוי צפוי)"""
    try:
        r = redis.Redis(host="redis-service", port=6379, decode_responses=True)
        return r.getset(ALERT_KEY, state)
    except redis.RedisError as e:
        logger.warning(f"Redis לא זמין: {e}")
        return None


def is_first_of_week(today: date) -> bool:
    days = trading_days(today - timedelta(days=10), today)
    i    = days.index(today)
    return i == 0 or days[i - 1].isocalendar()[:2] != today.isocalendar()[:2]


async def weekly_overview(bot: Bot, today: date):
    """סקירה שבועית (יום המסחר הראשון בשבוע), בלי עסקאות: מצב השוק, הדירוג, ומה צפוי בסבב הבא"""
    lines = [f"📅 *סקירה שבועית — {today:%d.%m}*\n"]
    try:
        lines += [index_line("SPY"), index_line("QQQ"), ""]
    except Exception as e:
        logger.warning(f"נתוני מדדים נכשלו: {e}")
    try:
        lines += [experiment_line(), ""]
    except Exception as e:
        logger.warning(f"השוואה ל-SPY נכשלה: {e}")

    try:
        rows, targets, held, leaving, entering = outlook()
        lines.append("📊 *דירוג הסקטורים:*")
        for line, r in zip(ranking_lines(rows, targets), rows):
            lines.append(line + (" 💼" if r["symbol"] in held else ""))
        lines.append(f"\n🔄 סבב הבא: {next_rebalance(today):%d.%m} בערב")
        lines.append(change_line(leaving, entering))
        swap_alert_state(",".join(leaving) + "|" + ",".join(entering))
    except Exception as e:
        logger.error(f"דירוג נכשל: {e}", exc_info=True)
        lines.append(f"⚠️ לא הצלחתי לדרג את הסקטורים: {str(e)[:150]}")

    lines.append("\n✅ = בטופ 3 · ⬇️ = מתחת לממוצע 200 יום · 💼 = בתיק")
    await send(bot, chat_id=CHAT_ID, text="\n".join(lines))


async def change_alert(bot: Bot, today: date):
    """בשאר הבקרים: הודעה רק אם השתנה מה שצפוי לקרות בסבב הבא"""
    rows, targets, held, leaving, entering = outlook()
    state = ",".join(leaving) + "|" + ",".join(entering)
    prev  = swap_alert_state(state)
    if state == prev or (prev is None and state == "|"):
        logger.info(f"אין שינוי בתחזית לסבב ({state})")
        return
    lines = [f"🔔 *שינוי בדירוג — {today:%d.%m}*\n", change_line(leaving, entering),
             f"🔄 הסבב: {next_rebalance(today):%d.%m} בערב — עד אז שום דבר לא נקנה או נמכר\n",
             *[line + (" 💼" if r["symbol"] in held else "") for line, r in zip(ranking_lines(rows, targets)[:5], rows)]]
    await send(bot, chat_id=CHAT_ID, text="\n".join(lines))


async def morning_scan(bot: Bot):
    """יום ראשון בחודש: קונים. יום ראשון בשבוע: סקירה שבועית. שאר הבקרים: התראה רק אם התחזית לסבב השתנתה"""
    today = datetime.now(NY).date()
    day   = trading_day_type(today)
    if day == "closed":
        logger.info("הבורסה סגורה היום")
        return
    if day not in ("first", "first_and_last"):
        if is_first_of_week(today):
            await weekly_overview(bot, today)
        else:
            await change_alert(bot, today)
        return

    try:
        rows = rank_sectors(include_today=False)
    except Exception as e:
        logger.error(f"דירוג נכשל: {e}", exc_info=True)
        await send(bot, chat_id=CHAT_ID, text=f"⚠️ *סבב חודשי:* לא הצלחתי לדרג את הסקטורים — לא קונה היום.\n{str(e)[:150]}")
        return

    targets   = pick_targets(rows)
    positions = get_positions()
    # רשת ביטחון: אם המכירה של סוף החודש לא רצה (למשל השרת היה למטה) — מוכרים עכשיו
    sold      = sell_non_targets(positions, targets)
    held      = {p["symbol"] for p in positions} - set(sold)
    slot      = get_equity() / MAX_POSITIONS
    bought    = [s for s in targets if s not in held and buy_notional(s, slot)]

    swap_alert_state("|")   # אחרי הסבב התיק תואם לדירוג — אין שינוי צפוי
    lines = ["🔄 *סבב חודשי — קנייה*\n", *ranking_lines(rows, targets), ""]
    if bought:
        lines.append(f"✅ קניתי: {', '.join(bought)} (${slot:,.0f} לכל אחד)")
    if sold:
        lines.append(f"🔻 מכרתי (לא נמכר בסוף החודש): {', '.join(sold)}")
    kept = [s for s in targets if s in held]
    if kept:
        lines.append(f"⏸️ ממשיך להחזיק: {', '.join(kept)}")
    if len(targets) < MAX_POSITIONS:
        lines.append(f"💵 {MAX_POSITIONS - len(targets)} מקומות במזומן — אין מספיק סקטורים במגמה עולה")
    lines.append("\n✅ = נבחר · ⬇️ = מתחת לממוצע 200 יום")
    await send(bot, chat_id=CHAT_ID, text="\n".join(lines))


async def evening_scan(bot: Bot):
    """בכל ערב: דוח תיק. ביום האחרון בחודש: גם מוכרים סקטורים שיצאו מהרשימה"""
    day       = trading_day_type(datetime.now(NY).date())
    if day == "closed":
        logger.info("הבורסה סגורה היום")
        return
    positions = get_positions()
    lines     = []

    if day in ("last", "first_and_last"):
        try:
            rows    = rank_sectors(include_today=True)
            targets = pick_targets(rows)
            sold    = sell_non_targets(positions, targets)
            lines  += ["🔄 *סבב חודשי — סוף חודש*\n", *ranking_lines(rows, targets), ""]
            lines.append(f"🔻 מכרתי: {', '.join(sold)}" if sold else "🔻 אין מה למכור")
            lines.append(f"🛒 מחר בבוקר: קנייה של מה שחסר מתוך {', '.join(targets) or 'אף סקטור (הכל במזומן)'}\n")
            positions = [p for p in positions if p["symbol"] not in sold]
        except Exception as e:
            logger.error(f"סבב סוף חודש נכשל: {e}", exc_info=True)
            lines.append(f"⚠️ סבב סוף חודש נכשל — לא מכרתי כלום. ינוסה שוב מחר בבוקר.\n{str(e)[:150]}\n")

    lines.append(f"🌆 *דוח ערב — {datetime.now(NY):%d.%m}:*\n")
    if not positions:
        lines.append("📭 אין פוזיציות פתוחות.")
    total_pl = 0.0
    for pos in positions:
        pl     = float(pos.get("unrealized_pl", 0))
        pl_pct = float(pos.get("unrealized_plpc", 0)) * 100
        total_pl += pl
        lines.append(f"{'🟢' if pl >= 0 else '🔴'} {pos['symbol']}: ${pl:,.2f} ({pl_pct:+.1f}%)")
    if positions:
        lines.append(f"\n{'🟢' if total_pl >= 0 else '🔴'} *סה\"כ P&L: ${total_pl:,.2f}*")
    lines.append(f"💼 שווי תיק: ${get_equity():,.2f}")
    await send(bot, chat_id=CHAT_ID, text="\n".join(lines))


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
