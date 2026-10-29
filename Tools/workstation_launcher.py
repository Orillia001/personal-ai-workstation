"""Config-driven, fixed-target application launcher for the local workstation."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _apps(root: Path) -> list[dict]:
    config_path = root / "Config" / "launcher.json"
    config = json.loads(config_path.read_text(encoding="utf-8-sig"))
    entries = config.get("apps")
    if config.get("schema_version") != 1 or not isinstance(entries, list):
        raise ValueError("unsupported launcher configuration")
    seen: set[str] = set()
    for entry in entries:
        app_id = entry.get("id")
        tool_name = entry.get("tool")
        if not isinstance(app_id, str) or not app_id or app_id in seen:
            raise ValueError("launcher IDs must be non-empty and unique")
        if not isinstance(tool_name, str) or not tool_name:
            raise ValueError(f"launcher '{app_id}' has no registered tool")
        seen.add(app_id)
    return entries


def list_apps(root: Path, discovered_tools: list[dict]) -> list[dict]:
    """Return configured app cards joined to the current workstation tool registry."""
    tools = {item["name"]: item for item in discovered_tools}
    result = []
    for entry in _apps(root):
        tool = tools.get(entry["tool"], {})
        executable = Path(tool.get("path") or "")
        available = bool(tool.get("found")) and executable.is_file() and executable.suffix.lower() == ".exe"
        result.append({
            "id": entry["id"],
            "name": entry.get("name", entry["tool"]),
            "tool": entry["tool"],
            "category": entry.get("category", "其他"),
            "description": entry.get("description", ""),
            "available": available,
        })
    return result


def launch_app(root: Path, app_id: str, discovered_tools: list[dict]) -> dict:
    """Launch one configured .exe, without accepting paths, arguments, or shell text."""
    entry = next((item for item in _apps(root) if item["id"] == app_id), None)
    if entry is None:
        raise ValueError("unknown application ID")
    tool = next((item for item in discovered_tools if item["name"] == entry["tool"]), None)
    if not tool or not tool.get("found"):
        raise ValueError("application is not available on this computer")
    executable = Path(tool["path"]).resolve(strict=True)
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise ValueError("only registered Windows applications can be launched")

    flags = 0
    if os.name == "nt":
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    process = subprocess.Popen(
        [str(executable)],
        cwd=root,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
        creationflags=flags,
    )
    return {"id": entry["id"], "name": entry.get("name", entry["tool"]), "launched": True}


def _project_directory(root: Path, project: str) -> Path:
    if not isinstance(project, str) or not project or project in {".", ".."}:
        raise ValueError("a project name is required")
    projects = (root / "Projects").resolve()
    path = (projects / project).resolve()
    if path.parent != projects or not path.is_dir():
        raise ValueError("unknown project")
    return path


def open_project_item(root: Path, project: str, item: str) -> dict:
    """Open a fixed folder or status file from one direct child of Projects."""
    if os.name != "nt":
        raise ValueError("opening a project in Explorer is only available on Windows")
    project_path = _project_directory(root, project)
    if item == "folder":
        target = project_path
    elif item == "status":
        target = project_path / "12-status.md"
        if not target.is_file():
            raise ValueError("project has no 12-status.md")
    else:
        raise ValueError("unsupported project item")

    os.startfile(str(target))
    return {"project": project, "opened": item}


def open_codex_session(root: Path, project: str) -> dict:
    """Open a PowerShell window and run the fixed Codex session script for a project."""
    if os.name != "nt":
        raise ValueError("PowerShell Codex sessions are only available on Windows")
    project_path = _project_directory(root, project)
    if not (project_path / "10-README.MD").is_file():
        raise ValueError("project is not registered as a managed workstation project")

    script = root / "Tools" / "open-codex-session.ps1"
    if not script.is_file():
        raise ValueError("Codex session launcher was not found")
    powershell = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    if not powershell.is_file():
        executable = shutil.which("pwsh") or shutil.which("powershell")
        if not executable:
            raise ValueError("PowerShell was not found")
        powershell = Path(executable)

    subprocess.Popen(
        [str(powershell), "-NoProfile", "-NoExit", "-ExecutionPolicy", "Bypass", "-File", str(script), "-ProjectName", project],
        cwd=root,
        stdin=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NEW_CONSOLE,
        close_fds=True,
    )
    return {"project": project, "started": True}
