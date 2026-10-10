"""Turn an Item into post text: either knoblog's prebuilt posts or simple {placeholder} templates, split into a
thread that fits X's weighted limit."""
from __future__ import annotations

import re
from datetime import datetime

from .numbers import fmt_num, parse_num, round_pct
from .weight import MAX_WEIGHT, bare_domains, weighted_len

ITEM_FIELDS = {"project", "date", "count", "short", "id", "title", "commit_url", "url", "disclaimer", "more", "lead"}
CHANGE_FIELDS = {"name", "old", "new", "change", "pct", "ratio", "file", "kind", "type", "project", "date", "short",
                 "commit_url", "url"}
TEMPLATE_FIELDS = {
    "bullet": set(), "header": ITEM_FIELDS, "footer": ITEM_FIELDS, "more_line": ITEM_FIELDS,
    "line": CHANGE_FIELDS, "text_line": CHANGE_FIELDS, "added_line": CHANGE_FIELDS,
    "removed_line": CHANGE_FIELDS, "other_line": CHANGE_FIELDS, "flag_line": CHANGE_FIELDS,
}
DEFAULT_TEMPLATES = {
    "header": "{project} update ({date}): {lead}",
    "bullet": "- ",
    "line": "{name} {old} → {new} ({change})",
    "text_line": "{name}: {old} → {new}",
    "flag_line": "{name} switched {new}",
    "added_line": "new: {name} = {new}",
    "removed_line": "removed: {name} (was {old})",
    "other_line": "{name} {kind}",
    "more_line": "+{more} more",
    "footer": "\n{url}\n{commit_url}\n{disclaimer}",
}
_TOKEN = re.compile(r"\{\{|\}\}|\{(\w*)\}")


class TemplateError(ValueError):
    pass


def fields(template: str) -> list[str]:
    return [m.group(1) for m in _TOKEN.finditer(template) if m.group(1) is not None]


def _literal(template: str) -> str:
    """The template with placeholders removed and {{ }} unescaped."""
    return _TOKEN.sub(lambda m: " " if m.group(1) is not None else m.group(0)[0], template)


def validate_templates(templates: dict) -> None:
    for key, tpl in templates.items():
        if key not in TEMPLATE_FIELDS:
            raise TemplateError(f"unknown template {key!r} (known: {', '.join(sorted(TEMPLATE_FIELDS))})")
        if not isinstance(tpl, str):
            raise TemplateError(f"template {key!r} must be a string")
        bad = [f for f in fields(tpl) if f not in TEMPLATE_FIELDS[key]]
        if bad:
            raise TemplateError(f"template {key!r} uses unknown placeholder {{{bad[0]}}}; "
                                f"allowed: {', '.join('{%s}' % f for f in sorted(TEMPLATE_FIELDS[key]))}")
        stripped = _TOKEN.sub(lambda m: "", tpl)
        if "{" in stripped or "}" in stripped:
            raise TemplateError(f"template {key!r} has an unbalanced brace (write {{{{ or }}}} for a literal brace)")


def render(tpl: str, values: dict) -> str:
    """Fill {placeholders}. A line whose placeholders are all empty/missing is dropped (so '{url}' disappears when
    there is no details page); {{ and }} are literal braces."""
    out = []
    for line in tpl.split("\n"):
        fs = fields(line)
        if fs and all(values.get(f) in (None, "") for f in fs):
            continue
        out.append(_TOKEN.sub(lambda m: m.group(0)[0] if m.group(1) is None
                              else ("" if values.get(m.group(1)) is None else str(values[m.group(1)])), line))
    return "\n".join(out)


def template_literal_text(templates: dict) -> str:
    return "\n".join(_literal(t) for t in templates.values())


def safe_name(name: str, style: str = "safe") -> str:
    """'safe' (default): dotted names X would auto-link as a domain (params.rs) become slash form (params/rs)."""
    if style == "raw":
        return name
    if style == "slash" or (style == "safe" and bare_domains(name)):
        return name.replace(".", "/")
    return name


def change_values(c: dict, ctx: dict, name_style: str = "safe", display_names: dict | None = None) -> dict:
    o, n = parse_num(c.get("old")), parse_num(c.get("new"))
    pct = ratio = None
    change = ""
    if o is not None and n is not None and o != 0 and n != 0 and (o < 0) != (n < 0):
        change = "sign flipped"
    elif o is not None and n is not None and o != 0 and o != n:
        p = (n - o) / abs(o) * 100
        pct = f"{round_pct(abs(p))}%"
        r = n / o
        if r >= 2:
            ratio = _ratio(r)
            change = f"{ratio} higher"
        elif 0 < r < 0.5:
            ratio = _ratio(1 / r)
            change = f"{ratio} lower"
        else:
            change = f"{pct} {'higher' if p > 0 else 'lower'}"
    elif o == 0 and n is not None and n != 0:
        change = "was 0"
    name = (display_names or {}).get(c.get("name"), None) or safe_name(str(c.get("name", "")), name_style)
    return {**ctx, "name": name, "old": _val(c.get("old")), "new": _val(c.get("new")), "change": change,
            "pct": pct, "ratio": ratio, "file": c.get("file"), "kind": c.get("kind"), "type": c.get("type")}


def _ratio(r: float) -> str:
    return (f"{r:.1f}".rstrip("0").rstrip(".") if r < 10 else str(int(round(r)))) + "x"


