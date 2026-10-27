"""League state, player valuation, schedule, and lineup optimization."""
import contextlib
import datetime as dt
import math
import random
from collections import defaultdict
from zoneinfo import ZoneInfo

from . import espn
from .config import AVAILABILITY, BENCH, CONFIG, IR, POLICY, SCORING_CONFIRMED, STAT_GP

ET = ZoneInfo("America/New_York")
POS_GROUP = {1: "G", 2: "G", 3: "F", 4: "F", 5: "C"}  # ESPN defaultPositionId


def fantasy_points(avg_stats, scoring):
    return sum(avg_stats.get(str(sid), 0.0) * pts for sid, pts in scoring.items())


class Player:
    def __init__(self, entry, scoring, season):
        p = entry["player"]
        self.id = p["id"]
        self.name = p["fullName"]
        self.pro_team = p["proTeamId"]
        self.pos_group = POS_GROUP.get(p.get("defaultPositionId"), "F")
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
        # Current form: last-15 average shrunk toward the rate. Used to judge short-term flex moves.
        kf, n15 = POLICY["form_prior_games"], self.gp15
        self.form = (n15 * self.last15_fpg + kf * self.rate) / (n15 + kf) if self.last15_fpg is not None and n15 else self.rate
        self.basis = None   # when set, expected uses it instead of rate (see League.form_basis)

    @property
    def availability(self):
        return AVAILABILITY.get(self.injury, 0.6)

    @property
    def expected(self):
        return (self.rate if self.basis is None else self.basis) * self.availability

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
        self.opponent = {}               # (pro_team, date) -> opposing pro_team
        self.sp_date = {}
        self.pro_abbrev = {}
        for t in espn.pro_schedule():
            self.pro_abbrev[t["id"]] = t["abbrev"]
            for sp, gs in (t.get("proGamesByScoringPeriod") or {}).items():
                for g in gs:
                    start = dt.datetime.fromtimestamp(g["date"] / 1000, ET)
                    self.games[t["id"]][start.date()] = start
                    opp = g["awayProTeamId"] if g["homeProTeamId"] == t["id"] else g["homeProTeamId"]
                    self.opponent[(t["id"], start.date())] = opp
                    self.sp_date[int(sp)] = start.date()
        self.date_sp = {d: sp for sp, d in self.sp_date.items()}
        # Matchup weeks run Monday-Sunday; week 1 is the partial opening week.
        first = min(self.sp_date.values())
        self.week_of = lambda d: ((d - (first - dt.timedelta(days=first.weekday()))).days // 7) + 1
        self.matchup_period = self.raw["status"]["currentMatchupPeriod"]
        week_start = first - dt.timedelta(days=first.weekday()) + dt.timedelta(weeks=self.matchup_period - 1)
        self.week_days = [d for d in (week_start + dt.timedelta(days=i) for i in range(7)) if d >= first]
        self.week_end = lambda period: week_start + dt.timedelta(weeks=period - self.matchup_period, days=6)

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

    def _starts(self, tid, upside):
        """[(FP rate, chance he plays)] for each remaining start in tid's best daily lineups. upside: every
        player who isn't OUT plays, at the better of rate and form, and the team streams free agents."""
        roster = [p for p in self.roster(tid) if p.lineup_slot != IR]
        fas = sorted((p for p in self.free_agents if p.status == "FREEAGENT"
                      and p.availability >= POLICY["add_min_availability"] and p.gp > 0), key=lambda p: -p.form)
        out = []
        for d in self.remaining_days():
            cands = list(roster)
            if upside:
                # Each player without a game that day could be dropped for a streamer who has one.
                idle = sum(1 for p in roster if not self.plays(p, d))
                cands += [p for p in fas if self.plays(p, d)][:min(idle, POLICY["upside_streamers"])]
            for p in self.day_projection(cands, d)[1]:
                if upside:
                    out.append((max(p.rate, p.form), 1.0))
                else:
                    out.append((p.rate, p.availability * (1 - POLICY["dnp_rate"])))
        return out

    def simulate_week(self, upside=None, team_id=None, opp_id=None, sims=None):
        """Monte Carlo of the rest of the week: each start draws a real game-to-game swing (game_ratios),
        each team gets a projection-error factor. upside: team id that gets its best case (see _starts).
        Returns (win chance, sorted final margins)."""
        team_id = team_id or CONFIG["my_team_id"]
        opp_id = opp_id or self.opponent_id(team_id)
        ratios = self.game_ratios() if len(self.game_ratios()) >= 200 else None
        rng = random.Random(f"{self.today}-{upside}")  # same inputs, same answer
        sides = []
        for tid in (team_id, opp_id):
            sides.append((self.week_projection(self.roster(tid), tid)[1], self._starts(tid, tid == upside)))
        margins = []
        sd = POLICY["model_sd_ratio"]
        for _ in range(sims or POLICY["sims"]):
            totals = []
            for done, starts in sides:
                fut = sum(rate * (rng.choice(ratios) if ratios else rng.lognormvariate(-0.08, 0.4))
                          for rate, play in starts if rng.random() < play)
                totals.append(done + fut * max(rng.gauss(1.0, sd), 0.0))
            margins.append(totals[0] - totals[1])
        margins.sort()
        wins = sum(1 for m in margins if m > 0) + 0.5 * sum(1 for m in margins if m == 0)
        return wins / len(margins), margins

    def win_probability(self, team_id=None, opp_id=None):
        """Chance team_id outscores opp_id this week (simulated, normal assumptions)."""
        return self.simulate_week(team_id=team_id, opp_id=opp_id)[0]

    # ---- power rankings -------------------------------------------------
    def games_per_week(self):
        """League-average NBA games per team per 7 days."""
        days = (max(self.sp_date.values()) - min(self.sp_date.values())).days + 1
        teams = [g for g in self.games.values() if g]  # games is a defaultdict; skip teamless lookups
        return 7 * sum(len(g) for g in teams) / (len(teams) * days)

    def power_rankings(self, before=None):
        """[(team_id, info)] best first, from results on days before `before` (default today) and current
        rosters. All values are FP per week except pf (season total)."""
        before = before or self.today
        played = sorted(sp for sp, d in self.sp_date.items() if d < before)
        days = len(played)
        recent = {sp for sp in played if self.sp_date[sp] >= before - dt.timedelta(days=7)}
        info = {tid: {"pf": 0.0, "l7": 0.0, "w": 0, "l": 0, "t": 0} for tid in self.teams}
        for m in self.raw["schedule"]:
            sides = [m[s] for s in ("home", "away") if s in m]
            pts = [{int(k): v for k, v in (s.get("pointsByScoringPeriod") or {}).items()} for s in sides]
            for s, p in zip(sides, pts):
                t = info[s["teamId"]]
                t["pf"] += sum(v for sp, v in p.items() if sp in played)
                t["l7"] += sum(v for sp, v in p.items() if sp in recent)
            # A week counts toward the record once its last day (Sunday) is before the cutoff.
            if len(sides) == 2 and self.week_end(m["matchupPeriodId"]) < before:
                a, b = (s.get("totalPoints", 0.0) for s in sides)
                for s, mine, theirs in ((sides[0], a, b), (sides[1], b, a)):
                    info[s["teamId"]]["w" if mine > theirs else "l" if mine < theirs else "t"] += 1
        gpw = self.games_per_week()
        trust = days / (days + POLICY["power_trust_days"]) if days else 0.0
        rs = POLICY["power_recent_share"]
        with self.form_basis():
            for tid, t in info.items():
                t["pace"] = 7 * t["pf"] / days if days else 0.0
                t["l7"] = 7 * t["l7"] / len(recent) if recent else 0.0
                t["roster"] = gpw * sum(p.expected for p in self.roster(tid) if p.lineup_slot != IR)
                perf = (1 - rs) * t["pace"] + rs * t["l7"]
                t["power"] = trust * perf + (1 - trust) * t["roster"] + POLICY["power_record_fp"] * (t["w"] - t["l"])
        return sorted(info.items(), key=lambda kv: -kv[1]["power"])

    def available_date(self, pl):
        """When a newly added player could first be started."""
        if pl.status == "WAIVERS":
            return self.today + dt.timedelta(days=max(1, round(self.acq.get("waiverHours", 24) / 24)))
        return self.today

    def games_left(self, pl):
        return sum(1 for d in self.remaining_days()
                   if self.plays(pl, d) and not (d == self.today and self.locked(pl, d)))

    def recent_adds(self):
        """{player id: when} for players we added within flex_recent_days (newest info from ESPN)."""
        if not hasattr(self, "_recent_adds"):
            out = {}
            try:
                cutoff = self.now - dt.timedelta(days=POLICY["flex_recent_days"])
                for t in espn.league("mTransactions2").get("transactions", []):
                    if (t.get("status") != "EXECUTED" or t.get("teamId") != CONFIG["my_team_id"]
                            or t.get("type") not in ("FREEAGENT", "WAIVER")):
                        continue
                    when = dt.datetime.fromtimestamp(t["proposedDate"] / 1000, ET)
                    if when < cutoff:
                        continue
                    for it in t["items"]:
                        if it["type"] == "ADD":
                            out[it["playerId"]] = max(when, out.get(it["playerId"], when))
            except Exception:
                out = {}
            self._recent_adds = out
        return self._recent_adds

    def flex_pool(self, mode=None):
        """Spots we're rotating: players we recently added and still have, newest first, up to the
        mode's cap. No recent adds -> the lowest-rated rostered player (plus near-equals)."""
        mode = mode or POLICY["mode"]
        cap = POLICY["flex_slots"][mode]
        mine = [p for p in self.roster() if p.lineup_slot != IR]
        adds = self.recent_adds()
        recent = sorted((p for p in mine if p.id in adds), key=lambda p: adds[p.id], reverse=True)
        if recent:
            return recent[:cap]
        mine.sort(key=lambda p: p.rate)
        if not mine:
            return []
        floor = mine[0].rate + POLICY["flex_margin"]
        return [p for p in mine if p.rate <= floor][:cap]

    @contextlib.contextmanager
    def form_basis(self):
        """Within the block, every player's expected FP uses current form instead of the rate."""
        for p in self.players.values():
            p.basis = p.form
        try:
            yield
        finally:
            for p in self.players.values():
                p.basis = None

    # ---- opponent strength ----------------------------------------------
    def defense(self):
        """{(opp_team, pos_group): factor}: how players score vs each NBA team relative to their
        own rate, over the last DEF_WINDOW days. >1 = easier matchup. Shrunk toward 1.0."""
        if hasattr(self, "_defense"):
            return self._defense
        today_sp = self.date_sp.get(self.today) or max(sp for sp, d in self.sp_date.items() if d < self.today)
        sums = defaultdict(lambda: [0.0, 0])
        self._ratios = []
        for sp in range(max(1, today_sp - POLICY["def_window"]), today_sp):
            day = self.sp_date.get(sp)
            for e in espn.game_logs(sp):
                pl = self.players.get(e["id"])
                if pl is None or pl.rate < POLICY["def_min_rate"]:
                    continue
                line = next((s for s in e["player"].get("stats", []) if s.get("scoringPeriodId") == sp
                             and s.get("statSourceId") == 0 and s.get("stats")), None)
                opp = self.opponent.get((e["player"]["proTeamId"], day))
                if not line or opp is None or not line["stats"].get("40"):  # skip DNPs (0 minutes)
                    continue
                raw = fantasy_points(line["stats"], self.scoring) / pl.rate
                self._ratios.append(raw)
                r = min(raw, 3.0)
                for key in ((opp, None), (opp, pl.pos_group)):
                    sums[key][0] += r
                    sums[key][1] += 1
        k_all, k_pos = POLICY["def_prior_all"], POLICY["def_prior_pos"]
        overall = {opp: (s + k_all) / (n + k_all) for (opp, g), (s, n) in sums.items() if g is None}
        self._defense = {(opp, g): (s + k_pos * overall[opp]) / (n + k_pos)
                         for (opp, g), (s, n) in sums.items() if g is not None}
        self._defense.update({(opp, None): f for opp, f in overall.items()})
        return self._defense

    def game_ratios(self):
        """Single-game FP / player rate for every game played over the look-back window: the real spread of
        nights (busts, 2x booms) that the week simulation samples from."""
        self.defense()
        return self._ratios

    def matchup_factor(self, pl, day):
        opp = self.opponent.get((pl.pro_team, day))
        d = self.defense()
        return d.get((opp, pl.pos_group), d.get((opp, None), 1.0))

    def remaining_games(self, pl):
        return [d for d in self.remaining_days()
                if self.plays(pl, d) and not (d == self.today and self.locked(pl, d))]

    def sos(self, pl):
        """Average matchup factor over this week's remaining games (1.0 = neutral)."""
        games = self.remaining_games(pl)
        return sum(self.matchup_factor(pl, d) for d in games) / len(games) if games else None

    def swap_value(self, add, drop, roster=None):
        """(rest-of-week FP gain on current form, ROS rate gain)."""
        wk, _ = self.evaluate_swap(add, drop, roster)
        return wk, add.rate - drop.rate

    def evaluate_swap(self, add, drop, roster=None):
        """Add `add` for `drop` on `roster` (default: ours), judged on current form and this week's
        schedule. Returns (week FP gain, [(date, slot) for each remaining day the add starts])."""
        roster = roster or self.roster()
        avail = {add: self.available_date(add)}
        new = [p for p in roster if p is not drop] + [add]
        with self.form_basis():
            base = self.week_projection(roster)[2]
            now = self.week_projection(new, available_from=avail)[2]
            starts = []
            for d in self.remaining_days():
                lineup = self.day_projection(new, d, avail)[1]
                if add in lineup:
                    starts.append((d, lineup[add]))
        return now - base, starts
