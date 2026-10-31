"""
סימולטור תיק יומי — מחקה את קצב העבודה של הבוט:
- החלטת קנייה בסוף יום t (על נתונים עד הסגירה של t) → ביצוע בפתיחה של t+1 (הבוט קונה ב-9:35)
- יציאות (סטופ / יעד / זמן / חוק של האסטרטגיה) נבדקות בסגירה ומבוצעות בסגירה (הבוט מוכר ב-15:45)
- החלקה (slippage) בכל צד, כמספר נקודות בסיס
"""
from dataclasses import dataclass, field

import numpy as np
import pandas as pd


@dataclass
class Trade:
    symbol:      str
    entry_date:  pd.Timestamp
    entry_price: float
    shares:      int
    exit_date:   pd.Timestamp | None = None
    exit_price:  float | None = None
    reason:      str = ""

    @property
    def pnl(self) -> float:
        return (self.exit_price - self.entry_price) * self.shares

    @property
    def ret(self) -> float:
        return self.exit_price / self.entry_price - 1


@dataclass
class Result:
    equity: pd.Series
    trades: list[Trade] = field(default_factory=list)
    exposure: pd.Series | None = None   # חלק התיק שמושקע במניות, לכל יום


def build_panels(strategy, data: dict[str, pd.DataFrame], spy: pd.DataFrame) -> dict[str, pd.DataFrame]:
    """מחשב אינדיקטורים לכל מניה ומיישר הכל ללוח המסחר של SPY (תאריכים × סימבולים)"""
    calendar = spy.index
    cols     = list(data)
    panels   = {k: pd.DataFrame(index=calendar, columns=cols, dtype=float) for k in ("open", "close", "score", "exit")}
    panels["ind"] = {}
    for sym, df in data.items():
        ind = strategy.indicators(df).reindex(calendar)
        panels["ind"][sym]   = ind
        panels["open"][sym]  = ind["open"]
        panels["close"][sym] = ind["close"]
        panels["score"][sym] = strategy.entry_score(ind)
        panels["exit"][sym]  = strategy.exit_signal(ind).astype(float)
    panels["market_ok"] = strategy.market_ok(spy).reindex(calendar).fillna(False).astype(bool)
    # לאסטרטגיות שמדרגות מניות זו מול זו (למשל momentum חודשי)
    strategy.cross_section(panels)
    return panels


def run(strategy, panels: dict, start: str, end: str | None = None, capital: float = 20_000) -> Result:
    dates   = panels["close"].loc[start:end].index
    open_   = panels["open"].loc[dates].to_numpy()
    close   = panels["close"].loc[dates].to_numpy()
    score   = panels["score"].loc[dates].to_numpy()
    exit_   = panels["exit"].loc[dates].to_numpy()
    mkt_ok  = panels["market_ok"].loc[dates].to_numpy()
    syms    = list(panels["close"].columns)
    slip    = strategy.slippage_bps / 10_000

    cash, held, trades = capital, {}, []          # held: עמודה → Trade
    last_px  = np.full(len(syms), np.nan)
    pending: list[int] = []                       # מועמדים לקנייה בפתיחה של מחר
    equity, exposure = np.empty(len(dates)), np.empty(len(dates))

    for i, date in enumerate(dates):
        # --- פתיחה: ביצוע הקניות שהוחלטו אתמול ---
        if pending:
            equity_now = cash + sum(t.shares * last_px[j] for j, t in held.items())
            for j in pending:
                px = open_[i, j]
                if np.isnan(px) or j in held or len(held) >= strategy.max_positions:
                    continue
                fill   = px * (1 + slip)
                shares = strategy.shares(fill, equity_now)
                if shares <= 0 or shares * fill > cash:
                    continue
                cash   -= shares * fill
                held[j] = Trade(syms[j], date, fill, shares)
            pending = []

        valid = ~np.isnan(close[i])
        last_px[valid] = close[i, valid]

        # --- סגירה: יציאות ---
        for j, t in list(held.items()):
            if np.isnan(close[i, j]):
                continue
            pl     = close[i, j] / t.entry_price - 1
            days   = (date - t.entry_date).days
            reason = None
            if strategy.target_pct is not None and pl >= strategy.target_pct:
                reason = "target"
            elif strategy.stop_pct is not None and pl <= -strategy.stop_pct:
                reason = "stop"
            elif strategy.max_hold_days is not None and days >= strategy.max_hold_days:
                reason = "time"
            elif exit_[i, j] == 1:
                reason = "rule"
            if reason:
                t.exit_date, t.exit_price, t.reason = date, close[i, j] * (1 - slip), reason
                cash += t.shares * t.exit_price
                trades.append(t)
                del held[j]

        invested     = sum(t.shares * last_px[j] for j, t in held.items())
        equity[i]    = cash + invested
        exposure[i]  = invested / equity[i] if equity[i] > 0 else 0

        # --- החלטה לקראת מחר ---
        if mkt_ok[i] and i + 1 < len(dates):
            pending = strategy.pick(score[i], held, syms)

    # סגירת מה שנשאר פתוח במחיר האחרון, כדי שיופיע בסטטיסטיקה
    for j, t in held.items():
        t.exit_date, t.exit_price, t.reason = dates[-1], last_px[j], "open"
        trades.append(t)

    return Result(pd.Series(equity, index=dates), trades, pd.Series(exposure, index=dates))
