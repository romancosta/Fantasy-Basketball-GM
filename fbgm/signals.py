"""Opportunity signals from NBA game logs: minutes trends and 'a rotation teammate is out'. Logs only carry total
rebounds, so FP here is a proxy (points + FGM + FTM + 2.3 x REB + 2 x (AST + STL + BLK) - 2 x TO), good for comparing a
player with himself, not for league scoring totals."""
import datetime as dt
from concurrent.futures import ThreadPoolExecutor

from . import espn, health
from .config import POLICY

LABELS = ("MIN", "FG", "FT", "REB", "AST", "BLK", "STL", "TO", "PTS")
REB_CREDIT = 2.3    # 1 per rebound + 2 more per offensive one (~28% of rebounds) + 1 more per defensive one


def made(cell):
    try:
        return int(str(cell).split("-")[0])
    except ValueError:
        return 0


def proxy_fp(row):
    return (row["PTS"] + row["FG"] + row["FT"] + REB_CREDIT * row["REB"]
            + 2 * (row["AST"] + row["STL"] + row["BLK"]) - 2 * row["TO"])


def games(player_id, season):
    """[{event, date, team, MIN, fp}] for the player's regular-season games, oldest first. [] if unavailable."""
    try:
        log = espn.gamelog(player_id, season)
    except Exception as exc:
        health.failed("NBA game logs (opportunity watch)", exc)
        return []
    labels = log.get("labels", [])
    idx = {name: labels.index(name) for name in LABELS if name in labels}
    if len(idx) < len(LABELS):
        return []
    events = log.get("events", {})
    out = []
    for st in log.get("seasonTypes", []):
        if "Regular" not in st.get("displayName", ""):
            continue
        for cat in st.get("categories", []):
            for ev in cat.get("events", []):
                meta = events.get(ev["eventId"])
                if not meta or not meta.get("team"):
                    continue
                s = ev["stats"]
                try:
                    row = {"MIN": float(s[idx["MIN"]]), "FG": made(s[idx["FG"]]), "FT": made(s[idx["FT"]]),
                           "REB": float(s[idx["REB"]]), "AST": float(s[idx["AST"]]), "BLK": float(s[idx["BLK"]]),
                           "STL": float(s[idx["STL"]]), "TO": float(s[idx["TO"]]), "PTS": float(s[idx["PTS"]])}
                except (ValueError, IndexError):
                    continue
                out.append({"event": ev["eventId"], "team": meta["team"]["id"],
                            "date": dt.datetime.fromisoformat(meta["gameDate"].replace("Z", "+00:00")).date(),
                            "MIN": row["MIN"], "fp": proxy_fp(row)})
    out.sort(key=lambda g: g["date"])
    return out


def mean(xs):
    xs = list(xs)
    return sum(xs) / len(xs) if xs else 0.0


def minutes_trend(gs, recent=5, before=10):
    """(minutes in the last `recent` games, minutes in the `before` games ahead of those) or None if too few games."""
    if len(gs) < recent + before:
        return None
    return (mean(g["MIN"] for g in gs[-recent:]), mean(g["MIN"] for g in gs[-recent - before:-recent]))


def estimate(form, trend, avg_min, stars_out):
    """Expected FP/G uplift for a player over his current form, or (0, '') if no signal.
    trend: (recent minutes, prior minutes) or None. stars_out: sum of (1 - availability) over rotation stars on his
    team who are out. Takes the larger of the two signals rather than adding them: a star who has been out for weeks
    is already in the player's recent form."""
    best, why = 0.0, ""
    if trend and trend[0] - trend[1] >= POLICY["signal_surge_min_gain"]:
        # Jump in output we expect to persist: the backtest keeps ~two thirds of a minutes-surge jump.
        gain = form * POLICY["signal_surge_keep"] * (trend[0] / max(trend[1], 1.0) - 1) * POLICY["signal_surge_scale"]
        if gain > best:
            best, why = gain, f"minutes {trend[0]:.0f} vs {trend[1]:.0f} over the 10 games before"
    if stars_out > 0:
        factor = POLICY["signal_out_bench"] if avg_min < 24 else POLICY["signal_out_rotation"]
        gain = form * (factor - 1) * min(stars_out, 1.0)
        if gain > best:
            best, why = gain, "star teammate out"
    return best, why


def opportunities(lg, season, n=5):
    """Free agents whose role may be growing: [(player, uplift FP/G, why, trend, stars out)] best first."""
    pool = sorted((p for p in lg.free_agents if p.status == "FREEAGENT" and p.gp > 0
                   and p.availability >= POLICY["add_min_availability"]), key=lambda p: -p.form)[:POLICY["signal_pool"]]
    with ThreadPoolExecutor(8) as ex:
        logs = list(ex.map(lambda p: games(p.id, season), pool))
    out = []
    for p, gs in zip(pool, logs):
        trend = minutes_trend(gs)
        avg_min = mean(g["MIN"] for g in gs[-10:]) if gs else 0.0
        stars = [q for q in lg.players.values() if q.pro_team == p.pro_team and q.id != p.id
                 and q.rate >= POLICY["signal_star_rate"] and q.availability < 1 and q.status == "ONTEAM"]
        stars_out = sum(1 - q.availability for q in stars)
        gain, why = estimate(p.form, trend, avg_min, stars_out)
        if gain >= POLICY["signal_min_uplift"]:
            out.append((p, gain, why, trend, [q for q in stars]))
    return sorted(out, key=lambda r: -r[1])[:n]
