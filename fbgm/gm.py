"""CLI: python3 -m fbgm <command> [options]"""
import argparse
import datetime as dt
import re
import sys

from . import espn, tracking
from .config import BENCH, CONFIG, DECIDED_LABEL, IR, OUTLOOK, POLICY, SLOT_NAMES
from .model import ET, League, fantasy_points, hungarian_max


def f1(x):
    return "-" if x is None else f"{x:.1f}"


def pos(pl):
    return "/".join(SLOT_NAMES[s] for s in sorted(pl.slots) if s <= 4) or "-"


def short(pl):
    return short_name(pl.name)


def short_name(name):
    parts = [w for w in name.split() if w.rstrip(".") not in ("Jr", "Sr", "II", "III", "IV")]
    return parts[-1]


def sos_str(lg, pl):
    f = lg.sos(pl)
    return "  -" if f is None else f"{f:4.2f}"


def opp_list(lg, pl):
    return ", ".join(f"{d:%a} {lg.pro_abbrev[lg.opponent[(pl.pro_team, d)]]} {lg.matchup_factor(pl, d):.2f}"
                     for d in lg.remaining_games(pl)) or "no games left"


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
    print(f"\n{'Player':24} {'Pos':9} {'St':2} {'Rate':>5} {'Szn':>5} {'L15':>5} {'Proj':>5} {'GP':>3} {'Gms':>3} {'SOS':>4} {'Own%':>5}")
    for p in fas:
        print(f"{p.name[:24]:24} {pos(p):9} {'W' if p.status == 'WAIVERS' else 'FA':2} {p.rate:5.1f} "
              f"{f1(p.season_fpg):>5} {f1(p.last15_fpg):>5} {f1(p.proj_fpg):>5} {p.gp:3} {lg.games_left(p):3} "
              f"{sos_str(lg, p)} {p.owned:5.1f}{inj(p)}")
    print("Rate = blended rest-of-season FP/G. Gms = unlocked games left this week. W = on waivers.\n"
          "SOS = this week's matchup strength (>1 easier, <1 tougher), by position, last 30 days.")


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
    print(f"\nMode: {mode}. FLEX = players we'd rotate: the lowest rate plus anyone within "
          f"{POLICY['flex_margin']:.0f} FP/G of it (max {POLICY['flex_slots'][mode]}).")
    if mode == "conservative" and under >= POLICY["aggressive_trigger"]:
        print(f"!! {under} underperformers -> consider --mode aggressive")


def cmd_swap(lg, a):
    header(lg)
    add = find(lg, a.add, lg.free_agents)
    drop = find(lg, a.drop, lg.roster())
    wk, starts = lg.evaluate_swap(add, drop)
    print(f"\nAdd  {add.name:24} form {add.form:5.1f}  rate {add.rate:5.1f}  games left {lg.games_left(add)}  "
          f"({'waivers, usable ' + str(lg.available_date(add)) if add.status == 'WAIVERS' else 'free agent'}){inj(add)}")
    print(f"Drop {drop.name:24} form {drop.form:5.1f}  rate {drop.rate:5.1f}  games left {lg.games_left(drop)}{inj(drop)}")
    print(f"Matchups  add: {opp_list(lg, add)} (SOS {sos_str(lg, add).strip()})")
    print(f"         drop: {opp_list(lg, drop)} (SOS {sos_str(lg, drop).strip()})")
    print(f"This week: {wk:+.1f} FP on current form | {starts_str(starts)} | ROS rate {add.rate - drop.rate:+.1f} FP/G")
    print("Verdict: " + verdict(lg, add, drop, wk, starts, a.mode))


def starts_str(starts):
    return ("starts " + ", ".join(f"{d:%a} {SLOT_NAMES[s]}" for d, s in starts)) if starts else "never fits the lineup"


def core_drop_ok(lg, p):
    """A core player is only a drop candidate when his outlook is badly hurt and IR can't take him."""
    if p.availability > POLICY["core_drop_max_availability"]:
        return False
    ir_open = lg.ir_slots and not any(x.lineup_slot == IR for x in lg.roster())
    return not (p.ir_eligible and ir_open)


def proven_upgrade(add, drop):
    """A healthy core player only goes for an add with a real track record who is better on both
    rest-of-season rate and current form."""
    return (add.gp >= POLICY["core_upgrade_min_gp"] and add.form >= drop.form
            and add.rate >= drop.rate + POLICY["core_upgrade_rate_gain"])


