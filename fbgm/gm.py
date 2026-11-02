"""CLI: python3 -m fbgm <command> [options]"""
import argparse
import datetime as dt
import sys
import traceback

from . import espn
from .config import BENCH, CONFIG, IR, POLICY, SLOT_NAMES
from .fmt import f1, inj, short_name
from .model import League, fantasy_points


def pos(pl):
    return "/".join(SLOT_NAMES[s] for s in sorted(pl.slots) if s <= 4) or "-"


def short(pl):
    return short_name(pl.name)


def sos_str(lg, pl):
    f = lg.sos(pl)
    return "  -" if f is None else f"{f:4.2f}"


def opp_list(lg, pl):
    return ", ".join(f"{d:%a} {lg.pro_abbrev[lg.opponent[(pl.pro_team, d)]]} {lg.matchup_factor(pl, d):.2f}"
                     for d in lg.remaining_games(pl)) or "no games left"


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
            notes.append("STREAM")
        if p.underperforming:
            notes.append("UNDERPERFORMING")
            under += 1
        if p.availability < 1:
            notes.append(p.injury)
        print(f"{p.name[:24]:24} {pos(p):9} {p.rate:5.1f} {f1(p.season_fpg):>5} {f1(p.last15_fpg):>5} "
              f"{p.prior:5.1f} {p.gp:3} {lg.games_left(p):3}  {' '.join(notes)}")
    mode = a.mode or POLICY["mode"]
    print(f"\nMode: {mode}. Core = the top {POLICY['core_size'][mode]} by rate; STREAM = the streaming spots we rotate daily.")
    if mode == "conservative" and under >= POLICY["aggressive_trigger"]:
        print(f"!! {under} underperformers -> consider --mode aggressive")


def cmd_swap(lg, a):
    header(lg)
    add = find(lg, a.add, lg.free_agents)
    drop = find(lg, a.drop, lg.roster())
    sw = lg.evaluate_swap(add, drop)
    wk, starts = sw.gain, sw.starts
    print(f"\nAdd  {add.name:24} form {add.form:5.1f}  rate {add.rate:5.1f}  games left {lg.games_left(add)}  "
          f"({'waivers, usable ' + str(lg.available_date(add)) if add.status == 'WAIVERS' else 'free agent'}){inj(add)}")
    print(f"Drop {drop.name:24} form {drop.form:5.1f}  rate {drop.rate:5.1f}  games left {lg.games_left(drop)}{inj(drop)}")
    print(f"Matchups  add: {opp_list(lg, add)} (SOS {sos_str(lg, add).strip()})")
    print(f"         drop: {opp_list(lg, drop)} (SOS {sos_str(lg, drop).strip()})")
    print(f"Next game day{'s' * (len(sw.days) > 1)}: {gain_str(sw)} on current form | {starts_str(starts)} | "
          f"ROS rate {add.rate - drop.rate:+.1f} FP/G")
    print(f"By day: {days_str(sw.days)}" + (f" (moving now: {days_str(sw.now_days)} = {sw.now_gain:+.0f})" if sw.wait else ""))
    when = timing_str(lg, sw, add, drop)
    v = verdict(lg, add, drop, wk, starts, a.mode, sw)
    if v.startswith("MOVE") and when:
        v = ("MOVE AFTER TONIGHT" if sw.wait else "MOVE") + v[4:] + f"; {when}"
    print("Verdict: " + v)


def next_day_str(lg, sw, add, drop):
    """The move's effect on the game day after the one it's judged on, e.g. 'Mon −19 if not refilled' ('' if none)."""
    if not sw.days:
        return ""
    nxt = lg.game_days(sw.days[-1][0] + dt.timedelta(days=1), 1)
    if not nxt:
        return ""
    g = lg.swap_days(add, drop, lg.roster(), nxt)[0][1]
    if round(g) == 0:
        return ""
    return f"{nxt[0]:%a} −{-g:.0f} if not refilled" if g < 0 else f"{nxt[0]:%a} +{g:.0f} too"


def gain_str(sw):
    """'+35 FP Mon' (or 'Mon-Tue' for a longer horizon): the move's gain over the game days it is judged on."""
    if not sw.days:
        return f"{sw.gain:+.0f} FP (no game day left)"
    first, last = sw.days[0][0], sw.days[-1][0]
    return f"{sw.gain:+.0f} FP {first:%a}" + (f"-{last:%a}" if last != first else "")


def days_str(days):
    """Day-by-day FP gain of a swap, e.g. 'Sat: −35, Sun: +40' (days that don't change are left out)."""
    shown = [(d, g) for d, g in days if round(g) != 0]
    return ", ".join(f"{d:%a}: {'−' if g < 0 else '+'}{abs(g):.0f}" for d, g in shown) or "no change"


