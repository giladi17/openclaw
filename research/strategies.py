"""
אסטרטגיות לבדיקה. כל אסטרטגיה מגדירה:
- indicators(df)  → DataFrame עם open/close ומה שהיא צריכה, מחושב רק מהעבר (rolling)
- entry_score(ind) → ציון לכל יום; NaN = לא נכנסים. גבוה = עדיף
- exit_signal(ind) → True ביום שבו יוצאים לפי חוק (בנוסף לסטופ/יעד/זמן)
- market_ok(spy)  → האם מותר לקנות היום לפי מצב השוק
"""
import math

import numpy as np
import pandas as pd


def sma(s: pd.Series, n: int) -> pd.Series:
    return s.rolling(n).mean()


def rsi_simple(close: pd.Series, n: int = 14) -> pd.Series:
    """RSI עם ממוצע פשוט של n השינויים האחרונים — בדיוק כמו calculate_rsi בבוט"""
    diff = close.diff()
    gain = diff.clip(lower=0).rolling(n).mean()
    loss = (-diff.clip(upper=0)).rolling(n).mean()
    return (100 - 100 / (1 + gain / loss)).where(loss != 0, 100.0)


class Strategy:
    name            = "base"
    max_positions   = 5
    max_new_per_day = 3
    top_n           = None     # כמה מהמובילים בכלל נבחנים (הבוט: 5, כולל כאלה שכבר בתיק)
    min_score       = 0
    stop_pct        = None
    target_pct      = None
    max_hold_days   = None     # ימים קלנדריים, כמו בבוט
    slippage_bps    = 5
    sizing          = "equal"  # equal = חלק שווה מהתיק לכל פוזיציה; fixed = fixed_qty מניות
    fixed_qty       = 2

    def __init__(self, **overrides):
        for k, v in overrides.items():
            if not hasattr(self, k):
                raise AttributeError(f"{self.name}: אין פרמטר {k}")
            setattr(self, k, v)

    def indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        return df.copy()

    def entry_score(self, ind: pd.DataFrame) -> pd.Series:
        raise NotImplementedError

    def exit_signal(self, ind: pd.DataFrame) -> pd.Series:
        return pd.Series(False, index=ind.index)

    market_filter   = None     # None או "sma200": קונים רק כש-SPY מעל הממוצע של 200 יום (Faber)

    def market_ok(self, spy: pd.DataFrame) -> pd.Series:
        if self.market_filter == "sma200":
            return spy["close"] > sma(spy["close"], 200)
        return pd.Series(True, index=spy.index)

    def cross_section(self, panels: dict) -> None:
        """אופציונלי: לשנות את panels["score"] / panels["exit"] לפי דירוג בין המניות"""

    def shares(self, price: float, equity: float) -> int:
        if self.sizing == "fixed":
            return self.fixed_qty
        return math.floor(equity / self.max_positions / price)

    def pick(self, scores: np.ndarray, held: dict, syms: list) -> list[int]:
        """מועמדים לקנייה מחר — לפי ציון, מהגבוה לנמוך; בשוויון לפי סדר הרשימה (כמו sort יציב בבוט)"""
        idx = [j for j in np.argsort(-np.nan_to_num(scores, nan=-np.inf), kind="stable") if not np.isnan(scores[j])]
        if self.top_n:
            idx = idx[:self.top_n]
        free = min(self.max_new_per_day, self.max_positions - len(held))
        return [j for j in idx if j not in held and scores[j] >= self.min_score][:max(free, 0)]

    def describe(self) -> str:
        return self.__doc__.strip().splitlines()[0] if self.__doc__ else self.name


class Baseline(Strategy):
    """האסטרטגיה הנוכחית של הבוט (agent/scanner.py), אחד לאחד"""
    name          = "baseline"
    top_n         = 5
    min_score     = 50
    stop_pct      = 0.10
    target_pct    = 0.15
    max_hold_days = 10
    sizing        = "fixed"

    def indicators(self, df):
        ind = df.copy()
        ind["rsi"]    = rsi_simple(df["close"], 14)
        ind["ma7"]    = sma(df["close"], 7)
        ind["ma20"]   = sma(df["close"], 20)
        ind["chg"]    = df["close"].pct_change() * 100
        ind["volr"]   = df["volume"] / df["volume"].rolling(10).mean()
        return ind

    def entry_score(self, ind):
        s = pd.Series(0.0, index=ind.index)
        s += np.where(ind["rsi"].between(35, 50), 30, np.where(ind["rsi"].between(30, 35), 20, 0))
        s += np.where(ind["ma7"] > ind["ma20"], 25, 0)
        s += np.where(ind["volr"] > 1.5, 20, 0)
        s += np.where((ind["chg"] > 0) & (ind["chg"] < 3), 25, 0)
        return s.where(ind["ma20"].notna())

    def market_ok(self, spy):
        return spy["close"] > sma(spy["close"], 20)


