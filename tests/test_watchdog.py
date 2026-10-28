import contextlib
import datetime as dt
import io
import unittest
from unittest import mock

from fbgm import gm
from fbgm.model import ET
from fbgm.watchdog import check_state_commits

NOW = dt.datetime(2026, 10, 29, 9, 30, tzinfo=ET)    # 13:30 UTC, same calendar day


class Evaluate(unittest.TestCase):
    def test_todays_commit_passes(self):
        ok, msg = check_state_commits([("2026-10-29T13:05:00+00:00", "nightly state 2026-10-29")], NOW)
        self.assertTrue(ok)
        self.assertIn("nightly state 2026-10-29", msg)

    def test_yesterdays_commit_fails_and_names_the_latest(self):
        ok, msg = check_state_commits([("2026-10-28T13:05:00+00:00", "nightly state 2026-10-28")], NOW)
        self.assertFalse(ok)
        self.assertIn("no 'nightly state 2026-10-29' commit", msg)
        self.assertIn("latest commit is 'nightly state 2026-10-28'", msg)

    def test_utc_date_after_et_evening_also_counts(self):
        late = dt.datetime(2026, 10, 29, 21, 0, tzinfo=ET)    # 01:00 UTC on the 30th
        self.assertTrue(check_state_commits([("x", "nightly state 2026-10-30")], late)[0])

    def test_empty_branch(self):
        ok, msg = check_state_commits([], NOW)
        self.assertFalse(ok)
        self.assertIn("no commits", msg)


class MainErrors(unittest.TestCase):
    def test_fatal_failure_prints_one_plain_error_and_exits_1(self):
        out = io.StringIO()
        with mock.patch.object(gm, "League", side_effect=RuntimeError("ESPN is down")), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                gm.main(["nightly"])
        self.assertEqual(cm.exception.code, 1)
        self.assertEqual(out.getvalue().strip(), "FBGM ERROR (nightly): RuntimeError: ESPN is down")


if __name__ == "__main__":
    unittest.main()
