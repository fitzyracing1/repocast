"""A deliberately simple built-in repo diff, for repos without knoblog.

For each commit in a range it pairs removed/added lines that look like `KEY = VALUE` / `KEY: VALUE` /
`#define KEY VALUE` / `const KEY: T = VALUE;` in the same file. A key that appears more than once among a file's
removed or added lines is ambiguous and dropped (no guessing). For nested YAML/JSON, Python/C++ expressions,
macros or parameter files with structure, use knoblog, which understands them.
"""
from __future__ import annotations

import re
import subprocess

VALUE = r'(?P<v>[-+]?(?:\d[\d_\']*\.?\d*|\.\d+)(?:[eE][-+]?\d+)?(?:_?[a-zA-Z]\w{0,4})?|true|false|True|False|"[^"\n]{0,80}"|\'[^\'\n]{0,80}\')'
KV = re.compile(
    r'^\s*(?:#define\s+)?(?:(?:export|pub(?:\(crate\))?|const|static|let|var|final|constexpr|readonly|private|public|protected|inline)\s+)*'
    r'(?:[\w:<>\[\]]+\s+)??["\']?(?P<k>[A-Za-z_][\w.\-]*)["\']?\s*(?::\s*[\w:<>\[\]]+\s*)?(?:=|:|\s)\s*' + VALUE +
    r'\s*[,;]?\s*(?:(?://|#|--).*)?$')
TYPES = {"int", "float", "double", "bool", "auto", "uint8_t", "uint16_t", "uint32_t", "int32_t", "size_t", "string"}


def parse_line(line: str) -> tuple[str, str] | None:
    m = KV.match(line)
    if not m or m.group("k") in TYPES:
        return None
    return m.group("k"), m.group("v").strip("'\"") if m.group("v")[0] in "'\"" else m.group("v")


def _git(repo: str, *args: str) -> str:
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout


def file_changes(lines: list[str]) -> list[dict]:
    """lines = one file's unified diff body (lines starting with + / -)."""
    rem: dict[str, list[str]] = {}
    add: dict[str, list[str]] = {}
    for ln in lines:
        if ln.startswith(("+++", "---")) or not ln[:1] in "+-":
            continue
        kv = parse_line(ln[1:])
        if kv:
            (add if ln[0] == "+" else rem).setdefault(kv[0], []).append(kv[1])
    out = []
    for k in sorted(set(rem) | set(add)):
        r, a = rem.get(k, []), add.get(k, [])
        if len(r) > 1 or len(a) > 1:
            continue  # ambiguous
        if r and a:
            if r[0] != a[0]:
                out.append({"name": k, "kind": "changed", "old": r[0], "new": a[0]})
        elif a:
            out.append({"name": k, "kind": "added", "old": None, "new": a[0]})
        else:
            out.append({"name": k, "kind": "removed", "old": r[0], "new": None})
    return out


def remote_commit_url(repo: str) -> str | None:
    try:
        url = _git(repo, "remote", "get-url", "origin").strip()
    except subprocess.CalledProcessError:
        return None
    m = re.match(r"(?:https://|git@)github\.com[:/](.+?)(?:\.git)?$", url)
    return f"https://github.com/{m.group(1)}/commit/{{sha}}" if m else None


def diff_repo(repo: str, rev_range: str, paths: list[str] | None = None, commit_url: str | None = None) -> dict:
    """{'generator': 'repocast diff', 'items': [...]} for every commit in `rev_range` with at least one change."""
    commit_url = commit_url or remote_commit_url(repo)
    shas = _git(repo, "rev-list", "--reverse", "--no-merges", rev_range).split()
    items = []
    for sha in shas:
        meta = _git(repo, "show", "-s", "--format=%cI%x00%s", sha).strip().split("\x00")
        out = _git(repo, "show", "--format=", "-U0", "--no-color", "--no-ext-diff", sha, "--", *(paths or []))
        changes, cur, buf = [], None, []

        def flush():
            if cur:
                for c in file_changes(buf):
                    changes.append({**c, "file": cur, "commit": sha})
        for ln in out.splitlines():
            if ln.startswith("diff --git "):
                flush()
                cur, buf = ln.split(" b/", 1)[-1], []
            else:
                buf.append(ln)
        flush()
        if changes:
            items.append({"id": sha, "short": sha[:7], "date": meta[0], "title": meta[1] if len(meta) > 1 else None,
                          "commit_url": commit_url.format(sha=sha) if commit_url else None, "changes": changes})
    return {"generator": "repocast diff", "repo": repo, "range": rev_range, "items": items}
