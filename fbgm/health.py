"""Run health: collect data problems and section failures so the report can show them instead of crashing or
silently degrading. Module state is per process (one report per run); call reset() in tests."""
import contextlib
import traceback

WARNINGS = []     # (source, message), de-duplicated, in the order raised
FAILURES = {}     # source -> [count, first error text]


def reset():
    WARNINGS.clear()
    FAILURES.clear()


def warn(message, source="data"):
    if (source, message) not in WARNINGS:
        WARNINGS.append((source, message))


def failed(source, exc):
    """A recoverable data fetch failed (news feed, game log, ...). Counted; shown once per source."""
    entry = FAILURES.setdefault(source, [0, f"{type(exc).__name__}: {exc}"[:120]])
    entry[0] += 1


@contextlib.contextmanager
def section(name):
    """Run one report section; if it raises, print a visible stand-in and record it, so the rest still goes out."""
    try:
        yield
    except Exception as exc:   # noqa: BLE001 - the point is to contain any section failure
        detail = f"{type(exc).__name__}: {exc}"[:200]
        warn(f"{name} section failed ({detail})", source="section")
        print(f"\n## {name}\n- ⚠️ Unavailable this run: {detail}")
        traceback.print_exc()   # stderr: full trace for debugging, not part of the report


def issues():
    """Every problem as a markdown bullet."""
    out = [f"- ⚠️ {msg}" for _, msg in WARNINGS]
    for source, (count, first) in FAILURES.items():
        out.append(f"- ⚠️ {source}: {count} request{'s' * (count != 1)} failed, results may be incomplete "
                   f"(first error: {first})")
    return out


def banner():
    n = len(issues())
    return f"> ⚠️ {n} data issue{'s' * (n != 1)} this run, see **Health** at the bottom." if n else None


def render():
    lines = issues()
    return "\n## Health\n" + "\n".join(lines) if lines else ""
