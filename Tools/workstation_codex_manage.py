"""Bounded file manager for user/project skills and agent rules.

Existing source changes require revisions; saved drafts require a preview ticket.
Plugin/system files are read-only. No downloaded skill script is executed.
"""
from __future__ import annotations
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import uuid
from pathlib import Path, PurePosixPath

import workstation_codex as mapping

_lock = threading.RLock()
_previews = {}
SLUG = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
MAX_BYTES = 120_000


class Conflict(ValueError):
    pass


def digest(value):
    return hashlib.sha256(value).hexdigest()


def safe(path, boundary):
    path, boundary = Path(path), Path(boundary)
    if not path.resolve().is_relative_to(boundary.resolve()):
        raise ValueError("目标超出登记目录")
    return path


def scopes(root, home):
    result = {
        "user": {"label": "用户级", "boundary": home, "skills": home / "skills", "roles": home / "agents", "rule": home / "AGENTS.md"},
        "shared": {"label": "用户共享技能", "boundary": home.parent / ".agents", "skills": home.parent / ".agents/skills"},
        "station": {"label": "工作站", "boundary": root, "skills": root / ".agents/skills", "roles": root / ".codex/agents", "rule": root / "AGENTS.md"},
        "desktop": {"label": "桌面入口规则", "boundary": root.parent / "个人工作站", "rule": root.parent / "个人工作站/AGENTS.md"},
    }
    for project in sorted((root / "Projects").glob("*")):
        if project.is_dir() and project.resolve().is_relative_to(root):
            result[f"project:{project.name}"] = {"label": project.name, "boundary": root,
                "skills": project / ".agents/skills", "roles": project / ".codex/agents", "rule": project / "AGENTS.md"}
    return result


def writable(path, boundary):
    safe(path, boundary)
    current = path
    while current != boundary.parent and current != current.parent:
        if current.is_symlink() or current.is_junction():
            return False
        current = current.parent
    return True


def target(root, home, kind, scope, name, active=True):
    registry = scopes(root, home)
    if scope not in registry or kind not in {"skill", "role", "rule"}:
        raise ValueError("管理范围无效")
    info = registry[scope]
    if kind == "rule":
        path = info.get("rule")
    else:
        if not isinstance(name, str) or not SLUG.fullmatch(name) or name.lower() in {"con", "prn", "aux", "nul", *(f"com{i}" for i in range(1, 10)), *(f"lpt{i}" for i in range(1, 10))}:
            raise ValueError("名称须为小写字母开头的英文字母、数字或短横线")
        base = info.get("skills" if kind == "skill" else "roles")
        path = base / name / "SKILL.md" if base and kind == "skill" else base / f"{name}.toml" if base else None
    if path is None:
        raise ValueError("此范围不支持该文件类型")
    if not active:
        path = path.with_name(path.name + ".disabled")
    safe(path, info["boundary"])
    return path, info["boundary"]


def entry_id(base):
    return digest(str(base.resolve()).casefold().encode())[:32]


