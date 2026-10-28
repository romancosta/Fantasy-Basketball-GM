"""Pre-tip lineup check: before today's games lock, is anyone in the wrong slot, and who could still sit?
Quiet when nothing needs doing. The nightly report is read in the morning; this covers the hours before tip-off,
when late scratches and game-time decisions are known."""
import datetime as dt
import re

from .config import BENCH, IR, POLICY, SLOT_NAMES
from .fmt import inj

# Headlines about today's availability worth showing for a starter.
TODAY_NEWS = re.compile(r"out|inactive|scratch|questionable|doubtful|game-time|probable|available|will play|"
                        r"will not play|won't play|sidelined|minutes restriction|rest", re.I)


def day_value(lg, pl, day):
    """Expected FP on `day`: rate x availability x chance he isn't sitting that night (rest or news ruling)."""
    return pl.expected * lg.rest_factor(pl, day)


def tip_str(lg, pl, day):
    t = lg.game_start(pl, day)
    return f"{t:%-I:%M %p}" if t else "no game"


def minutes_to(lg, t):
    return int((t - lg.now).total_seconds() // 60)


def lineup_changes(lg, day):
    """([(player, from_slot, to_slot)], total FP gain). Only moves that matter: a player with a game today changing
    slot, or a starter with no usable game today going to the bench. Locked players never move."""
    roster = lg.roster()
    value = lambda pl: day_value(lg, pl, day)   # noqa: E731
    full = lg.full_lineup(roster, day, value)
    moves = []
    for pl, slot in full.items():
        if slot == pl.lineup_slot or pl.lineup_slot == IR:
            continue
        plays = lg.plays(pl, day) and value(pl) > 0
        starting_now = pl.lineup_slot not in (BENCH, IR, None)
        if plays or (starting_now and slot == BENCH):
            moves.append((pl, pl.lineup_slot, slot))
    def total(assign):
        return sum(value(pl) for pl, s in assign.items() if s not in (BENCH, IR) and lg.plays(pl, day))
    current = {pl: pl.lineup_slot for pl in roster}
    return moves, total(full) - total(current), full


def risky_starters(lg, day, full):
    """Starters (in the best lineup) who could still not play: not fully healthy, or a likely rest night. Only
    listed when a bench player with an unlocked game could take his slot - with no cover there is nothing to decide."""
    out = []
    bench = [p for p in full if full[p] == BENCH and lg.plays(p, day) and not lg.locked(p, day)
             and day_value(lg, p, day) > 0]
    for pl, slot in full.items():
        if slot in (BENCH, IR) or not lg.plays(pl, day) or lg.locked(pl, day) or day_value(lg, pl, day) <= 0:
            continue
        if not any(slot in b.slots for b in bench):
            continue
        notes = []
        if pl.availability < 1:
            notes.append(f"{pl.injury.replace('_', '-').title()} ({pl.availability:.0%} to play)")
        chance = lg.rest_chance(pl, day)
        if POLICY["rest_flag"] <= chance < 1:
            notes.append(f"{chance:.0%} chance of a rest night")
        news = next((n for n in lg.news(pl)[:1] if TODAY_NEWS.search(n.get("headline", ""))), None)
        if news:
            when = dt.datetime.fromisoformat(news["published"].replace("Z", "+00:00"))
            if when >= lg.now - dt.timedelta(hours=POLICY["pretip_news_hours"]):
                notes.append(f"news: {news['headline'][:140]}")
        if notes:
            out.append((pl, slot, notes))
    return out


def drop_candidate(lg, day, full, exclude):
    """Who we could cut for a pickup without hurting tonight or the core: a flex-pool player or a bench player with
    no game tonight - never a player holding a starting slot (even an injured one). Lowest rest-of-season rate first; None if no such player."""
    idle_bench = [p for p in lg.roster() if p.lineup_slot == BENCH and not lg.plays(p, day)]
    starting = {p for p, s in full.items() if s not in (BENCH, IR)}   # incl. an injured core player holding a slot
    pool = {p for p in lg.flex_pool() + idle_bench if p not in exclude | starting and p.lineup_slot != IR}
    return min(pool, key=lambda p: p.rate) if pool else None


def dead_slots(lg, day, full):
    """[(player, slot, free agent, who to drop, FP the pickup adds tonight)] for starters in the best lineup who can't
    play tonight (OUT, or ruled out for the game) with nobody on the bench to cover. Reported only when a free
    agent with an unlocked game would add at least pretip_min_gain FP AND we have someone we'd really let go;
    otherwise there is nothing worth doing (a star sitting out isn't a drop/add), so no alert."""
    out = []
    pool = sorted((p for p in lg.free_agents if p.status == "FREEAGENT" and lg.plays(p, day) and not lg.locked(p, day)
                   and p.availability >= POLICY["add_min_availability"] and p.gp > 0), key=lambda p: -p.form)
    taken, dropped = set(), set()
    for pl, slot in full.items():
        if slot in (BENCH, IR) or not lg.plays(pl, day) or lg.locked(pl, day) or day_value(lg, pl, day) > 0:
            continue
        fa = next((p for p in pool if slot in p.slots and p not in taken), None)
        gain = day_value(lg, fa, day) if fa else 0.0
        drop = drop_candidate(lg, day, full, exclude={pl} | dropped)
        if fa and drop and gain >= POLICY["pretip_min_gain"]:
            taken.add(fa)
            dropped.add(drop)
            out.append((pl, slot, fa, drop, gain))
    return out


def returning_from_ir(lg, day):
    """IR-slot players ESPN no longer lists as OUT who have a game today: they probably need to leave IR."""
    return [pl for pl in lg.roster() if pl.lineup_slot == IR and pl.availability > 0 and lg.plays(pl, day)
            and not lg.locked(pl, day)]


def pretip(lg):
    """(status, lines). status: 'OK' (nothing to do), 'WATCH' (no change needed, but a starter may sit), 'ACTION'
    (change your lineup now), 'PICKUP' (lineup is set; an optional add would earn points), 'NONE' (no unlocked games today)."""
    day = lg.today
    unlocked = [pl for pl in lg.roster() if pl.lineup_slot != IR and lg.plays(pl, day) and not lg.locked(pl, day)]
    if not unlocked:
        return "NONE", ["no unlocked games left for your roster today"]
    first = min(lg.game_start(pl, day) for pl in unlocked)
    moves, gain, full = lineup_changes(lg, day)
    if gain < POLICY["pretip_min_gain"]:
        # Reshuffling for a few FP isn't worth an alert: judge the lineup as it stands now.
        moves, full = [], {pl: pl.lineup_slot for pl in lg.roster()}
    ir_ready = returning_from_ir(lg, day)
    risks = risky_starters(lg, day, full)
    dead = dead_slots(lg, day, full)
    head = f"first unlocked tip {first:%-I:%M %p} ET ({minutes_to(lg, first)} min)"
    lines = []
    if moves:
        lines.append(f"Lineup changes on ESPN (worth about {gain:+.0f} FP):")
        for pl, frm, to in sorted(moves, key=lambda m: m[2] != BENCH):
            why = "" if to != BENCH else f" ({'OUT' if pl.availability == 0 else 'no usable game'} today)"
            lines.append(f"  - {pl.name}: {SLOT_NAMES.get(frm, '?')} -> {SLOT_NAMES[to]}"
                         f"{why}{'' if to == BENCH else f' · {tip_str(lg, pl, day)} · proj {day_value(lg, pl, day):.0f}'}")
    for pl, slot, fa, drop, add in dead:
        why = "ruled out for tonight" if lg.rest_chance(pl, day) >= 1 else "OUT"
        lines.append(f"Optional pickup: {pl.name} ({SLOT_NAMES[slot]}) is {why} with no bench cover. +{fa.name} / "
                     f"-{drop.name} adds about {add:.0f} FP tonight (form {fa.form:.1f}, {tip_str(lg, fa, day)}{inj(fa)}).")
    for pl in ir_ready:
        lines.append(f"Move {pl.name} off IR: ESPN lists him {pl.injury.replace('_', '-').title()} and he plays today "
                     f"({tip_str(lg, pl, day)}); needs an open roster spot.")
    if risks:
        lines.append("Starters who might not play (check status before their tip):")
        for pl, slot, notes in sorted(risks, key=lambda r: lg.game_start(r[0], day)):
            lines.append(f"  - {pl.name} ({SLOT_NAMES[slot]}, {tip_str(lg, pl, day)}): " + "; ".join(notes) + inj(pl))
    status = "ACTION" if (moves or ir_ready) else "PICKUP" if dead else "WATCH" if risks else "OK"
    return status, [head] + lines if lines else [head]


def cmd_pretip(lg, a):
    status, lines = pretip(lg)
    label = {"OK": "PRETIP OK: nothing to change", "WATCH": "PRETIP WATCH: lineup is set, some starters are at risk",
             "ACTION": "PRETIP ACTION: change your lineup",
             "PICKUP": "PRETIP PICKUP: optional add, lineup itself is set", "NONE": "PRETIP OK"}[status]
    print(f"{label} · {lg.now:%a %m/%d %-I:%M %p} ET")
    for ln in lines:
        print(ln)
