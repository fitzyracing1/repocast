"""Posting backends.

  x        X API v2: POST /2/tweets (OAuth 1.0a user context), threads chained with reply.in_reply_to_tweet_id.
           Before the first post of a run it calls GET /2/users/me and refuses to post unless the token belongs to the
           configured account.
  outbox   Never posts: appends to an outbox (JSON Lines + a JSON Feed + plain text) for a human or another tool.
  dry-run  Never posts: prints what would be posted.
  plugin   "package.module:ClassName" implementing the Backend interface below.

Every backend's post_thread() returns the list of post ids, or raises PostError(definite=..., ids=[...]).
definite=True means the server clearly refused (nothing was created for the failing post); definite=False means the
outcome is unknown (timeout, connection reset, 5xx) and the runner will NEVER retry it automatically.
"""
from __future__ import annotations

import importlib
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone

from . import __version__, oauth
from .weight import weighted_len

API_BASE = "https://api.x.com/2"
CRED_ENV = ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_TOKEN_SECRET")
USER_AGENT = f"repocast/{__version__}"


class PostError(Exception):
    def __init__(self, msg: str, definite: bool, ids: list[str] | None = None):
        super().__init__(msg)
        self.definite, self.ids = definite, list(ids or [])


class AccountMismatch(Exception):
    """The credentials do not belong to the configured account (or it could not be verified). Nothing is posted."""


class Backend:
    name = "base"
    live = False  # True only for backends that publish somewhere public

    def verify(self) -> str:
        """Check the backend may post; return a description. Raise AccountMismatch to abort the run."""
        return self.name

    def post_thread(self, posts: list[str], item: dict) -> list[str]:
        raise NotImplementedError


class DryRunBackend(Backend):
    name = "dry-run"

    def __init__(self, log=print, **_):
        self.log = log

    def post_thread(self, posts, item):
        for i, p in enumerate(posts, 1):
            self.log(f"--- {item['short']} post {i}/{len(posts)} ({weighted_len(p)}/280) ---\n{p}")
        return [f"dry-run-{item['short']}-{i}" for i in range(1, len(posts) + 1)]


