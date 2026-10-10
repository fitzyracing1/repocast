"""repocast command line."""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

from . import __version__, backends, config, model, runner
from .weight import weighted_len


def _cfg(a) -> dict:
    over = {"input": {"path": getattr(a, "input", None), "kind": getattr(a, "kind", None), "posts": getattr(a, "posts", None)},
            "post": {"backend": "dry-run" if getattr(a, "dry_run", False) else getattr(a, "backend", None),
                     "state": getattr(a, "state", None), "outbox": getattr(a, "outbox", None),
                     "account": getattr(a, "account", None)}}
    if getattr(a, "mode", None):
        over["format"] = {"mode": a.mode}
    cfg = config.load(a.config if a.config else (("repocast.toml" if os.path.exists("repocast.toml") else None)), over)
    if not cfg["input"]["path"]:
        raise config.ConfigError("no input: pass --input or set [input].path")
    return cfg


def _items(cfg) -> list[dict]:
    return model.load(cfg["input"]["path"], cfg["input"]["kind"], cfg["input"]["posts"] or None)


def cmd_preview(a) -> int:
    cfg = _cfg(a)
    res = runner.preview(_items(cfg), cfg)
    if a.last:
        res = res[-a.last:]
    if a.json:
        print(json.dumps(res, indent=1, ensure_ascii=False))
        return 0
    ready = 0
    for r in res:
        if "posts" in r:
            ready += 1
            print(f"=== {r['short']} {r['date']} [{r['mode']}] READY ({', '.join(f'{n}/280' for n in r['weighted_lengths'])})")
            print("\n--- reply ---\n".join(r["posts"]))
        else:
            print(f"=== {r['short']} {r['date']} SKIP: {r['skip']}")
        print()
    print(f"{ready} ready, {len(res) - ready} skipped")
    return 0


def _summary(actions: list[dict]) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write("### repocast\n\n")
        for x in actions:
            f.write(f"- **{x['action']}** {x.get('id', '')[:7]} {x.get('reason', '') or x.get('error', '')}\n")
            for p in x.get("posts", []):
                f.write("\n  ```\n  " + p.replace("\n", "\n  ") + "\n  ```\n")


def _gh_output(**kv) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as f:
            for k, v in kv.items():
                f.write(f"{k}={v}\n")


def cmd_run(a) -> int:
    cfg = _cfg(a)
    p = cfg["post"]
    items = _items(cfg)
    env = dict(os.environ)
    try:
        be = backends.make(p["backend"], p, env)
    except ValueError as e:
        if p["backend"] == "x" and "missing credentials" in str(e):
            print(f"[repocast] {e}: DRY RUN", file=sys.stderr)
            be = backends.DryRunBackend()
        else:
            raise
    now = datetime.fromisoformat(a.now.replace("Z", "+00:00")) if a.now else datetime.now(timezone.utc)
    state, actions, changed = runner.run(items, cfg, runner.load_state(p["state"]), env, now, be)
    if changed and state is not None:
        runner.save_state(p["state"], state)
        print(f"[repocast] state saved: {p['state']}")
    _summary(actions)
    count = lambda k: sum(1 for x in actions if x["action"] == k)  # noqa: E731
    _gh_output(posted=count("posted"), would_post=count("would_post"), skipped=count("skip"), deferred=count("defer"),
               state_changed=str(changed).lower())
    if any(x["action"] == "abort" for x in actions):
        return 3
    if any(x["action"] in ("failed", "uncertain", "partial") for x in actions):
        return 1
    return 0


def cmd_count(a) -> int:
    text = sys.stdin.read() if a.text == "-" else a.text
    n = weighted_len(text)
    print(f"{n}/280{'' if n <= 280 else '  TOO LONG'}")
    return 0 if n <= 280 else 1


def cmd_diff(a) -> int:
    from .diff import diff_repo
    data = diff_repo(a.repo, a.range, a.path or None, a.commit_url)
    s = json.dumps(data, indent=1, ensure_ascii=False)
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            f.write(s + "\n")
        print(f"{len(data['items'])} commits with changes -> {a.out}")
    else:
        print(s)
    return 0


