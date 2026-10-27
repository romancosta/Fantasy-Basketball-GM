"""League state, player valuation, schedule, and lineup optimization."""
import datetime as dt
from collections import defaultdict
from zoneinfo import ZoneInfo

from . import espn
from .config import AVAILABILITY, BENCH, CONFIG, IR, POLICY, SCORING_CONFIRMED, STAT_GP

ET = ZoneInfo("America/New_York")


def fantasy_points(avg_stats, scoring):
    return sum(avg_stats.get(str(sid), 0.0) * pts for sid, pts in scoring.items())


class Player:
    def __init__(self, entry, scoring, season):
        p = entry["player"]
        self.id = p["id"]
        self.name = p["fullName"]
        self.pro_team = p["proTeamId"]
        self.slots = set(p["eligibleSlots"]) - {BENCH, IR}
        self.ir_eligible = IR in p["eligibleSlots"]
        self.injury = p.get("injuryStatus") or "ACTIVE"
        self.status = entry.get("status")              # ONTEAM / FREEAGENT / WAIVERS
        self.team_id = entry.get("onTeamId", 0)
        self.owned = p.get("ownership", {}).get("percentOwned", 0.0)
        self.lineup_slot = None
        self._rates(p.get("stats", []), scoring, season)

    def _rates(self, stats, scoring, season):
        by_id = {s["id"]: s for s in stats}

        def actual(split, yr):
            s = by_id.get(f"0{split}{yr}")
            if not s or not s.get("averageStats"):
                return None, 0
            avg = s["averageStats"]
            return fantasy_points(avg, scoring), int(avg.get(STAT_GP, 0))

        self.season_fpg, self.gp = actual(0, season)
        self.last15_fpg, self.gp15 = actual(2, season)
        self.last_year_fpg, gp_ly = actual(0, season - 1)
        proj = by_id.get(f"10{season}")
        self.proj_fpg = proj.get("appliedAverage") if proj else None

        priors = [x for x in (self.proj_fpg, self.last_year_fpg if gp_ly >= 20 else None) if x]
        self.prior = sum(priors) / len(priors) if priors else (self.season_fpg or 0.0)
        k, n = POLICY["prior_games"], self.gp
        cur = self.season_fpg or 0.0
        self.rate = (n * cur + k * self.prior) / (n + k) if (n + k) else 0.0

    @property
    def availability(self):
        return AVAILABILITY.get(self.injury, 0.6)

    @property
    def expected(self):
        return self.rate * self.availability

    @property
    def underperforming(self):
        if self.gp < POLICY["under_min_games"] or not self.prior:
            return False
        recent = self.last15_fpg if self.last15_fpg is not None else self.season_fpg
        return (self.season_fpg < POLICY["under_season_ratio"] * self.prior
                and recent < POLICY["under_recent_ratio"] * self.prior)


def hungarian_max(weights):
    """Max-weight assignment of rows to columns; returns {row: col}. weights[r][c] >= 0."""
    n_r, n_c = len(weights), len(weights[0]) if weights else 0
    n = max(n_r, n_c)
    if n == 0:
        return {}
    big = max((w for row in weights for w in row), default=0)
    cost = [[big - (weights[i][j] if i < n_r and j < n_c else 0) for j in range(n)] for i in range(n)]
    INF = float("inf")
    u, v, p, way = [0] * (n + 1), [0] * (n + 1), [0] * (n + 1), [0] * (n + 1)
    for i in range(1, n + 1):
        p[0], j0 = i, 0
        minv, used = [INF] * (n + 1), [False] * (n + 1)
        while True:
            used[j0] = True
            i0, delta, j1 = p[j0], INF, 0
            for j in range(1, n + 1):
                if not used[j]:
                    cur = cost[i0 - 1][j - 1] - u[i0] - v[j]
                    if cur < minv[j]:
                        minv[j], way[j] = cur, j0
                    if minv[j] < delta:
                        delta, j1 = minv[j], j
            for j in range(n + 1):
                if used[j]:
                    u[p[j]] += delta
                    v[j] -= delta
                else:
                    minv[j] -= delta
            j0 = j1
            if p[j0] == 0:
                break
        while j0:
            j1 = way[j0]
            p[j0] = p[j1]
            j0 = j1
    return {p[j] - 1: j - 1 for j in range(1, n + 1)
            if p[j] and p[j] - 1 < n_r and j - 1 < n_c and weights[p[j] - 1][j - 1] > 0}