def timing_str(lg, sw, add, drop):
    """When to make the move, or '' when it can be made now and counts from today."""
    first = f"{short(add)} first plays {sw.add_first:%a %m/%d}" if sw.add_first else f"{short(add)} has no game left"
    if sw.wait:
        t = lg.game_start(drop, lg.today)
        return f"drop after {short(drop)}'s game tonight ({t:%-I:%M %p}), {first}"
    if sw.effective > lg.today:
        why = "waiver claim clears" if add.status == "WAIVERS" and sw.effective == lg.available_date(add) else "counts from"
        return f"{why} {sw.effective:%a %m/%d}, {first}"
    return ""


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


def verdict(lg, add, drop, wk, starts, mode=None, sw=None):
    kind = drop_kind(lg, add, drop, lg.flex_pool(mode))
    if kind is None:
        return (f"NO - {drop.name} is core and {add.name} isn't a proven upgrade "
                f"({POLICY['core_upgrade_min_gp']}+ GP, rate +{POLICY['core_upgrade_rate_gain']:.0f}, form at least as good)")
    if not starts:
        return f"NO - {add.name} can't crack the starting lineup (positions/schedule)"
    when = gain_str(sw) if sw else f"{wk:+.0f} FP"
    if wk < POLICY["stream_min_gain"]:
        return f"NO - only {when} (bar {POLICY['stream_min_gain']:.0f})"
    why = {"flex": "streaming spot", "outlook": "core outlook changed", "upgrade": "proven upgrade over core"}[kind]
    return f"MOVE - {why}, {when} on current form"


def plan_moves(lg, a):
    """Best streaming moves on current form over the next game day(s) (POLICY stream_horizon_days), respecting lineup
    slots. Returns (streaming spots, hurt core, [(FP, starts, add, drop, swap)], alternatives for the first move)."""
    flex = lg.flex_pool(a.mode)
    roster = list(lg.roster())
    days = lg.plan_days()
    hurt = [p for p in roster if p not in flex and p.lineup_slot != IR and core_drop_ok(lg, p)]
    drops = [p for p in roster if p.lineup_slot != IR]
    cands = sorted(lg.free_agents, key=lambda p: -p.form)[:40]
    # Streamers: also consider the best schedule fits over the days a move could be judged on.
    cands += sorted(lg.free_agents, key=lambda p: -p.form * p.availability * sum(
        1 for d in days if lg.plays(p, d) and not lg.locked(p, d)))[:20]
    # Schedule fits: games on days our lineup has an open slot the add could fill.
    holes = {d: open_slots(lg, roster, d) for d in days}
    cands += sorted(lg.free_agents, key=lambda p: -p.form * p.availability * sum(
        1 for d in days if holes[d] & p.slots and lg.plays(p, d) and not lg.locked(p, d)))[:20]
    cands = [p for p in {c.id: c for c in cands}.values()
             if p.availability >= POLICY["add_min_availability"] and p.gp > 0]

    week_end = lg.week_days[-1]
    skipped = []

    def rank(roster, drops, cands):
        rows = []
        for add in cands:
            for drop in drops:
                if drop_kind(lg, add, drop, flex) is None:
                    continue
                sw = lg.evaluate_swap(add, drop, roster)
                if not (sw.starts and sw.gain >= POLICY["stream_min_gain"]):
                    continue
                sw.zone, sw.impact = impact_zone(lg, sw, add, drop, week_end)
                if sw.zone == "skip":
                    skipped.append(sw)
                    continue
                rows.append((sw.gain, sw.starts, add, drop, sw))
        # Earliest game day first (today's moves can't wait), then the biggest gain.
        rows.sort(key=lambda r: (r[4].days[0][0] if r[4].days else dt.date.max, -r[0]))
        # Neck and neck with the best move for that day: prefer one that can be made now, then the easier schedule.
        near = [r for r in rows if r[4].days[:1] == rows[0][4].days[:1]
                and r[0] >= rows[0][0] - POLICY["tie_week"]] if rows else []
        if near:
            best = max(near, key=lambda r: (not r[4].wait, lg.sos(r[2]) or 1.0, r[0]))
            rows.remove(best)
            rows.insert(0, best)
        return rows

    # Best single move first; then re-plan on the roster with that move applied from the day it takes effect.
    plan, alts, cur, left = [], [], {d: roster for d in days}, list(drops)
    while True:
        rows = rank(cur, left, cands)
        if not rows:
            break
        best = rows[0]
        plan.append(best)
        if len(plan) == 1:
            alts = [r for r in rows[1:] if r[3] is best[3]][: a.n]
        cur = {d: [p for p in r if p is not best[3]] + [best[2]] if d >= best[4].effective else r
               for d, r in cur.items()}
        left = [p for p in left if p is not best[3]]
        cands = [p for p in cands if p is not best[2]]
    # Nothing this week can move the result: only clear upgrades are worth making.
    lg.moves_skipped = len(skipped)
    if lg.plan_days() and lg.plan_days()[0] <= week_end and lg.week_dead():
        plan += upgrade_moves(lg, roster, {r[2] for r in plan}, {r[3] for r in plan})
    used = {r[2] for r in plan}
    return flex, hurt, plan, [r for r in alts if r[2] not in used]


