"""
מריץ אסטרטגיות מול SPY, בתקופת הפיתוח (in-sample) ובתקופת הבדיקה (out-of-sample).

  python research/run.py --list
  python research/run.py baseline baseline_eq --universe watchlist sp100 --save baseline
  python research/run.py rsi2 rsi2:market_filter=sma200 --periods is     # וריאנטים, רק תקופת הפיתוח
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import data
import engine
import metrics
from strategies import STRATEGIES

PERIODS = {
    "in-sample 2016–2022":   ("2016-01-01", "2022-12-31"),
    "out-of-sample 2023→":   ("2023-01-01", None),
}
CAPITAL = 20_000


def parse_spec(spec: str):
    """'rsi2' או 'rsi2:market_filter=sma200,entry_rsi=5' → (מחלקה, פרמטרים)"""
    name, _, rest = spec.partition(":")
    params = {}
    for pair in filter(None, rest.split(",")):
        key, _, raw = pair.partition("=")
        for conv in (int, float):
            try:
                params[key] = conv(raw)
                break
            except ValueError:
                pass
        else:
            params[key] = None if raw.lower() == "none" else raw
    return STRATEGIES[name], params


def main():
    p = argparse.ArgumentParser()
    p.add_argument("strategies", nargs="*")
    p.add_argument("--universe", nargs="+", default=["sp100"], choices=list(data.UNIVERSES))
    p.add_argument("--slippage", type=float, help="נקודות בסיס לכל צד (ברירת מחדל: של האסטרטגיה)")
    p.add_argument("--periods", nargs="+", default=["is", "oos"], choices=["is", "oos"],
                   help="is = 2016–2022 (פיתוח), oos = 2023→ (בדיקה). כשמכווננים פרמטרים — רק is")
    p.add_argument("--save", help="שם קובץ ב-research/results/ לשמירת הדוח")
    p.add_argument("--capital", type=float, default=CAPITAL, help="הון התחלתי (גדול = פחות עיגול של מניות שלמות)")
    p.add_argument("--refresh", action="store_true", help="להוריד נתונים מחדש")
    p.add_argument("--list", action="store_true")
    args = p.parse_args()

    if args.list or not args.strategies:
        for name, cls in STRATEGIES.items():
            print(f"{name:14} {cls().describe()}")
        return

    spy = data.load(["SPY"], refresh=args.refresh)["SPY"]
    report = []
    for universe in args.universe:
        stocks = data.load(data.UNIVERSES[universe], refresh=args.refresh)
        built = {}
        for spec in args.strategies:
            cls, params = parse_spec(spec)
            if args.slippage is not None:
                params["slippage_bps"] = args.slippage
            strat = cls(**params)
            built[spec] = (strat, engine.build_panels(strat, stocks, spy))
        for key, (period, (start, end)) in zip(("is", "oos"), PERIODS.items()):
            if key not in args.periods:
                continue
            rows = [("SPY buy & hold", metrics.summarize(metrics.buy_and_hold(spy["close"], start, end, args.capital)))]
            for spec, (strat, panels) in built.items():
                res = engine.run(strat, panels, start, end, args.capital)
                rows.append((spec, metrics.summarize(res.equity, res.trades, res.exposure)))
            title = f"### {universe} — {period}"
            print(title + "\n\n" + metrics.table(rows) + "\n")
            report.append(title + "\n\n" + metrics.table(rows))

    if args.save:
        out = Path(__file__).resolve().parent / "results" / f"{args.save}.md"
        out.parent.mkdir(exist_ok=True)
        out.write_text("\n\n".join(report) + "\n", encoding="utf-8")
        print(f"נשמר: {out}")


if __name__ == "__main__":
    main()
