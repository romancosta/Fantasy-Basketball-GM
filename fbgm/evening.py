"""Evening check, run after tonight's games tip: streaming moves for the next game day, made tonight.

The Godfather makes most of his adds between 6:30 and 11pm, after the player he drops has played, picking up someone who
plays tomorrow. This is that window. Quiet ('EVENING OK') when no move clears the bar."""
import datetime as dt

from .config import CONFIG, POLICY
from .gm import plan_moves


def evening(lg, a):
    """(status 'OK' or 'MOVES', [lines])."""
    from . import report   # report imports gm; load lazily like the CLI does
    nxt = lg.game_days(lg.today + dt.timedelta(days=1), 1)
    if not nxt:
        return "OK", ["EVENING OK · no NBA games scheduled ahead"]
    target = nxt[0]
    flex, _, plan, alts = plan_moves(lg, a)
    # Only moves judged on the next game day; anything still about tonight's late games is the pre-tip check's job.
    plan = [r for r in plan if r[4].days and r[4].days[0][0] == target]
    alts = [r for r in alts if r[4].days and r[4].days[0][0] == target] if plan else []
    if plan and target <= lg.week_days[-1] and week_is_decided(lg):
        return "OK", [f"EVENING OK · week {lg.matchup_period} is decided; no moves needed for {target:%a %m/%d}"]
    if not plan:
        return "OK", [f"EVENING OK · no streaming move adds {POLICY['stream_min_gain']:.0f}+ FP on {target:%a %m/%d}"]
    first = min((t for g in lg.games.values() for d, t in g.items() if d == target), default=None)
    lines = [f"EVENING MOVES · {len(plan)} for {target:%a %m/%d}" + (f" (first tip {first:%-I:%M %p})" if first else "")]
    lines += report.move_lines(lg, plan, alts, flex)
    bench = report.bench_line(lg, report.after_moves(lg, plan, target), target, f"{target:%a} (after these moves)")
    if bench:
        lines.append(bench)
    lines.append("- ↻ Hit Auto-set on ESPN after making these moves.")
    return "MOVES", lines


def week_is_decided(lg):
    """The nightly's stress test: this week's result can't change, so this week's moves don't matter."""
    from . import report
    me, opp = CONFIG["my_team_id"], lg.opponent_id()
    proj = {tid: lg.week_projection(lg.roster(tid), tid) for tid in (me, opp)}
    return bool(report.week_decided(lg, me, opp, proj))


def cmd_evening(lg, a):
    a.mode = getattr(a, "mode", None)
    a.n = getattr(a, "n", 3)
    print("\n".join(evening(lg, a)[1]))
