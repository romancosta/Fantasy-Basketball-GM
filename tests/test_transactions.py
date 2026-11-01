import datetime as dt
import unittest
from unittest import mock

from fbgm import espn
from fbgm.model import ET, League


class Transactions(unittest.TestCase):
    """League adds/drops over a window; ESPN returns one scoring period of transactions per request."""

    @staticmethod
    def txn(tid, team, kind, when, items, minute=5):
        ms = int(dt.datetime.combine(when, dt.time(22, minute), ET).timestamp() * 1000)
        return {"id": tid, "teamId": team, "type": kind, "status": "EXECUTED", "proposedDate": ms,
                "items": [{"type": k, "playerId": p} for k, p in items]}

    def rows(self, by_period, days=7, today=dt.date(2026, 10, 30)):
        asked = []

        def fake_league(*views, scoring_period=None, ttl=None):
            asked.append(scoring_period)
            return {"transactions": by_period.get(scoring_period, [])}
        lg = League.__new__(League)
        lg.now, lg.today = dt.datetime.combine(today, dt.time(2, 18), ET), today
        lg.date_sp, lg.sp_date = {today: 11}, {11: today}
        with mock.patch.object(espn, "league", fake_league):
            out = lg.transactions(days)
        return [(r["team"], r["kind"], r["player"]) for r in out], asked

    def test_every_team_and_earlier_periods(self):
        d = dt.date(2026, 10, 29)
        out, asked = self.rows({10: [self.txn(1, 27, "FREEAGENT", d, [("ADD", 5), ("DROP", 6)])],
                                8: [self.txn(2, 31, "WAIVER", dt.date(2026, 10, 27), [("ADD", 7)])]})
        self.assertEqual(out, [(31, "ADD", 7), (27, "ADD", 5), (27, "DROP", 6)])
        self.assertEqual(asked, list(range(4, 12)))      # the last 7 periods plus today's

    def test_lineup_moves_and_old_moves_are_ignored_but_plain_drops_count(self):
        d = dt.date(2026, 10, 29)
        out, _ = self.rows({
            10: [self.txn(1, 27, "ROSTER", d, [("ADD", 9), ("LINEUP", 3)]),      # lineup move
                 self.txn(2, 27, "ROSTER", d, [("DROP", 8)])],                    # a plain drop
            4: [self.txn(3, 31, "FREEAGENT", dt.date(2026, 10, 15), [("ADD", 10)])]})   # older than 7 days
        self.assertEqual(out, [(27, "DROP", 8)])

    def test_same_transaction_in_two_periods_is_counted_once(self):
        t = self.txn(1, 31, "FREEAGENT", dt.date(2026, 10, 29), [("ADD", 5)])
        out, _ = self.rows({10: [t], 11: [t]})
        self.assertEqual(out, [(31, "ADD", 5)])

    def test_drop_and_readd_minutes_apart_cancel(self):
        d = dt.date(2026, 10, 29)
        out, _ = self.rows({10: [self.txn(1, 27, "ROSTER", d, [("DROP", 5)], minute=5),
                                 self.txn(2, 27, "FREEAGENT", d, [("ADD", 5)], minute=6),
                                 self.txn(3, 27, "FREEAGENT", d, [("ADD", 6)], minute=30)]})
        self.assertEqual(out, [(27, "ADD", 6)])


if __name__ == "__main__":
    unittest.main()
