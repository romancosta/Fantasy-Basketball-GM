import datetime as dt
import unittest
from types import SimpleNamespace as NS

from fbgm import lookahead
from fbgm.config import BENCH, IR

MON = dt.date(2026, 10, 26)      # week 2 starts Monday Oct 26


def day(n):
    return MON + dt.timedelta(days=n)


class P:
    def __init__(self, name, team, slot=0, fp=40.0):
        self.name, self.pro_team, self.lineup_slot, self.expected, self.slots = name, team, slot, fp, {0, 1}


def make_lg(games, today=day(2), period=2):
    games_by_team = {t: {day(n): None for n in days} for t, days in games.items()}
    lg = NS(games=games_by_team, today=today, matchup_period=period)
    lg.week_days = [day(i) for i in range(7)]
    lg.remaining_days = lambda: [d for d in lg.week_days if d >= lg.today]
    lg.week_end = lambda p: day(6) + dt.timedelta(weeks=p - period)
    lg.plays = lambda pl, d: d in lg.games[pl.pro_team]
    lg.games_left = lambda pl: sum(1 for d in lg.remaining_days() if lg.plays(pl, d))
    lg.day_projection = lambda roster, d: (sum(p.expected for p in roster if lg.plays(p, d)),
                                           {p: 0 for p in roster if lg.plays(p, d)})
    return lg


class Lookahead(unittest.TestCase):
    def setUp(self):
        # team 1: Mon Wed Fri this week (today = Wed) + 4 games next week; team 2: 2 games each week
        self.lg = make_lg({1: [0, 2, 4, 7, 8, 10, 12], 2: [1, 3, 8, 10]})

    def test_days_of(self):
        self.assertEqual(lookahead.days_of(self.lg, 0), [day(2), day(3), day(4), day(5), day(6)])
        self.assertEqual(lookahead.days_of(self.lg, 1), [day(7 + i) for i in range(7)])

    def test_player_games_this_week_counts_only_games_left(self):
        self.assertEqual(lookahead.player_games(self.lg, P("a", 1), 0), 2)    # Wed, Fri (Mon is past)
        self.assertEqual(lookahead.player_games(self.lg, P("a", 1), 1), 4)
        self.assertEqual(lookahead.player_games(self.lg, P("b", 2), 1), 2)

    def test_team_week_starts_and_fp(self):
        roster = [P("a", 1, fp=50), P("b", 2, fp=30)]
        starts, fp = lookahead.team_week(self.lg, roster, 1)
        self.assertEqual((starts, fp), (6, 4 * 50 + 2 * 30))

    def test_league_average_games(self):
        self.assertEqual(lookahead.league_avg_games(self.lg, 1), 3.0)

    def test_marks(self):
        self.assertEqual(lookahead.mark(4, 3.0), "4▲")
        self.assertEqual(lookahead.mark(2, 3.0), "2▼")
        self.assertEqual(lookahead.mark(3, 3.0), "3")

    def test_opponents_by_week(self):
        sched = [{"matchupPeriodId": p, "home": {"teamId": 31}, "away": {"teamId": 40 + p}} for p in (2, 3, 4, 9)] + \
                [{"matchupPeriodId": 3, "home": {"teamId": 5}, "away": {"teamId": 6}}]
        self.assertEqual(lookahead.opponents_by_week(sched, 31, 2, 3), {0: 42, 1: 43, 2: 44})

    def test_active_roster_skips_ir(self):
        lg = make_lg({1: [0]})
        lg.roster = lambda tid=None: [P("a", 1, 0), P("ir", 1, IR), P("bench", 1, BENCH)]
        self.assertEqual([p.name for p in lookahead.active_roster(lg)], ["a", "bench"])


if __name__ == "__main__":
    unittest.main()
