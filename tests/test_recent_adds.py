import datetime as dt
import unittest
from unittest import mock

from fbgm import espn
from fbgm.model import ET, League


class RecentAdds(unittest.TestCase):
    """Flex pool = players we added in the last 7 days; ESPN returns one scoring period of transactions per request."""

    @staticmethod
    def txn(tid, team, kind, when, items):
        ms = int(dt.datetime.combine(when, dt.time(22, 5), ET).timestamp() * 1000)
        return {"id": tid, "teamId": team, "type": kind, "status": "EXECUTED", "proposedDate": ms,
                "items": [{"type": k, "playerId": p} for k, p in items]}

    def adds(self, by_period, today=dt.date(2026, 10, 30)):
        asked = []

        def fake_league(*views, scoring_period=None):
            asked.append(scoring_period)
            return {"transactions": by_period.get(scoring_period, [])}
        lg = League.__new__(League)
        lg.now, lg.today = dt.datetime.combine(today, dt.time(2, 18), ET), today
        lg.date_sp = {today: 11}
        with mock.patch.object(espn, "league", fake_league):
            return lg.recent_adds(), asked

    def test_adds_from_earlier_periods_count(self):
        d = dt.date(2026, 10, 29)
        out, asked = self.adds({10: [self.txn(1, 31, "FREEAGENT", d, [("ADD", 5), ("DROP", 6)])]})
        self.assertEqual(sorted(out), [5])
        self.assertEqual(asked, list(range(4, 12)))      # the last 7 periods plus today's

    def test_other_teams_drops_and_old_adds_are_ignored(self):
        d = dt.date(2026, 10, 29)
        out, _ = self.adds({
            10: [self.txn(1, 27, "FREEAGENT", d, [("ADD", 7)]),              # another team's add
                 self.txn(2, 31, "FREEAGENT", d, [("DROP", 8)]),             # our drop
                 self.txn(3, 31, "ROSTER", d, [("ADD", 9)])],                # a lineup move, not a pickup
            4: [self.txn(4, 31, "FREEAGENT", dt.date(2026, 10, 15), [("ADD", 10)])]})   # older than 7 days
        self.assertEqual(out, {})

    def test_same_transaction_in_two_periods_is_counted_once(self):
        d = dt.date(2026, 10, 29)
        t = self.txn(1, 31, "FREEAGENT", d, [("ADD", 5)])
        out, _ = self.adds({10: [t], 11: [t]})
        self.assertEqual(sorted(out), [5])


if __name__ == "__main__":
    unittest.main()
