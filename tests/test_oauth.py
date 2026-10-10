import unittest

from helpers import ROOT  # noqa: F401
from repocast import oauth


class TestOAuth(unittest.TestCase):
    def test_documented_example(self):
        # X developer docs, "Creating a signature" (OAuth 1.0a): expected signature hCtSmYh+iHYCEqBWrE7C7hYmtUk=
        h = oauth.header(
            "POST", "https://api.twitter.com/1.1/statuses/update.json",
            "xvz1evFS4wEEPTGEFPHBog", "kAcSOqF21Fu85e7zjz7ZN2U4ZRhfV3WpwPAoE3Z7kBw",
            "370773112-GmHxMAgYyLbNEtIKZeRNFsMKPR9EyMZeS9weJAEb", "LswwdoUaIvS8ltyTt5jkRh4J50vUPVVHtR2YPi5kE",
            params={"status": "Hello Ladies + Gentlemen, a signed OAuth request!", "include_entities": "true"},
            nonce="kYjzVBB8Y0ZFabxSWbWovY3uYSQ2pTgmZeNu2VS4cg", timestamp="1318622958")
        self.assertIn('oauth_signature="hCtSmYh%2BiHYCEqBWrE7C7hYmtUk%3D"', h)
        self.assertTrue(h.startswith("OAuth "))
        self.assertIn('oauth_signature_method="HMAC-SHA1"', h)

    def test_query_params_are_signed(self):
        a = oauth.header("GET", "https://api.x.com/2/users/me?user.fields=id", "k", "s", "t", "ts", nonce="n", timestamp="1")
        b = oauth.header("GET", "https://api.x.com/2/users/me", "k", "s", "t", "ts", nonce="n", timestamp="1")
        self.assertNotEqual(a, b)

    def test_percent_encoding(self):
        self.assertEqual(oauth.pct("Ladies + Gentlemen"), "Ladies%20%2B%20Gentlemen")
        self.assertEqual(oauth.pct("~-._"), "~-._")
