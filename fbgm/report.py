"""Recap and morning-report (markdown) commands."""
import contextlib
import datetime as dt
import io
import re

from . import espn, health, lookahead, season, signals, tracking
from .config import BENCH, CONFIG, DECIDED_LABEL, IR, OUTLOOK, POLICY
from .fmt import inj, short_name, table
from .gm import move_tag, plan_moves, pos
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
# A back-to-back only makes the report when the player's own news raises rest (not on the odds alone).
REST_TALK = re.compile(r"\brest(?:ing|ed)?\b|load management|maintenance|back-to-back|night off|could sit|may sit|"
                       r"might sit|sit out", re.I)


def news_section(lg, me, opp):
    """Significant news only: one-game rulings, rest talk in a player's own news (with his back-to-back odds), and fresh
    status news for rotation players. Plain back-to-back odds are already in the projections and are not shown."""
    days = lg.remaining_days() + [lg.week_days[-1] + dt.timedelta(days=1)]
    cutoff = lg.now - dt.timedelta(hours=POLICY["news_hours"])
    lines = []
    for tid, tag in ((me, "us"), (opp, "opp")):
        for p in sorted(lg.roster(tid), key=lambda p: -p.rate):
            if p.lineup_slot == IR or p.rate < POLICY["news_min_rate"]:
                continue
            ruling = lg.game_ruling(p)
            if ruling:
                after = "active" if ruling[1] == "rest" else "day-to-day"
                lines.append(f"- 🛌 **{p.name}** ({tag}) ruled out {ruling[0]:%a} ({ruling[1]}); {after} after")
                continue
            latest = lg.news(p)[:1]
            item = next((n for n in lg.news(p) if NEWSY.search(n.get("headline", ""))), None)
            fresh = item and dt.datetime.fromisoformat(item["published"].replace("Z", "+00:00")) >= cutoff
            if latest and REST_TALK.search(f"{latest[0].get('headline', '')} {latest[0].get('story', '')}") and fresh:
                legs = " · ".join(f"{d:%a} {c:.0%}" for d in days if (c := lg.rest_chance(p, d)) >= POLICY["rest_flag"])
                lines.append(f"- 💤 **{p.name}** ({tag}): rest in the news{f' · back-to-back sit odds {legs}' if legs else ''}")
            elif fresh:
                head = item["headline"]
                lines.append(f"- 📰 **{p.name}** ({tag}): {head if len(head) <= 140 else head[:137] + '...'}")
    if lines:
        print("\n## News")
        for line in lines:
            print(line)


def delta(x):
    return f"{x:+,.0f}"


def night_compare(lg, rec, snap):
    """Last night's projection vs the actual, per team: ({tid: {proj, actual, players}}, rebuilt). The projection comes
    from the morning snapshot for that day; with none it is rebuilt from today's rosters (rebuilt=True)."""
    day = rec["day"]
    out = {}
    for side in rec["sides"]:
        tid = side["tid"]
        if snap is None:
            total, lineup = lg.day_projection(lg.roster(tid), day)
            players = {pl.name: {"proj": round(pl.expected * lg.rest_factor(pl, day), 1), "lineup": True}
                       for pl in lineup}
        else:
            total, players = snap["teams"][str(tid)]["day"], snap["teams"][str(tid)]["players"]
        out[tid] = {"proj": total, "actual": side["day_pts"], "players": players}
    return out, snap is None


def night_cell(c, rebuilt):
    return f"{'~' if rebuilt else ''}{c['proj']:,.0f} → {c['actual']:,.0f} ({delta(c['actual'] - c['proj'])})"


