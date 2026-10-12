# Getting started

```bash
pip install repocast
repocast count "🤖 Nav2 defaults changed → https://example.com"   # weighted length

# change data: knoblog output, or the built-in diff
repocast diff --repo . --range v1.4.0..HEAD -o items.json

repocast preview -i items.json          # compose + gate, posts nothing
repocast run -c repocast.toml           # dry run unless REPOCAST_LIVE=true
```

See the README for a full annotated `repocast.toml` (sections `[input]`, `[format]`, `[format.templates]`, `[filter]`, `[post]`) and `examples/` for working configs (`x-algorithm`, `px4`, `nav2-template`).
