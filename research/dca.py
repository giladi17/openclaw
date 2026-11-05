"""
השוואת דרכים להכניס כסף למדד: DCA, קנייה רק במשברים, DCA עם רזרבה למשברים, ליבה + פילטר מגמה.

שני תרחישים:
  monthly — מפקידים $1,000 בכל חודש (משכורת). כל השיטות מקבלות בדיוק אותו כסף באותם מועדים.
  lump    — יש $20,000 עכשיו. נבדק על כל נקודת התחלה חודשית (חלונות מתגלגלים של 3 שנים).

כללים, כמו במנוע הראשי: ההחלטה לפי הסגירה של היום האחרון בחודש, הביצוע בפתיחה של היום הראשון
בחודש הבא; עלות 5bps לכל פעולה; מזומן מוחזק ב-BIL (פיקדון דולרי) ולכן מניב ריבית; שברי יחידות מותרים.

  python research/dca.py --save dca
"""
import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))

import data
from strategies import month_ends

COST = 5 / 10_000


class Book:
    """תיק עם כמה "סלים" (core / sat / cash), כל סל מחזיק יחידות של נכס אחד"""

    def __init__(self):
        self.units: dict[tuple[str, str], float] = {}

    def buy(self, bucket: str, sym: str, dollars: float, px: dict):
        if dollars > 0:
            key = (bucket, sym)
            self.units[key] = self.units.get(key, 0.0) + dollars * (1 - COST) / px[sym]

    def sell_all(self, bucket: str, sym: str, px: dict) -> float:
        units = self.units.pop((bucket, sym), 0.0)
        return units * px[sym] * (1 - COST)

    def value(self, px: dict, bucket: str | None = None) -> float:
        return sum(u * px[s] for (b, s), u in self.units.items() if bucket in (None, b))


# --- שיטות. כל אחת מקבלת: תיק, מחירי ביצוע, הפקדה החודש, מצב השוק (לפי הסגירה הקודמת), מספר החודש ---

def dca(book, px, cash, sig, i, a):
    """קונים את המדד מיד עם כל כסף שנכנס"""
    book.buy("core", a, cash, px)


def dip_only(threshold):
    def step(book, px, cash, sig, i, a):
        book.buy("cash", "BIL", cash, px)
        if sig["dd"] <= -threshold:                      # המדד ירד threshold מהשיא — נכנסים עם כל המזומן
            book.buy("core", a, book.sell_all("cash", "BIL", px), px)
    step.__doc__ = f"צוברים מזומן, ונכנסים עם הכל רק כשהמדד {threshold:.0%} מתחת לשיא"
    return step


def dca_reserve(threshold, reserve=0.3):
    def step(book, px, cash, sig, i, a):
        book.buy("core", a, cash * (1 - reserve), px)
        book.buy("cash", "BIL", cash * reserve, px)
        if sig["dd"] <= -threshold:
            book.buy("core", a, book.sell_all("cash", "BIL", px), px)
    step.__doc__ = f"{1 - reserve:.0%} למדד מיד, {reserve:.0%} לרזרבה שנכנסת כשהמדד {threshold:.0%} מתחת לשיא"
    return step


def core_trend(core=0.7):
    def step(book, px, cash, sig, i, a):
        book.buy("core", a, cash * core, px)
        sat = book.sell_all("sat", a, px) + book.sell_all("sat", "BIL", px) + cash * (1 - core)
        book.buy("sat", a if sig["above"] else "BIL", sat, px)
    step.__doc__ = f"{core:.0%} במדד תמיד, {1 - core:.0%} במדד רק כשהוא מעל SMA200 (אחרת BIL)"
    return step


def dca_12(book, px, cash, sig, i, a):
    """(רק לסכום חד-פעמי) מפזרים את הכניסה על 12 חודשים; מה שלא הושקע יושב ב-BIL"""
    book.buy("cash", "BIL", cash, px)
    if i < 12:
        rest = book.sell_all("cash", "BIL", px)
        book.buy("core", a, rest / (12 - i), px)
        book.buy("cash", "BIL", rest - rest / (12 - i), px)


METHODS = {
    "dca":           dca,
    "dip_only_10":   dip_only(0.10),
    "dip_only_20":   dip_only(0.20),
    "reserve_10":    dca_reserve(0.10),
    "reserve_20":    dca_reserve(0.20),
    "core70_trend":  core_trend(0.7),
}


class Prices:
    """מחירים מוכנים מראש כמילונים לכל יום — הסימולציה רצה אלפי פעמים"""

    def __init__(self):
        raw   = data.load(["SPY", "QQQ", "BIL"])
        idx   = raw["SPY"].index
        open_ = pd.DataFrame({s: d["open"] for s, d in raw.items()}).reindex(idx).ffill()
        close = pd.DataFrame({s: d["close"] for s, d in raw.items()}).reindex(idx).ffill()
        self.index  = idx
        self.opens  = open_.to_dict("index")
        self.closes = close.to_dict("index")
        self.dd     = {a: (close[a] / close[a].cummax() - 1).to_numpy() for a in ("SPY", "QQQ")}
        self.above  = {a: (close[a] > close[a].rolling(200).mean()).to_numpy() for a in ("SPY", "QQQ")}
        # יום ביצוע = היום הראשון בחודש; האות נלקח מהיום שלפניו (הסגירה האחרונה של החודש הקודם)
        me = month_ends(idx).to_numpy()
        self.is_exec = np.r_[False, me[:-1]]


