"""Evening check (moves for the next game day) and the bench call on crowded nights."""
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from fbgm import evening, gm, report
from tests.test_swap_timing import SAT, SUN, P, at, kuminga_case, make_lg, setUpModule, tearDownModule  # noqa: F401


class Evening(unittest.TestCase):
    def run_evening(self, lg):
        with mock.patch.object(evening, "week_is_decided", return_value=False):
            return evening.evening(lg, NS(mode=None, n=3))

    def test_after_tonights_tip_the_pickup_for_tomorrow_is_listed(self):
        lg, _, _ = kuminga_case(now=at(SAT, 22))        # Kuminga's 8 PM game has tipped
        status, lines = self.run_evening(lg)
        self.assertEqual(status, "MOVES")
        self.assertEqual(lines[0], "EVENING MOVES · 1 for Sun 11/01 (first tip 3:00 PM)")
        self.assertIn("**+Brandin Podziemski / −Jonathan Kuminga**: **+45 FP Sun**", "\n".join(lines))
        self.assertIn("counts from Sun 11/01", "\n".join(lines))

    def test_quiet_when_nothing_clears_the_bar(self):
        lg, _, podz = kuminga_case(now=at(SAT, 22))
        podz.expected = podz.form = podz.rate = 8.0        # adds under 10 FP
        status, lines = self.run_evening(lg)
        self.assertEqual((status, lines), ("OK", ["EVENING OK · no streaming move adds 10+ FP on Sun 11/01"]))

    def test_decided_week_skips(self):
        lg, _, _ = kuminga_case(now=at(SAT, 22))
        lg.matchup_period = 2
        with mock.patch.object(evening, "week_is_decided", return_value=True):
            status, lines = evening.evening(lg, NS(mode=None, n=3))
        self.assertEqual(status, "OK")
        self.assertIn("is decided", lines[0])


    def test_settled_week_is_quiet(self):
        lg, _, _ = kuminga_case(now=at(SAT, 22))
        lg.matchup_period, lg._settled = 2, 1.0
        self.assertEqual(self.run_evening(lg), ("OK", ["EVENING OK · week 2 is settled (100% win chance); no moves "
                                                       "needed for Sun 11/01"]))


class BenchCall(unittest.TestCase):
    def lg(self, roster, slots):
        games = {1: {SAT: at(SAT, 19)}}
        lg = make_lg(roster, [], games, at(SAT, 9))
        lg.slots = slots
        return lg

    def test_position_logjam_names_who_holds_his_slots(self):
        sga, murray = P("Shai Gilgeous-Alexander", {0, 5}, 0, 65, 1), P("Jamal Murray", {0, 5}, 5, 58, 1)
        dame, barrett = P("Damian Lillard", {0, 5}, 12, 46, 1), P("RJ Barrett", {1}, 1, 38, 1)
        lg = self.lg([sga, murray, dame, barrett], [0, 5, 1])
        calls = gm.bench_calls(lg, lg.roster(), SAT)
        self.assertEqual([(c[0].name, c[2]) for c in calls], [("Damian Lillard", "logjam")])
        self.assertEqual(gm.bench_str(lg, calls), "Lillard 46 (PG/G held by Gilgeous-Alexander, Murray; Barrett 38 starts)")

    def test_lowest_projection(self):
        a, b, c = P("Wing A", {1}, 1, 50, 1), P("Wing B", {1}, 12, 36, 1), P("Guard C", {0}, 0, 40, 1)
        lg = self.lg([a, b, c], [0, 1])
        self.assertEqual(gm.bench_str(lg, gm.bench_calls(lg, lg.roster(), SAT)), "B 36 (lowest projection)")

    def test_empty_slot_he_cannot_fill(self):
        g1, g2, g3 = P("Guard One", {0}, 0, 50, 1), P("Guard Two", {0}, 12, 40, 1), P("Wing", {1}, 1, 45, 1)
        lg = self.lg([g1, g2, g3], [0, 1, 4])           # nobody plays C
        self.assertEqual(gm.bench_str(lg, gm.bench_calls(lg, lg.roster(), SAT)),
                         "Two 40 (PG held by One; a slot he can't fill stays empty)")

    def test_nobody_benched_means_no_line(self):
        lg = self.lg([P("Guard", {0}, 0, 50, 1)], [0, 1])
        self.assertEqual(report.bench_line(lg, lg.roster(), SAT, "today"), "")


if __name__ == "__main__":
    unittest.main()
