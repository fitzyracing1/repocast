"""X weighted character counting (twitter-text v3 configuration).

* Code points in the "light" ranges (Latin, Greek, Cyrillic, most punctuation, ...) weigh 1; everything else
  (CJK, most symbols such as "→", ...) weighs 2.
* An emoji counts as 2 no matter how many code points it has (ZWJ sequences, skin tones, flags, keycaps).
* Every URL counts as 23 (t.co wrapping). Bare domain-like tokens ("param.rs", "example.com") are counted as URLs
  too, because X may auto-link them; this errs on the safe side.
* Text is NFC-normalised first. The limit is 280.
"""
from __future__ import annotations

import re
import unicodedata

MAX_WEIGHT = 280
URL_WEIGHT = 23
_LIGHT = ((0, 4351), (8192, 8205), (8208, 8223), (8242, 8247))
URL_RE = re.compile(r"https?://\S+|\b[\w-]+(?:\.[\w-]+)*\.[a-z]{2,}\b(?:/\S*)?", re.I)

ZWJ, VS16, KEYCAP = "\u200d", "\ufe0f", "\u20e3"


def _is_emoji_start(ch: str) -> bool:
    cp = ord(ch)
    return (0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF or 0x1F1E6 <= cp <= 0x1F1FF
            or cp in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x231A, 0x231B, 0x2328, 0x23CF, 0x24C2, 0x3030, 0x303D, 0x3297, 0x3299)
            or 0x23E9 <= cp <= 0x23FA or 0x25AA <= cp <= 0x25FE or 0x2194 <= cp <= 0x21AA)


def _is_modifier(ch: str) -> bool:
    cp = ord(ch)
    return ch in (VS16, KEYCAP) or 0x1F3FB <= cp <= 0x1F3FF or 0xE0020 <= cp <= 0xE007F


def _char_weight(ch: str) -> int:
    cp = ord(ch)
    return 1 if any(lo <= cp <= hi for lo, hi in _LIGHT) else 2


def _text_weight(s: str) -> int:
    total, i, n = 0, 0, len(s)
    while i < n:
        ch = s[i]
        # keycap: [0-9#*] VS16? U+20E3
        if ch in "0123456789#*" and i + 1 < n and (s[i + 1] == KEYCAP or (s[i + 1] == VS16 and i + 2 < n and s[i + 2] == KEYCAP)):
            total += 2
            i += 3 if s[i + 1] == VS16 else 2
            continue
        if _is_emoji_start(ch) and (ord(ch) >= 0x1F000 or (i + 1 < n and s[i + 1] == VS16) or ord(ch) >= 0x2600):
            j = i + 1
            if 0x1F1E6 <= ord(ch) <= 0x1F1FF and j < n and 0x1F1E6 <= ord(s[j]) <= 0x1F1FF:
                j += 1  # flag = pair of regional indicators
            while j < n and (_is_modifier(s[j]) or (s[j] == ZWJ and j + 1 < n)):
                if s[j] == ZWJ:
                    j += 2  # ZWJ + next emoji
                else:
                    j += 1
            total += 2
            i = j
            continue
        total += _char_weight(ch)
        i += 1
    return total


def url_spans(text: str) -> list[tuple[int, int]]:
    return [m.span() for m in URL_RE.finditer(text) if re.search(r"[a-z]", m.group(0), re.I)]


def weighted_len(text: str) -> int:
    """X's weighted length of `text`."""
    text = unicodedata.normalize("NFC", text)
    total, pos = 0, 0
    for a, b in url_spans(text):
        total += _text_weight(text[pos:a]) + URL_WEIGHT
        pos = b
    return total + _text_weight(text[pos:])


def fits(text: str, limit: int = MAX_WEIGHT) -> bool:
    return weighted_len(text) <= limit


def bare_domains(text: str) -> list[str]:
    """Domain-like tokens that are not explicit http(s) links (X may auto-link them)."""
    return [text[a:b] for a, b in url_spans(text) if not text[a:b].lower().startswith("http")]