def miss_line(rec, compare, me):
    """Our biggest lineup misses against the projection (a no-show counts as 0), or ''."""
    ours = {p[1]: p[2] for p in rec["sides"][0]["players"] if p[0] not in (BENCH, IR)}
    diffs = sorted((ours.get(n, 0.0) - v["proj"], n, v["proj"], ours.get(n, 0.0))
                   for n, v in compare[me]["players"].items() if v["lineup"])

    def fmt(d):
        return f"{short_name(d[1])} {d[3]:.0f} vs {d[2]:.0f}{' (DNP)' if d[1] not in ours else ''}"
    under = [d for d in diffs if d[0] <= -8][:3]
    over = [d for d in reversed(diffs) if d[0] >= 8][:3]
    parts = ([f"under: {', '.join(fmt(d) for d in under)}"] if under else []) + \
            ([f"over: {', '.join(fmt(d) for d in over)}"] if over else [])
    return "**Vs projection** · " + " · ".join(parts) if parts else ""


def vs_yesterday(snap, rec, tid, now, compare):
    """Change in the week total against what yesterday morning's snapshot projected, split into last night's miss and
    the re-projection of what's left: '+350 (+28 night, +322 rest)'. '-' when there is no comparable snapshot."""
    if snap is None or snap["period"] != rec["period"]:
        return "-"
    change = now - snap["teams"][str(tid)]["week"]
    if rec["final"]:
        return delta(change)
    miss = compare[tid]["actual"] - compare[tid]["proj"]
    return f"{delta(change)} ({delta(miss)} night, {delta(change - miss)} rest)"


def last_night_lines(lg, rec, compare, me):
    print("\n" + top_line(lg, rec))
    misses = miss_line(rec, compare, me)
    if misses:
        print("\n" + misses)
    alert = bench_alert(lg, rec)
    if alert:
        print("\n" + alert)


def matchup_section(lg, rec, snap, proj, today, me, opp):
    """One grid for the week: last night's projection vs actual, today's projection, the week so far, the week
    projection with margin, and how that moved since yesterday."""
    names = [lg.team_names[me], lg.team_names[opp]]
    print(f"\n## Matchup · Week {lg.matchup_period} vs {names[1]}")
    margins = scored([proj[me][0], proj[opp][0]])
    head = ["Team"] + ([f"{rec['day']:%a} proj → actual"] if rec else []) + [f"{lg.today:%a} proj", "Week so far",
                                                                           "Week proj (margin)"]
    if rec:
        head.append("Vs yesterday's proj")
        compare, rebuilt = night_compare(lg, rec, snap)
    rows = []
    for i, tid in enumerate((me, opp)):
        row = [names[i]]
        if rec:
            row.append(night_cell(compare[tid], rebuilt))
        row += [f"{today[tid]:,.0f}", f"{proj[tid][1]:,.0f}", margins[i]]
        if rec:
            row.append(vs_yesterday(snap, rec, tid, proj[tid][0], compare))
        rows.append(row)
    table(head, rows)
    if rec:
        last_night_lines(lg, rec, compare, me)


def week_final_section(lg, rec, snap, proj, today, me, opp):
    """Monday: last week's result (with how it compared to Sunday's projection), then the new week's preview."""
    a_, b_ = rec["sides"]
    won = a_["total"] > b_["total"]
    lost = a_["total"] < b_["total"]
    print(f"\n## Week {rec['period']} final {'🏆 WON' if won else '❌ LOST' if lost else '🤝 TIED'}")
    compare, rebuilt = night_compare(lg, rec, snap)
    cells = scored([a_["total"], b_["total"]])
    icons = ("🏆", "❌") if won else ("❌", "🏆") if lost else ("🤝", "🤝")
    rows = [[f"{icons[i]} {lg.team_names[s['tid']]}", night_cell(compare[s["tid"]], rebuilt), cells[i],
             vs_yesterday(snap, rec, s["tid"], s["total"], compare)] for i, s in enumerate(rec["sides"])]
    table(["Team", f"{rec['day']:%a} proj → actual", "Final (margin)", "Vs Sunday's week proj"], rows)
    last_night_lines(lg, rec, compare, me)
    print(f"\n## Week {lg.matchup_period} preview · vs {lg.team_names[opp]}")
    margins = scored([proj[me][0], proj[opp][0]])
    table(["Team", f"{lg.today:%a} proj", "Week proj (margin)"],
          [[lg.team_names[tid], f"{today[tid]:,.0f}", margins[i]] for i, tid in enumerate((me, opp))])


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
            line += f" · needs a roster spot{f' (clear {short_name(flex[0].name)})' if flex else ''}"
        if it["shift"]:
            line += f"\n  - Latest: {it['headline'][:160]} ({it['published']:%b %-d})"
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
        if POLICY["report_lookahead"]:
            ahead = range(1, POLICY["lookahead_weeks"] + 1)
            print(f"  - Games in the next {len(ahead)} weeks: +{short_name(add.name)} "
                  + "/".join(str(lookahead.player_games(lg, add, o)) for o in ahead)
                  + f" vs −{short_name(drop.name)} " + "/".join(str(lookahead.player_games(lg, drop, o)) for o in ahead))
    if alts:
        print("  - Backups: " + ", ".join(f"+{r[2].name} ({r[0]:+.0f})" for r in alts))
    if plan:
        print("- ↻ Update your lineups after making these moves.")


