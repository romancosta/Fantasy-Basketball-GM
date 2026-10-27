"""CLI: python3 -m fbgm <command> [options]"""
import argparse
import datetime as dt
import sys

from . import espn
from .config import BENCH, CONFIG, IR, POLICY, SLOT_NAMES
from .model import ET, League, fantasy_points


def f1(x):
    return "-" if x is None else f"{x:.1f}"


def pos(pl):
    return "/".join(SLOT_NAMES[s] for s in sorted(pl.slots) if s <= 4) or "-"


def short(pl):
    parts = [w for w in pl.name.split() if w.rstrip(".") not in ("Jr", "Sr", "II", "III", "IV")]
    return parts[-1]


def inj(pl):
    return "" if pl.injury == "ACTIVE" else f" [{pl.injury}]"


def header(lg):
    days = lg.remaining_days()
    span = f"{days[0]:%a %m/%d}-{days[-1]:%a %m/%d}" if days else "none"
    print(f"{lg.now:%a %m/%d %I:%M %p} ET | matchup week {lg.matchup_period} | days left: {span}")
    if lg.scoring_mismatch:
        print(f"!! scoring differs from confirmed table: {lg.scoring_mismatch}")


def find(lg, name, pool):
    name = name.lower()
    hits = [p for p in pool if name in p.name.lower()]
    if len(hits) != 1:
        sys.exit(f"'{name}': {'no match' if not hits else 'ambiguous: ' + ', '.join(p.name for p in hits[:6])}")
    return hits[0]


# ---- commands -------------------------------------------------------------
def cmd_matchup(lg, a):
    header(lg)
    me, opp = CONFIG["my_team_id"], lg.opponent_id()
    rows = []
    for tid in (me, opp):
        total, actual, future = lg.week_projection(lg.roster(tid), tid)
        rows.append((lg.team_names[tid], actual, future, total))
    print(f"\n{'Team':28} {'Actual':>7} {'Proj rest':>9} {'Proj total':>10}")
    for r in rows:
        print(f"{r[0]:28} {r[1]:7.0f} {r[2]:9.0f} {r[3]:10.0f}")
    print(f"Projected margin: {rows[0][3] - rows[1][3]:+.0f}")
    print("\nGames left (unlocked) by player:")
    for tid in (me, opp):
        ps = sorted(lg.roster(tid), key=lambda p: -p.rate)
        print(f"  {lg.team_names[tid]}: " + ", ".join(
            f"{short(p)} {lg.games_left(p)}{'*' if p.availability < 1 else ''}"
            for p in ps if p.lineup_slot != IR))
    print("  (* injury-discounted)")
    cmd_lineup(lg, a, quiet_header=True)


def cmd_lineup(lg, a, quiet_header=False):
    day = dt.date.fromisoformat(a.date) if getattr(a, "date", None) else lg.today
    if not quiet_header:
        header(lg)
    roster = lg.roster()
    pts, lineup = lg.day_projection(roster, day)
    print(f"\nOptimal lineup {day:%a %m/%d} (proj {pts:.0f} FP):")
    if not lineup:
        print("  No unlocked games left for this roster today.")
    started = set(lineup)
    full = lg.full_lineup(roster, day)
    for pl, slot in sorted(full.items(), key=lambda kv: kv[1]):
        if pl in started:
            t = lg.game_start(pl, day)
            print(f"  {SLOT_NAMES[slot]:6} {pl.name:24} {pl.expected:5.1f}  {t:%I:%M%p}{inj(pl)}")
    moves = [(p, s) for p, s in full.items() if s != p.lineup_slot]
    if moves:
        print("  Lineup changes on ESPN:")
        for p, s in sorted(moves, key=lambda m: m[1] == BENCH):
            note = "idle" if not lg.plays(p, day) else ("plays" if s != BENCH else "plays, no slot")
            print(f"    {p.name:24} {SLOT_NAMES.get(p.lineup_slot, '?'):6} -> {SLOT_NAMES[s]:6} ({note})")
    bench_play = [p for p in roster if p.lineup_slot == BENCH and lg.plays(p, day) and p not in started
                  and not (day == lg.today and lg.locked(p, day))]
    if bench_play:
        print("  Benched with a game (no better slot): " + ", ".join(p.name for p in bench_play))
    for pl in roster:
        if pl.availability == 0 and pl.lineup_slot != IR and pl.ir_eligible and lg.ir_slots:
            ir_used = any(p.lineup_slot == IR for p in roster)
            if not ir_used:
                print(f"  -> IR open: move {pl.name}{inj(pl)} to IR, freeing a roster spot for an add")


