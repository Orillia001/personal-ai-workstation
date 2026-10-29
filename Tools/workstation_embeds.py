"""Local project file browsing and user-operated PowerShell sessions for the web workbench."""

from __future__ import annotations

import base64
import codecs
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path


TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".toml", ".py", ".ps1",
                 ".js", ".ts", ".html", ".css", ".xml", ".log", ".ini", ".sql", ".svg"}
MAX_PREVIEW_BYTES = 128 * 1024
MAX_OUTPUT_CHARS = 100_000


def project_path(root: Path, project: str) -> Path:
    projects = (root / "Projects").resolve()
    if not project or Path(project).name != project:
        raise ValueError("请选择有效项目")
    candidate = projects / project
    if candidate.is_symlink() or not candidate.is_dir():
        raise ValueError("项目不存在")
    resolved = candidate.resolve()
    if resolved.parent != projects:
        raise ValueError("项目路径无效")
    return resolved


def project_entry(root: Path, project: str, relative: str) -> tuple[Path, Path]:
    base = project_path(root, project)
    if not isinstance(relative, str) or len(relative) > 500:
        raise ValueError("文件路径无效")
    parts = Path(relative.replace("\\", "/")).parts
    if Path(relative).is_absolute() or Path(relative).drive or any(part in ("..", ".") for part in parts):
        raise ValueError("文件路径必须在项目内")
    candidate = base.joinpath(*parts)
    if candidate.is_symlink() or any(parent.is_symlink() for parent in candidate.parents if parent != base):
        raise ValueError("不浏览符号链接")
    resolved = candidate.resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError("文件路径必须在项目内")
    return base, resolved


def list_project_files(root: Path, project: str, relative: str = "") -> dict:
    base, folder = project_entry(root, project, relative)
    if not folder.is_dir():
        raise ValueError("请选择项目内的文件夹")
    entries = []
    for entry in sorted(folder.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())):
        if entry.is_symlink() or entry.name in {".git", "__pycache__", "node_modules", ".venv"}:
            continue
        if len(entries) >= 300:
            break
        try:
            stat = entry.stat()
        except OSError:
            continue
        entries.append({"name": entry.name, "relative": entry.relative_to(base).as_posix(),
                        "kind": "directory" if entry.is_dir() else "file", "size": stat.st_size if entry.is_file() else None})
    return {"project": project, "relative": folder.relative_to(base).as_posix() if folder != base else "",
            "entries": entries, "truncated": len(entries) == 300}


def preview_project_file(root: Path, project: str, relative: str) -> dict:
    base, file = project_entry(root, project, relative)
    if not file.is_file() or file.suffix.lower() not in TEXT_SUFFIXES:
        raise ValueError("此文件类型不支持文本预览")
    with file.open("rb") as stream:
        raw = stream.read(MAX_PREVIEW_BYTES + 1)
    if b"\0" in raw:
        raise ValueError("二进制文件不支持文本预览")
    truncated = len(raw) > MAX_PREVIEW_BYTES
    return {"project": project, "relative": file.relative_to(base).as_posix(),
            "content": raw[:MAX_PREVIEW_BYTES].decode("utf-8-sig", errors="replace"), "truncated": truncated}


POWERSHELL_DRIVER = r"""
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::WriteLine('PowerShell 已就绪')
while ($true) {
    $encoded = [Console]::ReadLine()
    if ($null -eq $encoded) { break }
    try {
        $command = [Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($encoded))
        Invoke-Expression $command 2>&1 | Out-String -Stream -Width 160 | ForEach-Object { [Console]::WriteLine($_) }
    } catch {
        [Console]::WriteLine($_.ToString())
    }
    [Console]::WriteLine('')
}
"""


class TerminalSession:
    def __init__(self, project: str, cwd: Path, executable: str):
        self.id = uuid.uuid4().hex
        self.project = project
        self.last_used = time.monotonic()
        self.base_cursor = 0
        self.output = ""
        self.lock = threading.Lock()
        driver = base64.b64encode(POWERSHELL_DRIVER.encode("utf-16le")).decode("ascii")
        self.process = subprocess.Popen(
            [executable, "-NoLogo", "-NoProfile", "-EncodedCommand", driver],
            cwd=cwd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), bufsize=0,
        )
        threading.Thread(target=self._read_output, daemon=True).start()

    def _read_output(self) -> None:
        decoder = codecs.getincrementaldecoder("utf-8")("replace")
        try:
            while True:
                chunk = os.read(self.process.stdout.fileno(), 4096)
                if not chunk:
                    break
                self._append(decoder.decode(chunk))
            self._append(decoder.decode(b"", final=True))
        except OSError:
            pass

    def _append(self, text: str) -> None:
        if not text:
            return
        with self.lock:
            self.output += text
            if len(self.output) > MAX_OUTPUT_CHARS:
                removed = len(self.output) - MAX_OUTPUT_CHARS
                self.output = self.output[removed:]
                self.base_cursor += removed

    def poll(self, cursor: int) -> dict:
        self.last_used = time.monotonic()
        with self.lock:
            offset = max(0, cursor - self.base_cursor)
            text = self.output[offset:]
            next_cursor = self.base_cursor + len(self.output)
            truncated = cursor < self.base_cursor
        return {"session_id": self.id, "output": text, "cursor": next_cursor,
                "truncated": truncated, "running": self.process.poll() is None}

    def send(self, command: str) -> dict:
        if not isinstance(command, str) or not command.strip() or len(command) > 8000:
            raise ValueError("请输入 1–8000 字的 PowerShell 命令")
        if self.process.poll() is not None:
            raise ValueError("终端会话已结束")
        payload = base64.b64encode(command.encode("utf-8")) + b"\n"
        with self.lock:
            self.process.stdin.write(payload)
            self.process.stdin.flush()
        self.last_used = time.monotonic()
        return {"session_id": self.id, "accepted": True}

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
        if self.process.stdin:
            self.process.stdin.close()


class TerminalSessions:
    def __init__(self):
        self.sessions: dict[str, TerminalSession] = {}
        self.lock = threading.Lock()

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [key for key, session in self.sessions.items() if now - session.last_used > 3600]
        for key in expired:
            self.sessions.pop(key).close()

    def start(self, root: Path, project: str) -> dict:
        cwd = project_path(root, project)
        executable = shutil.which("pwsh")
        if not executable:
            raise ValueError("未找到 pwsh")
        with self.lock:
            self._prune()
            if len(self.sessions) >= 8:
                raise ValueError("终端会话已达上限，请先关闭一个")
            session = TerminalSession(project, cwd, executable)
            self.sessions[session.id] = session
        return {"session_id": session.id, "project": project, "cursor": 0}

    def get(self, session_id: str) -> TerminalSession:
        with self.lock:
            self._prune()
            session = self.sessions.get(session_id)
        if not session:
            raise ValueError("终端会话不存在或已过期")
        return session

    def close(self, session_id: str) -> dict:
        with self.lock:
            session = self.sessions.pop(session_id, None)
        if session:
            session.close()
        return {"closed": True}

    def close_all(self) -> None:
        with self.lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
        for session in sessions:
            session.close()
