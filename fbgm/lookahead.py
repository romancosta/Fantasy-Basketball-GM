"""Schedule look-ahead: how many games each player (and our lineup) has in the coming weeks, and how the weeks
compare with the opponents we'll face. Counts use today's injury statuses; this is for planning, not a forecast."""
import datetime as dt

from .config import IR, POLICY


def days_of(lg, offset):
    """The matchup week `offset` weeks from now: remaining days (not yet played) for offset 0, else its full week."""
    if offset == 0:
        return lg.remaining_days()
    end = lg.week_end(lg.matchup_period + offset)
    return [end - dt.timedelta(days=6 - i) for i in range(7)]


def player_games(lg, pl, offset):
    """Games pl has in that week; this week counts only games that haven't started."""
    if offset == 0:
        return lg.games_left(pl)
    return sum(1 for d in days_of(lg, offset) if lg.plays(pl, d))


def team_week(lg, roster, offset):
    """(starts, expected FP) from the best daily lineups across that week's days."""
    starts, fp = 0, 0.0
    for d in days_of(lg, offset):
        total, lineup = lg.day_projection(roster, d)
        starts += len(lineup)
        fp += total
    return starts, fp


def league_avg_games(lg, offset):
    days = days_of(lg, offset)
    teams = list(lg.games)
    return sum(sum(1 for d in days if d in lg.games[t]) for t in teams) / max(len(teams), 1)


def mark(games, avg):
    """▲ heavy week, ▼ light week for a player, against the league average that week."""
    if games >= avg + POLICY["lookahead_flag"]:
        return f"{games}▲"
    if games <= avg - POLICY["lookahead_flag"]:
        return f"{games}▼"
    return str(games)


def opponents_by_week(schedule, me, period, weeks):
    """{offset: opponent team id} for this week and the next `weeks`."""
    out = {}
    for m in schedule:
        off = m["matchupPeriodId"] - period
        if 0 <= off <= weeks and "away" in m and me in (m["home"]["teamId"], m["away"]["teamId"]):
            out[off] = m["away"]["teamId"] if m["home"]["teamId"] == me else m["home"]["teamId"]
    return out


def active_roster(lg, tid=None):
    return [p for p in lg.roster(tid) if p.lineup_slot != IR]
