import unittest

from fbgm import season


def matchup(period, home, away, hp=0.0, ap=0.0, winner="UNDECIDED"):
    return {"matchupPeriodId": period, "winner": winner, "home": {"teamId": home, "totalPoints": hp},
            "away": {"teamId": away, "totalPoints": ap}}


IDS = [1, 2, 3, 4]


def round_robin(weeks):
    """Weeks 1..weeks of a 4-team schedule: (1v2, 3v4), (1v3, 2v4), (1v4, 2v3), repeating."""
    pairs = [((1, 2), (3, 4)), ((1, 3), (2, 4)), ((1, 4), (2, 3))]
    return [matchup(w, a, b) for w in range(1, weeks + 1) for a, b in pairs[(w - 1) % 3]]


class Standings(unittest.TestCase):
    def test_counts_only_decided_weeks_before_the_current_one(self):
        sched = [matchup(1, 1, 2, 2000, 1900, "HOME"), matchup(1, 3, 4, 1800, 1800, "TIE"),
                 matchup(2, 1, 3, 500, 400)]       # week 2 is in progress
        rec = season.standings(sched, 2, IDS)
        self.assertEqual((rec[1]["w"], rec[1]["l"], rec[1]["pf"], rec[1]["pa"]), (1, 0, 2000, 1900))
        self.assertEqual((rec[2]["w"], rec[2]["l"]), (0, 1))
        self.assertEqual((rec[3]["t"], rec[4]["t"]), (1, 1))

    def test_order_key_wins_then_fewer_points_against(self):
        a = {"w": 3, "l": 1, "t": 0, "pf": 0, "pa": 5000}
        b = {"w": 3, "l": 1, "t": 0, "pf": 0, "pa": 4900}
        c = {"w": 4, "l": 0, "t": 0, "pf": 0, "pa": 9000}
        self.assertEqual(sorted("abc", key=lambda k: season.order_key({"a": a, "b": b, "c": c}[k])), ["c", "b", "a"])


class WeekSd(unittest.TestCase):
    def test_prior_until_three_weeks(self):
        past = [(1, 1, 2000, 2, 1900), (2, 1, 2100, 2, 1800)]
        self.assertEqual(season.week_sds({1: 2000, 2: 1800}, past, 0.1), {1: 200.0, 2: 180.0})

    def test_observed_spread_pulls_in_after_three_weeks(self):
        past = [(w, 1, pts, 2, 1800) for w, pts in enumerate([1500, 2500, 2000], 1)]
        sd = season.week_sds({1: 2000, 2: 1800}, past, 0.1)
        self.assertGreater(sd[1], 200)       # observed sd is 500, weighted 50/50 with the 200 prior
        self.assertEqual(sd[2], 90.0)        # constant 1800 -> observed sd 0, blended 50/50 with the 180 prior


def run(strength, weeks=6, p_me=0.5, rival=2, strength_sd=None, sims=1500):
    sched = round_robin(weeks)
    current = {t: (0.0, 1.0) for t in IDS}
    sd = {t: 0.1 * s for t, s in strength.items()}
    return season.simulate(sched, 1, IDS, strength, sd, current, 1, p_me, 2, rival, sims=sims, seed="t",
                           strength_sd=strength_sd)


class Simulate(unittest.TestCase):
    def test_dominant_team_makes_it_and_odds_sum_to_playoff_spots(self):
        out = run({1: 3000, 2: 1500, 3: 1500, 4: 1500}, p_me=0.99)
        self.assertGreater(out["playoff"][1], 0.99)
        self.assertAlmostEqual(sum(out["playoff"].values()), 2.0, places=6)
        self.assertGreater(out["wins"][1], 5)

    def test_equal_teams_are_close_to_even(self):
        out = run({t: 2000 for t in IDS}, weeks=12)
        for t in IDS:
            self.assertAlmostEqual(out["playoff"][t], 0.5, delta=0.08)

    def test_winning_this_week_helps(self):
        out = run({t: 2000 for t in IDS})
        self.assertGreater(out["me_if_win"], out["me_if_loss"])

    def test_pinned_win_chance_is_respected(self):
        out = run({t: 2000 for t in IDS}, p_me=0.9, sims=3000)
        won = out["me_if_win"] is not None
        self.assertTrue(won)
        # With a 90% win chance this week our expected wins sit well above the 50% baseline.
        self.assertGreater(out["wins"][1], 3.4)

    def test_rival_ahead_share(self):
        weak_me = run({1: 1500, 2: 2500, 3: 2000, 4: 2000})
        strong_me = run({1: 2500, 2: 1500, 3: 2000, 4: 2000})
        self.assertGreater(weak_me["rival_ahead"], 0.8)
        self.assertLess(strong_me["rival_ahead"], 0.2)

    def test_strength_uncertainty_pulls_certainty_down(self):
        sure = run({1: 2600, 2: 1800, 3: 1800, 4: 1800})
        unsure = run({1: 2600, 2: 1800, 3: 1800, 4: 1800}, strength_sd={t: 600 for t in IDS})
        self.assertLess(unsure["playoff"][1], sure["playoff"][1])

    def test_same_inputs_same_answer(self):
        s = {1: 2100, 2: 1900, 3: 2000, 4: 1800}
        self.assertEqual(run(s)["playoff"], run(s)["playoff"])


if __name__ == "__main__":
    unittest.main()