def season_section(lg, p_me):
    """Standings, playoff odds, and what this week is worth, from the schedule's results and a season simulation."""
    me = CONFIG["my_team_id"]
    sched = lg.raw["schedule"]
    ss = lg.raw["settings"]["scheduleSettings"]
    n_weeks, n_playoff = ss["matchupPeriodCount"], ss["playoffTeamCount"]
    ids = list(lg.teams)
    rankings = dict(lg.power_rankings())
    raw = {t: info["power"] - POLICY["power_record_fp"] * (info["w"] - info["l"]) for t, info in rankings.items()}
    past = season.completed_weeks(sched, lg.matchup_period)
    # Early ratings are noisy (a week of results, rosters mid-churn): pull them toward the league mean, less each week.
    weeks_played = len(past) / max(len(ids) / 2, 1)
    k = POLICY["season_strength_weeks"]
    pull = POLICY["season_regress"] * k / (k + weeks_played)
    mean = sum(raw.values()) / len(raw)
    strength = {t: mean + (s - mean) * (1 - pull) for t, s in raw.items()}
    sd = season.week_sds(strength, past, POLICY["season_sd_ratio"])
    share = len(lg.remaining_days()) / max(len(lg.week_days), 1)
    current = {t: (sum(lg.points_so_far(t).values()), share) for t in ids}
    rival = next((t for t in ids if CONFIG["rival_name"].lower() in lg.team_names[t].lower()), None)
    unsure = POLICY["season_strength_sd_ratio"] * (k / (k + weeks_played)) ** 0.5
    sim = season.simulate(sched, lg.matchup_period, ids, strength, sd, current, me, p_me, n_playoff, rival,
                          sims=POLICY["season_sims"], seed=f"season-{lg.today}",
                          strength_sd={t: unsure * strength[t] for t in ids})
    rec = season.standings(sched, lg.matchup_period, ids)
    order = sorted(ids, key=lambda t: season.order_key(rec[t]))
    # Rank ties on the model's expected wins so early-season rows (everyone 1-0) are in a useful order.
    order.sort(key=lambda t: (season.order_key(rec[t])[0], -sim["wins"][t]))
    print(f"\n## Season picture · week {lg.matchup_period} of {n_weeks} · top {n_playoff} make the playoffs")
    rows = []
    for i, t in enumerate(order):
        espn_pct = (lg.teams[t].get("currentSimulationResults") or {}).get("playoffPct")
        name = lg.team_names[t]
        name = f"**{name}**" if t == me else f"{name} 👑" if t == rival else name
        rr = rec[t]
        rows.append([str(i + 1), name, f"{rr['w']}-{rr['l']}" + (f"-{rr['t']}" if rr["t"] else ""),
                     f"{rr['pf']:,.0f}", f"{rr['pa']:,.0f}", f"{sim['playoff'][t]:.0%}",
                     f"{espn_pct:.0%}" if espn_pct is not None else "-"])
    table(["#", "Team", "W-L", "PF", "PA", "Playoffs", "ESPN says"], rows, text_cols=2)
    line = (f"\n**Us**: projected finish {sim['wins'][me]:.1f}-{n_weeks - sim['wins'][me]:.1f} · playoffs "
            f"{sim['playoff'][me]:.0%} · #1 seed {sim['seed1'][me]:.0%}")
    if rival is not None and sim["rival_ahead"] is not None:
        line += f" · {lg.team_names[rival]} finishes ahead of us in {sim['rival_ahead']:.0%} of sims"
    print(line)
    win, loss = sim["me_if_win"], sim["me_if_loss"]
    if win is not None and loss is not None:
        swing = win - loss
        flag = " 🎯 **Must-win week**" if swing >= POLICY["season_must_win_swing"] else ""
        print(f"\n**This week**: playoff odds {win:.0%} with a win, {loss:.0%} with a loss (swing {swing * 100:.0f} pts){flag}")
    nxt = sorted((m["matchupPeriodId"], m["home"]["teamId"] if m["away"]["teamId"] == me else m["away"]["teamId"])
                 for m in sched if m["matchupPeriodId"] > lg.matchup_period and "away" in m
                 and me in (m["home"]["teamId"], m["away"]["teamId"]))[:3]
    if nxt:
        parts = []
        for wk, opp in nxt:
            spread = (sd[me] ** 2 + sd[opp] ** 2 + (unsure * strength[me]) ** 2 + (unsure * strength[opp]) ** 2) ** 0.5
            p = season.ND.cdf((strength[me] - strength[opp]) / spread)
            parts.append(f"wk {wk} {lg.team_names[opp]} {p:.0%}")
        print("\n**Next**: " + " · ".join(parts))
    print("\n_Odds simulate every remaining week from team strength; seeding assumes record, then fewer points against._")