def drop_kind(lg, add, drop, flex):
    """'flex', 'outlook' (core, badly hurt), 'upgrade' (core, proven upgrade) or None if not droppable."""
    if drop in flex:
        return "flex"
    if core_drop_ok(lg, drop):
        return "outlook"
    return "upgrade" if proven_upgrade(add, drop) else None


def verdict(lg, add, drop, wk, starts, mode=None):
    kind = drop_kind(lg, add, drop, lg.flex_pool(mode))
    if kind is None:
        return (f"NO - {drop.name} is core and {add.name} isn't a proven upgrade "
                f"({POLICY['core_upgrade_min_gp']}+ GP, rate +{POLICY['core_upgrade_rate_gain']:.0f}, form at least as good)")
    if not starts:
        return f"NO - {add.name} can't crack the starting lineup (positions/schedule)"
    if wk < POLICY["flex_min_week_gain"]:
        return f"NO - only {wk:+.0f} FP this week (bar {POLICY['flex_min_week_gain']:.0f})"
    why = {"flex": "flex spot", "outlook": "core outlook changed", "upgrade": "proven upgrade over core"}[kind]
    return f"MOVE - {why}, {wk:+.0f} FP this week on current form"


def plan_moves(lg, a):
    """Best moves for this matchup week, on current form, respecting lineup slots.
    Returns (flex, hurt core, [(week FP, starts, add, drop)], alternatives for the first move)."""
    flex = lg.flex_pool(a.mode)
    roster = list(lg.roster())
    hurt = [p for p in roster if p not in flex and p.lineup_slot != IR and core_drop_ok(lg, p)]
    drops = [p for p in roster if p.lineup_slot != IR]
    cands = sorted(lg.free_agents, key=lambda p: -p.form)[:40]
    # Streamers: also consider the best schedule fits this week.
    cands += sorted(lg.free_agents, key=lambda p: -p.form * p.availability * lg.games_left(p))[:20]
    cands = [p for p in {c.id: c for c in cands}.values()
             if p.availability >= POLICY["add_min_availability"] and p.gp > 0]

    def rank(roster, drops, cands):
        rows = []
        for add in cands:
            for drop in drops:
                if drop_kind(lg, add, drop, flex) is None:
                    continue
                wk, starts = lg.evaluate_swap(add, drop, roster)
                if starts and wk >= POLICY["flex_min_week_gain"]:
                    rows.append((wk, starts, add, drop))
        rows.sort(key=lambda r: -r[0])
        # Neck and neck with the best move: prefer the easier schedule.
        near = [r for r in rows if r[0] >= rows[0][0] - POLICY["tie_week"]] if rows else []
        if near:
            best = max(near, key=lambda r: (lg.sos(r[2]) or 1.0, r[0]))
            rows.remove(best)
            rows.insert(0, best)
        return rows

    # Best single move first; then re-plan on the roster with that move applied.
    plan, alts, cur, left = [], [], roster, list(drops)
    while True:
        rows = rank(cur, left, cands)
        if not rows:
            break
        best = rows[0]
        plan.append(best)
        if len(plan) == 1:
            alts = [r for r in rows[1:] if r[3] is best[3]][: a.n]
        cur = [p for p in cur if p is not best[3]] + [best[2]]
        left = [p for p in left if p is not best[3]]
        cands = [p for p in cands if p is not best[2]]
    return flex, hurt, plan, alts


def move_tag(lg, r, flex):
    return {"flex": "", "outlook": " (core, outlook changed)",
            "upgrade": f" (core, proven upgrade: rate +{r[2].rate - r[3].rate:.1f} FP/G)"}[drop_kind(lg, r[2], r[3], flex)]


def cmd_advise(lg, a, quiet_header=False):
    """Best moves for this matchup week, on current form, respecting lineup slots."""
    if not quiet_header:
        header(lg)
    flex, hurt, plan, alts = plan_moves(lg, a)
    print("\nFlex: " + (", ".join(f"{p.name} (form {p.form:.1f})" for p in flex) or "none")
          + (f"  | core with changed outlook: {', '.join(f'{p.name}{inj(p)}' for p in hurt)}" if hurt else ""))

    def show(r):
        wk, starts, add, drop = r
        print(f"  MOVE +{add.name} / -{drop.name}{move_tag(lg, r, flex)}: week {wk:+.0f} FP, form {add.form:.1f} vs {drop.form:.1f}, "
              f"{starts_str(starts)}, SOS {sos_str(lg, add).strip()}"
              f"{' (waivers)' if add.status == 'WAIVERS' else ''}{inj(add)}")

    if not plan:
        print("No move clears the bar. Hold.")
    else:
        print("Recommended moves:")
        for r in plan:
            show(r)
        if alts:
            print("Alternatives for the same spot:")
            for r in alts:
                show(r)
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


