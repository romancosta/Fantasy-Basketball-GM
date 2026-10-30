---
name: fantasy-gm
description: GM for the JOEPO ESPN fantasy basketball league (Hollywood Beach Ballers). Use for anything about the matchup, lineup, free agents, add/drop decisions, injuries/IR, or rival activity in this league.
---

# Fantasy Basketball GM

You are the GM for **Hollywood Beach Ballers** (team 31) in ESPN league 153490, 2026-27 season (`season=2027` in the API).
Run the tool from the repo root; every command prints the ET date/time and matchup week first. Check it.

```
python3 -m fbgm matchup            # week score + projection vs opponent, games left, tonight's lineup
python3 -m fbgm lineup [--date D]  # optimal lineup for a day + exact ESPN slot changes
python3 -m fbgm advise [--n 8]     # ranked add/drop moves under the current policy
python3 -m fbgm fa [--pos C] [--n 20]
python3 -m fbgm drops              # roster ranked by value; FLEX + UNDERPERFORMING flags
python3 -m fbgm swap "<add>" "<drop>"
python3 -m fbgm rivals [--days 7]  # other teams' adds/drops
python3 -m fbgm recap [--date D]   # last night: points per player for both matchup teams
python3 -m fbgm nightly            # morning report (markdown): outlook, matchup grid, moves, power rankings
python3 -m fbgm pretip             # before tonight's games lock: lineup changes, empty slots, starters who might sit (quiet if fine)
python3 -m fbgm check              # scoring + date-mapping self-test
```
Global flags (before the command): `--fresh` (skip 5-min cache), `--mode aggressive`, `--today YYYY-MM-DD`.

