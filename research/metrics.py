import math

import pandas as pd


def summarize(equity: pd.Series, trades=None, exposure: pd.Series | None = None) -> dict:
    years   = max((equity.index[-1] - equity.index[0]).days / 365.25, 1e-9)
    rets    = equity.pct_change().dropna()
    out = {
        "return":  equity.iloc[-1] / equity.iloc[0] - 1,
        "cagr":    (equity.iloc[-1] / equity.iloc[0]) ** (1 / years) - 1,
        "max_dd":  (equity / equity.cummax() - 1).min(),
        "sharpe":  rets.mean() / rets.std() * math.sqrt(252) if rets.std() > 0 else 0.0,
        "exposure": exposure.mean() if exposure is not None else 1.0,
    }
    if trades is not None:
        closed = [t for t in trades if t.exit_price is not None]
        wins   = [t for t in closed if t.pnl > 0]
        gross_win  = sum(t.pnl for t in wins)
        gross_loss = -sum(t.pnl for t in closed if t.pnl <= 0)
        out.update({
            "trades":   len(closed),
            "win_rate": len(wins) / len(closed) if closed else 0.0,
            "avg_trade": sum(t.ret for t in closed) / len(closed) if closed else 0.0,
            "profit_factor": gross_win / gross_loss if gross_loss > 0 else float("inf"),
            "avg_days": sum((t.exit_date - t.entry_date).days for t in closed) / len(closed) if closed else 0.0,
        })
    return out


def buy_and_hold(close: pd.Series, start: str, end: str | None, capital: float) -> pd.Series:
    px = close.loc[start:end]
    return capital * px / px.iloc[0]


COLUMNS = [("return", "Return", "{:+.1%}"), ("cagr", "CAGR", "{:+.1%}"), ("max_dd", "MaxDD", "{:.1%}"),
           ("sharpe", "Sharpe", "{:.2f}"), ("exposure", "Exposure", "{:.0%}"), ("trades", "Trades", "{:d}"),
           ("win_rate", "Win%", "{:.0%}"), ("avg_trade", "AvgTrade", "{:+.2%}"),
           ("profit_factor", "PF", "{:.2f}"), ("avg_days", "Days", "{:.1f}")]


def table(rows: list[tuple[str, dict]]) -> str:
    """טבלת markdown: שורה לכל אסטרטגיה"""
    head = "| | " + " | ".join(c[1] for c in COLUMNS) + " |"
    sep  = "|---|" + "---:|" * len(COLUMNS)
    lines = [head, sep]
    for label, m in rows:
        cells = []
        for key, _, fmt in COLUMNS:
            v = m.get(key)
            cells.append("—" if v is None else fmt.format(int(v) if fmt == "{:d}" else v))
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    return "\n".join(lines)