def recap_data(lg, day):
    """One day's fantasy points for my matchup that day: {day, sp, period, final, sides: [me, opp]}, each side
    {tid, day_pts, total, players: [(slot, name, pts, stats, eligible slots)]}. None if no matchup that day."""
    sp = lg.date_sp.get(day)
    if sp is None:
        return None
    period = lg.week_of(day)
    box = espn.league("mBoxscore", "mMatchupScore", scoring_period=sp)
    me = CONFIG["my_team_id"]
    row = next((m for m in box["schedule"] if m["matchupPeriodId"] == period
                and me in (m["home"]["teamId"], m.get("away", {}).get("teamId"))), None)
    if not row:
        return None
    sides = []
    for side in sorted(("home", "away"), key=lambda s: row[s]["teamId"] != me):
        t = row[side]
        played = []
        for e in (t.get("rosterForCurrentScoringPeriod") or {}).get("entries", []):
            pe = e["playerPoolEntry"]
            st = next((s for s in pe["player"].get("stats", []) if s.get("scoringPeriodId") == sp
                       and s.get("statSourceId") == 0 and s.get("stats")), None)
            if st:
                played.append((e["lineupSlotId"], pe["player"]["fullName"], pe.get("appliedStatTotal", 0.0),
                               st["stats"], set(pe["player"].get("eligibleSlots", []))))
        played.sort(key=lambda x: (x[0] == BENCH, -x[2]))
        sides.append({"tid": t["teamId"], "day_pts": (t.get("pointsByScoringPeriod") or {}).get(str(sp), 0.0),
                      "total": t.get("totalPoints", 0.0), "players": played})
    return {"day": day, "sp": sp, "period": period, "final": period != lg.matchup_period, "sides": sides}


def bench_missed(lg, side):
    """(FP the best possible lineup would have added, bench scorers, empty starting slots) for one recap side."""
    starters = [p for p in side["players"] if p[0] not in (BENCH, IR)]
    bench = [p for p in side["players"] if p[0] == BENCH and p[2] > 0]
    empty = len(lg.slots) - len(starters)
    if not bench or empty <= 0:
        return 0.0, bench, empty
    pool = starters + bench
    assign = hungarian_max([[max(p[2], 0.0) if s in p[4] else 0.0 for s in lg.slots] for p in pool])
    best = sum(pool[r][2] for r in assign)
    return max(best - sum(p[2] for p in starters), 0.0), bench, empty


def cmd_recap(lg, a):
    """Previous night's fantasy points for my matchup, per player."""
    day = dt.date.fromisoformat(a.date) if getattr(a, "date", None) else lg.today - dt.timedelta(days=1)
    rec = recap_data(lg, day)
    if rec is None:
        print(f"\nNo matchup scoring on {day}.")
        return
    print(f"\nRecap {day:%a %m/%d} (week {rec['period']}):")
    for side in rec["sides"]:
        print(f"  {lg.team_names[side['tid']]}: {side['day_pts']:.0f} FP")
        for slot, name, pts, s, _ in side["players"]:
            line = "/".join(f"{s.get(k, 0):.0f}" for k in ("0", "6", "3", "2", "1", "11"))
            tag = " (bench, not counted)" if slot == BENCH else ""
            print(f"    {name:24} {pts:5.0f}  PTS/REB/AST/STL/BLK/TO {line}{tag}")
    if rec["final"]:
        a_, b_ = rec["sides"]
        res = "WON" if a_["total"] > b_["total"] else "LOST" if a_["total"] < b_["total"] else "TIED"
        print(f"  Week {rec['period']} final: {a_['total']:.0f}-{b_['total']:.0f} ({res})")


# ---- morning report (markdown) -------------------------------------------
def outlook(p):
    return next(label for floor, label in OUTLOOK if p >= floor)


