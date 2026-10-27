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
