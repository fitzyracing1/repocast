import io
import json
import os
import contextlib
import tempfile
import unittest

from helpers import ROOT
from repocast import cli, config, model, runner
from repocast.weight import weighted_len

EX = os.path.join(ROOT, "examples")


def preview(name):
    c = config.load(os.path.join(EX, name, "repocast.toml"))
    return runner.preview(model.load(c["input"]["path"], c["input"]["kind"]), c)


class TestExamples(unittest.TestCase):
    def test_x_algorithm_reproduces_xalgochangelog_text(self):
        expected = json.load(open(os.path.join(EX, "x-algorithm", "expected-posts.json")))["posts"]
        ready = {r["id"]: r["posts"] for r in preview("x-algorithm") if "posts" in r}
        self.assertEqual(len(ready), 23)
        self.assertEqual(ready, expected)

    def test_px4_and_nav2_examples(self):
        for name, n in (("px4", 16), ("nav2-template", 23)):
            res = preview(name)
            ready = [r for r in res if "posts" in r]
            self.assertEqual(len(ready), n, name)
            for r in ready:
                self.assertTrue(all(weighted_len(p) <= 280 for p in r["posts"]))

    def test_nav2_template_post(self):
        r = next(r for r in preview("nav2-template") if r["short"] == "af4233c")
        self.assertEqual(r["posts"][0].splitlines()[:2], ["🤖 Nav2 defaults changed (Aug 15) ⚙️",
                                                          "▸ velocity_smoother/max_accel[0]: 2.5 → 3.0 (20% higher)"])


class TestConfig(unittest.TestCase):
    def test_bad_configs(self):
        with tempfile.TemporaryDirectory() as d:
            for body, msg in (('[format]\nmode = "llm"', "mode"), ('[post]\nbackend = "x"', "account"),
                              ('[post]\nquiet_hours = "late"', "quiet_hours"), ('[nope]\n', "unknown section"),
                              ('[format]\ncolour = 1', "unknown key"), ('[format.templates]\nline = "{oops}"', "oops"),
                              ('[post]\ntimezone = "Mars/Base"', "time zone")):
                p = os.path.join(d, "c.toml")
                open(p, "w").write(body)
                with self.assertRaisesRegex(config.ConfigError, msg):
                    config.load(p)


class TestCli(unittest.TestCase):
    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(list(argv))
        return code, out.getvalue(), err.getvalue()

    def test_count(self):
        self.assertEqual(self.run_cli("count", "🤖 hi")[1].strip(), "5/280")
        self.assertEqual(self.run_cli("count", "x" * 281)[0], 1)

    def test_run_x_backend_without_live_is_dry_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as d:
            env = {k: os.environ.pop(k) for k in list(os.environ) if k.startswith(("X_", "REPOCAST_"))}
            try:
                state = os.path.join(d, "state.json")
                code, out, _ = self.run_cli("run", "-c", os.path.join(EX, "x-algorithm", "repocast.toml"), "--state", state)
                self.assertEqual(code, 0)
                self.assertIn("DRY RUN", out + _)
                self.assertFalse(os.path.exists(state))
            finally:
                os.environ.update(env)

    def test_run_outbox_baseline_then_nothing_new(self):
        with tempfile.TemporaryDirectory() as d:
            args = ("run", "-c", os.path.join(EX, "px4", "repocast.toml"), "--state", os.path.join(d, "s.json"), "--outbox", os.path.join(d, "ob"))
            code, out, _ = self.run_cli(*args)
            self.assertEqual(code, 0)
            self.assertIn("no backfill", out)
            st = json.load(open(os.path.join(d, "s.json")))
            self.assertEqual(len(st["items"]), 19)
            code, out, _ = self.run_cli(*args)
            self.assertFalse(os.path.exists(os.path.join(d, "ob")))

    def test_bad_input_exit_code(self):
        self.assertEqual(self.run_cli("preview", "-i", "/nonexistent.json")[0], 2)
