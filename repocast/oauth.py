"""OAuth 1.0a (RFC 5849) HMAC-SHA1 request signing, stdlib only.

X API v2 accepts OAuth 1.0a *user context* for POST /2/tweets and GET /2/users/me. A JSON request body is not part
of the signature; query parameters are.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import time
import urllib.parse


def pct(s) -> str:
    return urllib.parse.quote(str(s), safe="-._~")


def signature_base(method: str, url: str, params: list[tuple[str, str]]) -> str:
    parts = urllib.parse.urlsplit(url)
    base_url = f"{parts.scheme.lower()}://{parts.netloc.lower()}{parts.path}"
    allp = list(params) + urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    norm = "&".join(f"{k}={v}" for k, v in sorted((pct(k), pct(v)) for k, v in allp))
    return "&".join([method.upper(), pct(base_url), pct(norm)])


def header(method: str, url: str, consumer_key: str, consumer_secret: str, token: str, token_secret: str,
           params: dict | None = None, nonce: str | None = None, timestamp: str | None = None) -> str:
    """The Authorization header value. `params` = form/query params to sign (never a JSON body)."""
    oauth = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": nonce or secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": timestamp or str(int(time.time())),
        "oauth_token": token,
        "oauth_version": "1.0",
    }
    base = signature_base(method, url, list(oauth.items()) + list((params or {}).items()))
    key = f"{pct(consumer_secret)}&{pct(token_secret)}"
    oauth["oauth_signature"] = base64.b64encode(hmac.new(key.encode(), base.encode(), hashlib.sha1).digest()).decode()
    return "OAuth " + ", ".join(f'{pct(k)}="{pct(v)}"' for k, v in sorted(oauth.items()))
