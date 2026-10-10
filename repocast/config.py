"""repocast.toml loading and validation (stdlib tomllib)."""
from __future__ import annotations

import os
import re

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10
    import tomli as tomllib  # type: ignore

from .fmt import TemplateError, validate_templates

DEFAULTS = {
    "input": {"path": "", "kind": "auto", "posts": ""},
    "format": {"mode": "auto", "project": "", "date_format": "%b %-d", "disclaimer": "", "max_lines": 3,
               "max_posts": 4, "max_line_weight": 140, "highlight": [], "name_style": "safe", "display_names": {}, "templates": {},
               "trusted_text": [], "allow_mentions": False, "allow_hashtags": False, "honor_skips": True},
    "filter": {"kinds": ["changed", "added", "removed"], "include": "", "exclude": "", "files": "",
               "exclude_files": "", "min_pct": 0.0},
    "post": {"backend": "dry-run", "account": "", "account_id": "", "outbox": "outbox",
             "state": ".repocast/state.json", "max_per_run": 1, "max_per_day": 3, "stale_after_hours": 72,
             "max_attempts": 2, "quiet_hours": "", "timezone": "UTC", "live_env": "REPOCAST_LIVE",
             "kill_switch_env": "REPOCAST_KILL_SWITCH", "api_base": "https://api.x.com/2"},
}
MODES = ("auto", "prebuilt", "template")


class ConfigError(ValueError):
    pass


def _merge(base: dict, over: dict, where: str) -> dict:
    out = {}
    for sec, vals in base.items():
        given = over.get(sec, {})
        if not isinstance(given, dict):
            raise ConfigError(f"[{sec}] must be a table")
        unknown = set(given) - set(vals)
        if unknown:
            raise ConfigError(f"{where}: unknown key [{sec}].{sorted(unknown)[0]} (known: {', '.join(sorted(vals))})")
        out[sec] = {**vals, **given}
    unknown = set(over) - set(base)
    if unknown:
        raise ConfigError(f"{where}: unknown section [{sorted(unknown)[0]}]")
    return out


def validate(cfg: dict) -> dict:
    f, p, flt = cfg["format"], cfg["post"], cfg["filter"]
    if f["mode"] not in MODES:
        raise ConfigError(f"[format].mode must be one of {MODES}")
    try:
        validate_templates(f["templates"])
    except TemplateError as e:
        raise ConfigError(str(e))
    for k in ("max_lines", "max_posts", "max_per_run", "max_per_day", "max_attempts"):
        sec = f if k in f else p
        if not isinstance(sec[k], int) or sec[k] < 0:
            raise ConfigError(f"{k} must be a non-negative integer")
    if not 1 <= f["max_posts"] <= 25:
        raise ConfigError("max_posts must be between 1 and 25")
    for k in ("include", "exclude", "files", "exclude_files"):
        try:
            re.compile(flt[k])
        except re.error as e:
            raise ConfigError(f"[filter].{k}: bad regex ({e})")
    if p["quiet_hours"] and not re.fullmatch(r"\d{1,2}:\d{2}-\d{1,2}:\d{2}", p["quiet_hours"]):
        raise ConfigError("[post].quiet_hours must look like '22:00-07:00'")
    try:
        from zoneinfo import ZoneInfo
        ZoneInfo(p["timezone"])
    except Exception:  # noqa: BLE001
        raise ConfigError(f"[post].timezone: unknown time zone {p['timezone']!r}")
    if p["backend"] == "x" and not (p["account"] or p["account_id"]):
        raise ConfigError("[post].backend = 'x' needs account (the @username to post as) or account_id")
    return cfg


def load(path: str | None, overrides: dict | None = None) -> dict:
    raw: dict = {}
    base_dir = os.getcwd()
    if path:
        try:
            with open(path, "rb") as fh:
                raw = tomllib.load(fh)
        except FileNotFoundError:
            raise ConfigError(f"config not found: {path}")
        except tomllib.TOMLDecodeError as e:
            raise ConfigError(f"{path}: {e}")
        base_dir = os.path.dirname(os.path.abspath(path))
    cfg = _merge(DEFAULTS, raw, path or "config")
    for sec, vals in (overrides or {}).items():
        cfg[sec].update({k: v for k, v in vals.items() if v is not None})
    # relative paths in a config file are relative to that file
    for sec, key in (("input", "path"), ("input", "posts"), ("post", "state"), ("post", "outbox")):
        v = cfg[sec][key]
        if v and path and not os.path.isabs(v) and not (overrides or {}).get(sec, {}).get(key):
            cfg[sec][key] = os.path.normpath(os.path.join(base_dir, v))
    return validate(cfg)