def week_decided(lg, me, opp, proj):
    """('W' | 'L', banner) when the week passes the stress test, else None. Win: the opponent gets its upside
    (everyone plays, streams free agents daily) and we still win decided_win of the simulations. Loss: we get
    that upside - every move we could make - and still win no more than decided_loss."""
    lead = proj[me][1] - proj[opp][1]
    days = len(lg.remaining_days())
    left = f"{days} day{'s' * (days != 1)} left"
    name = lg.team_names[opp]
    n = POLICY["sims"]
    if lead > 0:
        p = lg.simulate_week(upside=opp, team_id=me, opp_id=opp)[0]
        if p >= POLICY["decided_win"]:
            return "W", (f"🔒 **WEEK {lg.matchup_period} DECIDED: WIN** · up {lead:,.0f} with {left}. Even if {name} "
                         f"plays everyone and streams free agents every day, we win {p:.1%} of {n:,} simulations. "
                         f"No roster moves needed this week.")
    elif lead < 0:
        p = lg.simulate_week(upside=me, team_id=me, opp_id=opp)[0]
        if p <= POLICY["decided_loss"]:
            return "L", (f"💀 **WEEK {lg.matchup_period} DECIDED: LOSS** · down {-lead:,.0f} with {left}. Even with "
                         f"all our players playing and us streaming free agents every day, we win {p:.1%} of "
                         f"{n:,} simulations. No moves will flip it this week.")
    return None


def scored(totals):
    """Per-team cells '1,992 (+285) 🟢' marking the leader and trailer, for two totals."""
    a, b = totals
    marks = ("🟢", "🔴") if a > b else ("🔴", "🟢") if a < b else ("⚪", "⚪")
    return [f"{x:,.0f} ({x - y:+,.0f}) {m}" for x, y, m in ((a, b, marks[0]), (b, a, marks[1]))]


def top_line(lg, rec):
    parts = []
    for side in rec["sides"]:
        top = [p for p in side["players"] if p[0] not in (BENCH, IR)][:3]
        parts.append(f"{lg.team_names[side['tid']]}: " + (", ".join(f"{short_name(p[1])} {p[2]:.0f}" for p in top) or "-"))
    return "**Top scorers** · " + " · ".join(parts)


def bench_alert(lg, rec):
    missed, bench, empty = bench_missed(lg, rec["sides"][0])
    if missed <= 0:
        return None
    who = ", ".join(f"{short_name(p[1])} {p[2]:.0f}" for p in bench)
    return (f"🔴 **BENCH POINTS LEFT BEHIND: {missed:.0f} FP** ({rec['day']:%a}) · bench scored: {who} · "
            f"{empty} of {len(lg.slots)} starting slots sat empty")


def table(header, rows, text_cols=1):
    """Markdown table; the first text_cols columns are left-aligned, the rest right-aligned."""
    print("| " + " | ".join(header) + " |")
    print("|" + "|".join(":--" if i < text_cols else "--:" for i in range(len(header))) + "|")
    for r in rows:
        print("| " + " | ".join(r) + " |")


NEWSY = re.compile(r"injur|questionable|doubtful|probable|\bout\b|ruled|rest|back-to-back|return|available|status|"
                   r"listed|restriction|start|bench|suspend|trade|sign|waive|day-to-day|game-time|sidelined|miss|"
                   r"absence|illness|sore|strain|sprain|surgery|mri|g league", re.I)


def news_section(lg, me, opp):
    """Back-to-back rest risks this week (plus the night after, for a Sun-Mon pair) and fresh status news, for
    our roster and the opponent's."""
    days = lg.remaining_days() + [lg.week_days[-1] + dt.timedelta(days=1)]
    cutoff = lg.now - dt.timedelta(hours=POLICY["news_hours"])
    rest, news = [], []
    for tid, tag in ((me, "us"), (opp, "opp")):
        for p in sorted(lg.roster(tid), key=lambda p: -p.rate):
            if p.lineup_slot == IR:
                continue
            ruling = lg.game_ruling(p)
            ruled = ruling[0] if ruling else None
            if ruling:
                after = "active" if ruling[1] == "rest" else "day-to-day"
                rest.append(f"- 🛌 **{p.name}** ({tag}) ruled out {ruled:%a} ({ruling[1]}) · counted as sitting {ruled:%a} "
                            f"only, {after} after")
            risky = [(d, lg.rest_chance(p, d)) for d in days if d != ruled]
            risky = [(d, c) for d, c in risky if c >= POLICY["rest_flag"]]
            if risky:
                pr = lg.rest_profile(p)
                legs = " · ".join(f"{d:%a} {c:.0%}" for d, c in risky)
                rest.append(f"- 💤 **{p.name}** ({tag}) back-to-back: chance he sits {legs} "
                            f"(sat {pr['sat1']} first / {pr['sat2']} second legs of {pr['b2b']} healthy B2Bs)")
            item = None if ruling else next((n for n in lg.news(p) if NEWSY.search(n.get("headline", ""))), None)
            if item and dt.datetime.fromisoformat(item["published"].replace("Z", "+00:00")) >= cutoff:
                head = item["headline"]
                news.append(f"- 📰 **{p.name}** ({tag}): {head if len(head) <= 160 else head[:157] + '...'}")
    print("\n## News & rest watch")
    for line in rest + news or ["- Nothing new."]:
        print(line)
    if rest:
        print("- Rest odds are already in the projections; check news before lock on those nights.")