def lookahead_section(lg):
    """Our lineup's games and projected FP over the coming weeks against each week's opponent, and each player's games."""
    me = CONFIG["my_team_id"]
    n = POLICY["lookahead_weeks"]
    opps = lookahead.opponents_by_week(lg.raw["schedule"], me, lg.matchup_period, n)
    mine = lookahead.active_roster(lg)
    print(f"\n## Schedule look-ahead · next {n} weeks")
    rows = []
    for off in range(n + 1):
        starts, fp = lookahead.team_week(lg, mine, off)
        opp = opps.get(off)
        o_starts, o_fp = lookahead.team_week(lg, lookahead.active_roster(lg, opp), off) if opp else (0, 0.0)
        label = "This week (left)" if off == 0 else f"Wk {lg.matchup_period + off}"
        gap = fp - o_fp
        rows.append([label, lg.team_names[opp] if opp else "-", f"{starts}", f"{fp:,.0f}", f"{o_starts}", f"{o_fp:,.0f}",
                     f"{gap:+,.0f}", f"{lookahead.league_avg_games(lg, off):.1f}"])
    table(["Week", "Opponent", "Our starts", "Our FP", "Opp starts", "Opp FP", "Edge", "Avg games"], rows, text_cols=2)
    head = ["Player"] + ["Left" if o == 0 else f"Wk {lg.matchup_period + o}" for o in range(n + 1)]
    avgs = [lookahead.league_avg_games(lg, o) for o in range(n + 1)]
    prow = []
    for pl in sorted(mine, key=lambda p: -p.rate)[:12]:
        prow.append([pl.name + inj(pl)] + [lookahead.mark(lookahead.player_games(lg, pl, o), avgs[o])
                                           for o in range(n + 1)])
    print()
    table(head, prow)
    print("\n_Games per player (▲ heavy / ▼ light week vs the league average). FP uses today's injury statuses and the best "
          "daily lineups; a player who is OUT counts as 0 in every week._")