def cmd_verify(a) -> int:
    cfg = _cfg(a) if (a.config or os.path.exists("repocast.toml")) else {"post": {"account": a.account, "account_id": None, "api_base": backends.API_BASE}}
    acct = a.account or cfg["post"]["account"]
    be = backends.XApiBackend({k: os.environ.get(k, "") for k in backends.CRED_ENV}, account=acct,
                              account_id=cfg["post"].get("account_id"), api_base=cfg["post"]["api_base"])
    try:
        print(f"OK: credentials belong to {be.verify()}")
        return 0
    except backends.AccountMismatch as e:
        print(f"MISMATCH: {e}", file=sys.stderr)
        return 3


def cmd_forget(a) -> int:
    st = runner.load_state(a.state)
    if not st:
        print("no state file", file=sys.stderr)
        return 1
    hits = [k for k in st["items"] if k.startswith(a.id)]
    if len(hits) != 1:
        print(f"{len(hits)} items match {a.id!r}", file=sys.stderr)
        return 1
    rec = st["items"].pop(hits[0])
    if rec["status"] in ("posted", "partial", "uncertain") and not a.force:
        print(f"{hits[0][:7]} is {rec['status']}: it may be public already. Check the account, then use --force.", file=sys.stderr)
        return 1
    runner.save_state(a.state, st)
    print(f"forgot {hits[0][:7]} ({rec['status']}); it will be considered again on the next run")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="repocast", description="Turn a repo's changes into accurate X posts, and post them safely.")
    ap.add_argument("--version", action="version", version=f"repocast {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--config", "-c", help="repocast.toml (default: ./repocast.toml if present)")
        sp.add_argument("--input", "-i", help="knoblog feed.json / changes.json, or repocast items JSON")
        sp.add_argument("--kind", choices=["auto", "knoblog-feed", "knoblog-changes", "items"])
        sp.add_argument("--posts", help="knoblog posts.json (with --kind knoblog-changes)")
        sp.add_argument("--mode", choices=config.MODES, help="prebuilt (knoblog's text), template, or auto")

    sp = sub.add_parser("preview", help="compose + gate every item; ignores state and caps; posts nothing")
    common(sp)
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--last", type=int, help="only the newest N items")
    sp.set_defaults(fn=cmd_preview)

    sp = sub.add_parser("run", help="one bot run: dedup, caps, quiet hours, kill switch, then the backend")
    common(sp)
    sp.add_argument("--backend", help="x | outbox | dry-run | module:Class")
    sp.add_argument("--dry-run", action="store_true", help="force the dry-run backend (records nothing)")
    sp.add_argument("--state", help="state file (dedup)")
    sp.add_argument("--outbox", help="outbox directory")
    sp.add_argument("--account", help="X username the credentials must belong to")
    sp.add_argument("--now", help=argparse.SUPPRESS)
    sp.set_defaults(fn=cmd_run)

    sp = sub.add_parser("count", help="X weighted length of a text ('-' = stdin)")
    sp.add_argument("text")
    sp.set_defaults(fn=cmd_count)

    sp = sub.add_parser("diff", help="built-in simple diff: KEY = VALUE changes per commit -> items JSON")
    sp.add_argument("--repo", default=".")
    sp.add_argument("--range", required=True, help="e.g. HEAD~20..HEAD or v1.0..main")
    sp.add_argument("--path", action="append", help="limit to these paths (repeatable)")
    sp.add_argument("--commit-url", help="e.g. https://github.com/o/r/commit/{sha} (default: from origin)")
    sp.add_argument("--out", "-o")
    sp.set_defaults(fn=cmd_diff)

    sp = sub.add_parser("verify-account", help="GET /2/users/me with the X_* credentials and compare to the account")
    sp.add_argument("--config", "-c")
    sp.add_argument("--account")
    sp.set_defaults(fn=cmd_verify, input=None)

    sp = sub.add_parser("forget", help="remove an item from the state file so it is considered again")
    sp.add_argument("id")
    sp.add_argument("--state", default=".repocast/state.json")
    sp.add_argument("--force", action="store_true")
    sp.set_defaults(fn=cmd_forget)

    a = ap.parse_args(argv)
    try:
        return a.fn(a)
    except (config.ConfigError, model.InputError, ValueError) as e:
        print(f"repocast: error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
