"""ESPN fantasy basketball API access with a short-lived on-disk cache."""
import hashlib
import json
import os
import time
import urllib.request

from .config import CONFIG

HOST = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/fba"
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".cache")
CACHE_TTL = 300  # seconds
FRESH = False  # set by --fresh


def _get(url, headers=None, ttl=CACHE_TTL):
    key = hashlib.sha1((url + json.dumps(headers or {}, sort_keys=True)).encode()).hexdigest()
    path = os.path.join(CACHE_DIR, key + ".json")
    if (ttl is None or not FRESH) and os.path.exists(path) and (ttl is None or time.time() - os.path.getmtime(path) < ttl):
        with open(path) as f:
            return json.load(f)
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    # ESPN cookies for private leagues when run outside the cloud env (proxy injects them there).
    if os.environ.get("ESPN_S2") and os.environ.get("SWID"):
        req.add_header("Cookie", f"espn_s2={os.environ['ESPN_S2']}; SWID={os.environ['SWID']}")
    with urllib.request.urlopen(req, timeout=60) as r:
        data = json.load(r)
    os.makedirs(CACHE_DIR, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f)
    return data


def league(*views, scoring_period=None):
    q = "&".join(f"view={v}" for v in views)
    if scoring_period:
        q += f"&scoringPeriodId={scoring_period}"
    url = f"{HOST}/seasons/{CONFIG['season']}/segments/0/leagues/{CONFIG['league_id']}?{q}"
    return _get(url)


def players(statuses=("ONTEAM", "FREEAGENT", "WAIVERS"), limit=500, scoring_period=None):
    filt = {"players": {
        "filterStatus": {"value": list(statuses)},
        "limit": limit,
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
    }}
    q = "view=kona_player_info" + (f"&scoringPeriodId={scoring_period}" if scoring_period else "")
    url = f"{HOST}/seasons/{CONFIG['season']}/segments/0/leagues/{CONFIG['league_id']}?{q}"
    return _get(url, {"x-fantasy-filter": json.dumps(filt)})["players"]


def pro_schedule():
    return _get(f"{HOST}/seasons/{CONFIG['season']}?view=proTeamSchedules_wl")["settings"]["proTeams"]


def game_logs(scoring_period, limit=500):
    """Every rostered/available player's stat line for one past scoring period. Cached indefinitely."""
    filt = {"players": {
        "limit": limit,
        "filterStatsForCurrentSeasonScoringPeriodId": {"value": [scoring_period]},
        "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
    }}
    url = (f"{HOST}/seasons/{CONFIG['season']}/segments/0/leagues/{CONFIG['league_id']}"
           f"?view=kona_player_info&scoringPeriodId={scoring_period}")
    return _get(url, {"x-fantasy-filter": json.dumps(filt)}, ttl=None)["players"]


SITE = "https://site.api.espn.com/apis"


def news(player_id, limit=10):
    """Recent Rotowire/ESPN news items for one player, newest first."""
    return _get(f"{SITE}/fantasy/v2/games/fba/news/players?limit={limit}&playerId={player_id}").get("feed", [])


def gamelog(player_id, season):
    """A player's NBA game log for a season (games he played). Past seasons cached indefinitely."""
    ttl = None if season < CONFIG["season"] else CACHE_TTL
    return _get(f"{SITE}/common/v3/sports/basketball/nba/athletes/{player_id}/gamelog?season={season}", ttl=ttl)


def team_schedule(team_id, season):
    """An NBA team's regular-season schedule. Past seasons cached indefinitely."""
    ttl = None if season < CONFIG["season"] else CACHE_TTL
    return _get(f"{SITE}/site/v2/sports/basketball/nba/teams/{team_id}/schedule?season={season}", ttl=ttl).get("events", [])