def inventory(root, home):
    rows, seen = [], set()
    registry = scopes(root, home)
    for scope, info in registry.items():
        candidates = []
        if info.get("rule"):
            candidates.append(("rule", "", info["rule"]))
        for folder in sorted(info.get("skills", root / "__absent__").glob("*")):
            if folder.is_dir() and SLUG.fullmatch(folder.name):
                candidates.append(("skill", folder.name, folder / "SKILL.md"))
        for path in sorted(info.get("roles", root / "__absent__").glob("*.toml*")):
            name = path.name.removesuffix(".disabled").removesuffix(".toml")
            if SLUG.fullmatch(name):
                candidates.append(("role", name, path.with_name(f"{name}.toml")))
        for kind, name, base in candidates:
            ident = entry_id(base)
            if ident in seen:
                continue
            seen.add(ident)
            disabled = base.with_name(base.name + ".disabled")
            path = base if base.is_file() else disabled
            try:
                if not path.is_file() or path.stat().st_size > MAX_BYTES:
                    continue
                safe(path, info["boundary"])
                raw = path.read_bytes()
                rows.append({"id": ident, "kind": kind, "name": name or info["label"], "scope": scope,
                    "scope_label": info["label"], "path": str(path), "active": path == base,
                    "writable": writable(path, info["boundary"]) and not (base.exists() and disabled.exists()),
                    "revision": digest(raw)})
            except (OSError, ValueError):
                continue
    skills, cache = mapping.discover_skills(root, home)
    for item in [s for s in skills if s["scope"] == "system"] + cache:
        ident = entry_id(Path(item["path"]))
        if ident not in seen:
            seen.add(ident)
            rows.append({"id": ident, "kind": "skill", "name": item["name"], "scope": "readonly",
                "scope_label": "系统 / 插件缓存", "path": item["path"], "active": True,
                "writable": False, "revision": item.get("sha256", "")})
    return {"items": rows, "scopes": [{"id": key, "label": value["label"],
        "kinds": [kind for kind, field in (("skill", "skills"), ("role", "roles")) if field in value]} for key, value in registry.items()]}


def existing(root, home, ident, revision=None, write=False):
    item = next((row for row in inventory(root, home)["items"] if row["id"] == ident), None)
    if item is None:
        raise ValueError("文件不在当前管理清单中")
    if write and not item["writable"]:
        raise ValueError("系统、插件缓存、链接或冲突入口只读")
    if revision is not None and revision != item["revision"]:
        raise Conflict("文件已被其他地方修改，请重新读取后预览")
    return item


def validate_content(kind, content):
    if not isinstance(content, str) or not content.strip() or len(content.encode()) > MAX_BYTES or "\x00" in content:
        raise ValueError("内容为空、过大或含无效字符")
    if kind == "skill":
        parts = content.lstrip("\ufeff").split("---", 2)
        if len(parts) != 3 or parts[0].strip() or not re.search(r"^name:\s*\S", parts[1], re.M) or not re.search(r"^description:\s*\S", parts[1], re.M):
            raise ValueError("Skill须包含以---分隔的name和description头字段")
    if kind == "role":
        fields = tomllib.loads(content)
        if not all(isinstance(fields.get(key), str) and fields[key].strip() for key in ("name", "description", "developer_instructions")):
            raise ValueError("Agent角色须填写name、description、developer_instructions")


def read_file(root, home, ident):
    item = existing(root, home, ident)
    raw = Path(item["path"]).read_bytes()
    return {**item, "revision": digest(raw), "content": raw.decode("utf-8-sig")}


def backup_root(root):
    path = root / "Backups" / "Codex-Rules"
    safe(path, root)
    if not writable(path, root):
        raise ValueError("备份目录不能是链接")
    path.mkdir(parents=True, exist_ok=True)
    return path


