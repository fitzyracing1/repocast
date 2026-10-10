"""compose -> gate -> safety checks -> backend. The only module that decides whether something is posted."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from . import fmt, gate
from .backends import AccountMismatch, Backend, DryRunBackend, PostError
from .numbers import TOKEN, parse_num, token_value
from .weight import weighted_len

TS = "%Y-%m-%dT%H:%M:%SZ"
COUNTED = ("posted", "partial", "uncertain")


# ---------------------------------------------------------------- state (dedup)
def load_state(path: str) -> dict | None:
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def text_hash(posts: list[str]) -> str:
    return hashlib.sha256("\n\u241e\n".join(posts).encode()).hexdigest()[:16]


def handled(state: dict, item_id: str, max_attempts: int) -> bool:
    rec = state["items"].get(item_id)
    if rec is None:
        return False
    return not (rec["status"] == "failed" and rec.get("attempts", 0) < max_attempts)


def posted_today(state: dict, now: datetime, tz: ZoneInfo) -> int:
    day = now.astimezone(tz).date()
    n = 0
    for r in state["items"].values():
        if r["status"] in COUNTED and r.get("at"):
            if _dt(r["at"]).astimezone(tz).date() == day:
                n += 1
    return n


def _dt(iso: str) -> datetime:
    d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# ---------------------------------------------------------------- switches
def truthy(v) -> bool:
    return str(v or "").strip().lower() in ("1", "true", "yes", "on")


def in_quiet_hours(now: datetime, spec: str, tz: ZoneInfo) -> bool:
    if not spec:
        return False
    a, b = spec.split("-")
    ah, am = map(int, a.split(":"))
    bh, bm = map(int, b.split(":"))
    t = now.astimezone(tz)
    cur, start, end = t.hour * 60 + t.minute, ah * 60 + am, bh * 60 + bm
    return start <= cur < end if start <= end else (cur >= start or cur < end)


# ---------------------------------------------------------------- compose + gate
def select_changes(item: dict, flt: dict) -> list[dict]:
    out = []
    for c in item.get("changes") or []:
        if c.get("kind", "changed") not in flt["kinds"]:
            continue
        name, path = str(c.get("name", "")), str(c.get("file", ""))
        if flt["include"] and not re.search(flt["include"], name):
            continue
        if flt["exclude"] and re.search(flt["exclude"], name):
            continue
        if flt["files"] and not re.search(flt["files"], path):
            continue
        if flt["exclude_files"] and re.search(flt["exclude_files"], path):
            continue
        if flt["min_pct"] and c.get("kind", "changed") == "changed":
            o, n = parse_num(c.get("old")), parse_num(c.get("new"))
            if o is not None and n is not None and o != 0 and abs(n - o) / abs(o) * 100 < flt["min_pct"]:
                continue
        out.append(c)
    return out


def literal_numbers(fcfg: dict) -> set[float]:
    text = fmt.template_literal_text({**fmt.DEFAULT_TEMPLATES, **fcfg["templates"]}) + "\n" + fcfg["disclaimer"]
    return {abs(v[0]) for t in TOKEN.findall(text) if (v := token_value(t))}


def compose(item: dict, cfg: dict) -> dict:
    """{'posts': [...], 'mode': 'prebuilt'|'template'} or {'skip': reason}. Every returned post passed the gate."""
    f = cfg["format"]
    changes = select_changes(item, cfg["filter"])
    if not changes:
        return {"skip": "no matching changes"}
    if item.get("skip_reason") and f["honor_skips"]:
        return {"skip": f"producer skipped: {item['skip_reason']}"}
    mode = f["mode"]
    if mode == "auto":
        mode = "prebuilt" if item.get("posts") else "template"
    if mode == "prebuilt":
        if not item.get("posts"):
            return {"skip": "no prebuilt posts for this item"}
        # prebuilt text (e.g. knoblog's) may cite any change of the item, but every number must still trace back
        posts, evidence_item = list(item["posts"]), item
        strip = list(f["trusted_text"]) + ([f["disclaimer"]] if f["disclaimer"] else [])
        extra: set[float] = set()
    else:
        sub = {**item, "changes": changes}
        try:
            posts = fmt.build(sub, f)
        except fmt.TemplateError as e:
            return {"skip": f"format: {e}"}
        evidence_item, strip = sub, ([f["disclaimer"]] if f["disclaimer"] else [])
        extra = literal_numbers(f) | {float(i) for i in range(len(posts) + 1)}
    try:
        gate.check(posts, evidence_item, max_posts=f["max_posts"], allow_mentions=f["allow_mentions"],
                   allow_hashtags=f["allow_hashtags"], literal_numbers=extra, strip=strip)
    except gate.GateError as e:
        return {"skip": f"gate: {e}"}
    return {"posts": posts, "mode": mode}


# ---------------------------------------------------------------- run
def run(items: list[dict], cfg: dict, state: dict | None, env: dict, now: datetime, backend: Backend,
        log=print) -> tuple[dict | None, list[dict], bool]:
    """One bot run. Returns (state, actions, state_changed). Never raises for a single bad item."""
    p = cfg["post"]
    tz = ZoneInfo(p["timezone"])
    ts = now.astimezone(timezone.utc).strftime(TS)
    if truthy(env.get(p["kill_switch_env"])):
        log(f"[repocast] kill switch {p['kill_switch_env']} is set: doing nothing")
        return state, [{"action": "killed"}], False

    persistent = not isinstance(backend, DryRunBackend)
    if getattr(backend, "live", False) and not truthy(env.get(p["live_env"])):
        log(f"[repocast] backend {backend.name!r} publishes publicly but {p['live_env']} is not 'true': DRY RUN")
        backend, persistent = DryRunBackend(log=log), False
    log(f"[repocast] backend: {backend.name}{'' if persistent else ' (nothing is recorded)'}")

    items = sorted(items, key=lambda i: _dt(i["date"]))
    if state is None:
        state = {"version": 1, "created_at": ts, "live_since": None, "items": {}}
        n = _mark_baseline(state, items, ts)
        if getattr(backend, "live", False):
            state["live_since"] = ts
        log(f"[repocast] no state yet: marked {n} existing items as handled (no backfill)")
        return state, [{"action": "baseline", "count": n}], persistent
    if getattr(backend, "live", False) and not state.get("live_since"):
        n = _mark_baseline(state, items, ts)
        state["live_since"] = ts
        log(f"[repocast] first live run: marked {n} items as handled (no backfill); posting starts with the next change")
        return state, [{"action": "baseline", "count": n}], persistent

    if in_quiet_hours(now, p["quiet_hours"], tz):
        log(f"[repocast] quiet hours ({p['quiet_hours']} {p['timezone']}): deferring everything")
        return state, [{"action": "quiet_hours"}], False

    actions: list[dict] = []
    changed = False
    threads = 0
    verified = False
    posted_hashes = {r.get("text_hash") for r in state["items"].values() if r.get("text_hash")}
    stale = timedelta(hours=p["stale_after_hours"])

    def record(item, **rec):
        nonlocal changed
        if persistent:
            state["items"][item["id"]] = {"short": item["short"], "date": item["date"], "at": ts, **rec}
            changed = True

    for it in items:
        if handled(state, it["id"], p["max_attempts"]):
            continue
        prev = state["items"].get(it["id"], {})
        if p["stale_after_hours"] and now - _dt(it["date"]) > stale:
            actions.append({"action": "skip", "id": it["id"], "reason": "stale"})
            record(it, status="skipped", reason=f"stale (older than {p['stale_after_hours']}h)")
            continue
        res = compose(it, cfg)
        if "skip" in res:
            log(f"[repocast] {it['short']}: skipped ({res['skip']})")
            actions.append({"action": "skip", "id": it["id"], "reason": res["skip"]})
            record(it, status="skipped", reason=res["skip"][:300])
            continue
        posts = res["posts"]
        h = text_hash(posts)
        if h in posted_hashes:
            actions.append({"action": "skip", "id": it["id"], "reason": "duplicate text"})
            record(it, status="skipped", reason="identical text was already posted")
            continue
        if threads >= p["max_per_run"] or posted_today(state, now, tz) >= p["max_per_day"]:
            log(f"[repocast] {it['short']}: deferred (caps: {p['max_per_run']}/run, {p['max_per_day']}/day)")
            actions.append({"action": "defer", "id": it["id"]})
            continue
        if not verified:
            try:
                who = backend.verify()
            except AccountMismatch as e:
                log(f"[repocast] ABORT: {e}")
                actions.append({"action": "abort", "reason": str(e)})
                return state, actions, changed
            verified = True
            log(f"[repocast] posting as {who}")
        threads += 1
        try:
            ids = backend.post_thread(posts, it)
        except PostError as e:
            status = "partial" if e.ids else ("failed" if e.definite else "uncertain")
            log(f"[repocast] {it['short']}: {status}: {e}")
            actions.append({"action": status, "id": it["id"], "error": str(e), "ids": e.ids})
            record(it, status=status, error=str(e)[:300], post_ids=e.ids, attempts=prev.get("attempts", 0) + 1,
                   text_hash=h if e.ids or not e.definite else None)
            if not e.definite or e.ids:
                posted_hashes.add(h)
            continue
        except AccountMismatch as e:
            log(f"[repocast] ABORT: {e}")
            actions.append({"action": "abort", "reason": str(e)})
            return state, actions, changed
        posted_hashes.add(h)
        log(f"[repocast] {it['short']}: {'posted' if persistent else 'would post'} {len(ids)} post(s)")
        actions.append({"action": "posted" if persistent else "would_post", "id": it["id"], "ids": ids, "posts": posts,
                        "weighted_lengths": [weighted_len(x) for x in posts]})
        record(it, status="posted", post_ids=ids, text_hash=h, backend=backend.name)
    return state, actions, changed


def _mark_baseline(state: dict, items: list[dict], ts: str) -> int:
    n = 0
    for it in items:
        if it["id"] not in state["items"]:
            state["items"][it["id"]] = {"short": it["short"], "date": it["date"], "status": "baseline", "at": ts}
            n += 1
    return n


def preview(items: list[dict], cfg: dict) -> list[dict]:
    """Compose + gate every item, ignoring state, caps and switches. For humans and CI checks."""
    out = []
    for it in sorted(items, key=lambda i: _dt(i["date"])):
        res = compose(it, cfg)
        out.append({"id": it["id"], "short": it["short"], "date": it["date"], **res,
                    **({"weighted_lengths": [weighted_len(x) for x in res["posts"]]} if "posts" in res else {})})
    return out
