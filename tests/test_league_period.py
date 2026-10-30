import datetime as dt
import unittest
from unittest import mock

from fbgm import espn
from fbgm.model import ET, League

# Scoring period 10 = Thu Oct 29, 11 = Fri Oct 30 (a Monday-Sunday week 2 runs Oct 26 - Nov 1; sp 1 = Tue Oct 20).
FIRST = dt.date(2026, 10, 20)


def game(sp, home, away):
    day = FIRST + dt.timedelta(days=sp - 1)
    ts = int(dt.datetime.combine(day, dt.time(20, 0), ET).timestamp() * 1000)
    return {"date": ts, "homeProTeamId": home, "awayProTeamId": away}


def pro_schedule():
    sched = {1: {}, 2: {}}
    for sp in range(1, 20):
        for t, other in ((1, 2), (2, 1)):
            sched[t][str(sp)] = [game(sp, 1, 2)]
    return [{"id": t, "abbrev": f"T{t}", "proGamesByScoringPeriod": sched[t]} for t in (1, 2)]


def player_entry(pid, name, team=1):
    return {"id": pid, "status": "ONTEAM", "onTeamId": 31, "player": {
        "id": pid, "fullName": name, "proTeamId": team, "defaultPositionId": 1, "eligibleSlots": [0, 5, 12, 13],
        "injuryStatus": "ACTIVE", "stats": [], "ownership": {"percentOwned": 50.0}}}


def league_payload(scoring_period, roster_names, status_period):
    return {
        "scoringPeriodId": scoring_period, "status": {"currentMatchupPeriod": status_period},
        "settings": {"scoringSettings": {"scoringItems": []},
                     "rosterSettings": {"lineupSlotCounts": {"0": 1, "12": 1, "13": 1}},
                     "acquisitionSettings": {}},
        "teams": [{"id": 31, "name": "Us", "roster": {"entries": [
            {"playerId": i, "lineupSlotId": 0, "playerPoolEntry": player_entry(i, n)} for i, n in roster_names.items()]}}],
        "schedule": []}


class ScoringPeriodSync(unittest.TestCase):
    def build(self, today, default_sp):
        calls = []

        def fake_league(*views, scoring_period=None):
            calls.append(scoring_period)
            if scoring_period is None:    # ESPN's default: its own current period (yesterday's roster before rollover)
                return league_payload(default_sp, {1: "Ryan Rollins"} if default_sp == 10 else {2: "Jonathan Kuminga"},
                                      status_period=2)
            return league_payload(scoring_period, {1: "Ryan Rollins"} if scoring_period == 10 else {2: "Jonathan Kuminga"},
                                  status_period=2)
        with mock.patch.object(espn, "league", fake_league), mock.patch.object(espn, "players", lambda **kw: []), \
                mock.patch.object(espn, "pro_schedule", pro_schedule), \
                mock.patch.object(League, "apply_rest_rulings", lambda self: None):
            lg = League(today)
        return lg, calls

    def test_before_espn_rolls_over_we_ask_for_todays_roster(self):
        # 2am Fri Oct 30: ESPN still says period 10 (Thursday), where Rollins is rostered and Kuminga is not.
        lg, calls = self.build(dt.date(2026, 10, 30), default_sp=10)
        self.assertEqual(calls, [None, 11])
        self.assertEqual([p.name for p in lg.roster(31)], ["Jonathan Kuminga"])

    def test_no_second_request_when_espn_is_already_on_today(self):
        lg, calls = self.build(dt.date(2026, 10, 30), default_sp=11)
        self.assertEqual(calls, [None])
        self.assertEqual([p.name for p in lg.roster(31)], ["Jonathan Kuminga"])

    def test_week_comes_from_our_calendar_not_espns_field(self):
        # Oct 30 is in week 2 (Mon Oct 26 - Sun Nov 1); a Monday 2am run is the case that matters: ESPN's field lags.
        lg, _ = self.build(dt.date(2026, 10, 26), default_sp=6)
        self.assertEqual(lg.matchup_period, 2)
        self.assertIsNone(lg.espn_matchup_period)     # ESPN hasn't rolled over, so its week number isn't compared

    def test_espn_week_is_kept_for_the_sanity_check_after_rollover(self):
        lg, _ = self.build(dt.date(2026, 10, 30), default_sp=11)
        self.assertEqual(lg.espn_matchup_period, 2)


if __name__ == "__main__":
    unittest.main()
