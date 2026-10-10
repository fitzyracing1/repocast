import io
import json
import os
import sys
import urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from repocast import config  # noqa: E402

CREDS = {"X_API_KEY": "ck", "X_API_SECRET": "cs", "X_ACCESS_TOKEN": "t", "X_ACCESS_TOKEN_SECRET": "ts"}


def cfg(**sections):
    """A validated config from DEFAULTS plus overrides: cfg(format={...}, post={...})."""
    return config.load(None, sections)


def item(id="a" * 40, date="2026-10-08T05:00:00Z", changes=None, **kw):
    return {"id": id, "short": id[:7], "date": date, "commit_url": f"https://github.com/o/r/commit/{id}", "url": None,
            "title": None, "posts": None, "skip_reason": None,
            "changes": changes if changes is not None else [{"name": "max_speed", "old": "0.5", "new": "0.75", "kind": "changed"}],
            **kw}


class FakeX:
    """Stands in for the X API. Records every request; `me` is who the token belongs to; `fail` maps the
    n-th POST (1-based) to an exception to raise."""

    def __init__(self, me=None, fail=None):
        self.me = me if me is not None else {"id": "42", "username": "MyBot"}
        self.fail = fail or {}
        self.requests = []
        self.posts = []

    def __call__(self, req, timeout):
        body = json.loads(req.data) if req.data else None
        self.requests.append((req.get_method(), req.full_url, body, dict(req.header_items())))
        if req.full_url.endswith("/users/me"):
            if isinstance(self.me, Exception):
                raise self.me
            return {"data": self.me}
        n = len(self.posts) + 1
        if n in self.fail:
            exc = self.fail.pop(n)
            raise exc
        self.posts.append(body)
        return {"data": {"id": str(1000 + n), "text": body["text"]}}


def http_error(code):
    return urllib.error.HTTPError("https://api.x.com/2/tweets", code, "err", {}, io.BytesIO(b'{"detail":"nope"}'))
