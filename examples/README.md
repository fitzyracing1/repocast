# Examples

Each folder holds a `repocast.toml` and a **trimmed** copy of knoblog's `feed.json`, which keeps the post-ready
commits and a few skipped ones and drops repeated per-change fields so the files stay small.
Try them:

```bash
repocast preview -c examples/x-algorithm/repocast.toml
repocast preview -c examples/px4/repocast.toml
repocast preview -c examples/nav2-template/repocast.toml
repocast run     -c examples/px4/repocast.toml --state /tmp/s.json --outbox /tmp/outbox   # first run = baseline
```

To regenerate a feed, run knoblog in a knoblog checkout:

```bash
knoblog run --repo <x-algorithm clone> --config examples/x-algorithm.yml --out /tmp/kx
knoblog run --config examples/nav2.yml --out /tmp/knav
knoblog run --config examples/px4.yml  --out /tmp/kpx4
```

`x-algorithm/expected-posts.json` holds the text the original @XAlgoChangelog bot
(`x-algorithm-changelog/xchangelog/bot.py`) composes for the same commits. `tests/test_examples.py` checks that
repocast's output is identical.

`workflows/post-changes.yml` is a complete scheduled GitHub Actions workflow: knoblog → repocast → commit state.