def delta(x):
    return f"{x:+,.0f}"


def vs_projection(lg, rec, snap, me, opp):
    """Last night's projected vs actual. snap: the morning snapshot for that day (None -> rebuilt from today's data)."""
    day = rec["day"]
    rebuilt = snap is None
    teams = {}
    for side in rec["sides"]:
        tid = side["tid"]
        if rebuilt:
            tot, lineup = lg.day_projection(lg.roster(tid), day)
            players = {pl.name: {"proj": round(pl.expected * lg.rest_factor(pl, day), 1), "lineup": True}
                       for pl in lineup}
            teams[tid] = {"day": tot, "week": None, "players": players}
        else:
            teams[tid] = {**snap["teams"][str(tid)]}
    print(f"\n## {day:%a} projected vs actual" + (" (rebuilt from current rosters; no snapshot saved)" if rebuilt else ""))
    rows = []
    for side in rec["sides"]:
        t = teams[side["tid"]]
        rows.append([lg.team_names[side["tid"]], f"{t['day']:,.0f}", f"{side['day_pts']:,.0f}",
                     f"**{delta(side['day_pts'] - t['day'])}**"])
    table(["Team", "Projected", "Actual", "Δ"], rows)
    # Biggest player misses on our side: lineup players vs what the snapshot expected (DNP counts as 0).
    ours = {p[1]: p[2] for p in rec["sides"][0]["players"] if p[0] not in (BENCH, IR)}
    diffs = [(ours.get(n, 0.0) - v["proj"], n, v["proj"], ours.get(n, 0.0))
             for n, v in teams[me]["players"].items() if v["lineup"]]
    diffs.sort()
    def fmt(d):
        return f"{short_name(d[1])} {d[3]:.0f} vs {d[2]:.0f} proj ({delta(d[0])}{', DNP' if d[1] not in ours else ''})"
    under = [d for d in diffs if d[0] <= -8][:3]
    over = [d for d in reversed(diffs) if d[0] >= 8][:3]
    if under or over:
        print("\n" + " · ".join(x for x in (
            "**Under** " + ", ".join(fmt(d) for d in under) if under else "",
            "**Over** " + ", ".join(fmt(d) for d in over) if over else "") if x))
    return teams


def week_delta(lg, rec, snap, teams_proj, p_now, me, opp):
    """Week total projection and win chance: yesterday morning's vs now (or vs the final score on Mondays)."""
    if snap is None or snap["period"] != rec["period"]:
        return
    final = rec["final"]
    print(f"\n## Week {rec['period']} {'result' if final else 'projection'}: {snap['date']} morning vs " +
          ("final" if final else "now"))
    rows = []
    for i, side in enumerate(rec["sides"]):
        tid = side["tid"]
        t = snap["teams"][str(tid)]
        now = side["total"] if final else teams_proj[tid][0]
        miss = side["day_pts"] - t["day"]
        rest = (now - t["week"]) - miss
        why = "" if final else f"{delta(miss)} last night, {delta(rest)} rest of week"
        rows.append([lg.team_names[tid], f"{t['week']:,.0f}", f"{now:,.0f}", f"**{delta(now - t['week'])}**", why])
    table(["Team", "Yesterday proj", "Final" if final else "Today proj", "Δ", "From"], rows)
    if not final:
        before = snap["win_prob"]
        print(f"\n**Win chance** {before:.0%} → {p_now:.0%} ({p_now - before:+.0%}) · margin "
              f"{delta(snap['teams'][str(me)]['week'] - snap['teams'][str(opp)]['week'])} → "
              f"{delta(teams_proj[me][0] - teams_proj[opp][0])}")