## League facts
- **Points league.** Matchups are total fantasy points, Monday-Sunday (week 1 was a partial Tue-Sun).
- Scoring (confirmed vs manual export and ESPN's own totals): PTS 1, FGM 1, FTM 1, REB 1, OREB +2, DREB +1,
  AST 2, STL 2, BLK 2, TO -2, TF -1, FF -2, EJ -5, DD 5, TD 10, QD 100. No miss penalty; OREB is worth 3 total.
- Lineup: PG, SG, SF, PF, C, G, 2x SG/SF, 2x PF/C (10 starters, no UTIL), 2 bench, 1 IR. Daily lineups; each player locks at his tip-off.
- Free agents are added immediately; dropped players sit on waivers ~24h (tool marks them `W`).
  Waiver timing is approximate - confirm on ESPN before relying on a waiver claim for a specific game.

## How values are computed
- **Rate** = rest-of-season FP/G: current-season average shrunk toward a prior
  (mean of ESPN projection and last season), weight = games / (games + 8). Early-season rates lean on the prior.
- **Expected** = rate x availability (OUT 0, DTD 0.6, DOUBTFUL 0.25).
- **SOS (matchup strength)** = how players at the same position group (G/F/C) score vs each NBA opponent relative
  to their own rate, last 30 days, shrunk toward neutral. >1 easier, <1 tougher; averaged over a player's remaining
  games this week. It's a **tiebreaker only**, not baked into the rate or week projection.
- **Week projection** = actual points so far + best daily lineup for each remaining day (Hungarian assignment
  over eligible slots). A pickup's weekly value is only the starts it actually adds, not raw games.

## GM policy (owner's instructions)
- **Flex spots first.** Flex = players we added in the last 7 days and still roster (newest first, max 2; 3 in
  aggressive mode). No recent adds -> the lowest-rated player. Everyone else is core and is only dropped when his
  outlook is badly hurt (OUT/DOUBTFUL, availability <= 0.25, no open IR slot) or for a **proven upgrade**: an add with
  8+ games, a rest-of-season rate 3+ FP/G higher, and current form at least as good. Never drop a core player for
  someone less proven.
- Flex moves are judged on **this matchup week and current form** (last-15 blended with the rate), not rest-of-season.
  A move needs >= 10 projected FP added to the week, from starts the add really gets: the week projection runs the
  lineup optimizer over the 10 starting slots, so an add whose position is full or who has no useful games gets nothing.
- The tool recommends the **best single move first**, then re-plans with that move applied for any other flex spot.
  Alternatives are other adds for the same spot. Neck-and-neck (within 3 FP): prefer the easier SOS.
- Move frequency is not a concern - churn flex spots as often as it pays.
- Never recommend players who are OUT or haven't played this season.
- If `drops` shows **3+ UNDERPERFORMING** players (8+ games, season < 80% and last-15 < 85% of prior), tell the owner and
  propose `--mode aggressive` (up to 3 flex spots). Don't switch without their OK.
- Always open/use an empty IR slot for an OUT player before dropping anyone.

## Roster freshness (important for the 2am run)
ESPN's default league view is of ITS current scoring period, which rolls over hours after midnight ET, so a 2am run would see
yesterday's roster and miss an add or drop made the evening before. `League._sync_scoring_period` therefore re-requests the
roster views for the scoring period of the date being reported (one extra request only when ESPN hasn't rolled over yet). The
matchup week likewise comes from our own Monday-Sunday calendar; ESPN's week number is only a sanity check once it has rolled over.

## Morning report (`nightly`)
Prints the finished report in markdown, including two overview sentences generated from the numbers (`overview()` in report.py: last night vs the opponent and projection, the week so far and the model's finish; Mondays: last week's result and the new week's opening projection). The routine replies with it verbatim.
- **Win chance** = 4,000 simulations of the rest of the week: every start draws a real single-game swing (that
  night's FP / player rate, sampled from the last 30 days of games: busts to 2x+ booms), healthy starters miss 5% of
  games, DTD players play 60%, plus a 6% projection-error factor per team. Outlook: 🟢 Strong (80%+), 🟢 Lean W
  (60%+), 🟡 Toss-up, 🟠 Lean L (<40%), 🔴 Weak (<20%).
- **Decided week** (🔒 Guaranteed W / 💀 Loss incoming) needs a stress test, not just a big margin. Win: give the
  opponent its upside (everyone not OUT plays at his better of rate and form, and it streams up to 2 free agents a day
  into idle players' spots) and we must still win 99% of simulations. Loss: give *us* that upside (all our best moves)
  and we must still win no more than 1%. Then the report opens with a DECIDED banner and roster moves say Skip.
- **News & rest watch**: for our roster and the opponent's. 💤 = a back-to-back leg (this week, plus the Monday after
  for a Sun-Mon pair) the player sits 15%+ of the time; 🛌 = news rules him out of one named game; 📰 = status news
  from the last 30 hours (box-score recaps skipped).
- **Back-to-back rest** (`League.rest_profile`): from this season's and last season's NBA game logs + team schedules,
  count each player's healthy back-to-backs (played the games before and after, and at least one leg) and which leg
  he sat. Chance to sit a leg = (sat + 5 x 5%) / (B2Bs + 5). It multiplies his expected FP on that night in every
  projection (lineups, moves, win chance), so e.g. LeBron on the Sunday of a Sun-Mon pair is discounted for the
  matchup's final day.
- **One-game rulings**: ESPN marks a player OUT when he's ruled out of a single game ("ruled out for Wednesday's
  game"), which would zero his week. Latest news like that makes him sit that day only: active after a rest night,
  day-to-day after an injury ruling.
- **Mondays**: separate "Week N final" (🏆/❌) and "Week N+1 preview" sections, plus a set-your-lineups reminder.
- **Bench alert** (red): shown only when our bench scored while some of the 10 starting slots sat empty; the FP is
  what the best hindsight lineup would have added.
- **Projected vs actual** (`fbgm/tracking.py`): each nightly run saves a snapshot (`state/snapshot-DATE.json`: per-team day and
  week projections, per-player projections, win chance). The next report compares last night's projection with the
  actual (team totals, biggest player misses/DNPs), and yesterday's week projection and win chance with today's,
  split into "last night's miss" and "rest of week re-projection". On Mondays it compares the final with Sunday's
  projection. No snapshot -> day numbers are rebuilt from current rosters (labelled) and week deltas are skipped.
  `state/` is an orphan git worktree of the `nightly-state` branch (gitignored on main) that the routine commits and pushes after each run (see docs/nightly-routine.md); without that, tomorrow has nothing to diff.
- **IR watch**: reads Rotowire news for players in our IR slot every run (return timelines like "at least four weeks",
  "mid-December", ESPN status upgrades). Silent while there is no timeline or a return is far off. A timeline's first
  appearance is announced once (re-announced if it moves 3+ days); from `ir_window_days` (14) out, every report shows the
  target date, first game and which flex player to clear. `state/ir_watch.json` remembers the last estimate. **Change alert** (any distance out): if the estimate moves
  `ir_shift_days` (3) or more, either way, it shows ⚠️ PUSHED BACK / MOVED UP with old vs new date; if a previously
  announced timeline disappears (setback, season-ending news) it shows 🚨.
- **Run health** (`fbgm/health.py`): a failure in one report section is contained (the section prints "Unavailable this
  run" and the rest goes out). Data problems - failed news/game-log/schedule/transaction fetches, an unreadable state
  file, a missing snapshot, a tiny player pool, no scoring period for today, a date-mapping mismatch, a scoring
  mismatch - add a "⚠️ data issues" banner under the outlook line and a closing **Health** section. An empty roster or
  missing opponent stops the run with a final `FBGM ERROR (...)` line. `python3 -m fbgm watchdog` (git only) checks the
  `nightly-state` branch for today's `nightly state` commit; run it from a separate routine (docs/watchdog-routine.md).
- **Pre-tip check** (`pretip`, `fbgm/pretip.py`): uses each player's expected FP *for tonight* (rate x availability x
  chance he sits, with one-game rulings from news counted as OUT tonight), keeps locked players where they are, and reports
  `PRETIP OK` (nothing to do), `WATCH` (set, but a starter might sit and a bench player could cover him), or `ACTION`
  (slot changes worth `pretip_min_gain` (10) FP tonight, or an IR player ESPN lists as playable), or `PICKUP` (lineup is
  set but an optional add earns points).
  It only alerts when points are actually at stake: a star who is OUT with no bench cover is silent unless a free
  agent adds 10+ FP tonight AND a flex-pool player who isn't starting tonight can be cut for him (core players, idle or injured, are never offered); at-risk starters are
  only listed when someone could cover; tiny reshuffles are ignored. Changes are only possible for games not yet started.
  Scheduled by docs/pretip-routine.md.
- **Playoff odds** (`fbgm/season.py`, shown in the League table): standings from completed weeks, and playoff odds from 4,000 simulations of every
  remaining week (21 regular-season weeks, top 4 of 8 make the playoffs; ESPN lists playoff weeks 22-23). Team strength =
  power-rankings strength without the record bonus, pulled toward the league mean early in the season, with a weekly score
  spread and an uncertainty about each team's true strength that both shrink as weeks are played. This week's win chance is
  pinned to the nightly's simulation. Shows the odds with a win vs a loss this week (🎯 Must-win when the gap is 15+ pts),
  the next three opponents, and the chance The Godfather finishes ahead of us. (ESPN's own simulation is no longer shown;
  it differed a lot early on.) ASSUMED, not verified: seeding by overall record with ties broken by fewer points against (ESPN's rule is labelled
  only "total points against"); divisions (East/West) are not modelled.
- **Compact report**: the nightly is a quick read. One **Matchup** grid holds last night's projected → actual, today's projection, the
  week so far, the week projection with margin, and the change since yesterday's projection (split into last night's miss and the
  rest of the week); the win chance line also shows yesterday's figure. **News** shows only one-game rulings, rest talk in a
  player's own news (with his back-to-back odds), and fresh status news for players at 30+ FP/G; plain back-to-back odds are in the
  projections but not listed. IR watch is one line per player (the headline only when the date moved). Footnotes are one line.
  Opportunity watch shows 3. A single **League** table (power order with move since yesterday, record, power, last-7 trend,
  playoff odds) plus one summary line (our odds with a win vs a loss and the must-win flag, #1 seed, The Godfather ahead of us,
  next three opponents) replaces the separate Season picture and Power rankings sections. The schedule look-ahead (below) is off by default (`report_lookahead`).
- **Schedule look-ahead** (`fbgm/lookahead.py`, hidden unless `report_lookahead` is on): games per player for the rest of this week and the next 3, marked ▲/▼ for
  heavy/light weeks against the league average, plus our lineup's starts and projected FP against each week's opponent
  (their roster too). Uses today's injury statuses (OUT = 0 in every week). Each recommended move also lists the add's vs
  the drop's games over the next 3 weeks. Informational only: it does not change which moves are recommended.
- **Opportunity watch** (`fbgm/signals.py`, backtested by `tools/backtest_signals.py` on 2025-26 game logs): free agents whose
  role may be growing. Two signals, taking the larger rather than adding them: a minutes surge (last 5 games +5 mpg over the
  10 before; players kept ~66% of the jump next 5 games and beat baseline by ~19%), or a star teammate (rate 40+) who is out
  (bench players scored ~27% more without a star, rotation players ~12%; constants are shaded down in config). Shows the top 5
  with an estimated FP/G uplift. Informational only: it does not feed `advise` or the move ranking.
- **Accuracy data capture**: besides `snapshot-DATE.json` (v2: each player's projection, availability and rest odds, plus
  `me`/`opp`), every nightly run saves `actuals-DATE.json` for the day just played (team points, each player's points, bench
  flag, and the winner when the week ended). A snapshot and actuals file with the same date form one scored day. Both are kept for
  200 days. `python3 -m fbgm accuracy` shows how many scored days exist; the review itself (bias, calibration, rest hit rate)
  starts once `accuracy_min_days` (14) are captured.
- **Power rankings** (FP/week, the League table's Power column): results (season pace 60% / last 7 days 40%) weighted days/(days+21) against roster
  strength (current roster on current form x league games per week), plus 25 FP per game over .500. Arrows compare
  with the ranking as of yesterday (same rosters, one day less of results).

## Giving advice
- Lead with the action, then the numbers (rate, week delta, ROS delta, games left). Keep it short.
- Check `rivals` before recommending a contested FA; note if a rival just dropped/added him.
- Remind about lineup changes for players whose games haven't locked yet.
- This tool is read-only; the owner makes all moves on ESPN.
- Data access works only in the cloud environment (proxy injects ESPN auth; news and NBA game logs come from
  site.api.espn.com, which must be an allowed host). Locally, set `ESPN_S2` and `SWID` cookies.
