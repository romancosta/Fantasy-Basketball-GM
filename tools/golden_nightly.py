"""Print the nightly report from cached ESPN data, for before/after comparison when refactoring.

    python3 -m fbgm --fresh nightly >/dev/null      # warm .cache
    python3 tools/golden_nightly.py > before.txt    # on the old code
    python3 tools/golden_nightly.py > after.txt     # on the new code
    cmp before.txt after.txt

Cache entries never expire here, state goes to a throwaway folder, and the date is fixed (default 2026-10-28), so
identical code gives identical output. Not a CI test: the cache is large and local.
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fbgm import espn, tracking  # noqa: E402
from fbgm.gm import main  # noqa: E402

espn.CACHE_TTL = 10 ** 9
tracking.STATE_DIR = tempfile.mkdtemp()
main(["--today", sys.argv[1] if len(sys.argv) > 1 else "2026-10-28", "nightly"])
