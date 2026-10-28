import datetime as dt
import unittest

from fbgm import pretip
from fbgm.config import AVAILABILITY, BENCH, IR
from fbgm.model import ET, League

TODAY = dt.date(2026, 10, 28)
NOW = dt.datetime(2026, 10, 28, 18, 0, tzinfo=ET)
EARLY = dt.datetime(2026, 10, 28, 19, 0, tzinfo=ET)
LATE = dt.datetime(2026, 10, 28, 21, 0, tzinfo=ET)
SLOTS = [0, 1]    # two starting slots: 0 = guard-ish, 1 = big-ish


class P:
    _ids = 0

    def __init__(self, name, slots, slot, fp=40.0, injury="ACTIVE", team=1, status="ONTEAM"):
        P._ids += 1
        self.id, self.name, self.slots, self.lineup_slot = P._ids, name, set(slots), slot
        self.injury, self.pro_team, self.status = injury, team, status
        self.expected = fp * AVAILABILITY[injury]
        self.form, self.gp, self.ir_eligible, self.rate = fp, 20, True, fp

    @property
    def availability(self):
        return AVAILABILITY[self.injury]


def make_lg(players, free_agents=(), games=None, now=NOW):
    """A League without the ESPN fetch: just the attributes the pre-tip check reads."""
    lg = League.__new__(League)
    lg.now, lg.today, lg.slots = now, now.date(), list(SLOTS)
    lg.games = games or {1: {TODAY: EARLY}, 2: {TODAY: LATE}}
    lg.rosters = {31: list(players)}
    lg.roster = lambda team_id=None: lg.rosters[31]
    lg.free_agents = list(free_agents)
    lg._rest_watch = set()
    lg._recent_adds = {}      # no recent adds: the flex pool falls back to the lowest-rated player
    lg._news = {p.id: [] for p in list(players) + list(free_agents)}
    return lg


class Pretip(unittest.TestCase):
    def test_clean_lineup_is_ok(self):
        lg = make_lg([P("Guard", {0}, 0), P("Big", {1}, 1), P("Bench", {0, 1}, BENCH, 20)])
        status, lines = pretip.pretip(lg)
        self.assertEqual(status, "OK")
        self.assertEqual(len(lines), 1)     # only the "first unlocked tip" header
        self.assertIn("7:00 PM", lines[0])

    def test_out_starter_is_swapped_for_a_bench_player(self):
        out = P("Hurt Guard", {0}, 0, injury="OUT")
        lg = make_lg([out, P("Big", {1}, 1), P("Backup", {0}, BENCH, 25)])
        status, lines = pretip.pretip(lg)
        self.assertEqual(status, "ACTION")
        text = "\n".join(lines)
        self.assertIn("Hurt Guard: PG -> BE (OUT today)", text)
        self.assertIn("Backup: BE -> PG", text)

    def test_idle_bench_player_is_not_suggested(self):
        lg = make_lg([P("Guard", {0}, 0), P("Big", {1}, 1), P("Idle", {0}, BENCH, 50, team=3)],
                     games={1: {TODAY: EARLY}, 3: {}})
        self.assertEqual(pretip.pretip(lg)[0], "OK")

    def test_star_out_with_no_cover_and_nobody_to_drop_is_silent(self):
        # Two players active tonight, one is a star who is now OUT. Nothing on the bench, nobody we would cut.
        star = P("Star", {0}, 0, 65, injury="OUT")
        fa = P("Streamer", {0}, None, 35, status="FREEAGENT")
        lg = make_lg([star, P("Big", {1}, 1, 50)], free_agents=[fa])
        self.assertEqual(pretip.pretip(lg)[0], "OK")

    def test_star_out_does_not_alert_even_with_a_pickup_if_the_only_drop_is_a_starter(self):
        lg = make_lg([P("Star", {0}, 0, 65, injury="OUT"), P("Big", {1}, 1), P("Wing", {0, 1}, BENCH, 30, team=3)],
                     free_agents=[P("Streamer", {0}, None, 35, status="FREEAGENT")],
                     games={1: {TODAY: EARLY}, 2: {TODAY: LATE}, 3: {}})
        # The idle bench player is a legitimate drop, so this one does alert (see the next test for the cost side).
        status, lines = pretip.pretip(lg)
        self.assertEqual(status, "ACTION")
        self.assertIn("Optional pickup: Star (PG) is OUT with no bench cover. +Streamer / -Wing", "\n".join(lines))

    def test_small_pickup_gain_is_not_worth_an_alert(self):
        lg = make_lg([P("Star", {0}, 0, 65, injury="OUT"), P("Big", {1}, 1), P("Wing", {0, 1}, BENCH, 30, team=3)],
                     free_agents=[P("Scrub", {0}, None, 6, status="FREEAGENT")],
                     games={1: {TODAY: EARLY}, 2: {TODAY: LATE}, 3: {}})
        self.assertEqual(pretip.pretip(lg)[0], "OK")

    def test_tiny_reshuffle_is_not_an_alert(self):
        lg = make_lg([P("Guard", {0}, BENCH, 41), P("Other", {0}, 0, 40), P("Big", {1}, 1)])
        self.assertEqual(pretip.pretip(lg)[0], "OK")

    def test_questionable_starter_without_cover_is_not_listed(self):
        lg = make_lg([P("Guard", {0}, 0, injury="DAY_TO_DAY"), P("Big", {1}, 1)])
        self.assertEqual(pretip.pretip(lg)[0], "OK")

    def test_questionable_starter_with_cover_is_a_watch_not_an_action(self):
        lg = make_lg([P("Guard", {0}, 0, injury="DAY_TO_DAY"), P("Big", {1}, 1), P("Cover", {0}, BENCH, 15)])
        status, lines = pretip.pretip(lg)
        self.assertEqual(status, "WATCH")
        self.assertIn("Guard (PG, 7:00 PM)", "\n".join(lines))

    def test_locked_players_never_move(self):
        started = P("Started", {0}, BENCH, 80, team=3)    # tipped at 6:30, already locked at 6:45
        games = {1: {TODAY: EARLY}, 3: {TODAY: dt.datetime(2026, 10, 28, 18, 30, tzinfo=ET)}}
        lg = make_lg([started, P("Guard", {0}, 0, 30), P("Big", {1}, 1)], games=games,
                     now=NOW.replace(minute=45))
        moves, _, _ = pretip.lineup_changes(lg, TODAY)
        self.assertNotIn(started, [m[0] for m in moves])
        self.assertEqual(pretip.pretip(lg)[0], "OK")

    def test_ir_player_back_on_the_court(self):
        back = P("Returner", {1}, IR, injury="DAY_TO_DAY")
        lg = make_lg([P("Guard", {0}, 0), P("Big", {1}, 1), back])
        status, lines = pretip.pretip(lg)
        self.assertEqual(status, "ACTION")
        self.assertIn("Move Returner off IR", "\n".join(lines))

    def test_ir_player_still_out_is_ignored(self):
        lg = make_lg([P("Guard", {0}, 0), P("Big", {1}, 1), P("Hurt", {1}, IR, injury="OUT")])
        self.assertEqual(pretip.pretip(lg)[0], "OK")

    def test_no_unlocked_games(self):
        lg = make_lg([P("Guard", {0}, 0)], now=NOW.replace(hour=23))
        self.assertEqual(pretip.pretip(lg)[0], "NONE")


if __name__ == "__main__":
    unittest.main()
