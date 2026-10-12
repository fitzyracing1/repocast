# repocast

repocast turns structured change data into X posts or threads that fit X's weighted 280-character limit. An accuracy gate checks that every number in a post comes from the data. Posts then go out through the X API v2, are written to an outbox, or are only printed (dry run). Built-in guard rails: dedup, caps, a kill switch, quiet hours, an account check, and no retries when the outcome is unknown.

- Python ≥ 3.10, standard library only (plus `tomli` on Python < 3.11)
- Console script `repocast` (`repocast.cli:main`) and a composite GitHub Action (`action.yml`)
- It grew out of the [x-algorithm-changelog](https://github.com/fitzyracing1/x-algorithm-changelog) bot, and its input is usually [knoblog](https://github.com/fitzyracing1/knoblog) output.

Pages: [Getting started](getting-started.md) · [Usage](usage.md) · [Architecture](architecture.md) · [Contributing](contributing.md)

CI (`ci.yml`) runs `pip install -e .` and then `python -m unittest discover -s tests -v`. A run is **lit** when it succeeds and **dark** otherwise.

MIT License. Copyright (c) 2026 Joshua Almeida
