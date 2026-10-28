"""Watchdog: did last night's nightly run persist its state? Needs git and the repo's `nightly-state` branch only
(no ESPN access), so it still works when ESPN is the thing that broke."""
import datetime as dt
import subprocess

from .model import ET


def check_state_commits(entries, now):
    """entries: [(iso commit time, subject)] newest first. now: aware datetime. Returns (ok, message). A run counts
    when a commit named 'nightly state YYYY-MM-DD' exists for today's ET or UTC date (the routine stamps with the
    container's clock, which is UTC)."""
    today_et = now.astimezone(ET).date()
    today_utc = now.astimezone(dt.timezone.utc).date()
    wanted = {f"nightly state {d}" for d in (today_et, today_utc)}
    for when, subject in entries:
        if subject in wanted:
            return True, f"OK: '{subject}' committed {when}"
    last = f"; latest commit is '{entries[0][1]}' from {entries[0][0]}" if entries else "; the branch has no commits"
    return False, f"no 'nightly state {today_et}' commit on the state branch{last}"


def cmd_watchdog(a):
    branch = a.branch
    try:
        subprocess.run(["git", "fetch", "-q", "origin", branch], check=True, capture_output=True, text=True, timeout=60)
        log = subprocess.run(["git", "log", f"origin/{branch}", "-20", "--format=%cI\t%s"], check=True,
                             capture_output=True, text=True, timeout=30).stdout
    except (subprocess.SubprocessError, OSError) as exc:
        detail = (getattr(exc, "stderr", None) or str(exc)).strip()[:200]
        print(f"WATCHDOG ALERT: could not read origin/{branch}: {detail}")
        return 1
    entries = [tuple(line.split("\t", 1)) for line in log.splitlines() if "\t" in line]
    ok, message = check_state_commits(entries, dt.datetime.now(ET))
    print(f"WATCHDOG {'OK' if ok else 'ALERT'}: {message.removeprefix('OK: ')}")
    return 0 if ok else 1
