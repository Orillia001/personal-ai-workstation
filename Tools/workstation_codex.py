"""Read Codex skill files, agent configuration and SQLite task metadata locally.

Never launches Codex, calls a model, reads auth/env files or publishes messages.
SQLite uses mode=ro and query_only. Log parsing projects only execution events.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path


_lock = threading.Lock()
_log_cache = {}
_task_cache = {}
ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{8,100}$")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def text(value, limit=1000):
    return value[:limit] if isinstance(value, str) else ""


def short_title(value):
    value = text(value, 1000)
    return value if len(value) <= 160 and "\n" not in value and not value.startswith(("# Files", "<")) else ""


def scalar_fields(path, allowed):
    """Project only named one-line metadata, never instructions or environment."""
    fields = {}
    with path.open(encoding="utf-8-sig") as stream:
        for line in stream:
            match = re.match(r'^\s*([a-z_]+)\s*=\s*(["\'])(.*?)\2\s*(?:#.*)?$', line)
            if match and match[1] in allowed:
                fields[match[1]] = text(match[3], 1000)
    return fields


def skill_file(path, scope, boundary):
    try:
        if not path.resolve().is_relative_to(boundary.resolve()) or path.stat().st_size > 100_000:
            return None
        raw = path.read_bytes()
        content = raw.decode("utf-8-sig")
        header = content.split("---", 2)[1] if content.startswith("---") else ""
        fields = {}
        for line in header.splitlines():
            match = re.match(r"^(name|description):\s*(.+)$", line)
            if match:
                fields[match[1]] = match[2].strip().strip("\"'")
        return {"name": fields.get("name") or path.parent.name,
                "description": text(fields.get("description"), 2000), "path": str(path),
                "scope": scope, "discovery": "file", "modified_at": path.stat().st_mtime,
                "sha256": hashlib.sha256(raw).hexdigest()}
    except (OSError, UnicodeError):
        return None


def discover_skills(root, home):
    rows, cached, seen = [], [], set()
    roots = [(home / "skills", "user", home), (home.parent / ".agents" / "skills", "user", home.parent / ".agents"),
             (root / ".agents" / "skills", "repo", root)]
    roots.extend((project / ".agents/skills", "repo", root) for project in sorted((root / "Projects").glob("*"))
                 if project.is_dir() and project.resolve().is_relative_to(root))
    for directory, scope, boundary in roots:
        paths = sorted(directory.glob("*/SKILL.md")) + sorted(directory.glob(".system/*/SKILL.md"))
        for path in paths:
            key = str(path.resolve()).casefold()
            if key in seen:
                continue
            seen.add(key)
            row = skill_file(path, "system" if ".system" in path.parts else scope, boundary)
            if row:
                rows.append(row)
    plugin_root = home / "plugins" / "cache"
    for path in sorted(plugin_root.glob("*/*/*/skills/*/SKILL.md"))[:1000]:
        if str(path.resolve()).casefold() in seen:
            continue
        row = skill_file(path, "plugin-cache", plugin_root)
        if row:
            row.update(name=f"{path.parents[3].name}:{row['name']}", version=path.parents[2].name)
            cached.append(row)
    return rows, cached


def agent_configuration(root, home):
    rules, roles = [], []
    projects = [p for p in sorted((root / "Projects").glob("*")) if p.is_dir() and p.resolve().is_relative_to(root)]
    candidates = [("用户规则", home / "AGENTS.md", home),
        ("桌面入口规则", root.parent / "个人工作站" / "AGENTS.md", root.parent / "个人工作站"),
        ("工作站规则", root / "AGENTS.md", root)]
    candidates.extend((f"项目规则 · {p.name}", p / "AGENTS.md", root) for p in projects)
    for label, path, boundary in candidates:
        try:
            if not path.is_file() or not path.resolve().is_relative_to(boundary.resolve()) or path.stat().st_size > 200_000:
                continue
            content = path.read_bytes()
            headings = [line.lstrip("# ") for line in content.decode("utf-8-sig").splitlines() if line.startswith("#")]
            rules.append({"name": label, "path": str(path), "headings": headings[:30],
                "sha256": hashlib.sha256(content).hexdigest(), "modified_at": path.stat().st_mtime})
        except (OSError, UnicodeError):
            continue
    role_roots = [(home / "agents", home), (root / ".codex" / "agents", root)] + [(p / ".codex" / "agents", root) for p in projects]
    for directory, boundary in role_roots:
        for path in sorted(directory.glob("*.toml"))[:200]:
            try:
                if not path.resolve().is_relative_to(boundary) or path.stat().st_size > 100_000:
                    continue
                fields = scalar_fields(path, {"name", "description", "model", "model_reasoning_effort"})
                roles.append({"name": fields.get("name") or path.stem, "path": str(path), **fields})
            except (OSError, UnicodeError):
                continue
    return {"rules": rules, "roles": roles}


def execution_record(path, home):
    unknown = {"status": "unknown", "event": None, "event_at": None, "runtime_verified": False}
    try:
        path = Path(path).resolve()
        if not any(path.is_relative_to(home / name) for name in ("sessions", "archived_sessions")) or path.suffix != ".jsonl":
            return unknown
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key in _log_cache:
            cached = dict(_log_cache[key])
            if cached["status"] == "running" and time.time() - stat.st_mtime > 90:
                cached["status"] = "unknown"
            return cached
        latest = None
        # Scan a bounded suffix. Never return message text, tool arguments or results.
        with path.open("rb") as stream:
            start = max(0, stat.st_size - 8 * 1024 * 1024)
            stream.seek(start)
            if start:
                stream.readline()
            for line in stream:
                if b'event_msg' not in line or not any(marker in line for marker in (b'task_started', b'task_complete', b'turn_aborted')):
                    continue
                try:
                    value = json.loads(line)
                except ValueError:
                    continue
                event = value.get("payload", {}).get("type") if value.get("type") == "event_msg" else None
                if event in {"task_started", "task_complete", "turn_aborted"}:
                    stamp = value.get("timestamp")
                    if isinstance(stamp, str):
                        latest = {"event": event, "event_at": stamp}
        result = dict(unknown)
        if latest:
            result.update(latest, status={"task_started": "running", "task_complete": "completed", "turn_aborted": "interrupted"}[latest["event"]])
            if result["status"] == "running" and time.time() - stat.st_mtime > 90:
                result["status"] = "unknown"
        # Bounded metadata cache, not a persisted mirror of conversation content.
        if len(_log_cache) > 300:
            _log_cache.clear()
        _log_cache[key] = result
        return dict(result)
    except (OSError, ValueError, TypeError, AttributeError):
        return unknown


def binding(root):
    try:
        path = root / "State" / "codex-map" / "context.json"
        if path.stat().st_size > 2000:
            return None
        value = json.loads(path.read_text(encoding="utf-8"))
        ident = value.get("root_thread_id")
        return ident if isinstance(ident, str) and ID_PATTERN.fullmatch(ident) else None
    except (OSError, ValueError, AttributeError):
        return None


def thread_metadata(root, home):
    result = {"threads": [], "agents": [], "root_thread_id": binding(root), "warnings": [], "has_more_threads": False}
    paths = sorted(home.glob("state_[0-9]*.sqlite"), key=lambda p: int(re.search(r"state_(\d+)", p.name)[1]), reverse=True)
    if not paths:
        result["warnings"].append("未发现 Codex 本地状态库，任务与子 Agent 暂不可读。")
        return result
    database = paths[0]
    if not database.resolve().is_relative_to(home):
        result["warnings"].append("状态库路径超出 Codex 目录，已跳过。")
        return result
    db = None
    try:
        db = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True, timeout=1)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA query_only=ON")
        columns = {row[1] for row in db.execute("PRAGMA table_info(threads)")}
        required = {"id", "cwd", "updated_at", "source", "rollout_path", "archived"}
        if not required <= columns:
            raise ValueError("unsupported schema")
        optional = [name for name in ("name", "title", "agent_nickname", "agent_role", "agent_path") if name in columns]
        selected = ','.join(sorted(required) + optional)

        def project(raw):
            row = dict(raw)
            return {"id": row["id"], "title": short_title(row.get("name") or row.get("title")),
                "cwd": text(row.get("cwd")), "updated_at": row.get("updated_at"), "source": text(row.get("source"), 120),
                "agent_name": text(row.get("agent_nickname"), 100), "agent_role": text(row.get("agent_role"), 100),
                "agent_path": text(row.get("agent_path"), 200), **execution_record(row.get("rollout_path", ""), home)}

        records = db.execute(f"SELECT {selected} FROM threads WHERE archived=0 ORDER BY updated_at DESC LIMIT 101").fetchall()
        result["has_more_threads"] = len(records) > 100
        result["threads"] = [project(row) for row in records[:100]]
        root_id = result["root_thread_id"]
        if root_id:
            queue, seen = [(root_id, None)], set()
            while queue and len(seen) < 100:
                ident, parent = queue.pop(0)
                if ident in seen:
                    continue
                seen.add(ident)
                raw = db.execute(f"SELECT {selected} FROM threads WHERE id=?", (ident,)).fetchone()
                if raw:
                    row = project(raw)
                    result["agents"].append({**row, "parent": parent,
                        "display_name": row["agent_path"] or row["agent_name"] or ("/root" if parent is None else ident)})
                try:
                    children = db.execute("SELECT child_thread_id FROM thread_spawn_edges WHERE parent_thread_id=?", (ident,)).fetchall()
                    queue.extend((row[0], ident) for row in children)
                except sqlite3.Error:
                    result["warnings"].append("本地状态库未提供子 Agent 关系表。")
                    break
        result["database"] = str(database)
    except (sqlite3.Error, ValueError, OSError):
        result["warnings"].append("Codex 状态库暂不可读或版本结构不同，请稍后刷新；未修改状态库。")
    finally:
        if db:
            db.close()
    return result


def catalog(root, *, refresh=False, home=None):
    # Every request reads metadata from local files; refresh adds no execution capability.
    root = Path(root).resolve()
    home = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()
    with _lock:
        skills, cached = discover_skills(root, home)
        tasks = thread_metadata(root, home)
        key = (str(root), str(home), tasks["root_thread_id"])
        if tasks["warnings"] and key in _task_cache:
            tasks = {**_task_cache[key], "warnings": tasks["warnings"], "stale": True}
        elif not tasks["warnings"]:
            tasks["read_at"] = utc_now()
            if len(_task_cache) > 10:
                _task_cache.clear()
            _task_cache[key] = tasks
        return {"schema_version": 2, "generated_at": utc_now(), "cwd": str(root), "source": "本机文件 · 只读映射",
            "local": {"skills": skills, "threads": tasks["threads"], "warnings": tasks["warnings"],
                      "collected_at": utc_now(), "task_collected_at": tasks.get("read_at"), "tasks_stale": tasks.get("stale", False),
                      "has_more_threads": tasks["has_more_threads"], "database": tasks.get("database")},
            "plugin_cache": cached, "configuration": agent_configuration(root, home),
            "agent_tree": {"root_thread_id": tasks["root_thread_id"], "agents": tasks["agents"],
                           "source": "Codex 本地父子关系 + 执行事件", "available": bool(tasks["agents"]),
                           "stale": tasks.get("stale", False), "read_at": tasks.get("read_at")}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(catalog(args.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