def impact_zone(lg, sw, add, drop, week_end):
    """('recommend' | 'optional' | 'skip', win-chance impact or None) for a streaming move (see POLICY impact_*)."""
    sw.new_week = bool(sw.days) and sw.days[0][0] > week_end
    if not sw.days or sw.new_week:
        return "recommend", None                      # judged on next week's games: the new week is wide open
    imp = lg.move_impact(sw.gain)
    if imp is None or imp >= POLICY["impact_recommend"]:
        return "recommend", imp
    if imp >= POLICY["impact_skip"] and not next_day_str(lg, sw, add, drop).endswith("if not refilled"):
        return "optional", imp
    return "skip", imp


def upgrade_moves(lg, roster, used_adds, used_drops):
    """Clear rest-of-season upgrades (proven_upgrade) for anyone on the active roster, best rate gain first, each add and
    drop used once. The add must fit the lineup (a start on one of his next 3 game days once the move is in effect)."""
    fas = [p for p in lg.free_agents if p.availability >= POLICY["add_min_availability"] and p.gp > 0
           and p not in used_adds]
    pairs = []
    for drop in roster:
        if drop.lineup_slot == IR or drop in used_drops:
            continue
        for add in fas:
            if proven_upgrade(add, drop):
                pairs.append((add.rate - drop.rate, add, drop))
    out, adds, drops = [], set(), set()
    for _, add, drop in sorted(pairs, key=lambda x: -x[0]):
        if add in adds or drop in drops:
            continue
        sw = lg.evaluate_swap(add, drop, roster)
        if not any(slot is not None for _, _, slot in lg.swap_days(add, drop, roster, lg.game_days(sw.effective, 3))):
            continue
        sw.zone, sw.impact = "upgrade", None
        out.append((sw.gain, sw.starts, add, drop, sw))
        adds.add(add)
        drops.add(drop)
    return out


def zone_tag(sw):
    """' · win chance +2.3 pts' / ' · new week' for a recommended or optional move, '' otherwise."""
    if getattr(sw, "zone", None) not in ("recommend", "optional"):
        return ""
    if getattr(sw, "new_week", False):
        return " · new week"
    return "" if sw.impact is None else f" · win chance +{100 * sw.impact:.1f} pts"


def open_slots(lg, roster, day):
    """Starting slots our best lineup leaves empty on `day` (slots held by started games count as filled)."""
    slots = list(lg.slots)
    for p in roster:
        if day == lg.today and lg.locked(p, day) and p.lineup_slot in slots:
            slots.remove(p.lineup_slot)
    for s in lg.day_projection(roster, day)[1].values():
        slots.remove(s)
    return set(slots)


def bench_calls(lg, roster, day):
    """Players with a game on `day` who don't make the best lineup: [(player, FP, reason, holders of his slots, lowest
    starter projecting below him, that starter's FP)], best first. reason is
    'logjam' when he only fits slots held by better players while someone worse starts elsewhere (or a slot stays
    empty), else 'lowest'. Locked games are left alone."""
    _, lineup = lg.day_projection(roster, day)
    value = {p: p.expected * lg.rest_factor(p, day) for p in roster}
    out = []
    for p in roster:
        if (p.lineup_slot == IR or p in lineup or not lg.plays(p, day) or value[p] <= 0
                or (day == lg.today and lg.locked(p, day))):
            continue
        holders = sorted((q for q, s in lineup.items() if s in p.slots), key=lambda q: -value[q])
        worse = [q for q in lineup if value[q] < value[p]]
        empty = len(lineup) < len(lg.slots)
        low = min(worse, key=lambda q: value[q]) if worse else None
        out.append((p, value[p], "logjam" if worse or empty else "lowest", holders, low, value.get(low)))
    return sorted(out, key=lambda r: -r[1])


