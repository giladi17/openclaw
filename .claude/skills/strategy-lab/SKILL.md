---
name: strategy-lab
description: Test, compare or improve a trading strategy for the OpenClaw bot with the research/ backtest engine. Use when the user asks whether a strategy works, wants to try a method (RSI(2), momentum, breakout, Minervini, etc.), change the scanner's rules, tune parameters, or decide what to run on paper or real money.
---

# Strategy Lab — how we test trading ideas

The goal is not a pretty backtest. It is an honest answer to: **does this beat buying SPY, after costs, on data it was not designed on?** Most ideas fail that test, and saying so is the job.

## The engine
Everything lives in `research/` (run from the repo root, plain Python + pandas):

```bash
python research/run.py --list                       # strategies available
python research/run.py baseline                      # one strategy, full report
python research/run.py baseline rsi2 --universe sp100   # compare several
```

- `research/data.py` — daily bars from Alpaca (split/dividend adjusted, SIP feed), cached in `research/data/` (gitignored). Keys come from `.env`.
- `research/engine.py` — portfolio simulator. Signals use data **through the close of day t**; entries fill at the **open of day t+1** (the bot buys at 9:35); rule-based exits fill at the **close** (the bot sells at 15:45). Slippage per side is a parameter.
- `research/strategies.py` — each strategy is a small class: indicators, entry score, exit rule, stop/target/hold, sizing.
- `research/metrics.py` — CAGR, max drawdown, Sharpe, exposure, trades, win rate, profit factor; always next to SPY buy & hold for the same dates.

## Rules (non-negotiable)
1. **No look-ahead.** A signal on day t may only use bars up to and including t. Fills happen after the signal (next open, or that day's close for exits decided at the close). Indicators are rolling, never centered, never fit on the full history.
2. **Split the data.** Design and tune on **in-sample 2016-01-01 → 2022-12-31**. Report **out-of-sample 2023-01-01 → today** once, at the end. If you tune after seeing out-of-sample, it is no longer out-of-sample — say so.
3. **Always show SPY** for the same period, and judge on risk-adjusted terms (Sharpe, max drawdown), not only total return.
4. **Costs on.** Default 5 bps slippage per side; check that results survive 10 bps.
5. **Enough trades.** Fewer than ~100 trades in-sample → the result is anecdotal; say so.
6. **Universe chosen before testing.** Prefer the broad `sp100` list. A hand-picked list of stocks that later went up (the old bot watchlist) inflates results — when you use it, show the `sp100` result beside it. Note that current index members carry survivorship bias.
7. **Few parameters, round numbers.** Prefer published/default values (RSI 2, SMA 200, 20/55-day breakouts). A strategy that only works at RSI 37 but not 35 or 40 is overfit — run a small neighborhood of each parameter and show it.
8. **Respect the live constraints:** account ~$20k → US PDT rule (no more than 3 same-day round trips in 5 days), so hold at least overnight. The bot acts twice a day (9:35 and 15:45 New York).

## Red flags to call out
- Great in-sample, flat or negative out-of-sample.
- Most of the profit from 1–2 trades or one symbol.
- Max drawdown much worse than SPY's with similar return.
- Results that change sign when slippage goes from 5 to 10 bps.
- Exposure near 100% with return below SPY (you paid for complexity and got the index, minus).

## How to report
Lead with the verdict in one or two sentences (beats SPY or not, in- and out-of-sample). Then one table per period: strategy vs SPY with CAGR, max DD, Sharpe, trades, win rate, exposure. Then caveats. Write the full report to `research/results/<name>.md` so it stays with the repo, and keep `research/results/README.md` as the running scoreboard (one line per strategy tested, newest first, with date).

## From research to the bot
Only a strategy that passes out-of-sample goes into `agent/scanner.py`, and then to **paper** first. Keep the live scanner's rules and the backtest strategy in sync — same indicators, same thresholds — and note any difference.
