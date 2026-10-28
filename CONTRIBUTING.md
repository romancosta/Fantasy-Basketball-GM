# Contributing

- One feature = one branch (`feat/<topic>`) and one PR, cut from the latest `main`. Small conventional commits
  (`feat:`, `fix:`, `refactor:`, `test:`, `docs:`, `ci:`, `chore:`).
- Python 3.9+, stdlib only at runtime. Dev tooling: `ruff` (lint) and `unittest` (tests).
- Before pushing: `ruff check . && python3 -m unittest discover -s tests -t .`
- Refactors must not change report output. Warm the cache with `python3 -m fbgm --fresh nightly`, then compare
  `python3 tools/golden_nightly.py` before and after (see the script's docstring).
- Tests must not use the network: build small fake leagues/players in the test, or pure inputs.
- New report sections are informational first; changing advice logic is a separate PR.
- Update `.claude/skills/fantasy-gm/SKILL.md` (rules and report behavior), `docs/nightly-routine.md` (routine steps)
  and `CHANGELOG.md` with each change.
- `main` holds code only. Nightly state lives on the `nightly-state` branch and must never be committed to `main`.

## Layout
- `fbgm/espn.py` data access + cache · `fbgm/model.py` league model, projections, simulation
- `fbgm/gm.py` CLI and advice commands · `fbgm/report.py` recap and nightly report · `fbgm/fmt.py` formatters
- `fbgm/tracking.py` snapshots and IR watch · `tests/` unit tests · `tools/` dev scripts
