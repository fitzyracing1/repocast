import unittest

from helpers import ROOT, cfg, item  # noqa: F401
from repocast import gate, runner

CH = [{"name": "threshold", "old": "125000", "new": "180000", "kind": "changed"},
      {"name": "timeout_ms", "old": None, "new": "7200000", "kind": "added"},
      {"name": "weight", "old": "0.02", "new": "0.015"}]


def ok(text, it=None, **kw):
    gate.check([text] if isinstance(text, str) else text, it or item(changes=CH), **kw)


class TestNumberGate(unittest.TestCase):
    def test_exact_values_and_formatting(self):
        ok("threshold 125,000 → 180,000")
        ok("weight 0.02 → 0.015")

    def test_derived_quantities(self):
        ok("threshold up 44%")          # 44.0% exactly
        ok("threshold 1.44x")            # ratio
        ok("+55,000")                    # difference
        ok("timeout 2 hours")            # 7,200,000 ms = 2 h
        ok("weight 25% lower")
        ok("weight 1.3x lower")          # inverse ratio 1.333.. rounded to 1 decimal

    def test_rounding_must_be_honest(self):
        with self.assertRaisesRegex(gate.GateError, "unverified number '45'"):
            ok("threshold up 45%")
        ok("threshold 1.4x")            # 1.44 shown with one decimal
        with self.assertRaisesRegex(gate.GateError, "unverified number '1.5'"):
            ok("threshold 1.5x")

    def test_invented_number_skipped(self):
        with self.assertRaisesRegex(gate.GateError, "unverified number '200,000'"):
            ok("threshold 125,000 → 200,000")
        with self.assertRaisesRegex(gate.GateError, "unverified number '1e6'"):
            ok("threshold 1e6")

    def test_counts_and_dates(self):
        ok("Update (Oct 8, 2026): 3 changes")
        with self.assertRaisesRegex(gate.GateError, "'4'"):
            ok("4 changes")

    def test_template_literals_and_trusted_text(self):
        ok("Top 17: weight 0.02", literal_numbers={17.0})
        with self.assertRaises(gate.GateError):
            ok("Top 17: weight 0.02")
        ok("v2 tracker 99 — weight 0.02", strip=["v2 tracker 99"])

    def test_identifiers_are_not_numbers(self):
        ok("nav2 px4 velocity_smoother/max_accel[0]... weight 0.02", it=item(changes=CH + [{"name": "x", "old": "0", "new": "1"}]))


class TestTextGate(unittest.TestCase):
    def test_mentions_hashtags_domains(self):
        with self.assertRaisesRegex(gate.GateError, "@mention"):
            ok("thanks @someone")
        with self.assertRaisesRegex(gate.GateError, "hashtag"):
            ok("weight 0.02 #ranking")
        ok("weight 0.02 #ranking", allow_hashtags=True)
        with self.assertRaisesRegex(gate.GateError, "domain-like"):
            ok("see params.rs")
        ok("see https://github.com/o/r")
        ok("issue #12 is not a hashtag", it=item(changes=[{"name": "a", "old": "12", "new": "13"}]))

    def test_length_and_thread_size(self):
        with self.assertRaisesRegex(gate.GateError, "281 weighted"):
            ok("x" * 281)
        with self.assertRaisesRegex(gate.GateError, "max_posts=2"):
            ok(["a", "b", "c"], max_posts=2)
        with self.assertRaisesRegex(gate.GateError, "empty"):
            ok(["a", "  "])


class TestComposeGate(unittest.TestCase):
    def test_prebuilt_text_with_invented_number_is_skipped(self):
        it = item(changes=CH, posts=["X update (Oct 8): threshold 125,000 → 180,000 (44% higher)"])
        self.assertIn("posts", runner.compose(it, cfg()))
        it["posts"] = ["X update (Oct 8): threshold 125,000 → 180,000 (50% higher)"]
        res = runner.compose(it, cfg())
        self.assertEqual(res["skip"], "gate: unverified number '50' in post 1: not in the change data")

    def test_template_numbers_in_user_text_are_allowed(self):
        c = cfg(format={"project": "P", "templates": {"header": "P 2.0 watch ({date}): {lead}"}})
        self.assertIn("posts", runner.compose(item(), c))

    def test_template_gate_uses_only_selected_changes(self):
        it = item(changes=CH, posts=["threshold 125,000"])
        c = cfg(format={"mode": "prebuilt"}, filter={"include": "^weight$"})
        self.assertIn("posts", runner.compose(it, c))  # prebuilt may cite any change of the item
        self.assertEqual(runner.compose(item(changes=CH), cfg(filter={"include": "^nope$"}))["skip"], "no matching changes")

    def test_producer_skip_is_honoured(self):
        it = item(skip_reason="bulk change")
        self.assertEqual(runner.compose(it, cfg())["skip"], "producer skipped: bulk change")
        self.assertIn("posts", runner.compose(it, cfg(format={"honor_skips": False})))