def best_lineup(players, slots):
    """players: list of Player (all with a game). slots: list of slot ids. Returns (points, {Player: slot})."""
    if not players or not slots:
        return 0.0, {}
    w = [[pl.expected if s in pl.slots else 0.0 for s in slots] for pl in players]
    assign = hungarian_max(w)
    lineup = {players[r]: slots[c] for r, c in assign.items()}
    return sum(pl.expected for pl in lineup), lineup


class League:
    def __init__(self, today=None):
        now = dt.datetime.now(ET)
        self.now = now if today is None else dt.datetime.combine(today, dt.time(0, 0), ET)
        self.today = self.now.date()
        lg = espn.league("mTeam", "mSettings", "mRoster", "mMatchupScore", "mBoxscore")
        self.raw = lg
        settings = lg["settings"]
        self.scoring = {i["statId"]: i["points"] for i in settings["scoringSettings"]["scoringItems"]}
        self.scoring_mismatch = {
            sid: (self.scoring.get(sid), SCORING_CONFIRMED.get(sid))
            for sid in set(self.scoring) | set(SCORING_CONFIRMED)
            if self.scoring.get(sid) != SCORING_CONFIRMED.get(sid)}
        counts = settings["rosterSettings"]["lineupSlotCounts"]
        self.slots = [int(s) for s, c in counts.items() for _ in range(c) if int(s) not in (BENCH, IR)]
        self.ir_slots = counts.get(str(IR), 0)
        self.teams = {t["id"]: t for t in lg["teams"]}
        self.team_names = {t["id"]: t.get("name") or f"{t.get('location', '')} {t.get('nickname', '')}".strip()
                           for t in lg["teams"]}
        self.acq = settings["acquisitionSettings"]
        self._schedule()
        self._players()

    # ---- schedule -------------------------------------------------------
    def _schedule(self):
        self.games = defaultdict(dict)   # pro_team -> {date: start datetime}
        self.sp_date = {}
        self.pro_abbrev = {}
        for t in espn.pro_schedule():
            self.pro_abbrev[t["id"]] = t["abbrev"]
            for sp, gs in (t.get("proGamesByScoringPeriod") or {}).items():
                for g in gs:
                    start = dt.datetime.fromtimestamp(g["date"] / 1000, ET)
                    self.games[t["id"]][start.date()] = start
                    self.sp_date[int(sp)] = start.date()
        self.date_sp = {d: sp for sp, d in self.sp_date.items()}
        # Matchup weeks run Monday-Sunday; week 1 is the partial opening week.
        first = min(self.sp_date.values())
        self.week_of = lambda d: ((d - (first - dt.timedelta(days=first.weekday()))).days // 7) + 1
        self.matchup_period = self.raw["status"]["currentMatchupPeriod"]
        week_start = first - dt.timedelta(days=first.weekday()) + dt.timedelta(weeks=self.matchup_period - 1)
        self.week_days = [d for d in (week_start + dt.timedelta(days=i) for i in range(7)) if d >= first]

    def game_start(self, player, day):
        return self.games[player.pro_team].get(day)

    def plays(self, player, day):
        return day in self.games[player.pro_team]

    def locked(self, player, day):
        start = self.game_start(player, day)
        return start is not None and start <= self.now

    # ---- players --------------------------------------------------------
    def _players(self):
        pool = espn.players()
        self.players = {e["id"]: Player(e, self.scoring, CONFIG["season"]) for e in pool}
        self.rosters = defaultdict(list)
        for t in self.raw["teams"]:
            for e in t["roster"]["entries"]:
                pid = e["playerId"]
                if pid not in self.players:  # rostered but outside top-N by ownership
                    self.players[pid] = Player({**e["playerPoolEntry"], "status": "ONTEAM",
                                                "onTeamId": t["id"]}, self.scoring, CONFIG["season"])
                pl = self.players[pid]
                pl.lineup_slot = e["lineupSlotId"]
                pl.team_id = t["id"]
                self.rosters[t["id"]].append(pl)
        self.free_agents = [p for p in self.players.values() if p.status in ("FREEAGENT", "WAIVERS")]

    def roster(self, team_id=None):
        return self.rosters[team_id or CONFIG["my_team_id"]]

    def opponent_id(self, team_id=None):
        team_id = team_id or CONFIG["my_team_id"]
        for m in self.matchup_rows():
            ids = (m["home"]["teamId"], m.get("away", {}).get("teamId"))
            if team_id in ids:
                return ids[1] if ids[0] == team_id else ids[0]

    def matchup_rows(self):
        return [m for m in self.raw["schedule"] if m["matchupPeriodId"] == self.matchup_period]

    def points_so_far(self, team_id):
        for m in self.matchup_rows():
            for side in ("home", "away"):
                if m.get(side, {}).get("teamId") == team_id:
                    return {int(k): v for k, v in (m[side].get("pointsByScoringPeriod") or {}).items()}
        return {}

    # ---- projection -----------------------------------------------------
    def day_projection(self, roster, day, available_from=None):
        """Expected FP from the best lineup on `day`. available_from: {Player: first date usable}."""
        avail = available_from or {}
        slots = list(self.slots)
        cands = []
        for pl in roster:
            if pl.lineup_slot == IR or not self.plays(pl, day) or pl.expected <= 0:
                continue
            if avail.get(pl, day) > day:
                continue
            if day == self.today and self.locked(pl, day):
                # Already-started games count as actual points; a locked starter keeps his slot.
                if pl.lineup_slot is not None and pl.lineup_slot not in (BENCH, IR) and pl.lineup_slot in slots:
                    slots.remove(pl.lineup_slot)
                continue
            cands.append(pl)
        return best_lineup(cands, slots)

    def full_lineup(self, roster, day):
        """Complete slot assignment for `day`: maximize projection, then keep players where they are.
        Locked players stay put. Returns {Player: slot} with unassigned players -> BENCH."""
        slots = list(self.slots)
        fixed, free = {}, []
        for pl in roster:
            if pl.lineup_slot == IR:
                fixed[pl] = IR
            elif day == self.today and self.locked(pl, day):
                fixed[pl] = pl.lineup_slot
                if pl.lineup_slot in slots:
                    slots.remove(pl.lineup_slot)
            else:
                free.append(pl)
        w = [[(1000 * pl.expected if self.plays(pl, day) else 0) + (1 if s == pl.lineup_slot else 0.5)
              if s in pl.slots else 0 for s in slots] for pl in free]
        assign = hungarian_max(w) if free and slots else {}
        out = dict(fixed)
        for r, pl in enumerate(free):
            out[pl] = slots[assign[r]] if r in assign else BENCH
        return out

    def remaining_days(self):
        return [d for d in self.week_days if d >= self.today]

    def week_projection(self, roster, team_id=None, available_from=None):
        actual = self.points_so_far(team_id) if team_id else {}
        done = sum(v for sp, v in actual.items() if self.sp_date.get(sp) and self.sp_date[sp] < self.today)
        today_live = actual.get(self.date_sp.get(self.today), 0.0)
        future = sum(self.day_projection(roster, d, available_from)[0] for d in self.remaining_days())
        return done + today_live + future, done + today_live, future

    def available_date(self, pl):
        """When a newly added player could first be started."""
        if pl.status == "WAIVERS":
            return self.today + dt.timedelta(days=max(1, round(self.acq.get("waiverHours", 24) / 24)))
        return self.today

    def games_left(self, pl):
        return sum(1 for d in self.remaining_days()
                   if self.plays(pl, d) and not (d == self.today and self.locked(pl, d)))

    def flex_pool(self, mode=None):
        """Spots we're willing to rotate: the lowest-rated rostered (non-IR) player, plus any
        others within flex_margin FP/G of him, up to the mode's cap."""
        mode = mode or POLICY["mode"]
        mine = sorted((p for p in self.roster() if p.lineup_slot != IR), key=lambda p: p.rate)
        if not mine:
            return []
        floor = mine[0].rate + POLICY["flex_margin"]
        return [p for p in mine if p.rate <= floor][: POLICY["flex_slots"][mode]]

    def swap_value(self, add, drop):
        roster = self.roster()
        base_total, _, base_future = self.week_projection(roster)
        new = [p for p in roster if p is not drop] + [add]
        _, _, new_future = self.week_projection(new, available_from={add: self.available_date(add)})
        return new_future - base_future, add.rate - drop.rate
