import contextlib
import io
import datetime as dt
import unittest
from types import SimpleNamespace as NS

from fbgm import health

D = dt.date


class Health(unittest.TestCase):
    def setUp(self):
        health.reset()
        self.addCleanup(health.reset)

    def test_clean_run_renders_nothing(self):
        self.assertEqual((health.render(), health.banner()), ("", None))

    def test_warnings_deduplicate(self):
        health.warn("ESPN pool looks empty")
        health.warn("ESPN pool looks empty")
        self.assertEqual(health.issues(), ["- ⚠️ ESPN pool looks empty"])

    def test_failures_are_counted_per_source(self):
        for _ in range(3):
            health.failed("news feed", OSError("timeout"))
        self.assertEqual(health.issues(), ["- ⚠️ news feed: 3 requests failed, results may be incomplete "
                                           "(first error: OSError: timeout)"])
        self.assertIn("1 data issue ", health.banner())

    def test_section_contains_a_crash(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with health.section("IR watch"):
                raise KeyError("boom")
            print("still running")
        self.assertIn("## IR watch\n- ⚠️ Unavailable this run: KeyError: 'boom'", out.getvalue())
        self.assertIn("still running", out.getvalue())
        self.assertIn("Traceback", err.getvalue())
        self.assertIn("IR watch section failed", health.render())

    def test_section_passes_through_when_fine(self):
        with health.section("x"):
            pass
        self.assertEqual(health.issues(), [])


class CheckLeague(unittest.TestCase):
    def setUp(self):
        health.reset()
        self.addCleanup(health.reset)

    def lg(self, **kw):
        base = dict(roster=lambda: ["p"], players=dict.fromkeys(range(500)), today=D(2026, 10, 28),
                    date_sp={D(2026, 10, 28): 9}, matchup_period=2, espn_matchup_period=2, scoring_mismatch={},
                    opponent_id=lambda: 3)
        base.update(kw)
        return NS(**base)

    def test_healthy_league_is_silent(self):
        health.check_league(self.lg())
        self.assertEqual(health.issues(), [])

    def test_each_warning(self):
        health.check_league(self.lg(players={}, date_sp={}, espn_matchup_period=3, scoring_mismatch={4: (1, 2)}))
        text = health.render()
        for needle in ("pool is unusually small", "no scoring period", "date mapping disagrees", "scoring differs"):
            self.assertIn(needle, text)

    def test_espn_week_is_only_checked_once_it_has_rolled_over(self):
        health.check_league(self.lg(espn_matchup_period=None, matchup_period=3))
        self.assertEqual(health.issues(), [])

    def test_fatal_problems_raise(self):
        with self.assertRaises(RuntimeError):
            health.check_league(self.lg(roster=lambda: []))
        with self.assertRaises(RuntimeError):
            health.check_league(self.lg(opponent_id=lambda: None))


if __name__ == "__main__":
    unittest.main()
