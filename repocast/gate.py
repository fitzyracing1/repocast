"""Accuracy and safety gate. A post that fails any check is never sent; the item is skipped with the reason.

Every number in a post must trace back to the structured change data:
  * exactly equal to an old/new value of one of the item's changes, or
  * a rounding of a quantity derived from one change (% change, ratio, inverse ratio, difference, and unit
    conversions such as ms -> h when the parameter name suggests a unit), or
  * a count no larger than the number of changes (e.g. "+2 more"), or
  * part of the date/thread numbering the formatter added, or literal text from the user's own templates.
Also rejected: over-length posts, too many posts, @mentions and #hashtags (unless allowed), bare domain-like tokens
outside real links, and empty posts.
"""
from __future__ import annotations

import re
from datetime import datetime

from .numbers import TOKEN, derived_quantities, has_unit, parse_num, token_value
from .weight import MAX_WEIGHT, bare_domains, weighted_len


class GateError(Exception):
    """The post must not go out; str(exc) is the skip reason."""


def _numbers_in(v) -> list[float]:
    if v is None:
        return []
    x = parse_num(v)
    if x is not None:
        return [x]
    return [y for t in re.findall(r"-?\d[\d_']*\.?\d*(?:[eE][-+]?\d+)?", str(v)) if (y := parse_num(t)) is not None]


def evidence(item: dict, extra: set[float] | None = None) -> tuple[set[float], set[float]]:
    """(exact values, derived quantities) the posts for `item` may contain."""
    exact: set[float] = set(extra or ())
    derived: set[float] = set()
    changes = item.get("changes") or []
    for c in changes:
        olds, news = _numbers_in(c.get("old")), _numbers_in(c.get("new"))
        exact.update(abs(v) for v in olds + news)
        o = parse_num(c.get("old"))
        n = parse_num(c.get("new"))
        derived |= derived_quantities(o, n, units=has_unit(c.get("name", "")))
        for k in ("pct_change", "ratio"):
            if isinstance(c.get(k), (int, float)):
                derived.add(abs(c[k]))
    exact.update(float(i) for i in range(len(changes) + 1))
    try:
        d = datetime.fromisoformat(str(item.get("date")).replace("Z", "+00:00"))
        exact.update({float(d.day), float(d.year), float(d.month)})
    except ValueError:
        pass
    return exact, derived


def traceable(tok: str, exact: set[float], derived: set[float]) -> bool:
    tv = token_value(tok)
    if tv is None:
        return False
    x, dec = tv
    if any(x == v for v in exact):
        return True
    if dec >= 99:
        return False
    tol = 0.5 * 10 ** (-dec) + 1e-9
    return any(abs(x - v) <= tol for v in derived)


def check(posts: list[str], item: dict, *, max_posts: int = 4, allow_mentions: bool = False, allow_hashtags: bool = False,
          literal_numbers: set[float] | None = None, strip: list[str] | None = None, limit: int = MAX_WEIGHT) -> None:
    """Raise GateError if any post may not go out. `strip` = trusted literal strings (header/disclaimer text) whose
    numbers are not checked; `literal_numbers` = numbers that appear in the user's templates."""
    if not posts:
        raise GateError("no post text")
    if len(posts) > max_posts:
        raise GateError(f"thread of {len(posts)} posts exceeds max_posts={max_posts}")
    exact, derived = evidence(item, literal_numbers)
    for i, p in enumerate(posts, 1):
        if not p.strip():
            raise GateError(f"post {i} is empty")
        n = weighted_len(p)
        if n > limit:
            raise GateError(f"post {i} is {n} weighted characters (limit {limit})")
        if not allow_mentions and re.search(r"(^|[^\w])[@＠]\w", p):
            raise GateError(f"post {i} contains an @mention")
        if not allow_hashtags and re.search(r"(^|\s)[#＃]\d*[^\W\d]", p):
            raise GateError(f"post {i} contains a hashtag")
        body = re.sub(r"https?://\S+", " ", p)
        for s in strip or []:
            if s:
                body = body.replace(s, " ")
        if bare_domains(body):
            raise GateError(f"post {i} contains a domain-like token X would auto-link: {bare_domains(body)[0]!r}")
        for tok in TOKEN.findall(body):
            if not traceable(tok, exact, derived):
                raise GateError(f"unverified number {tok!r} in post {i}: not in the change data")
