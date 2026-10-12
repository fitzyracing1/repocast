# Architecture

Pipeline: input (knoblog feed/changes, built-in diff, or items JSON) → compose → accuracy gate → dedup/caps/switches → backend (X API v2, outbox, or dry run).

| File | Role |
|---|---|
| `repocast/cli.py` | commands |
| `repocast/config.py` | `repocast.toml` loading |
| `repocast/model.py` | item model and input readers |
| `repocast/diff.py` | built-in simple diff |
| `repocast/fmt.py` | composing posts and threads (prebuilt text or `{placeholder}` templates) |
| `repocast/weight.py` | X weighted character counting |
| `repocast/numbers.py`, `gate.py` | accuracy gate: numbers must come from the data |
| `repocast/runner.py` | state, dedup, caps, quiet hours, kill switch |
| `repocast/backends.py`, `oauth.py` | X API v2 (OAuth 1.0a signing), outbox, dry run |
| `site/` | GitHub Pages site |