def cmd_fa(lg, a):
    header(lg)
    fas = lg.free_agents
    if a.pos:
        want = {k for k, v in SLOT_NAMES.items() if v == a.pos.upper()}
        fas = [p for p in fas if p.slots & want]
    fas = sorted(fas, key=lambda p: -p.rate)[: a.n]
    print(f"\n{'Player':24} {'Pos':9} {'St':2} {'Rate':>5} {'Szn':>5} {'L15':>5} {'Proj':>5} {'GP':>3} {'Gms':>3} {'Own%':>5}")
    for p in fas:
        print(f"{p.name[:24]:24} {pos(p):9} {'W' if p.status == 'WAIVERS' else 'FA':2} {p.rate:5.1f} "
              f"{f1(p.season_fpg):>5} {f1(p.last15_fpg):>5} {f1(p.proj_fpg):>5} {p.gp:3} {lg.games_left(p):3} "
              f"{p.owned:5.1f}{inj(p)}")
    print("Rate = blended rest-of-season FP/G. Gms = unlocked games left this week. W = on waivers.")


def cmd_drops(lg, a):
    header(lg)
    mine = sorted((p for p in lg.roster() if p.lineup_slot != IR), key=lambda p: p.rate)
    flex = set(lg.flex_pool(a.mode))
    print(f"\n{'Player':24} {'Pos':9} {'Rate':>5} {'Szn':>5} {'L15':>5} {'Prior':>5} {'GP':>3} {'Gms':>3}  Notes")
    under = 0
    for p in mine:
        notes = []
        if p in flex:
            notes.append("FLEX")
        if p.underperforming:
            notes.append("UNDERPERFORMING")
            under += 1
        if p.availability < 1:
            notes.append(p.injury)
        print(f"{p.name[:24]:24} {pos(p):9} {p.rate:5.1f} {f1(p.season_fpg):>5} {f1(p.last15_fpg):>5} "
              f"{p.prior:5.1f} {p.gp:3} {lg.games_left(p):3}  {' '.join(notes)}")
    mode = a.mode or POLICY["mode"]
    print(f"\nMode: {mode} ({POLICY['flex_slots'][mode]} flex spot). FLEX = players we'd rotate.")
    if mode == "conservative" and under >= POLICY["aggressive_trigger"]:
        print(f"!! {under} underperformers -> consider --mode aggressive")


def cmd_swap(lg, a):
    header(lg)
    add = find(lg, a.add, lg.free_agents)
    drop = find(lg, a.drop, lg.roster())
    wk, ros = lg.swap_value(add, drop)
    print(f"\nAdd  {add.name:24} rate {add.rate:5.1f}  games left {lg.games_left(add)}  "
          f"({'waivers, usable ' + str(lg.available_date(add)) if add.status == 'WAIVERS' else 'free agent'}){inj(add)}")
    print(f"Drop {drop.name:24} rate {drop.rate:5.1f}  games left {lg.games_left(drop)}{inj(drop)}")
    print(f"This week: {wk:+.1f} FP | Rest of season: {ros:+.1f} FP/G")
    print("Verdict: " + verdict(lg, add, drop, wk, ros, a.mode))


def verdict(lg, add, drop, wk, ros, mode=None):
    if ros >= 0 and wk >= 0:
        return "UPGRADE - better long-term and not worse this week"
    if ros >= 0:
        return f"UPGRADE (long-term) - costs {-wk:.0f} FP this week; time the move after this week's games"
    in_flex = drop in lg.flex_pool(mode)
    if (in_flex and ros >= -POLICY["stream_ros_tolerance"] and wk >= POLICY["stream_min_week_gain"]):
        return "STREAM - flex spot, small long-term cost, meaningful weekly gain"
    if not in_flex:
        return f"NO - {drop.name} is a core player (not in flex pool); long-term cost {ros:.1f} FP/G"
    return "NO - weekly gain too small for the long-term cost"


