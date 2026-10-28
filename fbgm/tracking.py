"""Nightly state: projection snapshots (so tomorrow's report can compare projected vs actual) and IR return watch."""
import datetime as dt
import json
import os
import re

from .config import CONFIG, IR, POLICY

STATE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "state")


def _load(name):
    try:
        with open(os.path.join(STATE_DIR, name)) as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _save(name, data):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(os.path.join(STATE_DIR, name), "w") as f:
        json.dump(data, f, indent=1, sort_keys=True)
        f.write("\n")


# ---- projection snapshots ---------------------------------------------------
def snapshot_name(day):
    return f"snapshot-{day}.json"


def load_snapshot(day):
    return _load(snapshot_name(day))


def save_snapshot(lg, proj, today, win_prob, teams):
    """Record this morning's projections. A morning snapshot (no game tipped yet) is refreshed on re-runs; once games
    have started, an existing snapshot is kept so later runs don't overwrite the pre-game numbers."""
    started = any(lg.locked(p, lg.today) for t in teams for p in lg.roster(t))
    if started and load_snapshot(lg.today):
        return
    snap = {"date": str(lg.today), "period": lg.matchup_period, "win_prob": win_prob, "teams": {}}
    for tid in teams:
        _, lineup = lg.day_projection(lg.roster(tid), lg.today)
        players = {}
        for pl in lg.roster(tid):
            if pl.lineup_slot != IR and lg.plays(pl, lg.today) and pl.expected > 0:
                players[pl.name] = {"proj": round(pl.expected * lg.rest_factor(pl, lg.today), 1),
                                    "lineup": pl in lineup}
        snap["teams"][str(tid)] = {"week": round(proj[tid][0], 1), "day": round(today[tid], 1), "players": players}
    _save(snapshot_name(lg.today), snap)
    # Keep the state folder small: only the last few weeks of snapshots matter.
    old = sorted(f for f in os.listdir(STATE_DIR) if f.startswith("snapshot-"))[:-30]
    for f in old:
        os.remove(os.path.join(STATE_DIR, f))


# ---- IR return watch ----------------------------------------------------------
NUM = {"a": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
       "nine": 9, "ten": 10, "twelve": 12}
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
CONTEXT = r"(?:return|back|target|expect|re-?evaluat|re-?assess|available|debut|reappear|rejoin|miss|out|sidelined)"
DURATION = re.compile(rf"\b(?:at least|about|around|roughly|approximately|another|next|for|up to)?\s*"
                      rf"(\d+|{'|'.join(NUM)})(?:-\d+)?\s+(week|month)s?\b", re.I)
DATE = re.compile(rf"\b(early|mid|late)?[- ]?\b({'|'.join(MONTHS)})[a-z]*\.?(?:\s+(\d{{1,2}})\b)?", re.I)
SOON = re.compile(r"return to practice|full[- ]contact|5-on-5|scrimmage|ramp(?:ing)? up|cleared|no restrictions|"
                  r"close to returning|nearing a return|could return|may return|set to return|expected to return|"
                  r"will return|upgraded|game-time|questionable", re.I)
SEASON_ENDING = re.compile(r"out for the season|season-ending|rest of the season|remainder of the season|"
                           r"miss the entire season|torn acl", re.I)


def _published(item):
    return dt.datetime.fromisoformat(item["published"].replace("Z", "+00:00")).date()


