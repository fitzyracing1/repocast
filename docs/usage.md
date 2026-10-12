# Usage

Common input options (`-c/--config`, `-i/--input`, `--kind auto|knoblog-feed|knoblog-changes|items`, `--posts`, `--mode prebuilt|template|auto`).

| Command | Purpose |
|---|---|
| `preview [--json] [--last N]` | compose and gate every item. Ignores state and caps, and posts nothing |
| `run [--backend x\|outbox\|dry-run\|module:Class] [--dry-run] [--state] [--outbox] [--account]` | one bot run: dedup, caps, quiet hours, kill switch, then the backend |
| `count TEXT` | X weighted length (`-` reads stdin) |
| `diff --range A..B [--repo .] [--path P] [--commit-url URL] [-o FILE]` | built-in `KEY = VALUE` diff → items JSON |
| `verify-account [--account]` | `GET /2/users/me` with the `X_*` credentials, compared against the configured account |
| `forget ID [--state .repocast/state.json] [--force]` | remove an item from the dedup state |

## Environment

| Variable | Effect |
|---|---|
| `REPOCAST_LIVE` | `true` posts for real. Anything else is a dry run |
| `REPOCAST_KILL_SWITCH` | `true` stops everything |
| `X_API_KEY`, `X_API_SECRET`, `X_ACCESS_TOKEN`, `X_ACCESS_TOKEN_SECRET` | X API credentials (keep them in CI secrets) |

## GitHub Action
Inputs: `config`, `input`, `backend`, `command`, `python-version`. Outputs: `posted`, `would_post`, `state_changed`. For a full example, see `examples/workflows/post-changes.yml`.
