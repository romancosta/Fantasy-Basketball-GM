"""Schedule-aware swaps: a drop's unplayed game today is not thrown away for an add who plays later."""
import contextlib
import datetime as dt
import io
import unittest
from collections import defaultdict
from types import SimpleNamespace as NS
from unittest import mock

from fbgm import gm, report
from fbgm.config import AVAILABILITY, BENCH
from fbgm.model import ET, League

SAT, SUN, TUE = dt.date(2026, 10, 31), dt.date(2026, 11, 1), dt.date(2026, 11, 3)
WEEK = [dt.date(2026, 10, 26) + dt.timedelta(days=i) for i in range(7)]   # Mon 10/26 - Sun 11/01


def at(day, hour):
    return dt.datetime.combine(day, dt.time(hour, 0), ET)


class P:
    _ids = 0

    def __init__(self, name, slots, slot, fp, team, status="ONTEAM"):
        P._ids += 1
        self.id, self.name, self.slots, self.lineup_slot = P._ids, name, set(slots), slot
        self.pro_team, self.status, self.injury, self.pos_group = team, status, "ACTIVE", "F"
        self.expected = self.form = self.rate = fp
        self.gp, self.ir_eligible, self.owned = 20, True, 5.0

    @property
    def availability(self):
        return AVAILABILITY[self.injury]


def make_lg(roster, fas, games, now, flex=()):
    lg = League.__new__(League)
    lg.now, lg.today, lg.slots, lg.ir_slots = now, now.date(), [0, 1], 0
    lg.games, lg.week_days, lg._defense = defaultdict(dict, games), WEEK, {}
    lg.opponent = {(t, d): 4 for t, g in games.items() for d in g}
    lg.rosters = {31: list(roster)}
    lg.roster = lambda team_id=None: lg.rosters[31]
    lg.free_agents, lg.players, lg.pro_abbrev = list(fas), {}, {1: "GS", 2: "GS", 3: "LAL", 4: "BOS"}
    lg._rest_watch = set()
    lg._recent_adds = {p.id: now for p in flex}
    return lg


def kuminga_case(now=at(SAT, 18), add_games=None):
    """Sat 10/31: Kuminga (flex, starting) plays tonight at 8:00 PM and not Sunday; Podziemski only plays Sunday."""
    kuminga = P("Jonathan Kuminga", {0}, 0, 35.0, team=1)
    big = P("Core Big", {1}, 1, 50.0, team=3)
    podz = P("Brandin Podziemski", {0}, None, 45.0, team=2, status="FREEAGENT")
    games = {1: {SAT: at(SAT, 20)}, 2: add_games or {SUN: at(SUN, 15)}, 3: {SAT: at(SAT, 19), SUN: at(SUN, 18)}}
    return make_lg([kuminga, big], [podz], games, now, flex=[kuminga]), kuminga, podz


def out(fn, *a):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*a)
    return buf.getvalue()


