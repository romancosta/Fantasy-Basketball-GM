"""Recap and morning-report (markdown) commands."""
import contextlib
import datetime as dt
import io
import re

from . import espn, health, tracking
from .config import BENCH, CONFIG, DECIDED_LABEL, IR, OUTLOOK, POLICY
from .fmt import inj, short_name, table
from .gm import move_tag, plan_moves
from .model import hungarian_max


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


def roster_moves(lg, a, decided):
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


def power_rankings_section(lg, me):
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


def nightly_body(lg, a):
    """Morning report in markdown: overview + outlook, matchup grid (Mondays: last week's final and the
    new week's preview), roster moves, power rankings. {{OVERVIEW}} is for the reader to fill in."""
    me, opp = CONFIG["my_team_id"], lg.opponent_id()
    try:
        rec = recap_data(lg, lg.today - dt.timedelta(days=1))
    except Exception as exc:   # noqa: BLE001 - the report is still useful without last night's recap
        health.warn(f"last night's box scores unavailable ({type(exc).__name__}: {exc})", source="espn")
        rec = None
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
        compare_with_snapshot(lg, rec, proj, p, me, opp)
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
            compare_with_snapshot(lg, rec, proj, p, me, opp)

    with health.section("IR watch"):
        ir_section(lg)
    with health.section("News & rest watch"):
        news_section(lg, me, opp)
    with health.section("Roster moves"):
        roster_moves(lg, a, decided)
    with health.section("Snapshot save", quiet=True):
        tracking.save_snapshot(lg, proj, today, p, (me, opp))
    with health.section("Power rankings"):
        power_rankings_section(lg, me)


def compare_with_snapshot(lg, rec, proj, p, me, opp):
    """Last night's projected-vs-actual and the week-projection delta, against yesterday's saved snapshot."""
    with health.section("Projected vs actual"):
        snap = tracking.load_snapshot(rec["day"])
        if snap is None:
            health.warn(f"no projection snapshot saved for {rec['day']}; last night's projections were rebuilt from "
                        f"current rosters and the week comparison is skipped", source="state")
        vs_projection(lg, rec, snap, me, opp)
        week_delta(lg, rec, snap, proj, p, me, opp)


def cmd_nightly(lg, a):
    """Morning report. The body is built first so a data-health banner can sit under the outlook line and a Health
    section can close the report; section failures are contained (see health.section)."""
    health.reset()
    health.check_league(lg)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        nightly_body(lg, a)
    text = buf.getvalue()
    banner = health.banner()
    if banner:
        lines = text.split("\n")
        at = next((i for i, ln in enumerate(lines) if "{{OVERVIEW}}" in ln), 0)
        text = "\n".join(lines[:at + 1] + ["", banner] + lines[at + 1:])
    print(text.rstrip("\n"))
    if health.issues():
        print(health.render())