def _estimate(item):
    """Return-date guess from one Rotowire item -> {est, kind, soon, season}. est may be None."""
    text = f"{item.get('headline', '')} {item.get('story', '')}"
    pub = _published(item)
    out = {"est": None, "kind": None, "soon": bool(SOON.search(text)), "season": bool(SEASON_ENDING.search(text))}
    for sentence in re.split(r"(?<=[.!?])\s+", text):
        if not re.search(CONTEXT, sentence, re.I):
            continue
        m = DURATION.search(sentence)
        if m:
            n = int(m.group(1)) if m.group(1).isdigit() else NUM[m.group(1).lower()]
            days = n * (7 if m.group(2).lower() == "week" else 30)
            out["est"] = pub + dt.timedelta(days=days)
            out["kind"] = "at least" if re.search(r"at least|minimum", sentence, re.I) else "about"
            return out
        for m in DATE.finditer(sentence):
            mon = MONTHS.index(m.group(2).lower()[:3]) + 1
            if not m.group(3) and not m.group(1):
                continue
            day = int(m.group(3)) if m.group(3) else {"early": 5, "mid": 15, "late": 25}[m.group(1).lower()]
            try:
                d = dt.date(pub.year, mon, min(day, 28 if mon == 2 else 30 if mon in (4, 6, 9, 11) else 31))
            except ValueError:
                continue
            if d < pub - dt.timedelta(days=30):
                d = d.replace(year=d.year + 1)
            out["est"], out["kind"] = d, "targeted"
            return out
    return out


def ir_status(lg):
    """For each of our IR players with a usable timeline: dict with name, est return date, first game, headline.
    Returned: a return within the window, a timeline's first sighting, any shift of the estimate by ir_shift_days+
    (pushed back or moved up, even far out), or a previously announced timeline that has disappeared."""
    window = dt.timedelta(days=POLICY["ir_window_days"])
    seen = _load("ir_watch.json") or {}
    out, new_seen = [], {}
    for pl in lg.roster():
        if pl.lineup_slot != IR:
            continue
        items = [n for n in lg.news(pl)[:8] if re.search(CONTEXT + r"|injur|timetable|weeks?|months?", n.get("headline", ""), re.I)
                 or SOON.search(n.get("story", ""))]
        est = None
        for n in items:
            e = _estimate(n)
            if e["season"]:
                est = {"est": None, "season": True}
                break
            if e["est"] or e["soon"]:
                est = {**e, "headline": n["headline"], "published": _published(n)}
                break
        # ESPN has already upgraded him from OUT while he still sits on IR: he is close.
        upgraded = pl.injury not in ("OUT", "INJURY_RESERVE", "SUSPENSION")
        prev = seen.get(str(pl.id), {})
        prev_est = dt.date.fromisoformat(prev["est"]) if prev.get("est") else None
        lost = None
        if not est or est.get("season"):
            if upgraded:
                est = {"est": lg.today, "kind": "status", "soon": True, "headline": f"ESPN status now {pl.injury}",
                       "published": lg.today}
            else:
                # No usable timeline now. If we had announced one, that is itself news (setback / season-ending).
                head = items[0] if items else None
                if prev_est and head:
                    lost = {"season": bool(est and est.get("season")), "headline": head["headline"],
                            "published": _published(head)}
                    out.append({"player": pl, "est": None, "kind": None, "first": None, "near": False,
                                "headline": lost["headline"], "published": lost["published"], "upgraded": False,
                                "days": None, "prev": prev_est, "shift": None, "lost": lost})
                new_seen[str(pl.id)] = {"name": pl.name, "est": str(prev_est) if prev_est else None,
                                        "lost": bool(lost) or prev.get("lost", False)}
                continue
        target = est["est"] or lg.today
        if upgraded:
            target = min(target, lg.today)
        target = max(target, lg.today) if (est["soon"] and not est["est"]) else target
        first = next((d for d in sorted(lg.games[pl.pro_team]) if d >= max(target, lg.today)), None)
        new_seen[str(pl.id)] = {"name": pl.name, "est": str(target)}
        near = target - lg.today <= window
        shift = (target - prev_est).days if prev_est else None
        moved = shift is not None and abs(shift) >= POLICY["ir_shift_days"]
        if near or prev_est is None or moved:
            out.append({"player": pl, "est": target, "kind": est["kind"] or "about", "first": first, "near": near,
                        "headline": est["headline"], "published": est["published"], "upgraded": upgraded,
                        "days": (target - lg.today).days, "prev": prev_est, "shift": shift if moved else None,
                        "lost": None})
    _save("ir_watch.json", new_seen)
    return out
