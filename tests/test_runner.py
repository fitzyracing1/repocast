import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from helpers import CREDS, FakeX, cfg, http_error, item
from repocast import runner
from repocast.backends import DryRunBackend, OutboxBackend, XApiBackend

NOW = datetime(2026, 10, 9, 15, 0, tzinfo=timezone.utc)
LIVE = {"REPOCAST_LIVE": "true", **CREDS}


def ids(n, start=0):
    return [f"{i:040x}" for i in range(start + 1, start + n + 1)]


def items(n, start=0, hours_ago=1):
    return [item(id=i, date=(NOW - timedelta(hours=hours_ago, minutes=k)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 changes=[{"name": f"p{k}", "old": "1", "new": str(k + 2)}]) for k, i in enumerate(ids(n, start))]


def live_state(handled=()):
    return {"version": 1, "live_since": "2026-10-01T00:00:00Z", "items": {i: {"short": i[:7], "date": "", "status": "baseline", "at": "2026-10-01T00:00:00Z"} for i in handled}}


def quiet(*a, **k):
    pass


def x(fake=None):
    fake = fake or FakeX()
    return XApiBackend(CREDS, account="MyBot", http=fake), fake


class TestBaseline(unittest.TestCase):
    def test_first_run_posts_nothing(self):
        be, fake = x()
        st, acts, changed = runner.run(items(3), cfg(), None, LIVE, NOW, be, quiet)
        self.assertEqual(acts, [{"action": "baseline", "count": 3}])
        self.assertTrue(changed)
        self.assertEqual({r["status"] for r in st["items"].values()}, {"baseline"})
        self.assertEqual(fake.requests, [])

    def test_first_live_run_after_dry_runs_posts_nothing(self):
        st = {"version": 1, "live_since": None, "items": {}}
        be, fake = x()
        st, acts, _ = runner.run(items(2), cfg(), st, LIVE, NOW, be, quiet)
        self.assertEqual(acts[0]["action"], "baseline")
        self.assertIsNotNone(st["live_since"])
        self.assertEqual(fake.requests, [])


class TestSwitches(unittest.TestCase):
    def test_kill_switch(self):
        be, fake = x()
        st, acts, changed = runner.run(items(2), cfg(), live_state(), {**LIVE, "REPOCAST_KILL_SWITCH": "true"}, NOW, be, quiet)
        self.assertEqual(acts, [{"action": "killed"}])
        self.assertFalse(changed)
        self.assertEqual(fake.requests, [])

    def test_kill_switch_env_name_is_configurable(self):
        be, fake = x()
        _, acts, _ = runner.run(items(1), cfg(post={"kill_switch_env": "STOP"}), live_state(), {**LIVE, "STOP": "1"}, NOW, be, quiet)
        self.assertEqual(acts, [{"action": "killed"}])

    def test_live_backend_without_live_env_is_a_dry_run(self):
        be, fake = x()
        st = live_state()
        st2, acts, changed = runner.run(items(1), cfg(), st, CREDS, NOW, be, quiet)
        self.assertEqual(acts[0]["action"], "would_post")
        self.assertFalse(changed)
        self.assertEqual(fake.requests, [])
        self.assertEqual(st2["items"], {})

    def test_quiet_hours_defer(self):
        c = cfg(post={"quiet_hours": "22:00-07:00", "timezone": "America/New_York"})
        be, fake = x()
        late = datetime(2026, 10, 10, 3, 30, tzinfo=timezone.utc)  # 23:30 New York
        _, acts, changed = runner.run(items(1), c, live_state(), LIVE, late, be, quiet)
        self.assertEqual(acts, [{"action": "quiet_hours"}])
        self.assertEqual(fake.requests, [])
        _, acts, _ = runner.run(items(1), c, live_state(), LIVE, NOW, be, quiet)  # 11:00 New York
        self.assertEqual(acts[0]["action"], "posted")

    def test_quiet_hours_window(self):
        tz = runner.ZoneInfo("UTC")
        at = lambda h, m=0: datetime(2026, 1, 1, h, m, tzinfo=timezone.utc)  # noqa: E731
        self.assertTrue(runner.in_quiet_hours(at(23), "22:00-07:00", tz))
        self.assertTrue(runner.in_quiet_hours(at(6, 59), "22:00-07:00", tz))
        self.assertFalse(runner.in_quiet_hours(at(7), "22:00-07:00", tz))
        self.assertTrue(runner.in_quiet_hours(at(13), "12:00-14:00", tz))
        self.assertFalse(runner.in_quiet_hours(at(13), "", tz))


class TestDedupAndCaps(unittest.TestCase):
    def test_posts_once_then_never_again(self):
        be, fake = x()
        its = items(1)
        st, acts, _ = runner.run(its, cfg(), live_state(), LIVE, NOW, be, quiet)
        self.assertEqual(acts[0]["action"], "posted")
        self.assertEqual(st["items"][its[0]["id"]]["post_ids"], ["1001"])
        st, acts, changed = runner.run(its, cfg(), st, LIVE, NOW, be, quiet)
        self.assertEqual(acts, [])
        self.assertFalse(changed)
        self.assertEqual(len(fake.posts), 1)

    def test_state_survives_disk_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "s", "state.json")
            be, fake = x()
            st, _, _ = runner.run(items(1), cfg(), live_state(), LIVE, NOW, be, quiet)
            runner.save_state(path, st)
            st, acts, _ = runner.run(items(1), cfg(), runner.load_state(path), LIVE, NOW, be, quiet)
            self.assertEqual(acts, [])
            self.assertFalse(os.path.exists(path + ".tmp"))

    def test_identical_text_is_not_posted_twice(self):
        be, fake = x()
        a, b = items(2)
        b["changes"] = a["changes"]
        b["date"], b["commit_url"] = a["date"], a["commit_url"]
        st, acts, _ = runner.run([a, b], cfg(post={"max_per_run": 5}), live_state(), LIVE, NOW, be, quiet)
        self.assertEqual([x["action"] for x in acts], ["posted", "skip"])
        self.assertEqual(acts[1]["reason"], "duplicate text")

    def test_per_run_cap(self):
        be, fake = x()
        st, acts, _ = runner.run(items(3), cfg(post={"max_per_run": 1}), live_state(), LIVE, NOW, be, quiet)
        self.assertEqual([a["action"] for a in acts], ["posted", "defer", "defer"])
        self.assertEqual(len(fake.posts), 1)

    def test_per_day_cap_counts_earlier_runs(self):
        be, fake = x()
        c = cfg(post={"max_per_run": 5, "max_per_day": 3})
        st = live_state()
        st["items"]["f" * 40] = {"short": "fffffff", "date": "", "status": "posted", "at": "2026-10-09T01:00:00Z"}
        st, acts, _ = runner.run(items(4), c, st, LIVE, NOW, be, quiet)
        self.assertEqual([a["action"] for a in acts], ["posted", "posted", "defer", "defer"])
        st, acts, _ = runner.run(items(4), c, st, LIVE, NOW + timedelta(days=1), be, quiet)
        self.assertEqual([a["action"] for a in acts], ["posted", "posted"])  # next day: the deferred ones go out

    def test_stale_items_are_skipped(self):
        be, fake = x()
        st, acts, _ = runner.run(items(1, hours_ago=100), cfg(), live_state(), LIVE, NOW, be, quiet)
        self.assertEqual(acts[0], {"action": "skip", "id": ids(1)[0], "reason": "stale"})
        self.assertEqual(fake.requests, [])

    def test_gate_failures_are_skipped_with_reason(self):
        be, fake = x()
        it = item(date="2026-10-09T14:00:00Z", posts=["Big news: 999 → 1000"])
        st, acts, _ = runner.run([it], cfg(), live_state(), LIVE, NOW, be, quiet)
        self.assertEqual(acts[0]["action"], "skip")
        self.assertIn("unverified number '999'", acts[0]["reason"])
        self.assertEqual(st["items"][it["id"]]["status"], "skipped")
        self.assertEqual(fake.requests, [])


