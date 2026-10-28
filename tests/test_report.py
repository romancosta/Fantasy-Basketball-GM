import contextlib
import datetime as dt
import io
import unittest
from types import SimpleNamespace as NS

from fbgm import fmt, report
from fbgm.config import BENCH, DECIDED_LABEL

D = dt.date


def capture(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        out = fn(*a)
    return buf.getvalue(), out


class Helpers(unittest.TestCase):
    def test_outlook_thresholds(self):
        self.assertEqual(report.outlook(0.85), "🟢 Strong")
        self.assertEqual(report.outlook(0.60), "🟢 Lean W")
        self.assertEqual(report.outlook(0.50), "🟡 Toss-up")
        self.assertEqual(report.outlook(0.25), "🟠 Lean L")
        self.assertEqual(report.outlook(0.05), "🔴 Weak")

    def test_decided_labels_exist(self):
        self.assertEqual(set(DECIDED_LABEL), {"W", "L"})

    def test_scored_marks_leader(self):
        self.assertEqual(report.scored([1000, 900]), ["1,000 (+100) 🟢", "900 (-100) 🔴"])
        self.assertEqual(report.scored([900, 900]), ["900 (+0) ⚪", "900 (+0) ⚪"])

    def test_short_name_drops_suffix(self):
        self.assertEqual(fmt.short_name("Michael Porter Jr."), "Porter")
        self.assertEqual(fmt.short_name("LeBron James"), "James")

    def test_table_alignment(self):
        out, _ = capture(fmt.table, ["Team", "FP"], [["A", "1"]])
        self.assertEqual(out.splitlines()[:2], ["| Team | FP |", "|:--|--:|"])


def snapshot(me_day=300.0, opp_day=280.0, me_week=1500.0, opp_week=1400.0, period=2):
    def team(day, week, players):
        return {"day": day, "week": week, "players": players}
    return {"date": "2026-10-27", "period": period, "win_prob": 0.70, "teams": {
        "1": team(me_day, me_week, {"Ann Able": {"proj": 50.0, "lineup": True},
                                    "Bob Best": {"proj": 40.0, "lineup": True},
                                    "Cy Cool": {"proj": 35.0, "lineup": True},
                                    "Bench Guy": {"proj": 20.0, "lineup": False}}),
        "2": team(opp_day, opp_week, {})}}


def recap(me_pts=(("Ann Able", 80.0), ("Bob Best", 20.0)), final=False, totals=(1000.0, 900.0)):
    mine = [(0, n, p, {}, set()) for n, p in me_pts]
    return {"day": D(2026, 10, 27), "sp": 9, "period": 2, "final": final, "sides": [
        {"tid": 1, "day_pts": sum(p for _, p in me_pts), "total": totals[0], "players": mine},
        {"tid": 2, "day_pts": 250.0, "total": totals[1], "players": []}]}


LG = NS(team_names={1: "Us", 2: "Them"})


class ProjectedVsActual(unittest.TestCase):
    def test_day_table_and_misses(self):
        out, _ = capture(report.vs_projection, LG, recap(), snapshot(), 1, 2)
        self.assertIn("| Us | 300 | 100 | **-200** |", out)
        self.assertIn("| Them | 280 | 250 | **-30** |", out)
        self.assertIn("**Over** Able 80 vs 50 proj (+30)", out)
        # Cool never appears in the box score: counts as 0 against 35 projected.
        self.assertIn("Cool 0 vs 35 proj (-35, DNP)", out)
        self.assertIn("Best 20 vs 40 proj (-20)", out)
        self.assertNotIn("Bench", out)   # bench players aren't judged

    def test_small_misses_are_not_listed(self):
        out, _ = capture(report.vs_projection, LG, recap((("Ann Able", 52.0), ("Bob Best", 38.0), ("Cy Cool", 36.0))),
                         snapshot(), 1, 2)
        self.assertNotIn("**Under**", out)
        self.assertNotIn("**Over**", out)


class WeekDelta(unittest.TestCase):
    PROJ = {1: (1400.0, 0, 0), 2: (1450.0, 0, 0)}

    def test_delta_split_into_miss_and_rest(self):
        out, _ = capture(report.week_delta, LG, recap(), snapshot(), self.PROJ, 0.60, 1, 2)
        # Us: 1500 -> 1400 = -100; last night missed by -200, so the rest of the week gained +100.
        self.assertIn("| Us | 1,500 | 1,400 | **-100** | -200 last night, +100 rest of week |", out)
        self.assertIn("**Win chance** 70% → 60% (-10%) · margin +100 → -50", out)

    def test_monday_compares_final_to_sunday_projection(self):
        out, _ = capture(report.week_delta, LG, recap(final=True, totals=(1550.0, 1380.0)), snapshot(), self.PROJ,
                         0.60, 1, 2)
        self.assertIn("final", out)
        self.assertIn("| Us | 1,500 | 1,550 | **+50** |", out)
        self.assertNotIn("**Win chance**", out)

    def test_other_week_snapshot_is_skipped(self):
        out, _ = capture(report.week_delta, LG, recap(), snapshot(period=1), self.PROJ, 0.60, 1, 2)
        self.assertEqual(out, "")

    def test_missing_snapshot_is_skipped(self):
        out, _ = capture(report.week_delta, LG, recap(), None, self.PROJ, 0.60, 1, 2)
        self.assertEqual(out, "")


class BenchMissed(unittest.TestCase):
    def test_bench_points_with_empty_slot(self):
        lg = NS(slots=[0, 1])
        side = {"players": [(0, "A", 30.0, {}, {0}), (BENCH, "B", 25.0, {}, {1})]}
        missed, bench, empty = report.bench_missed(lg, side)
        self.assertEqual((missed, empty, [b[1] for b in bench]), (25.0, 1, ["B"]))

    def test_nothing_missed_when_slots_full(self):
        lg = NS(slots=[0])
        side = {"players": [(0, "A", 30.0, {}, {0}), (BENCH, "B", 45.0, {}, {0})]}
        self.assertEqual(report.bench_missed(lg, side)[0], 0.0)


if __name__ == "__main__":
    unittest.main()
