# repocast

**Turn any repo's changes into accurate, ready-to-post X posts, and post them safely.**

repocast is for people who build bots that post on X about code changes, such as changelog bots, "parameter
watch" accounts, or release announcers. You give it structured change data. It writes posts or threads that fit X's
weighted 280-character limit and checks that every number in them comes from the data. It then posts them through
the X API v2, or writes them to an outbox, or only prints them. The guard rails a bot needs are built in: dedup,
caps, a kill switch, quiet hours, an account check, and no retries when the outcome is unknown.

Pure Python standard library (3.10+); no third-party dependency at runtime.

```
knoblog feed.json / changes.json  ─┐
repocast diff (built-in, simple)  ─┼─▶ compose ─▶ accuracy gate ─▶ dedup/caps/switches ─▶ X API v2 │ outbox │ dry run
your own items JSON               ─┘   (prebuilt text or {placeholder} templates)
```

It grew out of the [@XAlgoChangelog](https://github.com/fitzyracing1/x-algorithm-changelog) bot. With the config in
`examples/x-algorithm/` it reproduces that bot's post text exactly, for all 23 post-worthy commits (this is a test).

## Quickstart (CLI)

```bash
pip install repocast                    # or: pip install "repocast[knoblog]"
repocast count "🤖 Nav2 defaults changed → https://example.com"     # 51/280

# 1) change data: knoblog's output (preferred) or the built-in diff
knoblog run --config knoblog.yml --out site            # writes site/feed.json, changes.json, posts.json
#   or
repocast diff --repo . --range v1.4.0..HEAD -o items.json

# 2) look at what would be posted (no state, no caps, posts nothing)
repocast preview -i site/feed.json

# 3) a real run. Without REPOCAST_LIVE=true this is still a dry run and records nothing.
repocast run -c repocast.toml
```

`repocast.toml`:

```toml
[input]
path = "site/feed.json"        # knoblog feed.json / changes.json (+ posts.json), or repocast items JSON

[format]
mode = "auto"                  # prebuilt (knoblog's text) | template | auto (prebuilt when available)
project = "MyRobot"
disclaimer = "Values are repo defaults."
max_lines = 3                  # change lines after the headline
max_posts = 4                  # longest thread allowed

[format.templates]             # optional; plain {placeholders}, no template engine
header = "🤖 {project} update ({date}): {lead}"
line   = "{name} {old} → {new} ({change})"

[filter]
exclude_files = "(^|/)tests?/"

[post]
backend = "x"                  # x | outbox | dry-run | package.module:Class
account = "MyRobotChanges"     # the ONLY account this bot may post as (checked via GET /2/users/me)
state = ".repocast/state.json" # dedup state: commit it or cache it between runs
max_per_run = 1
max_per_day = 3
stale_after_hours = 72
quiet_hours = "22:00-07:00"
timezone = "America/New_York"
```

## Quickstart (GitHub Action)

```yaml
- uses: fitzyracing1/knoblog@v0          # or any step that writes change data
  with: { config: knoblog.yml, out: site }
- id: rc
  uses: fitzyracing1/repocast@v0
  with: { config: repocast.toml }
  env:
    REPOCAST_LIVE: ${{ vars.REPOCAST_LIVE }}                 # 'true' to actually post
    REPOCAST_KILL_SWITCH: ${{ vars.REPOCAST_KILL_SWITCH }}   # 'true' stops everything
    X_API_KEY: ${{ secrets.X_API_KEY }}
    X_API_SECRET: ${{ secrets.X_API_SECRET }}
    X_ACCESS_TOKEN: ${{ secrets.X_ACCESS_TOKEN }}
    X_ACCESS_TOKEN_SECRET: ${{ secrets.X_ACCESS_TOKEN_SECRET }}
# then commit .repocast/state.json when steps.rc.outputs.state_changed == 'true'
```

A complete scheduled workflow is in [`examples/workflows/post-changes.yml`](examples/workflows/post-changes.yml). It
covers concurrency, the state commit, and the switches. Action outputs: `posted`, `would_post`, `state_changed`.
Each run also writes a step summary showing every post.

## Input

| Source | What repocast reads |
| --- | --- |
| knoblog `feed.json` (preferred) | per commit: the change records **and** knoblog's ready-made post text / skip reason |
| knoblog `changes.json` (+ `posts.json` next to it) | flat change records grouped by commit; prebuilt posts if `posts.json` is there |
| `repocast diff` | `KEY = VALUE`, `KEY: VALUE`, `#define KEY VALUE` and `const KEY: T = VALUE;` changes per commit. A key that appears twice in one file is dropped as ambiguous. Use knoblog for nested YAML, parameter tables, macros and expressions. |
| your own JSON | `{"items": [{"id", "date", "commit_url", "url", "changes": [{"name", "old", "new", "kind", "file"}], "posts"?}]}` |

`kind` is `changed`, `added`, `removed`, `moved` or `renamed`. knoblog is an optional extra
(`pip install "repocast[knoblog]"`). repocast only reads knoblog's files, so either tool can run in a separate step.

## Formatting

* **X weighted counting** (twitter-text v3 rules). Every URL counts as 23. Domain-like tokens such as `params.rs` also
  count as 23, and the gate rejects them because X would auto-link them. CJK characters and most symbols (`→`, `▸`)
  weigh 2. An emoji weighs 2 whatever its length: ZWJ families, skin tones, flags and keycaps included. Text is NFC
  normalised. Run `repocast count "…"` to check a text.
* **Threads.** The headline goes in the first post, then whole change lines, then the footer on the last post. The
  footer is never left alone in a tiny reply. Each reply is chained to the post before it with
  `reply.in_reply_to_tweet_id`.
* **Templates** use plain `{placeholders}`, written `{{`/`}}` for literal braces. An unknown placeholder fails when
  the config loads, not at 3 a.m. A line whose placeholders are all empty is dropped, so `{url}` disappears when
  there is no details page.

  | template | placeholders |
  | --- | --- |
  | `header`, `footer`, `more_line` | `{project} {date} {count} {short} {id} {title} {commit_url} {url} {disclaimer} {more} {lead}` |
  | `line`, `text_line`, `flag_line`, `added_line`, `removed_line`, `other_line` | `{name} {old} {new} {change} {pct} {ratio} {file} {kind} {type}` + `{project} {date} {short} {commit_url} {url}` |
  | `bullet` | (literal prefix for each change line, default `- `) |

  `{change}` reads like `25% higher`, `7.2x lower` or `sign flipped`. Highlighted names (`highlight = [...]`) lead,
  then the biggest relative changes. `name_style = "safe"` (the default) turns dotted names that X would link into
  slash form. `display_names` maps raw names to friendly ones.

## The accuracy gate

A post is sent only if **every number in it traces back to the change data**. A number passes if it is one of these:

* an old or new value of one of the item's changes (`125,000` matches `125_000`);
* a correctly rounded quantity derived from one change: percent change, ratio, inverse ratio or difference. Unit
  conversions (ms ↔ s ↔ min ↔ h ↔ d, KiB/MiB) count only when the parameter name suggests a unit, as in `timeout_ms`;
* a count no larger than the number of changes (`+3 more`), or part of the item's date;
* a number you typed into your own templates. With prebuilt text, numbers in `trusted_text` and the disclaimer
  also pass.

The gate also rejects @mentions and #hashtags (unless allowed), domain-like tokens outside real links, any post
over 280 weighted characters, and threads longer than `max_posts`. A failed check never goes to X. The item is
skipped and the reason is recorded:

```
=== 1a2b3c4 SKIP: gate: unverified number '50' in post 1: not in the change data
```

Prebuilt text, such as knoblog's, goes through the same gate, so a bug or a hand edit upstream cannot put a wrong
number on X.

## Posting backends

| backend | what it does |
| --- | --- |
| `x` | X API v2 `POST /2/tweets` with OAuth 1.0a user context. The HMAC-SHA1 signer is stdlib and tested against X's documented example. Before the first post of a run it calls `GET /2/users/me` and aborts the run unless the token belongs to `account` / `account_id`. |
| `outbox` | Never posts. It appends to `outbox/outbox.jsonl` and also writes `outbox.json` (JSON Feed) and `outbox.txt`, for human review or another tool. |
| `dry-run` | Never posts and records nothing. It prints each post with its weighted length. |
| `package.module:Class` | Your own backend: subclass `repocast.backends.Backend`, then implement `post_thread(posts, item) -> ids` and optionally `verify()`. |

## Safety model

* **Off by default.** A backend that publishes (`x`) runs as a dry run unless `REPOCAST_LIVE=true` and all four
  `X_*` credentials are set. The variable name can be changed with `live_env`.
* **Kill switch.** When `REPOCAST_KILL_SWITCH` is true, the run does nothing at all. The variable name can be changed
  with `kill_switch_env`. In Actions, make it a repository *variable* so you can flip it from your phone.
* **No backfill.** The first run, and the first live run after dry runs, mark every existing item as handled.
  Posting starts with the next change.
* **Dedup.** The state file records every item that was posted or skipped, plus a hash of the text. The same
  change never posts twice, and neither does the same text. It is written atomically.
* **Caps.** `max_per_run` and `max_per_day` apply, with the day counted in `timezone`. Items over the cap are
  deferred, not dropped. Items older than `stale_after_hours` are skipped.
* **Quiet hours.** `quiet_hours = "22:00-07:00"` in `timezone` defers the whole run.
* **Never retry an unknown outcome.** A timeout, a reset connection or a 5xx response might mean the post exists,
  so the item is marked `uncertain` and is never retried automatically. A 4xx response means a definite failure,
  which is retried up to `max_attempts`. If a thread fails partway, it is recorded as `partial` with the IDs that
  were posted. After you check the account, `repocast forget <sha> --force` makes repocast consider an item again.
* **Right account only.** If `GET /2/users/me` fails or names another account, the run aborts before any post.
  Check it yourself with `repocast verify-account --account MyBot`.
* **Exit codes.** `0` means OK, `1` means something failed or is uncertain (so CI turns red), `2` means bad
  config/input, and `3` means the account check failed.

## Running an automated account on X

X has specific rules for bots, and they change, so read the current versions:
[Developer Guidelines → Automation rules](https://docs.x.com/developer-guidelines),
[X automation rules (Help Center)](https://help.x.com/en/rules-and-policies/x-automation) and the
[Developer Policy](https://developer.x.com/en/developer-terms/policy).

**The "Automated by" label.** Log in as the bot, open *Settings and privacy → Your account → Account information →
Automation* ([x.com/settings/account/automation](https://x.com/settings/account/automation)), and set the managing
account to the human account responsible for the bot. The profile then shows "Automated by @you".

**Cost: Pay Per Use credits.** The X API is billed per request from prepaid credits, and creating a post is a
billable write. **Prices change, and posts that contain links can be priced differently,** so this README quotes no
numbers. Check [X API pricing](https://docs.x.com/x-api/getting-started/pricing) and the Developer Console before
going live, and set a spending limit there. repocast's caps (`max_per_run`, `max_per_day`, `max_posts`) are also
your cost ceiling: a thread of N posts makes N billable create requests. The `GET /2/users/me` check is a read and
is made only on runs that are about to post. An `outbox` or `dry-run` backend makes no API calls at all.

**Automated-account checklist**

- [ ] The bot has its own account. Never use your personal account's tokens.
- [ ] The "Automated by @you" label is on, and the bio says it is a bot and who runs it.
- [ ] The X app has *Read and write* permission. The access token was generated **after** setting that permission
      (an older token stays read-only).
- [ ] `account` (or `account_id`) in `repocast.toml` is the bot's handle. Run `repocast verify-account` once.
- [ ] Credentials are stored only as CI secrets. `REPOCAST_LIVE` and `REPOCAST_KILL_SWITCH` are repository
      variables.
- [ ] The posts are original, informative and not repetitive. There are no unsolicited @mentions or replies and no
      hashtag stuffing (the gate blocks mentions and hashtags by default).
- [ ] Caps are sized to your budget, a spending limit is set in the Developer Console, and quiet hours are set if
      your audience sleeps.
- [ ] Watched `repocast preview` and a few `dry-run`/`outbox` runs before flipping `REPOCAST_LIVE`.
- [ ] Someone watches the bot's mentions and failed runs (exit code 1 turns CI red), and knows where the kill switch
      is.

## Examples

* [`examples/x-algorithm/`](examples/x-algorithm/): knoblog's x-algorithm feed in `prebuilt` mode. It reproduces the
  @XAlgoChangelog post text exactly (`expected-posts.json`, checked by the tests).
* [`examples/px4/`](examples/px4/): knoblog → X for PX4 firmware defaults, sent to an outbox with quiet hours.
* [`examples/nav2-template/`](examples/nav2-template/): Nav2 parameter changes in your own words, using a custom
  template with emoji.

```text
🤖 Nav2 defaults changed (Aug 15) ⚙️
▸ velocity_smoother/max_accel[0]: 2.5 → 3.0 (20% higher)
▸ velocity_smoother/max_decel[0]: -2.5 → -3.0 (20% lower)
▸ velocity_smoother/max_accel[2]: 3.2 → 3.5 (9.4% higher)
```

## Development

```bash
python -m unittest discover -s tests -v      # no network: the X API is mocked
```

MIT licensed. © 2026 Joshua Almeida.

## Documentation

- In-repo docs: [docs/](docs/index.md)
- Wiki: [https://github.com/fitzyracing1/repocast/wiki](https://github.com/fitzyracing1/repocast/wiki)

## Plans

This project is free, and its license stays as is. Support it through [GitHub Sponsors](https://github.com/sponsors/fitzyracing1):

- **Free**: use the code, community support.
- **Pro ($49/month)**: priority issues and support.
- **Team ($199/month)**: priority support for your team plus early access.