def _val(v):
    if v is None:
        return None
    if isinstance(v, bool) or str(v).lower() in ("true", "false"):
        return "ON" if str(v).lower() == "true" else "OFF"
    if parse_num(v) is None:
        return str(v)
    s = str(v).strip()
    # plain integers get thousands separators (125,000); anything else is shown as written, minus C/Rust suffixes
    return fmt_num(v, exact=False) if re.fullmatch(r"[-+]?\d[\d_']*", s) else fmt_num(s.replace("_", ""), exact=True)


def _is_flag(c: dict) -> bool:
    return str(c.get("new")).lower() in ("true", "false") and str(c.get("old")).lower() in ("true", "false")


def line_for(c: dict, vals: dict, t: dict) -> str:
    kind = c.get("kind", "changed")
    if kind == "added":
        return render(t["added_line"], vals)
    if kind == "removed":
        return render(t["removed_line"], vals)
    if kind not in ("changed", None):
        return render(t["other_line"], vals)
    if _is_flag(c):
        return render(t["flag_line"], vals)
    if vals["change"]:
        return render(t["line"], vals)
    return render(t["text_line"], vals)


def order(changes: list[dict], highlight: list[str] | None = None) -> list[dict]:
    """Highlighted names first, then numeric changes by size of the change, then the rest (stable)."""
    hl = highlight or []

    def key(ic):
        i, c = ic
        o, n = parse_num(c.get("old")), parse_num(c.get("new"))
        mag = abs((n - o) / o) if (o not in (None, 0) and n is not None) else -1
        return (hl.index(c.get("name")) if c.get("name") in hl else len(hl), -mag, i)

    return [c for _, c in sorted(enumerate(changes), key=key)]


def fmt_date(iso: str, date_format: str) -> str:
    d = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    return d.strftime(date_format.replace("%-d", str(d.day)).replace("%-m", str(d.month)))


def build(item: dict, cfg: dict, limit: int = MAX_WEIGHT) -> list[str]:
    """Template mode: a thread for `item` (list of post texts). Raises TemplateError if it cannot fit."""
    t = {**DEFAULT_TEMPLATES, **(cfg.get("templates") or {})}
    changes = order(item.get("changes") or [], cfg.get("highlight"))
    max_lines = int(cfg.get("max_lines", 8))
    ctx = {"project": cfg.get("project", ""), "date": fmt_date(item["date"], cfg.get("date_format", "%b %-d")),
           "short": item.get("short"), "id": item.get("id"), "title": item.get("title"),
           "commit_url": item.get("commit_url"), "url": item.get("url"), "disclaimer": cfg.get("disclaimer") or None,
           "count": len(changes)}
    max_line = int(cfg.get("max_line_weight", 140))
    lines, long_ = [], 0
    for c in changes:
        ln = line_for(c, change_values(c, ctx, cfg.get("name_style", "safe"), cfg.get("display_names")), t).strip("\n")
        if not ln.strip():
            continue
        if weighted_len(ln) > max_line:
            long_ += 1  # e.g. a long list value: counted in "+N more" rather than truncated
            continue
        if ln not in lines:  # mirrored files often repeat the same fact
            lines.append(ln)
    if not lines:
        raise TemplateError("no change fits on a line" if long_ else "no changes to post")
    if "{lead}" in t["header"]:
        lead, rest = lines[0], lines[1:]
    else:
        lead, rest = None, lines
    shown, more = rest[:max_lines], max(0, len(rest) - max_lines) + long_
    ctx = {**ctx, "lead": lead, "more": more if more > 0 else None}
    shown = [t["bullet"] + ln for ln in shown]
    header = render(t["header"], ctx)
    body = shown + ([t["bullet"] + render(t["more_line"], ctx)] if more > 0 else [])
    footer = render(t["footer"], ctx)
    return split(header, body, footer, limit, int(cfg.get("max_posts", 4)))


def split(header: str, lines: list[str], footer: str, limit: int = MAX_WEIGHT, max_posts: int = 4) -> list[str]:
    """Pack header + lines + footer into as few posts as possible; never break a line. The footer stays together
    on the last post (or gets a post of its own)."""
    posts, cur = [], header
    for ln in lines:
        cand = f"{cur}\n{ln}" if cur else ln
        if weighted_len(cand) <= limit:
            cur = cand
            continue
        if not cur or weighted_len(ln) > limit:
            raise TemplateError(f"a single line is longer than {limit} weighted characters: {ln[:60]!r}")
        posts.append(cur)
        cur = ln
    if footer.strip():
        cand = f"{cur}\n{footer}" if cur else footer.lstrip("\n")
        if weighted_len(cand) <= limit:
            cur = cand
        else:
            if weighted_len(footer.strip("\n")) > limit:
                raise TemplateError("footer alone is longer than the limit")
            tail = footer.strip("\n")
            # don't leave the footer alone in a tiny reply: carry the last body line over with it when possible
            head, _, last = cur.rpartition("\n")
            if cur != header and len(head) >= len(header) and weighted_len(f"{last}\n{footer}") <= limit:
                cur, tail = head, f"{last}\n{footer}"
            posts.append(cur)
            cur = tail
    posts.append(cur)
    if weighted_len(posts[0]) > limit:
        raise TemplateError("header alone is longer than the limit")
    if len(posts) > max_posts:
        raise TemplateError(f"needs {len(posts)} posts (max_posts={max_posts}); lower max_lines")
    return posts
