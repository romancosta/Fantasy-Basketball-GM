"""League constants and GM policy knobs."""

CONFIG = {
    "league_id": 153490,
    "season": 2027,          # ESPN labels the 2026-27 season as 2027
    "my_team_id": 31,        # Hollywood Beach Ballers
}

# Confirmed against the league's manual scoring export (statId -> points).
SCORING_CONFIRMED = {
    0: 1,     # PTS
    13: 1,    # FGM
    15: 1,    # FTM
    4: 2,     # OREB
    5: 1,     # DREB
    6: 1,     # REB
    3: 2,     # AST
    2: 2,     # STL
    1: 2,     # BLK
    11: -2,   # TO
    7: -5,    # EJ
    8: -2,    # FF
    10: -1,   # TF
    37: 5,    # DD
    38: 10,   # TD
    39: 100,  # QD
}
STAT_GP = "42"

POLICY = {
    # conservative: one rotating "flex" roster spot; aggressive: up to three.
    "mode": "conservative",
    "flex_slots": {"conservative": 1, "aggressive": 3},
    # A stream may cost at most this much rest-of-season FP/G vs the player dropped...
    "stream_ros_tolerance": 1.5,
    # ...and only if it gains at least this many projected FP this matchup week.
    "stream_min_week_gain": 15.0,
    # Shrinkage: current-season games needed to weigh equal to the prior.
    "prior_games": 8,
    # Underperformer: >= min games and current + last-15 rates below these shares of the prior.
    "under_min_games": 8,
    "under_season_ratio": 0.80,
    "under_recent_ratio": 0.85,
    # Suggest switching to aggressive when this many rostered players are underperforming.
    "aggressive_trigger": 3,
}

# Chance a player plays, by ESPN injury status.
AVAILABILITY = {
    "ACTIVE": 1.0, "NORMAL": 1.0, "DAY_TO_DAY": 0.6, "QUESTIONABLE": 0.6,
    "DOUBTFUL": 0.25, "OUT": 0.0, "INJURY_RESERVE": 0.0, "SUSPENSION": 0.0,
}

SLOT_NAMES = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F", 7: "SG/SF",
              8: "G/F", 9: "PF/C", 10: "F/C", 11: "UTIL", 12: "BE", 13: "IR"}
BENCH, IR = 12, 13
