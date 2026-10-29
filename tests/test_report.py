import contextlib
import datetime as dt
import io
import unittest
from types import SimpleNamespace as NS

from fbgm import fmt, health, report
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


class Pl:
    def __init__(self, name, expected):
        self.name, self.expected = name, expected


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


class LastNight(unittest.TestCase):
    def test_compare_uses_the_snapshot(self):
        compare, rebuilt = report.night_compare(LG, recap(), snapshot())
        self.assertFalse(rebuilt)
        self.assertEqual((compare[1]["proj"], compare[1]["actual"]), (300.0, 100.0))
        self.assertEqual(report.night_cell(compare[1], rebuilt), "300 → 100 (-200)")
        self.assertEqual(report.night_cell(compare[2], rebuilt), "280 → 250 (-30)")

    def test_rebuilt_projection_is_marked(self):
        a = Pl("Ann Able", 50.0)
        lg = NS(team_names=LG.team_names, roster=lambda tid: [a], rest_factor=lambda p, d: 1.0,
                day_projection=lambda roster, day: (50.0, {a: 0}))
        compare, rebuilt = report.night_compare(lg, recap(), None)
        self.assertTrue(rebuilt)
        self.assertEqual(report.night_cell(compare[1], rebuilt), "~50 → 100 (+50)")

    def test_misses_list_the_big_gaps_and_no_shows(self):
        compare, _ = report.night_compare(LG, recap(), snapshot())
        line = report.miss_line(recap(), compare, 1)
        self.assertIn("over: Able 80 vs 50", line)
        self.assertIn("Cool 0 vs 35 (DNP)", line)      # Cool never appears in the box score
        self.assertIn("Best 20 vs 40", line)
        self.assertNotIn("Bench", line)                # bench players aren't judged

    def test_small_misses_are_not_listed(self):
        rec = recap((("Ann Able", 52.0), ("Bob Best", 38.0), ("Cy Cool", 36.0)))
        compare, _ = report.night_compare(LG, rec, snapshot())
        self.assertEqual(report.miss_line(rec, compare, 1), "")


class VsYesterday(unittest.TestCase):
    def cell(self, now, rec=None, snap=None, tid=1):
        rec = rec or recap()
        snap = snap if snap is not None else snapshot()
        compare, _ = report.night_compare(LG, rec, snap)
        return report.vs_yesterday(snap, rec, tid, now, compare)

    def test_change_split_into_night_and_rest(self):
        # Us: week projection 1,500 -> 1,400 = -100; the night missed by -200, so the rest of the week gained +100.
        self.assertEqual(self.cell(1400.0), "-100 (-200 night, +100 rest)")

    def test_monday_compares_the_final_to_sundays_projection(self):
        self.assertEqual(self.cell(1550.0, rec=recap(final=True, totals=(1550.0, 1380.0))), "+50")

    def test_other_week_or_no_snapshot_is_a_dash(self):
        compare, _ = report.night_compare(LG, recap(), snapshot())
        self.assertEqual(report.vs_yesterday(snapshot(period=1), recap(), 1, 1400.0, compare), "-")
        self.assertEqual(report.vs_yesterday(None, recap(), 1, 1400.0, compare), "-")


def grid_lg():
    a = Pl("Ann Able", 50.0)
    return NS(team_names=LG.team_names, matchup_period=2, today=D(2026, 10, 28), roster=lambda tid: [a],
              rest_factor=lambda p, d: 1.0, day_projection=lambda roster, day: (50.0, {a: 0}), slots=[0, 1, 2])


class MatchupGrid(unittest.TestCase):
    PROJ = {1: (1400.0, 900.0, 500.0), 2: (1450.0, 950.0, 500.0)}
    TODAY = {1: 330.0, 2: 310.0}

    def test_one_grid_holds_night_today_week_and_change(self):
        out, _ = capture(report.matchup_section, grid_lg(), recap(), snapshot(), self.PROJ, self.TODAY, 1, 2)
        self.assertEqual(out.count("| Team |"), 1)                       # a single table
        self.assertIn("| Team | Tue proj → actual | Wed proj | Week so far | Week proj (margin) | Vs yesterday's proj |", out)
        self.assertIn("| Us | 300 → 100 (-200) | 330 | 900 | 1,400 (-50) 🔴 | -100 (-200 night, +100 rest) |", out)
        self.assertIn("**Top scorers**", out)

    def test_first_day_without_a_recap_has_no_night_columns(self):
        out, _ = capture(report.matchup_section, grid_lg(), None, None, self.PROJ, self.TODAY, 1, 2)
        self.assertIn("| Team | Wed proj | Week so far | Week proj (margin) |", out)
        self.assertNotIn("Vs yesterday", out)

    def test_monday_final_and_preview(self):
        rec = recap(final=True, totals=(1550.0, 1380.0))
        out, _ = capture(report.week_final_section, grid_lg(), rec, snapshot(), self.PROJ, self.TODAY, 1, 2)
        self.assertIn("## Week 2 final 🏆 WON", out)
        self.assertIn("| 🏆 Us | 300 → 100 (-200) | 1,550 (+170) 🟢 | +50 |", out)
        self.assertIn("## Week 2 preview · vs Them", out)