class TestFailures(unittest.TestCase):
    def test_uncertain_is_never_retried(self):
        be, fake = x(FakeX(fail={1: TimeoutError("read timed out")}))
        st, acts, _ = runner.run(items(1), cfg(), live_state(), LIVE, NOW, be, quiet)
        self.assertEqual(acts[0]["action"], "uncertain")
        self.assertEqual(st["items"][ids(1)[0]]["status"], "uncertain")
        st, acts, _ = runner.run(items(1), cfg(), st, LIVE, NOW, be, quiet)
        self.assertEqual(acts, [])
        self.assertEqual(sum(1 for r in fake.requests if r[0] == "POST"), 1)  # the one attempt, never repeated

    def test_definite_failure_retried_up_to_max_attempts(self):
        fake = FakeX(fail={1: http_error(429), 2: http_error(429)})
        be, _ = x(fake)
        c = cfg(post={"max_attempts": 2})
        st, acts, _ = runner.run(items(1), c, live_state(), LIVE, NOW, be, quiet)
        self.assertEqual(acts[0]["action"], "failed")
        fake.fail = {1: http_error(429)}
        st, acts, _ = runner.run(items(1), c, st, LIVE, NOW, be, quiet)
        self.assertEqual(acts[0]["action"], "failed")
        self.assertEqual(st["items"][ids(1)[0]]["attempts"], 2)
        st, acts, _ = runner.run(items(1), c, st, LIVE, NOW, be, quiet)
        self.assertEqual(acts, [])  # attempts exhausted

    def test_partial_thread_is_recorded_and_not_retried(self):
        be, fake = x(FakeX(fail={2: http_error(400)}))
        it = item(id="c" * 40, date="2026-10-09T14:00:00Z", posts=["max_speed 0.5", "→ 0.75"])
        st, acts, _ = runner.run([it], cfg(), live_state(), LIVE, NOW, be, quiet)
        self.assertEqual(acts[0]["action"], "partial")
        self.assertEqual(st["items"][it["id"]]["post_ids"], ["1001"])
        st, acts, _ = runner.run([it], cfg(), st, LIVE, NOW, be, quiet)
        self.assertEqual(acts, [])


