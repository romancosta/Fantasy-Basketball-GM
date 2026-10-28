import unittest

from fbgm.config import SCORING_CONFIRMED
from fbgm.model import best_lineup, fantasy_points, hungarian_max


class FantasyPoints(unittest.TestCase):
    def test_known_stat_line(self):
        # 29 PTS, 11-15 FG... via ESPN stat ids: PTS 0, FGM 13, FTM 15, REB 6, AST 3, STL 2, BLK 1, TO 11.
        line = {"0": 29, "13": 11, "15": 6, "6": 9, "3": 9, "2": 6, "1": 1, "11": 3}
        self.assertEqual(fantasy_points(line, SCORING_CONFIRMED), 29 + 11 + 6 + 9 + 18 + 12 + 2 - 6)

    def test_bonuses_and_penalties(self):
        self.assertEqual(fantasy_points({"37": 1, "38": 1, "39": 1}, SCORING_CONFIRMED), 5 + 10 + 100)
        self.assertEqual(fantasy_points({"7": 1, "8": 1, "10": 2}, SCORING_CONFIRMED), -5 - 2 - 2)

    def test_missing_stats_are_zero(self):
        self.assertEqual(fantasy_points({}, SCORING_CONFIRMED), 0)


class Assignment(unittest.TestCase):
    def test_hungarian_picks_best_total(self):
        w = [[10, 1], [9, 8]]
        self.assertEqual(hungarian_max(w), {0: 0, 1: 1})
        w = [[10, 9], [9, 1]]
        self.assertEqual(hungarian_max(w), {0: 1, 1: 0})

    def test_ineligible_cells_stay_unassigned(self):
        self.assertEqual(hungarian_max([[0, 0], [5, 0]]), {1: 0})

    def test_best_lineup_respects_eligibility(self):
        class P:
            def __init__(self, name, fp, slots):
                self.name, self.expected, self.slots = name, fp, set(slots)
        a, b, c = P("a", 50, {0}), P("b", 40, {0, 1}), P("c", 30, {1})
        total, lineup = best_lineup([a, b, c], [0, 1])
        self.assertEqual(total, 90)   # a at slot 0, b at slot 1 beats b at 0 and c at 1 (70)
        self.assertEqual({p.name: s for p, s in lineup.items()}, {"a": 0, "b": 1})

    def test_empty_inputs(self):
        self.assertEqual(best_lineup([], [0]), (0.0, {}))


if __name__ == "__main__":
    unittest.main()
