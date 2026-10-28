import datetime as dt
import tempfile
import unittest
from types import SimpleNamespace as NS
from unittest import mock

from fbgm import tracking
from fbgm.config import BENCH, IR

D = dt.date


def news(headline, story="", published="2026-10-07T23:07:33Z"):
    return {"headline": headline, "story": story, "published": published, "type": "Rotowire"}


class Estimate(unittest.TestCase):
    def test_at_least_n_weeks(self):
        e = tracking._estimate(news("Nurkic will miss at least the next four weeks due to a toe tear."))
        self.assertEqual((e["est"], e["kind"]), (D(2026, 11, 4), "at least"))

    def test_months(self):
        e = tracking._estimate(news("Smith is expected to be out about two months."))
        self.assertEqual(e["est"], D(2026, 10, 7) + dt.timedelta(days=60))

    def test_explicit_month_day(self):
        e = tracking._estimate(news("Jones is targeting a return on December 12 against Boston."))
        self.assertEqual((e["est"], e["kind"]), (D(2026, 12, 12), "targeted"))

    def test_early_mid_late_month(self):
        e = tracking._estimate(news("Lee will be re-evaluated in mid-January."))
        self.assertEqual(e["est"], D(2027, 1, 15))

    def test_no_timeline(self):
        e = tracking._estimate(news("Brown remains out with a sore ankle."))
        self.assertIsNone(e["est"])

    def test_season_ending(self):
        self.assertTrue(tracking._estimate(news("Davis is out for the season with a torn ACL."))["season"])

    def test_soon_phrase(self):
        self.assertTrue(tracking._estimate(news("Cole was cleared for full-contact practice."))["soon"])


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        patch = mock.patch.object(tracking, "STATE_DIR", self.tmp)
        patch.start()
        self.addCleanup(patch.stop)


class Player:
    def __init__(self, pid, name, slot, injury):
        self.id, self.name, self.lineup_slot, self.injury = pid, name, slot, injury
        self.pro_team, self.rate, self.expected = 1, 30.0, 30.0


def player(pid, name, slot, injury="OUT"):
    return Player(pid, name, slot, injury)


class Snapshot(Fixture):
    def make_lg(self, locked):
        a = player(1, "Ann", 0, "ACTIVE")
        b = player(2, "Bob", BENCH, "ACTIVE")
        return NS(today=D(2026, 10, 28), matchup_period=2, roster=lambda tid: [a, b],
                  locked=lambda p, d: locked, plays=lambda p, d: True, rest_factor=lambda p, d: 0.9,
                  day_projection=lambda r, d: (27.0, {a: 0}))

    def test_round_trip(self):
        lg = self.make_lg(locked=False)
        tracking.save_snapshot(lg, {7: (500.0, 0, 0), 8: (400.0, 0, 0)}, {7: 120.0, 8: 100.0}, 0.81, (7, 8))
        snap = tracking.load_snapshot(D(2026, 10, 28))
        self.assertEqual(snap["win_prob"], 0.81)
        t = snap["teams"]["7"]
        self.assertEqual((t["week"], t["day"]), (500.0, 120.0))
        self.assertEqual(t["players"]["Ann"], {"proj": 27.0, "lineup": True})
        self.assertFalse(t["players"]["Bob"]["lineup"])

    def test_started_games_keep_pregame_snapshot(self):
        tracking.save_snapshot(self.make_lg(False), {7: (500.0, 0, 0)}, {7: 120.0}, 0.81, (7,))
        tracking.save_snapshot(self.make_lg(True), {7: (999.0, 0, 0)}, {7: 999.0}, 0.5, (7,))
        self.assertEqual(tracking.load_snapshot(D(2026, 10, 28))["teams"]["7"]["week"], 500.0)

    def test_missing_snapshot(self):
        self.assertIsNone(tracking.load_snapshot(D(2000, 1, 1)))


class IrStatus(Fixture):
    TODAY = D(2026, 10, 28)

    def lg(self, items, injury="OUT", slot=IR):
        pl = player(5, "Nur", slot, injury)
        games = {1: {self.TODAY + dt.timedelta(days=i): None for i in range(0, 60, 2)}}
        return NS(today=self.TODAY, roster=lambda: [pl], news=lambda p: items, games=games)

    def run_ir(self, items, **kw):
        return tracking.ir_status(self.lg(items, **kw))

    def test_far_return_announced_once(self):
        far = [news("Nur is out about two months.", published="2026-10-27T10:00:00Z")]
        first = self.run_ir(far)
        self.assertEqual(len(first), 1)
        self.assertFalse(first[0]["near"])
        self.assertEqual(self.run_ir(far), [])      # no daily reminder

    def test_near_return_reported_nightly(self):
        near = [news("Nur will miss at least the next two weeks.", published="2026-10-20T10:00:00Z")]
        for _ in range(2):
            out = self.run_ir(near)
            self.assertEqual(len(out), 1)
            self.assertTrue(out[0]["near"])
        self.assertEqual(out[0]["est"], D(2026, 11, 3))
        self.assertEqual(out[0]["first"], D(2026, 11, 3))   # games every other day from today

    def test_pushed_back_far_out_is_flagged(self):
        self.run_ir([news("Nur is out about two months.", published="2026-10-27T10:00:00Z")])
        out = self.run_ir([news("Nur is out about three months.", published="2026-10-28T10:00:00Z")])
        self.assertEqual(len(out), 1)
        self.assertGreaterEqual(out[0]["shift"], 20)

    def test_small_shift_is_ignored(self):
        self.run_ir([news("Nur is out about two months.", published="2026-10-27T10:00:00Z")])
        self.assertEqual(self.run_ir([news("Nur is out about two months.", published="2026-10-28T10:00:00Z")]), [])

    def test_timeline_lost_is_flagged(self):
        self.run_ir([news("Nur is out about two months.", published="2026-10-27T10:00:00Z")])
        out = self.run_ir([news("Nur is out for the season with surgery.", published="2026-10-28T10:00:00Z")])
        self.assertTrue(out[0]["lost"]["season"])

    def test_status_upgrade_while_on_ir(self):
        out = self.run_ir([news("Nur is progressing.")], injury="DAY_TO_DAY")
        self.assertTrue(out[0]["upgraded"])

    def test_non_ir_players_ignored(self):
        self.assertEqual(self.run_ir([news("Nur out about two weeks.")], slot=0), [])


class CorruptState(Fixture):
    def test_unreadable_file_warns_and_reads_as_missing(self):
        from fbgm import health
        health.reset()
        self.addCleanup(health.reset)
        with open(f"{self.tmp}/snapshot-2026-10-28.json", "w") as f:
            f.write("{not json")
        self.assertIsNone(tracking.load_snapshot(D(2026, 10, 28)))
        self.assertIn("snapshot-2026-10-28.json is unreadable", health.render())


if __name__ == "__main__":
    unittest.main()
