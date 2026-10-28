# Fantasy-Basketball-GM
GM for a points-based fantasy basketball team.

ESPN league 153490 (Hollywood Beach Ballers). Read-only advice tool + Claude skill.

```
python3 -m fbgm matchup | lineup | advise | fa | drops | swap "<add>" "<drop>" | rivals | check
```
See `.claude/skills/fantasy-gm/SKILL.md` for league rules, valuation model and GM policy.
Python 3.9+ stdlib only. Outside the Claude cloud env, set `ESPN_S2` and `SWID` cookies for API access.

Development: see `CONTRIBUTING.md` and `CHANGELOG.md`. Tests: `python3 -m unittest discover -s tests -t .`