class BaselineEqual(Baseline):
    """אותם סיגנלים כמו baseline, אבל כל פוזיציה = 20% מהתיק (במקום 2 מניות) — בודק את איכות הסיגנל"""
    name   = "baseline_eq"
    sizing = "equal"


def rsi_wilder(close: pd.Series, n: int) -> pd.Series:
    """RSI המקורי של Wilder (החלקה אקספוננציאלית) — מה ש-Connors משתמש בו"""
    diff = close.diff()
    gain = diff.clip(lower=0).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    loss = (-diff.clip(upper=0)).ewm(alpha=1 / n, adjust=False, min_periods=n).mean()
    return 100 - 100 / (1 + gain / loss)


class RSI2(Strategy):
    """Connors RSI(2): מניה במגמה עולה (מעל SMA200) שירדה חזק — קונים, יוצאים כשהיא סוגרת מעל SMA5"""
    name      = "rsi2"
    entry_rsi = 10
    exit_ma   = 5

    def indicators(self, df):
        ind = df.copy()
        ind["rsi2"]   = rsi_wilder(df["close"], 2)
        ind["sma200"] = sma(df["close"], 200)
        ind["sma_x"]  = sma(df["close"], self.exit_ma)
        return ind

    def entry_score(self, ind):
        ok = (ind["close"] > ind["sma200"]) & (ind["rsi2"] < self.entry_rsi)
        return (100 - ind["rsi2"]).where(ok)          # הכי "מכורה" קודם

    def exit_signal(self, ind):
        return ind["close"] > ind["sma_x"]


class Momentum(Strategy):
    """Jegadeesh–Titman 12-1: בסוף כל חודש מחזיקים את 5 המניות עם התשואה הגבוהה ב-12 חודשים (בלי החודש האחרון)"""
    name            = "momentum"
    lookback        = 252
    skip            = 21
    max_new_per_day = 5

    def indicators(self, df):
        ind = df.copy()
        ind["mom"] = df["close"].shift(self.skip) / df["close"].shift(self.lookback) - 1
        return ind

    def entry_score(self, ind):
        return ind["mom"]

    def cross_section(self, panels):
        dates     = panels["score"].index
        month_end = pd.Series(dates.to_period("M"), index=dates)
        month_end = month_end != month_end.shift(-1)              # יום המסחר האחרון בחודש
        rank      = panels["score"].rank(axis=1, ascending=False)
        in_top    = rank <= self.max_positions
        # ביום האיזון: יוצאים ממי שלא בטופ, וקונים רק מתוך הטופ. בשאר הימים — לא עושים כלום
        panels["exit"]  = (~in_top).astype(float).mul(month_end.astype(float), axis=0)
        panels["score"] = panels["score"].where(in_top).where(month_end, axis=0)


class Minervini(Strategy):
    """Minervini Trend Template: מגמה עולה מובהקת + קרוב לשיא שנתי, כניסה בפריצה של 20 יום, סטופ 8%, יציאה מתחת ל-SMA50"""
    name     = "minervini"
    stop_pct = 0.08
    breakout = 20

    def indicators(self, df):
        ind = df.copy()
        c   = df["close"]
        for n in (50, 150, 200):
            ind[f"sma{n}"] = sma(c, n)
        ind["sma200_1m"] = ind["sma200"].shift(21)
        ind["hi52"]      = c.rolling(252).max()
        ind["lo52"]      = c.rolling(252).min()
        ind["prev_hi"]   = c.rolling(self.breakout).max().shift(1)
        ind["rs"]        = c / c.shift(126) - 1                   # עוצמה יחסית: תשואת חצי שנה, לדירוג
        return ind

    def entry_score(self, ind):
        c  = ind["close"]
        ok = ((c > ind["sma150"]) & (c > ind["sma200"]) & (ind["sma150"] > ind["sma200"])
              & (ind["sma200"] > ind["sma200_1m"]) & (ind["sma50"] > ind["sma150"]) & (c > ind["sma50"])
              & (c >= 1.3 * ind["lo52"]) & (c >= 0.75 * ind["hi52"])
              & (c > ind["prev_hi"]))
        return ind["rs"].where(ok)

    def exit_signal(self, ind):
        return ind["close"] < ind["sma50"]


class Donchian(Strategy):
    """Turtle System 2: כניסה בפריצה לשיא של 55 יום, יציאה בשבירה של השפל של 20 יום"""
    name       = "donchian"
    entry_days = 55
    exit_days  = 20

    def indicators(self, df):
        ind = df.copy()
        ind["hi_in"]  = df["high"].rolling(self.entry_days).max().shift(1)
        ind["lo_out"] = df["low"].rolling(self.exit_days).min().shift(1)
        ind["rs"]     = df["close"] / df["close"].shift(126) - 1
        return ind

    def entry_score(self, ind):
        return ind["rs"].where(ind["close"] > ind["hi_in"])

    def exit_signal(self, ind):
        return ind["close"] < ind["lo_out"]