def simulate(method, asset, P, start, end, deposits):
    """deposits(i) = כמה כסף נכנס בחודש ה-i. מחזיר (שווי יומי, תזרימים)"""
    lo = P.index.searchsorted(pd.Timestamp(start))
    hi = len(P.index) if end is None else P.index.searchsorted(pd.Timestamp(end), side="right")
    book, flows, values, i = Book(), [], [], 0
    for k in range(lo, hi):
        d = P.index[k]
        if P.is_exec[k]:
            cash = deposits(i)
            if cash:
                flows.append((d, cash))
            method(book, P.opens[d], cash, {"dd": P.dd[asset][k - 1], "above": bool(P.above[asset][k - 1])}, i, asset)
            i += 1
        values.append(book.value(P.closes[d]))
    return pd.Series(values, index=P.index[lo:hi]), flows


def irr(flows, end_date, end_value) -> float:
    """תשואה שנתית משוקללת-כסף (כמה הכסף שהופקד הרוויח בממוצע לשנה)"""
    t0 = flows[0][0]
    def npv(r):
        v = sum(-c / (1 + r) ** ((d - t0).days / 365.25) for d, c in flows)
        return v + end_value / (1 + r) ** ((end_date - t0).days / 365.25)
    lo, hi = -0.99, 3.0
    for _ in range(100):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if npv(mid) > 0 else (lo, mid)
    return mid


def max_dd_of_returns(values: pd.Series, flows) -> float:
    """ירידה מקסימלית של התשואה (לא של השווי, שמושפע מההפקדות)"""
    dep  = pd.Series(dict(flows)).reindex(values.index).fillna(0)
    rets = (values - dep) / values.shift(1) - 1
    idx  = (1 + rets.fillna(0)).cumprod()
    return (idx / idx.cummax() - 1).min()


def monthly_report(P) -> str:
    out = []
    for label, (start, end) in {"2016–2022": ("2016-11-01", "2022-12-31"), "2023→": ("2023-01-01", None),
                                "2016→ (הכל)": ("2016-11-01", None)}.items():
        rows = ["| שיטה | נכס | הופקד | שווי בסוף | תשואה שנתית (IRR) | ירידה מקס' |", "|---|---|---:|---:|---:|---:|"]
        for asset in ("SPY", "QQQ"):
            for name, method in METHODS.items():
                v, f = simulate(method, asset, P, start, end, lambda i: 1000.0)
                rows.append(f"| {name} | {asset} | ${sum(c for _, c in f):,.0f} | ${v.iloc[-1]:,.0f} | "
                            f"{irr(f, v.index[-1], v.iloc[-1]):+.1%} | {max_dd_of_returns(v, f):.1%} |")
        out.append(f"### $1,000 בחודש — {label}\n\n" + "\n".join(rows))
    return "\n\n".join(out)


def lump_report(P, months=36) -> str:
    starts = [d for d in P.index[P.is_exec] if d >= pd.Timestamp("2016-11-01")]
    methods = {"lump (הכל בבת אחת)": dca, "dca_12 (פיזור על שנה)": dca_12, **{k: v for k, v in METHODS.items() if k != "dca"}}
    out = []
    for asset in ("SPY", "QQQ"):
        results = {name: [] for name in methods}
        for s in starts:
            e_pos = P.index.get_loc(s) + months * 21
            if e_pos >= len(P.index):
                break
            end = P.index[e_pos]
            for name, method in methods.items():
                v, f = simulate(method, asset, P, s, end, lambda i: 20_000.0 if i == 0 else 0.0)
                results[name].append((v.iloc[-1], (v / v.cummax() - 1).min()))
        lump = np.array([r[0] for r in results["lump (הכל בבת אחת)"]])
        rows = ["| שיטה | שווי חציוני אחרי 3 שנים | הגרוע ביותר | מנצח את lump | ירידה מקס' חציונית |", "|---|---:|---:|---:|---:|"]
        for name, rs in results.items():
            vals = np.array([r[0] for r in rs])
            dds  = np.array([r[1] for r in rs])
            win  = "—" if name.startswith("lump") else f"{(vals > lump).mean():.0%}"
            rows.append(f"| {name} | ${np.median(vals):,.0f} | ${vals.min():,.0f} | {win} | {np.median(dds):.1%} |")
        out.append(f"### $20,000 בבת אחת, {asset} — {len(lump)} נקודות התחלה (כל חודש, 2016-11 → )\n\n" + "\n".join(rows))
    return "\n\n".join(out)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--save")
    args = p.parse_args()
    P = Prices()
    report = "## תרחיש 1 — הפקדה חודשית\n\n" + monthly_report(P) + \
             "\n\n## תרחיש 2 — סכום חד-פעמי, חלונות של 3 שנים\n\n" + lump_report(P)
    print(report)
    if args.save:
        out = Path(__file__).resolve().parent / "results" / f"{args.save}.md"
        out.write_text(report + "\n", encoding="utf-8")
        print(f"\nנשמר: {out}")


if __name__ == "__main__":
    main()