def opportunity_section(lg):
    """Free agents whose role may be growing (minutes surge, or a star teammate is out). Informational: the move
    recommendations above do not use it."""
    found = signals.opportunities(lg, CONFIG["season"])
    if not found:
        return
    print("\n## Opportunity watch")
    for pl, gain, why, trend, stars in found:
        out = ", ".join(f"{short_name(q.name)} ({q.injury.replace('_', '-').title()})" for q in stars)
        bits = [why]
        if stars and "star" not in why:
            bits.append(f"{out} out")
        elif stars:
            bits = [f"{out} out"]
        print(f"- **{pl.name}** ({pos(pl)}, {lg.pro_abbrev[pl.pro_team]}, form {pl.form:.1f}): about **+{gain:.0f} FP/G** "
              f"possible · " + " · ".join(bits) + f" · {pl.owned:.0f}% owned{inj(pl)}")


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
    print("\n_FP per week · Pace = season rate, L7 = last 7 days, Roster = roster on current form · arrows vs yesterday._")


def nightly_body(lg, a):
    """Morning report in markdown: overview + outlook, matchup grid (Mondays: last week's final and the
    new week's preview), roster moves, power rankings. {{OVERVIEW}} is for the reader to fill in."""
    me, opp = CONFIG["my_team_id"], lg.opponent_id()
    try:
        rec = recap_data(lg, lg.today - dt.timedelta(days=1))
    except Exception as exc:   # noqa: BLE001 - the report is still useful without last night's recap
        health.warn(f"last night's box scores unavailable ({type(exc).__name__}: {exc})", source="espn")
        rec = None
    if rec:
        with health.section("Actuals save", quiet=True):
            tracking.save_actuals(rec)
    snap = None
    if rec:
        with health.section("Yesterday's snapshot", quiet=True):
            snap = tracking.load_snapshot(rec["day"])
            if snap is None:
                health.warn(f"no projection snapshot saved for {rec['day']}; last night's projections were rebuilt from "
                            f"current rosters and the week comparison is skipped", source="state")
    p = lg.win_probability(me, opp)
    print(f"# {lg.now:%a %b %-d, %Y · %-I:%M %p} ET")
    if lg.scoring_mismatch:
        print(f"\n!! League scoring differs from the confirmed table: {lg.scoring_mismatch}")
    proj = {tid: lg.week_projection(lg.roster(tid), tid) for tid in (me, opp)}
    decided = week_decided(lg, me, opp, proj)
    if decided:
        print(f"\n> {decided[1]}")
    label = DECIDED_LABEL[decided[0]] if decided else outlook(p)
    was = f", {snap['win_prob']:.0%} yesterday" if snap and snap["period"] == lg.matchup_period else ""
    print(f"\n{{{{OVERVIEW}}}} **Outlook: {label}** ({p:.0%} win chance{was})")

    # Today: points already scored in started games + best lineup for the games still to come.
    sp_today = lg.date_sp.get(lg.today)
    today = {tid: lg.points_so_far(tid).get(sp_today, 0.0) + lg.day_projection(lg.roster(tid), lg.today)[0]
             for tid in (me, opp)}
    with health.section("Matchup"):
        if rec and rec["final"]:
            week_final_section(lg, rec, snap, proj, today, me, opp)
        else:
            matchup_section(lg, rec, snap, proj, today, me, opp)

    with health.section("Season picture"):
        season_section(lg, p)
    if POLICY["report_lookahead"]:
        with health.section("Schedule look-ahead"):
            lookahead_section(lg)
    with health.section("IR watch"):
        ir_section(lg)
    with health.section("News & rest watch"):
        news_section(lg, me, opp)
    with health.section("Roster moves"):
        roster_moves(lg, a, decided)
    with health.section("Opportunity watch"):
        opportunity_section(lg)
    with health.section("Snapshot save", quiet=True):
        tracking.save_snapshot(lg, proj, today, p, (me, opp))
    with health.section("Power rankings"):
        power_rankings_section(lg, me)


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