class TestAccountGuard(unittest.TestCase):
    def test_run_aborts_before_any_post_on_wrong_account(self):
        be, fake = x(FakeX(me={"id": "1", "username": "NotMyBot"}))
        st, acts, _ = runner.run(items(2), cfg(post={"max_per_run": 2}), live_state(), LIVE, NOW, be, quiet)
        self.assertEqual(acts[-1]["action"], "abort")
        self.assertIn("@NotMyBot", acts[-1]["reason"])
        self.assertEqual([r[0] for r in fake.requests], ["GET"])
        self.assertEqual(st["items"], {})  # nothing recorded: it will be tried again once fixed

    def test_verified_once_per_run(self):
        be, fake = x()
        runner.run(items(2), cfg(post={"max_per_run": 2}), live_state(), LIVE, NOW, be, quiet)
        self.assertEqual([r[0] for r in fake.requests], ["GET", "POST", "POST"])

    def test_no_api_call_when_nothing_to_post(self):
        be, fake = x()
        runner.run(items(1), cfg(), live_state(ids(1)), LIVE, NOW, be, quiet)
        self.assertEqual(fake.requests, [])


class TestOtherBackends(unittest.TestCase):
    def test_outbox_records_state(self):
        with tempfile.TemporaryDirectory() as d:
            st, acts, changed = runner.run(items(1), cfg(), {"version": 1, "live_since": None, "items": {}}, {}, NOW, OutboxBackend(d), quiet)
            self.assertEqual(acts[0]["action"], "posted")
            self.assertTrue(changed)
            self.assertTrue(os.path.exists(os.path.join(d, "outbox.jsonl")))

    def test_dry_run_records_nothing(self):
        st, acts, changed = runner.run(items(1), cfg(), live_state(), {}, NOW, DryRunBackend(log=quiet), quiet)
        self.assertEqual(acts[0]["action"], "would_post")
        self.assertFalse(changed)