def record(root, item, operation, payload=None):
    ident = uuid.uuid4().hex
    folder = backup_root(root) / ident
    folder.mkdir()
    if payload is not None:
        (folder / "content").write_bytes(payload)
    metadata = {key: item[key] for key in ("id", "kind", "name", "scope", "active", "revision")}
    metadata.update(backup_id=ident, operation=operation, created_at=mapping.utc_now())
    (folder / "record.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    return folder, metadata


def atomic_write(path, payload, boundary):
    safe(path, boundary)
    if not writable(path, boundary):
        raise ValueError("链接文件不能写入")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    safe(temporary, boundary)
    try:
        with temporary.open("xb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def preview(root, home, args):
    content = args.get("content")
    if args.get("id"):
        item = existing(root, home, args["id"], args.get("revision"), write=True)
        path = Path(item["path"])
        before = path.read_text(encoding="utf-8-sig")
    else:
        if args.get("kind") not in {"skill", "role"}:
            raise ValueError("新建仅支持Skill或Agent角色")
        path, boundary = target(root, home, args.get("kind"), args.get("scope"), args.get("name"))
        if path.exists() or path.with_name(path.name + ".disabled").exists():
            raise Conflict("同名入口已存在，不会覆盖")
        if args.get("kind") == "skill" and path.parent.exists():
            raise Conflict("同名技能目录已存在，不会覆盖")
        if not writable(path, boundary):
            raise ValueError("目标目录只读")
        item = {"id": entry_id(path), "kind": args["kind"], "scope": args["scope"], "name": args["name"],
                "active": True, "revision": "new", "path": str(path), "writable": True}
        before = ""
    validate_content(item["kind"], content)
    ticket = uuid.uuid4().hex
    _previews[ticket] = {"root": str(root), "home": str(home), "item": item,
        "content_hash": digest(content.encode()), "expires": time.monotonic() + 900}
    for key in list(_previews):
        if _previews[key]["expires"] < time.monotonic():
            del _previews[key]
    difference = ''.join(difflib.unified_diff(before.splitlines(True), content.splitlines(True), fromfile="原文件", tofile="拟保存内容"))
    return {"preview_id": ticket, "path": str(path), "diff": difference or "内容没有变化。", "changed": before != content}


def save(root, home, args):
    ticket = _previews.get(args.get("preview_id"))
    content = args.get("content")
    if not ticket or ticket["root"] != str(root) or ticket["home"] != str(home) or ticket["expires"] < time.monotonic() or not isinstance(content, str) or digest(content.encode()) != ticket["content_hash"]:
        raise Conflict("预览已失效或内容有变化，请重新预览")
    item = ticket["item"]
    path, boundary = target(root, home, item["kind"], item["scope"], item["name"], item["active"])
    if item["revision"] == "new":
        if path.exists() or path.with_name(path.name + ".disabled").exists() or item["kind"] == "skill" and path.parent.exists():
            raise Conflict("目标已存在，不会覆盖")
        raw = b""
    else:
        current = existing(root, home, item["id"], item["revision"], write=True)
        if current["active"] != item["active"] or current["path"] != item["path"]:
            raise Conflict("文件入口状态已变化，请重新读取后预览")
        raw = Path(current["path"]).read_bytes()
    validate_content(item["kind"], content)
    newline = "\r\n" if b"\r\n" in raw else "\n"
    payload = content.replace("\r\n", "\n").replace("\n", newline).encode()
    if raw.startswith(b"\xef\xbb\xbf"):
        payload = b"\xef\xbb\xbf" + payload
    folder, metadata = record(root, item, "create" if item["revision"] == "new" else "save", raw)
    atomic_write(path, payload, boundary)
    del _previews[args["preview_id"]]
    return {"saved": True, "backup_id": metadata["backup_id"], "id": item["id"], "revision": digest(payload), "path": str(path)}


def toggle_or_archive(root, home, args, operation):
    item = existing(root, home, args.get("id"), args.get("revision"), write=True)
    if item["active"] != args.get("active"):
        raise Conflict("文件入口状态已变化，请刷新清单后操作")
    source = Path(item["path"])
    _, boundary = target(root, home, item["kind"], item["scope"], item["name"], item["active"])
    raw = source.read_bytes()
    if operation == "toggle":
        destination, _ = target(root, home, item["kind"], item["scope"], item["name"], not item["active"])
        if destination.exists():
            raise Conflict("另一状态的同名入口已存在")
        folder, metadata = record(root, item, operation, raw)
        safe(source, boundary); safe(destination, boundary)
        source.rename(destination)
    else:
        folder, metadata = record(root, item, operation)
        movable = source.parent if item["kind"] == "skill" else source
        safe(movable, boundary); safe(folder / "payload", root)
        if not writable(movable, boundary):
            raise ValueError("链接目录不能移入备份")
        shutil.move(str(movable), str(folder / "payload"))
    return {"saved": True, "backup_id": metadata["backup_id"], "message": "入口已切换；不会中断已经执行的任务。" if operation == "toggle" else "已移入备份，可从备份历史恢复。"}


def history(root):
    rows = []
    for path in backup_root(root).glob("*/record.json"):
        try:
            safe(path, root)
            data = json.loads(path.read_text(encoding="utf-8"))
            rows.append({**data, "available": data.get("operation") not in {"create", "install"} and not data.get("restored_at") and ((path.parent / "content").exists() or (path.parent / "payload").exists())})
        except (OSError, ValueError):
            continue
    return {"items": sorted(rows, key=lambda row: row["created_at"], reverse=True)[:100]}


def restore(root, home, args):
    ident = args.get("backup_id")
    if not isinstance(ident, str) or not re.fullmatch(r"[a-f0-9]{32}", ident):
        raise ValueError("备份ID无效")
    folder = backup_root(root) / ident
    metadata = json.loads((folder / "record.json").read_text(encoding="utf-8"))
    if metadata.get("restored_at"):
        raise Conflict("该备份已经恢复")
    if metadata["operation"] in {"create", "install"}:
        raise ValueError("新建前没有文件版本，可使用移入备份撤销")
    path, boundary = target(root, home, metadata["kind"], metadata["scope"], metadata["name"], metadata["active"])
    current = next((r for r in inventory(root, home)["items"] if r["id"] == metadata["id"]), None)
    if current:
        existing(root, home, current["id"], args.get("revision"), write=True)
        if current["active"] != args.get("active"):
            raise Conflict("文件入口状态已变化，请重新读取备份历史")
    elif args.get("revision") != "missing":
        raise Conflict("当前文件状态变化，请重新读取备份历史")
    elif path.exists() or path.with_name(path.name.removesuffix(".disabled") if not metadata["active"] else path.name + ".disabled").exists():
        raise Conflict("目标存在未登记的文件，不覆盖恢复")
    if metadata["operation"] == "archive":
        destination = path.parent if metadata["kind"] == "skill" else path
        if destination.exists() or current:
            raise Conflict("目标已存在，不覆盖恢复")
        safe(destination, boundary); safe(folder / "payload", root)
        payload_file = folder / "payload" / path.name if metadata["kind"] == "skill" else folder / "payload"
        if not payload_file.is_file() or digest(payload_file.read_bytes()) != metadata["revision"]:
            raise ValueError("备份入口哈希不匹配")
        if not writable(destination, boundary):
            raise ValueError("恢复目标是链接")
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(folder / "payload"), str(destination))
    else:
        payload = (folder / "content").read_bytes()
        if digest(payload) != metadata["revision"]:
            raise ValueError("备份哈希不匹配")
        if current:
            record(root, current, "save", Path(current["path"]).read_bytes())
        atomic_write(path, payload, boundary)
        if current and Path(current["path"]) != path:
            safe(Path(current["path"]), boundary).unlink()
    metadata["restored_at"] = mapping.utc_now()
    (folder / "record.json").write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")
    return {"saved": True, "message": "已恢复备份版本。"}


def install(root, home, args, preview_only=False):
    repo, ref, subpath = args.get("repo", ""), args.get("ref", "main"), args.get("subpath", ".")
    if not isinstance(repo, str) or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
        raise ValueError("GitHub仓库须为owner/repo")
    if not isinstance(ref, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_./-]{0,120}", ref) or ".." in ref:
        raise ValueError("分支或标签无效")
    if not isinstance(subpath, str) or '\\' in subpath or PurePosixPath(subpath).is_absolute() or '..' in PurePosixPath(subpath).parts or not re.fullmatch(r"[A-Za-z0-9_./ -]+", subpath):
        raise ValueError("仓库目录必须是安全的相对路径")
    path, boundary = target(root, home, "skill", args.get("scope"), args.get("name"))
    if path.parent.exists() or not writable(path, boundary):
        raise Conflict("目标已存在或不是可写源目录")
    if preview_only:
        return {"path": str(path.parent), "repo": repo, "ref": ref, "subpath": subpath, "message": "仅下载到此目录，不执行技能脚本。"}
    helper = Path.home() / ".codex/skills/.system/skill-installer/scripts/install-skill-from-github.py"
    if not helper.is_file():
        raise ValueError("本机官方skill-installer助手不可用")
    # The helper is preinstalled; downloaded skill scripts are never executed.
    with tempfile.TemporaryDirectory(prefix="codex-skill-download-") as staging:
        try:
            completed = subprocess.run([sys.executable, str(helper), "--repo", repo, "--ref", ref, "--path", subpath,
                "--name", args["name"], "--dest", staging, "--method", "download"],
                capture_output=True, timeout=90, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        except subprocess.TimeoutExpired:
            raise ValueError("下载超时，请核对网络后重试。") from None
        downloaded = Path(staging) / args["name"]
        entry = downloaded / "SKILL.md"
        if completed.returncode or not entry.is_file():
            raise ValueError("安装未完成，请核对仓库、版本、目录或网络；不会覆盖同名目录。")
        if entry.stat().st_size > MAX_BYTES:
            raise ValueError("下载的技能入口过大")
        validate_content("skill", entry.read_text(encoding="utf-8-sig"))
        # Recheck the final absolute target after the network request, before moving.
        safe(path, boundary)
        if path.parent.exists() or not writable(path, boundary):
            raise Conflict("下载期间目标目录发生变化，不会覆盖")
        path.parent.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(downloaded), str(path.parent))
    record(root, {"id": entry_id(path), "kind": "skill", "name": args["name"], "scope": args["scope"],
        "active": True, "revision": digest(path.read_bytes())}, "install")
    return {"saved": True, "id": entry_id(path), "message": "Skill已下载到源目录，未执行其脚本。"}


def dispatch(root, payload, *, home=None):
    root = Path(root).resolve()
    home = Path(home or os.environ.get("CODEX_HOME") or Path.home() / ".codex").resolve()
    if not isinstance(payload, dict):
        raise ValueError("管理请求无效")
    action = payload.get("action")
    allowed = {"inventory": {"action"}, "read": {"action", "id"}, "history": {"action"},
        "preview": {"action", "id", "revision", "kind", "scope", "name", "content"},
        "save": {"action", "preview_id", "content", "confirmed"},
        "toggle": {"action", "id", "revision", "active", "confirmed"}, "archive": {"action", "id", "revision", "active", "confirmed"},
        "restore": {"action", "backup_id", "revision", "active", "confirmed"},
        "install": {"action", "repo", "ref", "subpath", "name", "scope", "confirmed"}}
    allowed["install-preview"] = allowed["install"] - {"confirmed"}
    if not isinstance(action, str) or action not in allowed or set(payload) - allowed[action]:
        raise ValueError("管理动作或请求字段无效")
    for key in ("id", "revision", "preview_id", "kind", "scope", "name", "content", "repo", "ref", "subpath", "backup_id"):
        if key in payload and not isinstance(payload[key], str):
            raise ValueError("管理字段类型无效")
    if action in {"toggle", "archive", "restore"} or action == "preview" and payload.get("id"):
        if not isinstance(payload.get("revision"), str):
            raise ValueError("缺少文件修订号，请重新读取")
    if action in {"save", "toggle", "archive", "restore", "install"} and payload.get("confirmed") is not True:
        raise ValueError("请在界面确认具体文件操作")
    if action in {"toggle", "archive"} and not isinstance(payload.get("active"), bool) or "active" in payload and not isinstance(payload["active"], bool):
        raise ValueError("缺少有效的入口状态，请刷新清单")
    with _lock:
        if action == "inventory": return inventory(root, home)
        if action == "read": return read_file(root, home, payload.get("id"))
        if action == "history": return history(root)
        if action == "preview": return preview(root, home, payload)
        if action == "save": return save(root, home, payload)
        if action in {"toggle", "archive"}: return toggle_or_archive(root, home, payload, action)
        if action == "restore": return restore(root, home, payload)
        return install(root, home, payload, preview_only=action == "install-preview")
