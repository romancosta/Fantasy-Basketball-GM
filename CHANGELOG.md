# Changelog

Notable changes to the nightly report and tooling. Newest first.

## Unreleased
- Foundations (M0): report code split into `fbgm/report.py` and `fbgm/fmt.py`; unit test suite under `tests/`; CI (lint +
  tests) on PRs; `tools/golden_nightly.py` for before/after report comparisons.

## 2026-10-28
- Nightly report: projected vs actual for last night (team and player level), yesterday's week projection and win
  chance vs today's. Snapshots persist on the `nightly-state` branch.
- IR watch: return timeline tracking, with alerts when a return is near, when its estimate moves, or when it disappears.
