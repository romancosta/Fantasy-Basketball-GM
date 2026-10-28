import contextlib
import io
import unittest

from fbgm import health


class Health(unittest.TestCase):
    def setUp(self):
        health.reset()
        self.addCleanup(health.reset)

    def test_clean_run_renders_nothing(self):
        self.assertEqual((health.render(), health.banner()), ("", None))

    def test_warnings_deduplicate(self):
        health.warn("ESPN pool looks empty")
        health.warn("ESPN pool looks empty")
        self.assertEqual(health.issues(), ["- ⚠️ ESPN pool looks empty"])

    def test_failures_are_counted_per_source(self):
        for _ in range(3):
            health.failed("news feed", OSError("timeout"))
        self.assertEqual(health.issues(), ["- ⚠️ news feed: 3 requests failed, results may be incomplete "
                                           "(first error: OSError: timeout)"])
        self.assertIn("1 data issue ", health.banner())

    def test_section_contains_a_crash(self):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            with health.section("IR watch"):
                raise KeyError("boom")
            print("still running")
        self.assertIn("## IR watch\n- ⚠️ Unavailable this run: KeyError: 'boom'", out.getvalue())
        self.assertIn("still running", out.getvalue())
        self.assertIn("Traceback", err.getvalue())
        self.assertIn("IR watch section failed", health.render())

    def test_section_passes_through_when_fine(self):
        with health.section("x"):
            pass
        self.assertEqual(health.issues(), [])


if __name__ == "__main__":
    unittest.main()
