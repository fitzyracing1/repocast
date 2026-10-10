import unittest

from helpers import ROOT  # noqa: F401
from repocast.weight import bare_domains, fits, weighted_len


class TestWeight(unittest.TestCase):
    def test_ascii(self):
        self.assertEqual(weighted_len("hello world"), 11)

    def test_urls_count_23(self):
        self.assertEqual(weighted_len("https://example.com/" + "x" * 200), 23)
        self.assertEqual(weighted_len("see http://a.co"), 4 + 23)

    def test_bare_domain_counts_as_url(self):
        self.assertEqual(weighted_len("params.rs"), 23)
        self.assertEqual(bare_domains("edit params.rs and https://x.com"), ["params.rs"])

    def test_numbers_are_not_urls(self):
        self.assertEqual(weighted_len("0.015 → 0.02"), 13)

    def test_cjk_and_symbols_weigh_2(self):
        self.assertEqual(weighted_len("日本語"), 6)
        self.assertEqual(weighted_len("→"), 2)
        self.assertEqual(weighted_len("é"), 1)  # Latin-1 supplement is light

    def test_emoji_sequences_weigh_2(self):
        for e in ["👍", "👍🏽", "👨‍👩‍👧‍👦", "🇺🇸", "1️⃣", "❤️", "🤖", "⚙️"]:
            self.assertEqual(weighted_len(e), 2, e)
        self.assertEqual(weighted_len("🤖 bot"), 6)

    def test_nfc(self):
        self.assertEqual(weighted_len("e\u0301"), 1)

    def test_limit(self):
        self.assertTrue(fits("a" * 280))
        self.assertFalse(fits("a" * 281))
        self.assertFalse(fits("日" * 141))
        self.assertTrue(fits("日" * 140))