def bench_str(lg, calls):
    """'Lillard 46 (PG/G held by SGA, Murray; Barrett 38 starts) · Kuminga 36 (lowest projection)'."""
    bits = []
    for p, v, why, holders, worse, worse_v in calls:
        if why == "logjam":
            held = ", ".join(short(q) for q in holders[:3]) or "nobody"
            tail = f"; {short(worse)} {worse_v:.0f} starts" if worse else "; a slot he can't fill stays empty"
            where = [SLOT_NAMES[s] for s in sorted(p.slots) if s <= 4] + (["G"] if 5 in p.slots & set(lg.slots) else [])
            bits.append(f"{short(p)} {v:.0f} ({'/'.join(where)} held by {held}{tail})")
        else:
            bits.append(f"{short(p)} {v:.0f} (lowest projection)")
    return " · ".join(bits)


def move_tag(lg, r, flex):
    return {"flex": "", "outlook": " (core, outlook changed)",
            "upgrade": f" (core, proven upgrade: rate +{r[2].rate - r[3].rate:.1f} FP/G)"}[drop_kind(lg, r[2], r[3], flex)]


def cmd_advise(lg, a, quiet_header=False):
    """Best streaming moves for the next game day, on current form, respecting lineup slots."""
    if not quiet_header:
        header(lg)
    flex, hurt, plan, alts = plan_moves(lg, a)
    if getattr(lg, "moves_skipped", 0) and lg.week_dead():
        print(f"\nWeek {lg.matchup_period} can't be moved by today's moves: only clear upgrades are shown.")
    print("\nStreaming spots: " + (", ".join(f"{p.name} (form {p.form:.1f})" for p in flex) or "none")
          + (f"  | core with changed outlook: {', '.join(f'{p.name}{inj(p)}' for p in hurt)}" if hurt else ""))

    def show(r):
        wk, starts, add, drop, sw = r
        when = timing_str(lg, sw, add, drop)
        label = {"optional": "OPTIONAL", "upgrade": "UPGRADE"}.get(getattr(sw, "zone", None), "MOVE")
        if sw.wait:
            label = "WAIT" if label == "MOVE" else label + " (after tonight)"
        extra = (f"rate {add.rate:.1f} vs {drop.rate:.1f}" if getattr(sw, "zone", None) == "upgrade"
                 else gain_str(sw) + zone_tag(sw))
        print(f"  {label} +{add.name} / -{drop.name}{move_tag(lg, r, flex)}: {extra}, form {add.form:.1f} vs {drop.form:.1f}, "
              f"{starts_str(starts)}, SOS {sos_str(lg, add).strip()}"
              f"{' (waivers)' if add.status == 'WAIVERS' else ''}{inj(add)}")
        nd = next_day_str(lg, sw, add, drop)
        if len(sw.days) > 1 or when or nd:
            print(f"    by day: {days_str(sw.days)}" + (f" · next: {nd}" if nd else "") + (f" · {when}" if when else ""))

    if not plan:
        print("No clear upgrade available. Hold." if getattr(lg, "moves_skipped", 0) and lg.week_dead()
              else "No move clears the bar. Hold.")
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
    print(f"\nLast {a.days} days:")
    for t in reversed(lg.transactions(a.days)):
        pl = lg.players.get(t["player"])
        extra = f" (rate {pl.rate:.1f}, now {'FA' if pl.status != 'ONTEAM' else 'rostered'})" if pl else ""
        print(f"  {t['when']:%a %m/%d %I:%M%p} {lg.team_names.get(t['team'], t['team']):26} {t['kind']:4} "
              f"{pl.name if pl else t['player']}{extra}")


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
    sub.add_parser("pretip", help="lineup check before today's games lock (quiet when nothing to do)")
    p = sub.add_parser("evening", help="after tonight's tips: streaming moves for the next game day (quiet when none)")
    p.add_argument("--n", type=int, default=3)
    sub.add_parser("accuracy", help="how much projected-vs-actual data has been captured")
    p = sub.add_parser("watchdog", help="check that last night's state was committed (needs git only)")
    p.add_argument("--branch", default="nightly-state")
    a = ap.parse_args(argv)
    if a.cmd == "watchdog":
        from .watchdog import cmd_watchdog
        sys.exit(cmd_watchdog(a))
    if a.cmd == "accuracy":
        from .tracking import cmd_accuracy
        sys.exit(cmd_accuracy(a))
    espn.FRESH = a.fresh
    try:
        lg = League(dt.date.fromisoformat(a.today) if a.today else None)
        from . import report   # imports this module, so load it lazily
        if a.cmd == "pretip":
            from .pretip import cmd_pretip as cmd
        elif a.cmd == "evening":
            from .evening import cmd_evening as cmd
        else:
            cmd = getattr(report, f"cmd_{a.cmd}", None) or globals()[f"cmd_{a.cmd}"]
        cmd(lg, a)
    except Exception as exc:   # noqa: BLE001 - one plain error line for the routine, full trace on stderr
        traceback.print_exc()
        print(f"FBGM ERROR ({a.cmd}): {type(exc).__name__}: {exc}")
        sys.exit(1)