def ir_section(lg):
    """Our IR players, only when a return is near or a timeline first shows up."""
    items = tracking.ir_status(lg)
    if not items:
        return
    flex = lg.flex_pool()
    print("\n## IR watch")
    for it in items:
        pl = it["player"]
        if it["lost"]:
            what = ("season-ending news" if it["lost"]["season"] else "no return timeline anymore")
            print(f"- 🚨 **{pl.name}**: previously expected back ~{it['prev']:%b %-d}, now {what}.\n"
                  f"  - Latest: {it['headline'][:200]} ({it['published']:%b %-d})")
            continue
        first = f"{it['first']:%a %b %-d}" if it["first"] else "no scheduled game left"
        if it["upgraded"]:
            when = f"ESPN status is now {pl.injury}: activate-ready"
        elif it["near"]:
            when = f"target return {it['kind']} {it['est']:%b %-d} ({it['days']}d)" if it["days"] > 0 else "return is here"
        else:
            when = f"timeline set: {it['kind']} {it['est']:%b %-d} ({it['days']}d out), nothing to do yet"
        line = f"- 🩹 **{pl.name}** (rate {pl.rate:.1f}): {when} · first game **{first}**"
        if it["shift"]:
            s_ = it["shift"]
            line = (f"- ⚠️ **{pl.name}** (rate {pl.rate:.1f}): return {'PUSHED BACK' if s_ > 0 else 'MOVED UP'} "
                    f"{abs(s_)}d, from {it['prev']:%b %-d} to {it['est']:%b %-d} ({it['days']}d out) · first game **{first}**")
        if it["near"]:
            spot = f" Likely spot to clear: {flex[0].name} (rate {flex[0].rate:.1f})." if flex else ""
            line += f"\n  - Move him off IR before tip-off; the roster needs an open spot.{spot}"
        line += f"\n  - Latest: {it['headline'][:200]} ({it['published']:%b %-d})"
        print(line)