class OutboxBackend(Backend):
    """Writes <dir>/outbox.jsonl (append), <dir>/outbox.json (JSON Feed 1.1 of the last 100) and <dir>/outbox.txt."""
    name = "outbox"

    def __init__(self, path: str = "outbox", **_):
        self.dir = path

    def post_thread(self, posts, item):
        os.makedirs(self.dir, exist_ok=True)
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        rec = {"id": item["id"], "short": item["short"], "date": item["date"], "commit_url": item.get("commit_url"),
               "queued_at": now, "posts": posts, "weighted_lengths": [weighted_len(p) for p in posts]}
        with open(os.path.join(self.dir, "outbox.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        with open(os.path.join(self.dir, "outbox.jsonl"), encoding="utf-8") as f:
            recs = [json.loads(ln) for ln in f if ln.strip()][-100:]
        feed = {"version": "https://jsonfeed.org/version/1.1", "title": "repocast outbox",
                "items": [{"id": r["id"], "url": r.get("commit_url"), "date_published": r["queued_at"],
                           "content_text": "\n\n---\n\n".join(r["posts"]), "_repocast": {"posts": r["posts"]}}
                          for r in reversed(recs)]}
        tmp = os.path.join(self.dir, "outbox.json.tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(feed, f, indent=1, ensure_ascii=False)
        os.replace(tmp, os.path.join(self.dir, "outbox.json"))
        with open(os.path.join(self.dir, "outbox.txt"), "a", encoding="utf-8") as f:
            f.write(f"=== {item['short']} ({item['date']}) ===\n" + "\n--- reply ---\n".join(posts) + "\n\n")
        return [f"outbox-{item['short']}-{i}" for i in range(1, len(posts) + 1)]


def _http_json(req: urllib.request.Request, timeout: int) -> dict:
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


class XApiBackend(Backend):
    name = "x"
    live = True

    def __init__(self, creds: dict, account: str | None = None, account_id: str | None = None,
                 api_base: str = API_BASE, timeout: int = 30, http=_http_json, **_):
        missing = [k for k in CRED_ENV if not (creds.get(k) or "").strip()]
        if missing:
            raise ValueError("missing credentials: " + ", ".join(missing))
        if not account and not account_id:
            raise ValueError("the x backend needs account (username) or account_id so it can refuse to post elsewhere")
        self.creds, self.account, self.account_id = creds, (account or "").lstrip("@"), account_id
        self.api, self.timeout, self.http = api_base.rstrip("/"), timeout, http
        self.verified: dict | None = None

    def _auth(self, method: str, url: str) -> str:
        c = self.creds
        return oauth.header(method, url, c["X_API_KEY"], c["X_API_SECRET"], c["X_ACCESS_TOKEN"], c["X_ACCESS_TOKEN_SECRET"])

    def verify(self) -> str:
        url = f"{self.api}/users/me"
        req = urllib.request.Request(url, method="GET", headers={"Authorization": self._auth("GET", url), "User-Agent": USER_AGENT})
        try:
            data = self.http(req, self.timeout)["data"]
        except Exception as e:  # noqa: BLE001 - any failure means we cannot prove who we are
            raise AccountMismatch(f"could not verify the account via GET /2/users/me: {type(e).__name__}: {e}")
        uname, uid = str(data.get("username", "")), str(data.get("id", ""))
        if self.account and uname.lower() != self.account.lower():
            raise AccountMismatch(f"credentials belong to @{uname}, but the configured account is @{self.account}")
        if self.account_id and uid != str(self.account_id):
            raise AccountMismatch(f"credentials belong to user id {uid}, but the configured account_id is {self.account_id}")
        self.verified = {"username": uname, "id": uid}
        return f"@{uname} ({uid})"

    def create_post(self, text: str, reply_to: str | None) -> str:
        if self.verified is None:
            raise AccountMismatch("refusing to post: account not verified (call verify() first)")
        url = f"{self.api}/tweets"
        body = {"text": text}
        if reply_to:
            body["reply"] = {"in_reply_to_tweet_id": reply_to}
        req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST", headers={
            "Authorization": self._auth("POST", url), "Content-Type": "application/json", "User-Agent": USER_AGENT})
        return str(self.http(req, self.timeout)["data"]["id"])

    def post_thread(self, posts, item):
        ids: list[str] = []
        for text in posts:
            try:
                ids.append(self.create_post(text, ids[-1] if ids else None))
            except AccountMismatch:
                raise
            except urllib.error.HTTPError as e:
                detail = ""
                try:
                    detail = e.read().decode("utf-8", "replace")[:300]
                except Exception:  # noqa: BLE001
                    pass
                # 4xx: the API refused, nothing was created. 5xx: a gateway error can hide a created post -> unknown.
                raise PostError(f"HTTP {e.code}: {detail}", definite=e.code < 500, ids=ids)
            except Exception as e:  # noqa: BLE001 - timeout / reset / bad response: the post may exist
                raise PostError(f"{type(e).__name__}: {e}", definite=False, ids=ids)
        return ids


def make(kind: str, opts: dict, env: dict, log=print) -> Backend:
    if kind == "dry-run":
        return DryRunBackend(log=log)
    if kind == "outbox":
        return OutboxBackend(path=opts.get("outbox", "outbox"))
    if kind == "x":
        return XApiBackend({k: env.get(k, "") for k in CRED_ENV}, account=opts.get("account"),
                           account_id=opts.get("account_id"), api_base=opts.get("api_base", API_BASE))
    if ":" in kind:
        mod, cls = kind.split(":", 1)
        obj = getattr(importlib.import_module(mod), cls)(**opts, env=env, log=log)
        if not isinstance(obj, Backend) and not hasattr(obj, "post_thread"):
            raise TypeError(f"{kind} does not implement post_thread()")
        return obj
    raise ValueError(f"unknown backend {kind!r} (x, outbox, dry-run or module:Class)")