class NewsFilter(unittest.TestCase):
    NOW = dt.datetime(2026, 10, 28, 12, 0, tzinfo=dt.timezone.utc)

    def lg(self, news, rate=40.0, ruling=None, rest=0.0):
        pl = NS(name="Star Guy", rate=rate, lineup_slot=0, id=1)
        item = {"headline": news[0], "story": news[1] if len(news) > 1 else "", "published": "2026-10-28T08:00:00Z"}
        return NS(now=self.NOW, remaining_days=lambda: [D(2026, 10, 28), D(2026, 10, 29)], week_days=[D(2026, 11, 1)],
                  roster=lambda tid: [pl], game_ruling=lambda p: ruling, news=lambda p: [item],
                  rest_chance=lambda p, d: rest)

    def run_news(self, lg):
        return capture(report.news_section, lg, 1, 2)[0]

    def test_back_to_back_odds_alone_show_nothing(self):
        out = self.run_news(self.lg(("Star Guy dropped 30 points in the win.",), rest=0.2))
        self.assertEqual(out, "")

    def test_rest_talk_in_the_news_shows_the_odds(self):
        out = self.run_news(self.lg(("Star Guy could rest on the second night of a back-to-back.",), rest=0.2))
        self.assertIn("💤 **Star Guy** (us): rest in the news · back-to-back sit odds Wed 20% · Thu 20%", out)

    def test_injury_news_is_shown_for_rotation_players_only(self):
        self.assertIn("📰 **Star Guy**", self.run_news(self.lg(("Star Guy (ankle) is questionable.",))))
        self.assertEqual(self.run_news(self.lg(("Star Guy (ankle) is questionable.",), rate=12.0)), "")

    def test_one_game_ruling_is_shown(self):
        out = self.run_news(self.lg(("x",), ruling=(D(2026, 10, 28), "injury")))
        self.assertIn("🛌 **Star Guy** (us) ruled out Wed (injury); day-to-day after", out)


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


class NightlyWrapper(unittest.TestCase):
    """cmd_nightly adds the health banner under the outlook line and a Health section at the end."""

    def setUp(self):
        health.reset()
        self.addCleanup(health.reset)
        self._check, self._body = health.check_league, report.nightly_body
        health.check_league = lambda lg: None
        self.addCleanup(setattr, health, "check_league", self._check)
        self.addCleanup(setattr, report, "nightly_body", self._body)

    def run_with(self, body):
        report.nightly_body = body
        return capture(report.cmd_nightly, None, None)[0]

    def test_clean_report_is_unchanged(self):
        out = self.run_with(lambda lg, a: print("# Head\n\n{{OVERVIEW}} **Outlook: x**\n\n## Body"))
        self.assertEqual(out, "# Head\n\n{{OVERVIEW}} **Outlook: x**\n\n## Body\n")

    def test_issue_adds_banner_and_health_section(self):
        def body(lg, a):
            print("# Head\n\n{{OVERVIEW}} **Outlook: x**\n\n## Body")
            health.warn("something is off")
        lines = self.run_with(body).splitlines()
        i = lines.index("{{OVERVIEW}} **Outlook: x**") if "{{OVERVIEW}} **Outlook: x**" in lines else 2
        self.assertTrue(lines[i + 2].startswith("> ⚠️ 1 data issue"))
        self.assertEqual(lines[-2:], ["## Health", "- ⚠️ something is off"])

    def test_failed_section_is_contained(self):
        def body(lg, a):
            print("# Head\n\n{{OVERVIEW}} **Outlook: x**")
            with health.section("IR watch"):
                raise ValueError("bad")
            print("\n## Power rankings")
        with contextlib.redirect_stderr(io.StringIO()):
            out = self.run_with(body)
        self.assertIn("## IR watch\n- ⚠️ Unavailable this run: ValueError: bad", out)
        self.assertIn("## Power rankings", out)
        self.assertIn("IR watch section failed", out)


if __name__ == "__main__":
    unittest.main()
