"""Numeric literals: parsing, display, and the derived quantities a post may legitimately mention."""
from __future__ import annotations

import math
import re

NUM = r"[-+]?(?:\d[\d_']*\.?\d*(?:[eE][-+]?\d+)?|\.\d+(?:[eE][-+]?\d+)?)"
_SUFFIX = r"(?:_?(?:f32|f64|u8|u16|u32|u64|usize|i8|i16|i32|i64|isize)|[fFlLuU]{1,3})"
_NUM_FULL = re.compile(rf"\(\s*{NUM}{_SUFFIX}?\s*\)|{NUM}{_SUFFIX}?")
_HEX = re.compile(r"0[xX][0-9a-fA-F_]+[uUlL]{0,3}")
# A number as it appears in post text: 1,000 / 0.25 / 1.0e-10 / 27 (not part of an identifier such as nav2 or _P2).
TOKEN = re.compile(r"(?<![\w.])\d[\d,]*\.?\d*(?:[eE][-+]?\d+)?")


def parse_num(v) -> float | None:
    """'0.4', '-43.2', '125_000', '1.0f64', '0.95f', '(10)', '1e-3', '0x10' -> float; anything else -> None."""
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v) if math.isfinite(v) else None
    s = str(v).strip().replace("\u2212", "-")
    if _HEX.fullmatch(s):
        return float(int(re.sub(r"[uUlL_]", "", s), 16))
    if not _NUM_FULL.fullmatch(s):
        return None
    s = s.strip("() ")
    s = re.sub(rf"{_SUFFIX}$", "", s).replace("_", "").replace("'", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return x if math.isfinite(x) else None


def token_value(tok: str) -> tuple[float, int] | None:
    """(value, decimals) for a number token found in post text."""
    t = tok.replace(",", "").rstrip(".")
    x = parse_num(t)
    if x is None:
        return None
    mant = re.split(r"[eE]", t)[0]
    dec = len(mant.split(".")[1]) if "." in mant else 0
    if re.search(r"[eE]", t):
        dec = 99  # scientific notation must match a value exactly
    return x, dec


def fmt_num(v, exact: bool = True) -> str:
    """exact=True: the literal as written (minus C/Rust suffixes); exact=False: '0.0' -> '0', '125000' -> '125,000'."""
    if exact:
        out = re.sub(rf"(?<=[\d.]){_SUFFIX}$", "", str(v).strip()).strip("()")
        return (out[:-1] if out.endswith(".") and out[:-1][-1:].isdigit() else out) or str(v)
    x = parse_num(v)
    if x is None:
        return str(v)
    if x == int(x) and abs(x) < 1e15 and not re.search(r"[eE]", str(v)):
        n = int(x)
        return f"{n:,}" if abs(n) >= 1000 else str(n)
    return re.sub(rf"{_SUFFIX}$", "", str(v).strip().strip("()").replace("_", "")).lstrip("+")


def round_pct(p: float) -> str:
    return f"{p:.1f}".rstrip("0").rstrip(".") if p < 10 else str(int(round(p)))


UNIT_FACTORS = (1 / 60, 1 / 3600, 1 / 86400, 60, 3600, 86400, 1 / 1000, 1000, 24, 1 / 24, 1 / 1024, 1024, 1 / 1048576)


UNIT_WORDS = {"ms", "msec", "msecs", "millis", "us", "s", "sec", "secs", "second", "seconds", "min", "mins", "minute",
              "minutes", "h", "hr", "hrs", "hour", "hours", "day", "days", "timeout", "duration", "interval", "period",
              "delay", "ttl", "age", "byte", "bytes", "kib", "mib", "kb", "mb", "size", "time"}


def has_unit(name: str) -> bool:
    """True when a parameter name suggests a unit (timeout_ms, CacheTtlSecs, max_age), enabling unit conversions."""
    words = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(name)).lower()
    return any(w in UNIT_WORDS for w in re.split(r"[^a-z0-9]+", words))


def derived_quantities(old: float | None, new: float | None, units: bool = False) -> set[float]:
    """Quantities computed from one change that a post may quote (rounded): % change, ratio, inverse ratio,
    difference, and, when the name suggests a unit (`units=True`), conversions (s/min/h/d, ms, KiB/MiB)."""
    out: set[float] = set()
    for v in (old, new):
        if v is not None:
            out.add(abs(v))
            if units:
                out.update(abs(v) * f for f in UNIT_FACTORS)
    if old is not None and new is not None:
        out.add(abs(new - old))
        if old != 0:
            out.add(abs(new - old) / abs(old) * 100)
            if new != 0:
                out.add(abs(new) / abs(old))
                out.add(abs(old) / abs(new))
    return out
