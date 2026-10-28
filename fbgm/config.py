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
    # Flex pool = players we added in the last flex_recent_days (still rostered), newest first,
    # capped per mode. With no recent adds it falls back to the lowest-rated player (plus anyone
    # within flex_margin FP/G of him).
    "mode": "conservative",
    "flex_slots": {"conservative": 2, "aggressive": 3},
    "flex_recent_days": 7,
    "flex_margin": 3.0,
    # Flex moves are judged on this matchup week and current form (last-15 blended with the rate).
    # A move must add at least this many projected FP to the week, from starts the add really gets.
    "flex_min_week_gain": 10.0,
    "form_prior_games": 5,
    # Core players are only drop candidates when their outlook is badly hurt (availability at or
    # below this, e.g. OUT/DOUBTFUL) and they can't just go to an open IR slot.
    "core_drop_max_availability": 0.25,
    # Adds must be at least this likely to play (skips OUT/DOUBTFUL/DTD adds).
    "add_min_availability": 0.6,
    # Shrinkage: current-season games needed to weigh equal to the prior.
    "prior_games": 8,
    # Underperformer: >= min games and current + last-15 rates below these shares of the prior.
    "under_min_games": 8,
    "under_season_ratio": 0.80,
    "under_recent_ratio": 0.85,
    # Suggest switching to aggressive when this many rostered players are underperforming.
    "aggressive_trigger": 3,
    # Opponent strength: look-back window (days), shrinkage (player-games), min rate to sample.
    "def_window": 30,
    "def_prior_all": 40,
    "def_prior_pos": 20,
    "def_min_rate": 15.0,
    # Moves within this many week FP of the best are "neck and neck"; break the tie on matchup strength.
    "tie_week": 3.0,
    # A healthy core player is only dropped for a proven upgrade: the add has this many games, a
    # rest-of-season rate at least this much higher, and current form at least as good.
    "core_upgrade_min_gp": 8,
    "core_upgrade_rate_gain": 3.0,
    # Win chance: simulate the rest of the week this many times, drawing each start's FP from real game-to-game
    # swings (last def_window days), times a projection-error factor (sd as a share of remaining FP).
    # Healthy starters miss this share of games (rest, late scratches).
    "sims": 4000,
    "model_sd_ratio": 0.06,
    "dnp_rate": 0.05,
    # Power rankings (FP/week units): results get weight days / (days + trust_days) against roster
    # strength; recent_share of the results part is the last 7 days; each game over .500 adds record_fp.
    "power_trust_days": 21,
    "power_recent_share": 0.4,
    "power_record_fp": 25.0,
    # The week counts as decided (lead with it, skip this week's moves) only under a stress test: the other
    # side gets its upside (everyone not OUT plays at his better of rate/form, and it streams up to
    # upside_streamers free agents a day into idle players' spots) and we still win decided_win of the
    # simulations. A loss is decided when we get that upside (i.e. even our best moves) and still win
    # no more than decided_loss.
    "upside_streamers": 2,
    # Back-to-back rest: from this season and last, each player's healthy back-to-backs (he played the games
    # either side) and which leg he sat. Chance to sit a leg = (sat + prior_games * base) / (b2bs + prior_games).
    "rest_seasons": 2,
    "rest_prior_games": 5,
    "rest_base": 0.05,
    # Report flags a coming leg at or above this chance to sit, and news from the last news_hours.
    "rest_flag": 0.15,
    "news_hours": 30,
    # IR players are mentioned in the report only once a return is within this many days (or a timeline first appears).
    "ir_window_days": 14,
    # ...and whenever a known return estimate moves by this many days or more (either direction), however far out.
    "ir_shift_days": 3,
    "decided_win": 0.99,
    "decided_loss": 0.01,
}

# Outlook labels by minimum win chance, best first.
# 🔒 Guaranteed W and 💀 Loss incoming are reserved for weeks that pass the decided stress test.
OUTLOOK = [(0.80, "🟢 Strong"), (0.60, "🟢 Lean W"), (0.40, "🟡 Toss-up"), (0.20, "🟠 Lean L"), (0.0, "🔴 Weak")]
DECIDED_LABEL = {"W": "🔒 Guaranteed W", "L": "💀 Loss incoming"}

# Chance a player plays, by ESPN injury status.
AVAILABILITY = {
    "ACTIVE": 1.0, "NORMAL": 1.0, "DAY_TO_DAY": 0.6, "QUESTIONABLE": 0.6,
    "DOUBTFUL": 0.25, "OUT": 0.0, "INJURY_RESERVE": 0.0, "SUSPENSION": 0.0,
}

SLOT_NAMES = {0: "PG", 1: "SG", 2: "SF", 3: "PF", 4: "C", 5: "G", 6: "F", 7: "SG/SF",
              8: "G/F", 9: "PF/C", 10: "F/C", 11: "UTIL", 12: "BE", 13: "IR"}
BENCH, IR = 12, 13
