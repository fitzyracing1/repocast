import json
import os
import subprocess
import tempfile
import unittest

from helpers import ROOT, cfg
from repocast import diff, model, runner


def write(d, name, obj):
    p = os.path.join(d, name)
    with open(p, "w") as f:
        json.dump(obj, f)
    return p


CHANGE = {"commit": "a" * 40, "short": "aaaaaaa", "date": "2026-10-08T05:00:00Z", "commit_url": "https://g/c/a",
          "file": "params.yaml", "name": "max_speed", "kind": "changed", "old": "0.5", "new": "0.75"}


class TestLoaders(unittest.TestCase):
    def test_knoblog_changes_plus_posts(self):
        with tempfile.TemporaryDirectory() as d:
            p = write(d, "changes.json", {"generator": "knoblog", "changes": [CHANGE, {**CHANGE, "name": "min_speed", "old": "0.1", "new": "0.2"}]})
            write(d, "posts.json", {"posts": [{"sha": "a" * 40, "status": "ready", "posts": ["max_speed 0.5 → 0.75"]}]})
            its = model.load(p)  # posts.json next to it is picked up automatically
            self.assertEqual(len(its), 1)
            self.assertEqual(len(its[0]["changes"]), 2)
            self.assertEqual(its[0]["posts"], ["max_speed 0.5 → 0.75"])
            self.assertEqual(runner.compose(its[0], cfg())["mode"], "prebuilt")
            self.assertEqual(runner.compose(its[0], cfg(format={"mode": "template", "project": "X"}))["mode"], "template")

    def test_knoblog_feed(self):
        its = model.load(os.path.join(ROOT, "examples", "px4", "feed.json"))
        self.assertTrue(all(i["source"] == "knoblog-feed" for i in its))
        self.assertTrue(any(i["posts"] for i in its) and any(i["skip_reason"] for i in its))

    def test_items_format_and_errors(self):
        with tempfile.TemporaryDirectory() as d:
            its = model.load(write(d, "i.json", {"items": [{"id": "v1.2.0", "date": "2026-10-01", "changes": [CHANGE]}]}))
            self.assertEqual(its[0]["short"], "v1.2.0")
            with self.assertRaisesRegex(model.InputError, "no date"):
                model.load(write(d, "j.json", {"items": [{"id": "x"}]}))
            with self.assertRaisesRegex(model.InputError, "cannot tell"):
                model.load(write(d, "k.json", [1, 2]))
            with self.assertRaisesRegex(model.InputError, "not found"):
                model.load(os.path.join(d, "missing.json"))


def git(repo, *a):
    subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@t", *a], check=True, capture_output=True)


class TestOwnDiff(unittest.TestCase):
    def test_line_parsing(self):
        cases = {"max_speed: 0.5": ("max_speed", "0.5"), "MAX = 10  # comment": ("MAX", "10"),
                 "const LIMIT: u32 = 125_000;": ("LIMIT", "125_000"), "#define GAIN 1.5f": ("GAIN", "1.5f"),
                 '  "retries": 3,': ("retries", "3"), "enabled: true": ("enabled", "true"), "x = f(3)": None}
        for line, want in cases.items():
            self.assertEqual(diff.parse_line(line), want, line)

    def test_ambiguous_keys_are_dropped(self):
        out = diff.file_changes(["-a: 1", "+a: 2", "-gain: 1", "-gain: 2", "+gain: 3", "+gain: 4", "+new_key: 5"])
        self.assertEqual(out, [{"name": "a", "kind": "changed", "old": "1", "new": "2"},
                               {"name": "new_key", "kind": "added", "old": None, "new": "5"}])

    def test_diff_repo_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            open(os.path.join(d, "cfg.yaml"), "w").write("max_speed: 0.5\nname: robot\n")
            git(d, "add", ".")
            git(d, "commit", "-qm", "init")
            open(os.path.join(d, "cfg.yaml"), "w").write("max_speed: 0.75\nname: robot\ntimeout_ms: 7200000\n")
            git(d, "commit", "-qam", "faster")
            data = diff.diff_repo(d, "HEAD~1..HEAD", commit_url="https://github.com/o/r/commit/{sha}")
            self.assertEqual(len(data["items"]), 1)
            it = data["items"][0]
            self.assertEqual(it["title"], "faster")
            self.assertEqual([(c["name"], c["old"], c["new"]) for c in it["changes"]],
                             [("max_speed", "0.5", "0.75"), ("timeout_ms", None, "7200000")])
            p = os.path.join(d, "items.json")
            json.dump(data, open(p, "w"))
            res = runner.compose(model.load(p)[0], cfg(format={"project": "Robot"}))
            self.assertIn("max_speed 0.5 → 0.75 (50% higher)", res["posts"][0])
            self.assertIn("timeout_ms = 7,200,000", res["posts"][0])