def cmd_nightly(lg, a):
    """Morning report in markdown: overview + outlook, matchup grid (Mondays: last week's final and the
    new week's preview), roster moves, power rankings. {{OVERVIEW}} is for the reader to fill in."""
    me, opp = CONFIG["my_team_id"], lg.opponent_id()
    rec = recap_data(lg, lg.today - dt.timedelta(days=1))
    p = lg.win_probability(me, opp)
    print(f"# {lg.now:%a %b %-d, %Y · %-I:%M %p} ET")
    if lg.scoring_mismatch:
        print(f"\n!! League scoring differs from the confirmed table: {lg.scoring_mismatch}")
    proj = {tid: lg.week_projection(lg.roster(tid), tid) for tid in (me, opp)}
    decided = week_decided(lg, me, opp, proj)
    if decided:
        print(f"\n> {decided[1]}")
    label = DECIDED_LABEL[decided[0]] if decided else outlook(p)
    print(f"\n{{{{OVERVIEW}}}} **Outlook: {label}** ({p:.0%} win chance)")

    # Today: points already scored in started games + best lineup for the games still to come.
    sp_today = lg.date_sp.get(lg.today)
    today = {tid: lg.points_so_far(tid).get(sp_today, 0.0) + lg.day_projection(lg.roster(tid), lg.today)[0]
             for tid in (me, opp)}
    tday = f"{lg.today:%a} proj"
    names = [lg.team_names[me], lg.team_names[opp]]
    if rec and rec["final"]:
        a_, b_ = rec["sides"]
        won = a_["total"] > b_["total"]
        print(f"\n## Week {rec['period']} final {'🏆 WON' if won else '❌ LOST' if a_['total'] < b_['total'] else '🤝 TIED'}")
        cells = scored([a_["total"], b_["total"]])
        results = ("🏆", "❌") if won else ("❌", "🏆") if a_["total"] < b_["total"] else ("🤝", "🤝")
        table(["Team", f"{rec['day']:%a}", "Final (margin)"],
              [[f"{results[i]} {lg.team_names[s['tid']]}", f"{s['day_pts']:,.0f}", cells[i]] for i, s in enumerate(rec["sides"])])
        print("\n" + top_line(lg, rec))
        alert = bench_alert(lg, rec)
        if alert:
            print("\n" + alert)
        snap = tracking.load_snapshot(rec["day"])
        vs_projection(lg, rec, snap, me, opp)
        week_delta(lg, rec, snap, proj, p, me, opp)
        print(f"\n## Week {lg.matchup_period} preview · vs {names[1]}")
        cells = scored([proj[me][0], proj[opp][0]])
        table(["Team", tday, "Proj (margin)"],
              [[names[i], f"{today[tid]:,.0f}", cells[i]] for i, tid in enumerate((me, opp))])
    else:
        print(f"\n## Matchup summary · Week {lg.matchup_period} vs {names[1]}")
        day_pts = {s["tid"]: s["day_pts"] for s in rec["sides"]} if rec else {}
        cells = scored([proj[me][0], proj[opp][0]])
        yday = f"{lg.today - dt.timedelta(days=1):%a}"
        table(["Team", yday, tday, "Week", "Proj (margin)"],
              [[names[i], f"{day_pts.get(tid, 0):,.0f}", f"{today[tid]:,.0f}", f"{proj[tid][1]:,.0f}", cells[i]]
               for i, tid in enumerate((me, opp))])
        if rec:
            print("\n" + top_line(lg, rec))
            alert = bench_alert(lg, rec)
            if alert:
                print("\n" + alert)
            snap = tracking.load_snapshot(rec["day"])
            vs_projection(lg, rec, snap, me, opp)
            week_delta(lg, rec, snap, proj, p, me, opp)

    ir_section(lg)
    news_section(lg, me, opp)

    print("\n## Roster moves")
    flex, _, plan, alts = plan_moves(lg, a)
    if lg.today.weekday() == 0:
        print("- 📋 New week: set your lineups for the week.")
    print("- Flex: " + (", ".join(f"{q.name} (form {q.form:.1f})" for q in flex) or "none"))
    if decided:
        print(f"- **Skip** · week {lg.matchup_period} is decided; this week's moves can't change the result.")
        plan, alts = [], []
    elif not plan:
        print(f"- **Hold** · no move adds {POLICY['flex_min_week_gain']:.0f}+ FP this week.")
    for r in plan:
        wk, starts, add, drop = r
        print(f"- **+{add.name} / −{drop.name}**{move_tag(lg, r, flex)}: **{wk:+.0f} FP this week** · "
              f"form {add.form:.1f} vs {drop.form:.1f} · {len(starts)} start{'s' * (len(starts) != 1)}"
              f"{' · waivers' if add.status == 'WAIVERS' else ''}{inj(add)}")
    if alts:
        print("  - Backups: " + ", ".join(f"+{r[2].name} ({r[0]:+.0f})" for r in alts))
    if plan:
        print("- ↻ Update your lineups after making these moves.")

    tracking.save_snapshot(lg, proj, today, p, (me, opp))

    print("\n## Power rankings")
    now = lg.power_rankings()
    prev = {tid: i for i, (tid, _) in enumerate(lg.power_rankings(lg.today - dt.timedelta(days=1)))}
    rows = []
    for i, (tid, t) in enumerate(now):
        d = prev[tid] - i if prev else 0
        move = f"▲{d}" if d > 0 else f"▼{-d}" if d < 0 else "–"
        name = f"**{lg.team_names[tid]}**" if tid == me else lg.team_names[tid]
        rec_ = f"{t['w']}-{t['l']}" + (f"-{t['t']}" if t["t"] else "")
        trend = "🔥" if t["l7"] > 1.05 * t["pace"] else "🧊" if t["l7"] < 0.95 * t["pace"] else ""
        rows.append([f"{i + 1} {move}", name, rec_, f"{t['pace']:,.0f}", f"{t['l7']:,.0f}{trend}",
                     f"{t['roster']:,.0f}", f"{t['power']:,.0f}"])
    table(["#", "Team", "W-L", "Pace", "L7", "Roster", "Power"], rows, text_cols=2)
    print("\n_FP per week. Pace = season scoring rate, L7 = last 7 days, Roster = current roster on current form. "
          "Power blends results (more weight as the season goes) with roster strength, plus record. Arrows = vs yesterday._")


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
    p = sub.add_parser("recap"); p.add_argument("--date")
    p = sub.add_parser("nightly"); p.add_argument("--n", type=int, default=3)
    a = ap.parse_args(argv)
    espn.FRESH = a.fresh
    lg = League(dt.date.fromisoformat(a.today) if a.today else None)
    globals()[f"cmd_{a.cmd}"](lg, a)
