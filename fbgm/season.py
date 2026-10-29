"""Season picture: standings from the schedule results, and Monte Carlo playoff odds from the remaining schedule.
Team strength is the power-rankings strength (results + roster, without the record bonus); every future week is a
normal draw around it. Our current-week win chance is pinned to the nightly's simulated figure."""
import random
from statistics import NormalDist


ND = NormalDist()


def completed_weeks(schedule, period):
    """Matchups finished before `period`: [(period, home id, home pts, away id, away pts)]."""
    out = []
    for m in schedule:
        if m["matchupPeriodId"] < period and "away" in m and m.get("winner") not in (None, "UNDECIDED"):
            out.append((m["matchupPeriodId"], m["home"]["teamId"], m["home"].get("totalPoints", 0.0),
                        m["away"]["teamId"], m["away"].get("totalPoints", 0.0)))
    return out


def standings(schedule, period, team_ids):
    """{team: {w, l, t, pf, pa}} from completed weeks."""
    rec = {t: {"w": 0, "l": 0, "t": 0, "pf": 0.0, "pa": 0.0} for t in team_ids}
    for _, h, hp, a, ap in completed_weeks(schedule, period):
        for t, mine, theirs in ((h, hp, ap), (a, ap, hp)):
            r = rec[t]
            r["pf"] += mine
            r["pa"] += theirs
            r["w" if mine > theirs else "l" if mine < theirs else "t"] += 1
    return rec


def order_key(r):
    """Sort key, best first: wins (ties count half), then points against per the league's tiebreak setting.
    ASSUMPTION: fewer points against ranks higher (ESPN labels the rule only 'total points against')."""
    return (-(r["w"] + 0.5 * r["t"]), r["pa"])


def week_sds(strength, past, ratio):
    """Weekly score spread per team: the share-of-mean prior, pulled toward each team's own observed spread once it
    has 3+ completed weeks."""
    sd = {t: ratio * s for t, s in strength.items()}
    scores = {}
    for _, h, hp, a, ap in past:
        scores.setdefault(h, []).append(hp)
        scores.setdefault(a, []).append(ap)
    for t, xs in scores.items():
        if len(xs) >= 3:
            mean = sum(xs) / len(xs)
            seen = (sum((x - mean) ** 2 for x in xs) / (len(xs) - 1)) ** 0.5
            w = len(xs) / (len(xs) + 3)
            sd[t] = w * seen + (1 - w) * sd[t]
    return sd


def simulate(schedule, period, team_ids, strength, sd, current, me, p_me, n_playoff, rival=None, sims=4000,
             seed="season", strength_sd=None):
    """Playoff odds. current: {team: (points so far this week, share of the week still to play)}. Returns
    {'playoff': {team: share}, 'seed1': {...}, 'wins': {team: expected final wins}, 'rank': {team: [share by rank]},
     'me_if_win': share of sims making playoffs when we win this week, 'me_if_loss': same when we lose,
     'rival_ahead': share of sims where `rival` finishes above us}. strength_sd: {team: spread} - each simulated
    season draws every team's true strength around the estimate, so early ratings aren't taken as gospel."""
    strength_sd = strength_sd or {}
    rng = random.Random(seed)
    base = standings(schedule, period, team_ids)
    # Per team: expected finish of this week, and the future matchups.
    this_week = [m for m in schedule if m["matchupPeriodId"] == period and "away" in m]
    future = [(m["matchupPeriodId"], m["home"]["teamId"], m["away"]["teamId"])
              for m in schedule if m["matchupPeriodId"] > period and "away" in m]
    mu_now = {t: current[t][0] + strength[t] * current[t][1] for t in team_ids}
    sd_now = {t: sd[t] * max(current[t][1], 0.05) ** 0.5 for t in team_ids}
    shift = {t: 0.0 for t in team_ids}
    for m in this_week:       # pin our matchup to the nightly's win chance
        a, b = m["home"]["teamId"], m["away"]["teamId"]
        if me in (a, b) and 0.0 < p_me < 1.0:
            opp = b if a == me else a
            spread = (sd_now[me] ** 2 + sd_now[opp] ** 2) ** 0.5
            gap = ND.inv_cdf(p_me) * spread - (mu_now[me] - mu_now[opp])
            shift[me], shift[opp] = gap / 2, -gap / 2
    out = {"playoff": dict.fromkeys(team_ids, 0), "seed1": dict.fromkeys(team_ids, 0), "wins": dict.fromkeys(team_ids, 0.0),
           "rank": {t: [0] * len(team_ids) for t in team_ids}}
    win_n = loss_n = win_in = loss_in = rival_ahead = 0
    for _ in range(sims):
        r = {t: dict(v) for t, v in base.items()}
        won_now = None
        true = {t: strength[t] + rng.gauss(0.0, strength_sd.get(t, 0.0)) for t in team_ids}
        for m in this_week:
            a, b = m["home"]["teamId"], m["away"]["teamId"]
            sa = rng.gauss(mu_now[a] + shift[a] + (true[a] - strength[a]) * current[a][1], sd_now[a])
            sb = rng.gauss(mu_now[b] + shift[b] + (true[b] - strength[b]) * current[b][1], sd_now[b])
            for t, mine, theirs in ((a, sa, sb), (b, sb, sa)):
                r[t]["pf"] += mine
                r[t]["pa"] += theirs
                r[t]["w" if mine > theirs else "l"] += 1
                if t == me:
                    won_now = mine > theirs
        for _, a, b in future:
            sa, sb = rng.gauss(true[a], sd[a]), rng.gauss(true[b], sd[b])
            for t, mine, theirs in ((a, sa, sb), (b, sb, sa)):
                r[t]["pf"] += mine
                r[t]["pa"] += theirs
                r[t]["w" if mine > theirs else "l"] += 1
        order = sorted(team_ids, key=lambda t: order_key(r[t]))
        for i, t in enumerate(order):
            out["rank"][t][i] += 1
            out["wins"][t] += r[t]["w"] + 0.5 * r[t]["t"]
        for t in order[:n_playoff]:
            out["playoff"][t] += 1
        out["seed1"][order[0]] += 1
        if rival is not None and order.index(rival) < order.index(me):
            rival_ahead += 1
        if won_now is not None:
            if won_now:
                win_n += 1
                win_in += me in order[:n_playoff]
            else:
                loss_n += 1
                loss_in += me in order[:n_playoff]
    for k in ("playoff", "seed1", "wins"):
        out[k] = {t: v / sims for t, v in out[k].items()}
    out["rank"] = {t: [x / sims for x in v] for t, v in out["rank"].items()}
    out["me_if_win"] = win_in / win_n if win_n else None
    out["me_if_loss"] = loss_in / loss_n if loss_n else None
    out["rival_ahead"] = rival_ahead / sims if rival is not None else None
    return out