def month_ends(index: pd.DatetimeIndex) -> pd.Series:
    """True ביום המסחר האחרון בכל חודש"""
    period = pd.Series(index.to_period("M"), index=index)
    return period != period.shift(-1)


class Rotation(Strategy):
    """בסיס לאסטרטגיות חודשיות על ETF-ים: בסוף כל חודש targets() קובע מה מחזיקים; כל השאר נמכר"""
    max_new_per_day = 99
    sectors = ["XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC"]

    def indicators(self, df):
        ind = df.copy()
        c   = df["close"]
        ind["sma200"] = sma(c, 200)
        for n in (21, 63, 126, 252):
            ind[f"r{n}"] = c / c.shift(n) - 1
        return ind

    def entry_score(self, ind):
        return pd.Series(np.nan, index=ind.index)

    @staticmethod
    def col(panels, name: str) -> pd.DataFrame:
        return pd.DataFrame({sym: ind[name] for sym, ind in panels["ind"].items()})

    def targets(self, panels) -> pd.DataFrame:
        raise NotImplementedError

    def cross_section(self, panels):
        me  = month_ends(panels["close"].index)
        tgt = self.targets(panels).reindex(columns=panels["close"].columns).fillna(False).astype(bool)
        panels["exit"]  = (~tgt).astype(float).mul(me.astype(float), axis=0)
        panels["score"] = pd.DataFrame(1.0, index=tgt.index, columns=tgt.columns).where(tgt).where(me, axis=0)


class TrendSPY(Rotation):
    """Faber: מחזיקים SPY כשהוא מעל SMA200 (בדיקה בסוף חודש), אחרת BIL (פיקדון דולרי)"""
    name          = "trend_spy"
    max_positions = 1
    asset         = "SPY"

    def targets(self, panels):
        up  = self.col(panels, "close")[self.asset] > self.col(panels, "sma200")[self.asset]
        out = pd.DataFrame(False, index=up.index, columns=[self.asset, "BIL"])
        out[self.asset], out["BIL"] = up, ~up
        return out


class TrendQQQ(TrendSPY):
    """כמו trend_spy, על QQQ (נאסד"ק 100)"""
    name  = "trend_qqq"
    asset = "QQQ"


class GEM(Rotation):
    """Antonacci Dual Momentum: אם SPY עלה ב-12 חודשים יותר מ-BIL — מחזיקים את החזק מבין SPY ו-EFA (חו"ל), אחרת IEF (אג"ח)"""
    name          = "gem"
    max_positions = 1

    def targets(self, panels):
        r   = self.col(panels, "r252")
        out = pd.DataFrame(False, index=r.index, columns=["SPY", "EFA", "IEF"])
        risk_on = r["SPY"] > r["BIL"]
        out["SPY"] = risk_on & (r["SPY"] >= r["EFA"])
        out["EFA"] = risk_on & (r["EFA"] > r["SPY"])
        out["IEF"] = ~risk_on & r["SPY"].notna()
        return out


class SectorMomentum(Rotation):
    """Faber Relative Strength: 3 הסקטורים עם המומנטום הגבוה (ממוצע 3/6/12 חודשים), רק אם הם מעל SMA200; השאר במזומן"""
    name          = "sector_mom"
    max_positions = 3
    pool          = "sectors"

    def targets(self, panels):
        syms  = self.sectors if self.pool == "sectors" else [s for s in panels["ind"] if s != "BIL"]
        mom   = (self.col(panels, "r63") + self.col(panels, "r126") + self.col(panels, "r252"))[syms] / 3
        above = (self.col(panels, "close") > self.col(panels, "sma200"))[syms]
        top   = mom.rank(axis=1, ascending=False) <= self.max_positions
        return top & above


class AssetMomentum(SectorMomentum):
    """כמו sector_mom, על כל ה-ETF-ים (סקטורים, מדדים, חו"ל, אג"ח, זהב) — 5 החזקים"""
    name          = "asset_mom"
    max_positions = 5
    pool          = "all"


class EqualHold(Rotation):
    """ביקורת: קונים את כל הרשימה במשקל שווה ומחזיקים. אסטרטגיה על אותה רשימה צריכה לנצח את זה — אחרת היתרון בא מהרשימה"""
    name          = "equal_hold"
    max_positions = 103   # כמספר המניות ב-sp100

    def targets(self, panels):
        return self.col(panels, "close").notna()


STRATEGIES = {cls.name: cls for cls in (Baseline, BaselineEqual, RSI2, Momentum, Minervini, Donchian,
                                        TrendSPY, TrendQQQ, GEM, SectorMomentum, AssetMomentum, EqualHold)}