class SwapTiming(unittest.TestCase):
    def test_drop_playing_tonight_vs_add_starting_tomorrow_waits(self):
        lg, kuminga, podz = kuminga_case()
        sw = lg.evaluate_swap(podz, kuminga)
        self.assertTrue(sw.wait)
        self.assertEqual(sw.effective, SUN)
        self.assertEqual(sw.add_first, SUN)
        self.assertAlmostEqual(sw.gain, 45.0)                  # keeps Kuminga's 35 tonight
        self.assertEqual(sw.days, [(SUN, 45.0)])
        self.assertAlmostEqual(sw.now_gain, 10.0)              # the old "+10" that cost tonight's game
        self.assertEqual(gm.days_str(sw.now_days), "Sat: −35, Sun: +45")
        self.assertEqual(gm.timing_str(lg, sw, podz, kuminga),
                         "drop after Kuminga's game tonight (8:00 PM), Podziemski first plays Sun 11/01")

    def test_report_says_wait_until_after_tonight_not_move_now(self):
        lg, _, _ = kuminga_case()
        text = out(report.roster_moves, lg, NS(mode=None, n=3), None)
        self.assertIn("**+Brandin Podziemski / −Jonathan Kuminga**: **+45 FP this week**", text)
        self.assertIn("By day: Sun: +45 · ⏳ **Not now: drop after Kuminga's game tonight (8:00 PM), Podziemski first "
                      "plays Sun 11/01** (moving now: Sat: −35, Sun: +45 = +10)", text)

    def test_advise_and_swap_label_the_wait(self):
        lg, _, _ = kuminga_case()
        a = NS(mode=None, n=3, add="Podziemski", drop="Kuminga", date=None)
        with mock.patch.object(gm, "cmd_lineup"):
            text = out(gm.cmd_advise, lg, a, True)
        self.assertIn("WAIT +Brandin Podziemski / -Jonathan Kuminga", text)
        self.assertNotIn("MOVE +Brandin", text)
        with mock.patch.object(gm, "header"):
            text = out(gm.cmd_swap, lg, a)
        self.assertIn("Verdict: MOVE AFTER TONIGHT - flex spot, +45 FP", text)
        self.assertIn("moving now: Sat: −35, Sun: +45 = +10", text)

    def test_add_who_also_plays_today_moves_now(self):
        lg, kuminga, podz = kuminga_case(add_games={SAT: at(SAT, 19), SUN: at(SUN, 15)})
        sw = lg.evaluate_swap(podz, kuminga)
        self.assertFalse(sw.wait)
        self.assertEqual(sw.effective, SAT)
        self.assertEqual(sw.days, [(SAT, 10.0), (SUN, 45.0)])
        self.assertEqual(gm.timing_str(lg, sw, podz, kuminga), "")

    def test_drop_whose_game_has_tipped_counts_from_the_next_day(self):
        lg, kuminga, podz = kuminga_case(now=at(SAT, 21), add_games={SAT: at(SAT, 22), SUN: at(SUN, 15)})
        sw = lg.evaluate_swap(podz, kuminga)
        self.assertFalse(sw.wait)
        self.assertEqual(sw.effective, SUN)                    # tonight's 10 PM game isn't counted for the add
        self.assertEqual(sw.days, [(SUN, 45.0)])
        self.assertEqual(gm.timing_str(lg, sw, podz, kuminga), "counts from Sun 11/01, Podziemski first plays Sun 11/01")

    def test_drop_idle_today_moves_now(self):
        lg, kuminga, podz = kuminga_case()
        lg.games[1] = {}
        sw = lg.evaluate_swap(podz, kuminga)
        self.assertFalse(sw.wait)
        self.assertEqual(sw.days, [(SAT, 0.0), (SUN, 45.0)])
        self.assertEqual(gm.days_str(sw.days), "Sun: +45")

    def test_prefers_a_drop_who_does_not_start_tonight(self):
        lg, kuminga, podz = kuminga_case()
        idle = P("Idle Bench", {0, 1}, BENCH, 5.0, team=4)
        lg.rosters[31].append(idle)
        lg._recent_adds[idle.id] = lg.now
        _, _, plan, _ = gm.plan_moves(lg, NS(mode=None, n=3))
        self.assertEqual([(r[2].name, r[3].name, r[4].wait) for r in plan], [("Brandin Podziemski", "Idle Bench", False)])

    def test_planned_wait_keeps_the_drop_in_tonights_lineup(self):
        # After "+Podziemski / -Kuminga, after tonight", a second pickup can't use Kuminga's slot tonight.
        lg, kuminga, podz = kuminga_case()
        big = lg.rosters[31][1]
        idle = P("Idle Bench", {0, 1}, BENCH, 5.0, team=4)
        tonight = P("Tonight Guard", {0}, None, 30.0, team=5, status="FREEAGENT")
        lg.games[5] = {SAT: at(SAT, 21)}
        by_day = {SAT: [kuminga, big, idle], SUN: [podz, big, idle]}
        self.assertAlmostEqual(lg.evaluate_swap(tonight, idle, by_day).gain, 0.0)
        self.assertAlmostEqual(lg.evaluate_swap(tonight, idle, [podz, big, idle]).gain, 30.0)


class OpportunityNextGame(unittest.TestCase):
    def test_label_has_next_unplayed_game(self):
        lg, _, podz = kuminga_case()
        line = out(self._section, lg, podz)
        self.assertIn("next game Sun 11/01 (1 left this week)", line)

    def test_tipped_game_is_not_counted(self):
        lg, _, podz = kuminga_case(now=at(SAT, 21), add_games={SAT: at(SAT, 19), TUE: at(TUE, 19)})
        self.assertIn("next game Tue 11/03 (0 left this week)", out(self._section, lg, podz))

    @staticmethod
    def _section(lg, pl):
        with mock.patch.object(report.signals, "opportunities", return_value=[(pl, 6.0, "minutes surge", None, [])]):
            report.opportunity_section(lg)


if __name__ == "__main__":
    unittest.main()
