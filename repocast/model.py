"""Input: structured change data, normalised to Items.

Item = {
  "id": stable id used for dedup (commit SHA for git sources),
  "short": short id, "date": ISO 8601, "title": optional headline,
  "commit_url": link to the change, "url": optional details page,
  "changes": [Change, ...],
  "posts": optional prebuilt post texts (e.g. knoblog's), still gated before use,
  "skip_reason": optional reason the producer already decided not to post,
}
Change = {"name", "old", "new", "kind": changed|added|removed|moved|renamed, "file", "type", "pct_change", "ratio", ...}

Sources: knoblog feed.json (preferred: changes + prebuilt posts per item), knoblog changes.json (+ optional
posts.json), repocast's own items JSON, or `repocast diff` (a simple built-in repo diff).
"""
from __future__ import annotations

import json
import os


class InputError(Exception):
    pass


def _read(path: str):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        raise InputError(f"input file not found: {path}")
    except json.JSONDecodeError as e:
        raise InputError(f"{path}: invalid JSON ({e})")


def _short(sha: str) -> str:
    return sha[:7]


def from_knoblog_feed(data: dict) -> list[dict]:
    items = []
    for it in data.get("items", []):
        kb = it.get("_knoblog") or {}
        sha = kb.get("commit") or it["id"]
        post = kb.get("post") or {}
        items.append({
            "id": sha, "short": _short(sha), "date": it.get("date_published"), "title": it.get("title"),
            "commit_url": kb.get("commit_url") or it.get("external_url"), "url": it.get("url"),
            "changes": kb.get("changes") or [],
            "posts": post.get("posts") if post.get("status") == "ready" else None,
            "skip_reason": post.get("reason") if post.get("status") == "skip" else None,
            "source": "knoblog-feed",
        })
    return items


def from_knoblog_changes(data: dict, posts: dict | None = None) -> list[dict]:
    by: dict[str, dict] = {}
    for c in data.get("changes", []):
        sha = c["commit"]
        it = by.setdefault(sha, {"id": sha, "short": _short(sha), "date": c.get("date"), "commit_url": c.get("commit_url"),
                                 "url": None, "changes": [], "posts": None, "skip_reason": None, "source": "knoblog-changes"})
        it["changes"].append(c)
    for p in (posts or {}).get("posts", []):
        it = by.get(p["sha"])
        if it is None:
            continue  # posts.json mentions commits whose changes are not in changes.json: nothing to verify against
        if p.get("status") == "ready":
            it["posts"] = p["posts"]
        else:
            it["skip_reason"] = p.get("reason")
    return sorted(by.values(), key=lambda i: i["date"] or "")


def from_items(data: dict) -> list[dict]:
    out = []
    for it in data.get("items", []):
        if "id" not in it:
            raise InputError("every item needs an 'id'")
        out.append({"short": _short(str(it["id"])), "url": None, "posts": None, "skip_reason": None, "title": None,
                    "commit_url": None, **it, "changes": it.get("changes") or [], "source": "items"})
    return out


def load(path: str, kind: str = "auto", posts_path: str | None = None) -> list[dict]:
    """Load items from a file. kind: auto | knoblog-feed | knoblog-changes | items."""
    data = _read(path)
    if kind == "auto":
        if isinstance(data, dict) and str(data.get("version", "")).startswith("https://jsonfeed.org"):
            kind = "knoblog-feed"
        elif isinstance(data, dict) and "changes" in data and "items" not in data:
            kind = "knoblog-changes"
        elif isinstance(data, dict) and "items" in data:
            kind = "items"
        else:
            raise InputError(f"{path}: cannot tell the input format (expected a knoblog feed.json/changes.json or repocast items)")
    if kind == "knoblog-feed":
        items = from_knoblog_feed(data)
    elif kind == "knoblog-changes":
        if posts_path is None:
            sib = os.path.join(os.path.dirname(path), "posts.json")
            posts_path = sib if os.path.exists(sib) else None
        items = from_knoblog_changes(data, _read(posts_path) if posts_path else None)
    elif kind == "items":
        items = from_items(data)
    else:
        raise InputError(f"unknown input kind {kind!r}")
    for it in items:
        if not it.get("date"):
            raise InputError(f"item {it['id']} has no date")
    return items