def cmd_advise(lg, a):
    """Best moves: evaluate top free agents against the flex pool and any IR opening."""
    header(lg)
    flex = lg.flex_pool(a.mode)
    cands = sorted(lg.free_agents, key=lambda p: -p.rate)[:40]
    # Streamers: also consider the best schedule fits this week.
    cands += sorted(lg.free_agents, key=lambda p: -p.expected * lg.games_left(p))[:20]
    seen, rows = set(), []
    for add in cands:
        # Conservative: never recommend someone who is out or hasn't played yet this season.
        if add.id in seen or add.availability == 0 or add.gp == 0:
            continue
        seen.add(add.id)
        for drop in flex:
            wk, ros = lg.swap_value(add, drop)
            v = verdict(lg, add, drop, wk, ros, a.mode)
            if not v.startswith("NO"):
                rows.append((v.split()[0], ros, wk, add, drop, v))
    rows.sort(key=lambda r: (r[0] != "UPGRADE", -(r[1] * 10 + r[2] / 5)))
    print(f"\nFlex pool: {', '.join(f'{p.name} ({p.rate:.1f})' for p in flex)}")
    if not rows:
        print("No moves clear the bar. Hold.")
    for kind, ros, wk, add, drop, v in rows[: a.n]:
        print(f"  {kind:7} +{add.name} / -{drop.name}: week {wk:+.0f} FP, ROS {ros:+.1f} FP/G"
              f"{' (waivers)' if add.status == 'WAIVERS' else ''}{inj(add)}")
    cmd_lineup(lg, a, quiet_header=True)


def cmd_rivals(lg, a):
    header(lg)
    tx = espn.league("mTransactions2").get("transactions", [])
    cutoff = lg.now - dt.timedelta(days=a.days)
    rows = []
    for t in tx:
        if t.get("status") != "EXECUTED" or t.get("type") not in ("FREEAGENT", "WAIVER"):
            continue
        when = dt.datetime.fromtimestamp(t["proposedDate"] / 1000, ET)
        if when < cutoff:
            continue
        for it in t["items"]:
            if it["type"] in ("ADD", "DROP"):
                pl = lg.players.get(it["playerId"])
                rows.append((when, lg.team_names.get(t["teamId"], t["teamId"]), it["type"],
                             pl.name if pl else it["playerId"], pl))
    rows.sort(key=lambda r: r[0], reverse=True)
    print(f"\nLast {a.days} days:")
    for when, team, kind, name, pl in rows:
        extra = f" (rate {pl.rate:.1f}, now {'FA' if pl.status != 'ONTEAM' else 'rostered'})" if pl else ""
        print(f"  {when:%a %m/%d %I:%M%p} {team:26} {kind:4} {name}{extra}")


def cmd_check(lg, a):
    """Verify our scoring math against ESPN's applied totals and last week's matchup."""
    header(lg)
    print(f"\nLeague scoring == confirmed table: {not lg.scoring_mismatch}")
    bad = n = 0
    raw = espn.players(limit=150)
    for e in raw:
        for s in e["player"].get("stats", []):
            if s.get("statSourceId") == 0 and s.get("stats") and s.get("appliedTotal") is not None:
                ours = fantasy_points(s["stats"], lg.scoring)
                n += 1
                if abs(ours - s["appliedTotal"]) > 0.01:
                    bad += 1
    print(f"Per-player actual stat lines checked: {n}, mismatches vs ESPN: {bad}")
    print(f"Today {lg.today} = scoring period {lg.date_sp.get(lg.today)}; "
          f"week days {lg.week_days[0]}..{lg.week_days[-1]}")


def main(argv=None):
    ap = argparse.ArgumentParser(prog="fbgm")
    ap.add_argument("--fresh", action="store_true", help="ignore the 5-minute cache")
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD, ET)")
    ap.add_argument("--mode", choices=["conservative", "aggressive"])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("matchup")
    p = sub.add_parser("lineup"); p.add_argument("--date")
    p = sub.add_parser("fa"); p.add_argument("--pos"); p.add_argument("--n", type=int, default=20)
    sub.add_parser("drops")
    p = sub.add_parser("swap"); p.add_argument("add"); p.add_argument("drop")
    p = sub.add_parser("advise"); p.add_argument("--n", type=int, default=8)
    p = sub.add_parser("rivals"); p.add_argument("--days", type=int, default=7)
    sub.add_parser("check")
    a = ap.parse_args(argv)
    espn.FRESH = a.fresh
    lg = League(dt.date.fromisoformat(a.today) if a.today else None)
    globals()[f"cmd_{a.cmd}"](lg, a)
