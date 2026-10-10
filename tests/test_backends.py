import json
import os
import socket
import tempfile
import unittest

from helpers import CREDS, FakeX, http_error, item
from repocast import backends
from repocast.backends import AccountMismatch, PostError, XApiBackend


def x(fake, **kw):
    return XApiBackend(CREDS, http=fake, **{"account": "MyBot", **kw})


class TestThreads(unittest.TestCase):
    def test_thread_is_reply_chained(self):
        fake = FakeX()
        be = x(fake)
        be.verify()
        ids = be.post_thread(["one", "two", "three"], item())
        self.assertEqual(ids, ["1001", "1002", "1003"])
        self.assertEqual(fake.posts, [{"text": "one"}, {"text": "two", "reply": {"in_reply_to_tweet_id": "1001"}},
                                      {"text": "three", "reply": {"in_reply_to_tweet_id": "1002"}}])
        methods = [(m, u) for m, u, _, _ in fake.requests]
        self.assertEqual(methods[0], ("GET", "https://api.x.com/2/users/me"))
        self.assertTrue(all(u == "https://api.x.com/2/tweets" and m == "POST" for m, u in methods[1:]))
        for _, _, _, h in fake.requests:
            self.assertTrue(h["Authorization"].startswith("OAuth "))
            self.assertIn('oauth_consumer_key="ck"', h["Authorization"])
            self.assertIn('oauth_token="t"', h["Authorization"])

    def test_4xx_is_definite_and_keeps_partial_ids(self):
        be = x(FakeX(fail={2: http_error(403)}))
        be.verify()
        with self.assertRaises(PostError) as cm:
            be.post_thread(["a", "b", "c"], item())
        self.assertTrue(cm.exception.definite)
        self.assertEqual(cm.exception.ids, ["1001"])
        self.assertIn("HTTP 403", str(cm.exception))

    def test_timeout_and_5xx_are_uncertain(self):
        for exc in (socket.timeout("timed out"), ConnectionResetError(), http_error(503)):
            be = x(FakeX(fail={1: exc}))
            be.verify()
            with self.assertRaises(PostError) as cm:
                be.post_thread(["a"], item())
            self.assertFalse(cm.exception.definite, exc)


class TestAccountCheck(unittest.TestCase):
    def test_wrong_account_is_refused(self):
        fake = FakeX(me={"id": "7", "username": "SomeoneElse"})
        be = x(fake)
        with self.assertRaisesRegex(AccountMismatch, "@SomeoneElse.*@MyBot"):
            be.verify()
        self.assertEqual(fake.posts, [])

    def test_username_is_case_insensitive_and_at_optional(self):
        x(FakeX(me={"id": "42", "username": "mybot"}), account="@MyBot").verify()

    def test_account_id_must_match_too(self):
        with self.assertRaisesRegex(AccountMismatch, "user id 42"):
            x(FakeX(), account_id="43").verify()
        x(FakeX(), account=None, account_id="42").verify()

    def test_unverifiable_is_refused(self):
        with self.assertRaisesRegex(AccountMismatch, "could not verify"):
            x(FakeX(me=http_error(401))).verify()

    def test_cannot_post_before_verify(self):
        fake = FakeX()
        with self.assertRaises(AccountMismatch):
            x(fake).post_thread(["a"], item())
        self.assertEqual(fake.requests, [])

    def test_account_is_required(self):
        with self.assertRaisesRegex(ValueError, "account"):
            XApiBackend(CREDS, http=FakeX())
        with self.assertRaisesRegex(ValueError, "missing credentials: X_ACCESS_TOKEN"):
            XApiBackend({**CREDS, "X_ACCESS_TOKEN": ""}, account="a")


class TestOutbox(unittest.TestCase):
    def test_outbox_writes_files_and_never_calls_network(self):
        with tempfile.TemporaryDirectory() as d:
            be = backends.make("outbox", {"outbox": d}, {})
            self.assertFalse(be.live)
            be.post_thread(["p1", "p2 🤖"], item())
            be.post_thread(["q"], item(id="b" * 40))
            lines = open(os.path.join(d, "outbox.jsonl")).read().splitlines()
            self.assertEqual(json.loads(lines[0])["posts"], ["p1", "p2 🤖"])
            self.assertEqual(json.loads(lines[0])["weighted_lengths"], [2, 5])
            feed = json.load(open(os.path.join(d, "outbox.json")))
            self.assertEqual([i["id"] for i in feed["items"]], ["b" * 40, "a" * 40])
            self.assertIn("--- reply ---", open(os.path.join(d, "outbox.txt")).read())


class PluginBackend(backends.Backend):
    name = "plugin"

    def __init__(self, env=None, log=None, **opts):
        self.sent = []

    def post_thread(self, posts, item):
        self.sent.append(posts)
        return ["p1"]


class TestPlugin(unittest.TestCase):
    def test_module_class(self):
        be = backends.make("test_backends:PluginBackend", {}, {})
        self.assertEqual(be.post_thread(["a"], item()), ["p1"])
        with self.assertRaises(ValueError):
            backends.make("nope", {}, {})
