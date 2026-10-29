# Changelog

Notable changes to the nightly report and tooling. Newest first.

## Unreleased
- Compact nightly: one Matchup grid (night, today, week, change since yesterday); News limited to significant items; IR watch one line; look-ahead off by default; shorter footnotes; 3 opportunities.
- Accuracy data capture (M6, part 1): snapshots v2, daily actuals files, 200-day retention, `fbgm accuracy` status. The review itself comes after ~14 scored days.
- Opportunity watch (M5): free agents with a minutes surge or a star teammate out, backed by a backtest tool. Informational only.
- Schedule look-ahead (M4): games per player and lineup FP vs each opponent for the next 3 weeks; moves show next-3-week games.
- Season picture (M3): standings, playoff odds, must-win flag and Godfather watch in the nightly.
- Pre-tip lineup check (M2): `fbgm pretip` and a routine that runs before tonight's games lock.
- Monitoring (M1): section failures are contained; silent data failures are counted; data checks; health banner and
  Health section; `fbgm watchdog` and a watchdog routine; `FBGM ERROR` line on fatal failures; nightly routine persists
  state before replying.
- Foundations (M0): report code split into `fbgm/report.py` and `fbgm/fmt.py`; unit test suite under `tests/`; CI (lint +
  tests) on PRs; `tools/golden_nightly.py` for before/after report comparisons.

## 2026-10-28
- Nightly report: projected vs actual for last night (team and player level), yesterday's week projection and win
  chance vs today's. Snapshots persist on the `nightly-state` branch.
- IR watch: return timeline tracking, with alerts when a return is near, when its estimate moves, or when it disappears.
