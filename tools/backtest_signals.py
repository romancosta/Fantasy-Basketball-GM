"""Backtest the opportunity signals on a full past season of NBA game logs (cached after the first run).

    python3 tools/backtest_signals.py [season] [--players N]

Signal A (minutes surge): after a 5-game stretch averaging 5+ more minutes than the 10 games before it, do the next 5
games keep the higher output? Compared with everyone else's next-5 vs the prior 15 (the baseline drift).
Signal B (rotation teammate out): for non-star players, output in games a star teammate missed vs games he played.
Prints effect sizes; the report's constants (config.POLICY signal_*) come from these.
"""
import os
import sys
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbgm import espn, signals  # noqa: E402
from fbgm.config import CONFIG  # noqa: E402

season = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else CONFIG["season"] - 1
n_players = int(sys.argv[sys.argv.index("--players") + 1]) if "--players" in sys.argv else 450
espn.FRESH = False

pool = espn.players(limit=n_players)
ids = [e["player"]["id"] for e in pool]
with ThreadPoolExecutor(8) as ex:
    logs = dict(zip(ids, ex.map(lambda i: signals.games(i, season), ids)))
logs = {i: g for i, g in logs.items() if len(g) >= 20}
print(f"season {season}: {len(logs)} players with 20+ games")

# --- Signal A: minutes surge
sig, ctl = [], []
for gs in logs.values():
    for t in range(15, len(gs) - 5):
        last5 = signals.mean(g["MIN"] for g in gs[t - 5:t])
        prev10 = signals.mean(g["MIN"] for g in gs[t - 15:t - 5])
        base15 = signals.mean(g["fp"] for g in gs[t - 15:t])
        if base15 <= 0 or last5 < 15:
            continue
        nxt = signals.mean(g["fp"] for g in gs[t:t + 5])
        last5_fp = signals.mean(g["fp"] for g in gs[t - 5:t])
        row = (nxt / base15, nxt / last5_fp if last5_fp > 0 else None, last5_fp / base15)
        (sig if last5 - prev10 >= 5 else ctl).append(row)
def avg(rows, k):
    xs = [r[k] for r in rows if r[k] is not None]
    return signals.mean(xs)
print("\nSignal A: minutes surge (+5 mpg over the prior 10 games)")
print(f"  windows: {len(sig)} with the signal, {len(ctl)} without")
print(f"  next-5 FP / prior-15 FP:  signal {avg(sig, 0):.3f}   others {avg(ctl, 0):.3f}")
print(f"  next-5 FP / last-5 FP:    signal {avg(sig, 1):.3f}   others {avg(ctl, 1):.3f}")
print(f"  last-5 FP / prior-15 FP:  signal {avg(sig, 2):.3f}   others {avg(ctl, 2):.3f}")
gain = avg(sig, 0) - avg(ctl, 0)
chase = (avg(sig, 0) - 1) / (avg(sig, 2) - 1) if avg(sig, 2) != 1 else 0
print(f"  -> surge players beat the baseline by {gain:+.3f}; they keep {chase:.0%} of their recent jump")

# --- Signal B: a rotation teammate is out
team_events = {}
for gs in logs.values():
    for g in gs:
        team_events.setdefault(g["team"], set()).add(g["event"])
avg_min = {i: signals.mean(g["MIN"] for g in gs) for i, gs in logs.items()}
avg_fp = {i: signals.mean(g["fp"] for g in gs) for i, gs in logs.items()}
stars = {i for i in logs if avg_min[i] >= 28 and avg_fp[i] >= 38}
ratios = {"bench (12-24 mpg)": [], "rotation (24-32 mpg)": []}
weights = {k: [] for k in ratios}
for s in stars:
    sg = logs[s]
    star_events = {g["event"] for g in sg}
    team = sg[-1]["team"]
    first, last = sg[0]["date"], sg[-1]["date"]
    for x, xg in logs.items():
        if x == s or xg[-1]["team"] != team or not (12 <= avg_min[x] < 32) or avg_fp[x] <= 0:
            continue
        with_s = [g["fp"] for g in xg if g["event"] in star_events]
        without = [g["fp"] for g in xg if g["event"] not in star_events and first <= g["date"] <= last
                   and g["team"] == team]
        if len(without) >= 4 and len(with_s) >= 8:
            bucket = "bench (12-24 mpg)" if avg_min[x] < 24 else "rotation (24-32 mpg)"
            ratios[bucket].append(signals.mean(without) / signals.mean(with_s))
            weights[bucket].append(len(without))
print("\nSignal B: a 28+ mpg, 38+ FP star teammate is out")
for k, rs in ratios.items():
    if rs:
        w = sum(a * b for a, b in zip(rs, weights[k])) / sum(weights[k])
        print(f"  {k}: {len(rs)} player-star pairs, FP without him / with him = {w:.3f} (games-weighted)")
