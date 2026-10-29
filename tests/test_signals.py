import datetime as dt
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from fbgm import signals
from fbgm.config import AVAILABILITY


def log(rows, labels=None):
    """A fake ESPN site gamelog with one regular-season category; rows = [(date, team, [stats...])]."""
    labels = labels or ["MIN", "FG", "FT", "REB", "AST", "BLK", "STL", "TO", "PTS"]
    events, evs = {}, []
    for i, (date, team, stats) in enumerate(rows):
        events[str(i)] = {"gameDate": f"{date}T00:00:00Z", "team": {"id": team}}
        evs.append({"eventId": str(i), "stats": stats})
    return {"labels": labels, "events": events,
            "seasonTypes": [{"displayName": "2025-26 Regular Season", "categories": [{"events": evs}]},
                            {"displayName": "2025-26 Postseason", "categories": [{"events": [
                                {"eventId": "x", "stats": ["1"] * len(labels)}]}]}]}


def row(minutes, fp_pts=10):
    # 10 pts, 4-8 FG, 2-2 FT, 5 reb, 3 ast, 1 blk, 1 stl, 2 to
    return [str(minutes), "4-8", "2-2", "5", "3", "1", "1", "2", str(fp_pts)]


class Parsing(unittest.TestCase):
    def test_proxy_fp(self):
        with mock.patch.object(signals.espn, "gamelog", return_value=log([("2026-01-02", 7, row(30))])):
            games = signals.games(1, 2026)
        self.assertEqual(len(games), 1)
        # 10 pts + 4 FGM + 2 FTM + 2.3 x 5 reb + 2 x (3 ast + 1 stl + 1 blk) - 2 x 2 to
        self.assertAlmostEqual(games[0]["fp"], 10 + 4 + 2 + 11.5 + 10 - 4)
        self.assertEqual((games[0]["MIN"], games[0]["team"], games[0]["date"]), (30.0, 7, dt.date(2026, 1, 2)))

    def test_postseason_is_ignored_and_games_sorted(self):
        rows = [("2026-02-01", 7, row(20)), ("2026-01-01", 7, row(30))]
        with mock.patch.object(signals.espn, "gamelog", return_value=log(rows)):
            games = signals.games(1, 2026)
        self.assertEqual([g["MIN"] for g in games], [30.0, 20.0])

    def test_missing_labels_or_fetch_error_gives_nothing(self):
        with mock.patch.object(signals.espn, "gamelog", return_value=log([("2026-01-02", 7, ["1"])], labels=["MIN"])):
            self.assertEqual(signals.games(1, 2026), [])
        with mock.patch.object(signals.espn, "gamelog", side_effect=OSError("down")):
            self.assertEqual(signals.games(1, 2026), [])


class Trend(unittest.TestCase):
    def test_minutes_trend(self):
        gs = [{"MIN": 20.0}] * 10 + [{"MIN": 30.0}] * 5
        self.assertEqual(signals.minutes_trend(gs), (30.0, 20.0))

    def test_too_few_games(self):
        self.assertIsNone(signals.minutes_trend([{"MIN": 20.0}] * 14))


class Estimate(unittest.TestCase):
    def test_no_signal(self):
        self.assertEqual(signals.estimate(30.0, (22.0, 21.0), 22.0, 0.0), (0.0, ""))

    def test_minutes_surge(self):
        gain, why = signals.estimate(30.0, (30.0, 20.0), 30.0, 0.0)
        self.assertGreater(gain, 3)
        self.assertIn("minutes 30 vs 20", why)

    def test_star_out_bench_vs_rotation(self):
        bench, why = signals.estimate(30.0, None, 18.0, 1.0)
        rotation, _ = signals.estimate(30.0, None, 28.0, 1.0)
        self.assertAlmostEqual(bench, 30 * 0.20)
        self.assertAlmostEqual(rotation, 30 * 0.10)
        self.assertEqual(why, "star teammate out")

    def test_doubtful_star_counts_partially_and_more_stars_cap_at_one(self):
        half, _ = signals.estimate(30.0, None, 18.0, 0.5)
        two, _ = signals.estimate(30.0, None, 18.0, 2.0)
        self.assertAlmostEqual(half, 30 * 0.20 * 0.5)
        self.assertAlmostEqual(two, 30 * 0.20)

    def test_takes_the_larger_signal_not_the_sum(self):
        both, _ = signals.estimate(30.0, (30.0, 20.0), 18.0, 1.0)
        surge, _ = signals.estimate(30.0, (30.0, 20.0), 18.0, 0.0)
        out, _ = signals.estimate(30.0, None, 18.0, 1.0)
        self.assertEqual(both, max(surge, out))


class P:
    def __init__(self, pid, team, form=30.0, rate=30.0, injury="ACTIVE", status="FREEAGENT"):
        self.id, self.pro_team, self.form, self.rate, self.gp = pid, team, form, rate, 10
        self.injury, self.status = injury, status

    @property
    def availability(self):
        return AVAILABILITY[self.injury]


class Opportunities(unittest.TestCase):
    def test_free_agent_with_star_out_is_found_and_others_are_not(self):
        star = P(1, 7, rate=50, injury="OUT", status="ONTEAM")
        fa_same_team = P(2, 7)
        fa_other_team = P(3, 8)
        lg = NS(free_agents=[fa_same_team, fa_other_team], players={p.id: p for p in (star, fa_same_team, fa_other_team)})
        flat = [{"MIN": 18.0, "fp": 30.0}] * 12
        with mock.patch.object(signals, "games", return_value=flat):
            found = signals.opportunities(lg, 2027)
        self.assertEqual([r[0].id for r in found], [2])
        self.assertAlmostEqual(found[0][1], 30 * 0.20)

    def test_nobody_when_there_is_no_signal(self):
        lg = NS(free_agents=[P(2, 7)], players={})
        with mock.patch.object(signals, "games", return_value=[{"MIN": 18.0, "fp": 30.0}] * 12):
            self.assertEqual(signals.opportunities(lg, 2027), [])


if __name__ == "__main__":
    unittest.main()
