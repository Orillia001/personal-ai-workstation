"""Read matching Edge favorites on demand; never persist their full URLs."""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit


MAX_BOOKMARK_FILE_BYTES = 8 * 1024 * 1024
MAX_BOOKMARK_NODES = 20_000


def _edge_bookmark_files(user_data: Path) -> list[Path]:
    profiles = [user_data / "Default", *sorted(user_data.glob("Profile *"))]
    return [profile / "Bookmarks" for profile in profiles if (profile / "Bookmarks").is_file()]


def _iter_bookmarks(node: object):
    stack = [node]
    seen = 0
    while stack and seen < MAX_BOOKMARK_NODES:
        current = stack.pop()
        seen += 1
        if isinstance(current, dict):
            if current.get("type") == "url":
                yield str(current.get("name", "")), str(current.get("url", ""))
            children = current.get("children")
            if isinstance(children, list):
                stack.extend(reversed(children))
        elif isinstance(current, list):
            stack.extend(reversed(current))


def find_edge_bookmark_url(query: str, base_url: str = "", *, user_data: Path | None = None) -> str:
    """Return one unambiguous favorite; allow HTTP only for an explicit HTTP site."""
    if user_data is None:
        local_data = os.environ.get("LOCALAPPDATA")
        if not local_data:
            raise ValueError("无法定位 Edge 收藏夹")
        user_data = Path(local_data) / "Microsoft" / "Edge" / "User Data"
    query = query.strip().casefold()
    if not query:
        raise ValueError("请填写收藏夹搜索词")
    base = urlsplit(base_url) if base_url else None
    expected_host = base.hostname if base else None
    allowed_schemes = {"https", "http"} if base and base.scheme.lower() == "http" else {"https"}
    matches: dict[str, int] = {}
    for path in _edge_bookmark_files(user_data):
        if path.stat().st_size > MAX_BOOKMARK_FILE_BYTES:
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            continue
        roots = document.get("roots", {})
        for name, url in _iter_bookmarks(list(roots.values()) if isinstance(roots, dict) else []):
            try:
                parsed = urlsplit(url)
                host = parsed.hostname
            except ValueError:
                continue
            if (parsed.scheme.lower() not in allowed_schemes or not host or "\\" in url
                    or any(char.isspace() for char in url)
                    or parsed.scheme.lower() == "http" and parsed.username is not None):
                continue
            if expected_host and host != expected_host and not host.endswith("." + expected_host):
                continue
            folded_name = name.casefold()
            score = 3 if folded_name == query else 2 if query in folded_name else 1 if query in host.casefold() or expected_host else 0
            if score:
                matches[url] = max(score, matches.get(url, 0))
    if not matches:
        raise ValueError("Edge 收藏夹中没有匹配的网站")
    highest = max(matches.values())
    best = [url for url, score in matches.items() if score == highest]
    if len(best) != 1:
        raise ValueError("找到多个匹配的 Edge 收藏夹，请填写更具体的搜索词")
    return best[0]
