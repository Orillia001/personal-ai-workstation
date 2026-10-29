from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import html
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


_AI_STATUS_CACHE: tuple[float, dict] | None = None


def codex_sandbox_compat_args() -> list[str]:
    """Use the documented native Windows fallback after elevated provisioning failed locally."""
    return ["-c", 'windows.sandbox="unelevated"'] if os.name == "nt" else []


def workbench_capabilities() -> dict:
    """Versioned discovery contract for future local workbench clients."""
    return {
        "schema_version": 1,
        "features": {
            "matt_workflow": {"map": "POST /api/workbench/matt-map", "actor": "current-codex-chat", "mode": "method-map-and-explicit-records"},
            "visual_workflows": {"drafts": "POST /api/workbench/workflows", "mode": "compose-preview-only", "model_routing": "metadata-quality-first-preview"},
            "coursework_runtime": {"endpoint": "POST /api/workbench/coursework", "mode": "finance-profile-controlled-execution", "human_gates": ["plan", "method", "release"]},
            "projects": {"overview": "GET /api/workbench/overview", "documents": "POST /api/projects/content"},
            "applications": {"list": "GET /api/launcher/apps", "launch": "POST /api/launcher/launch"},
            "intake": {"plan": "POST /api/workbench/intake/scan", "apply": "POST /api/apply"},
            "window_draft": {"page": "GET /workbench", "demo": "GET /workbench/layout-prototype", "create": "POST /api/workbench/window-draft"},
            "layout_state": {"load": "POST /api/workbench/layout-state/load", "save": "POST /api/workbench/layout-state/save"},
            "embedded_tools": {"project_files": "POST /api/workbench/project-files", "file_preview": "POST /api/workbench/project-file/preview",
                               "terminal_start": "POST /api/workbench/terminal/start", "terminal_input": "POST /api/workbench/terminal/input",
                               "terminal_poll": "POST /api/workbench/terminal/poll", "terminal_close": "POST /api/workbench/terminal/close"},
            "settings": {"read": "GET /api/workbench/settings", "update": "POST /api/workbench/settings"},
            "education_network": {"catalog": "GET /api/education/network", "graph": "GET /api/education/network?course=<course-id>",
                                  "progress": "GET /api/education/progress?course=<course-id>",
                                  "update": "POST /api/education/learning-status", "open_note": "POST /api/education/open-note"},
            "operations": {"activity": "GET /api/workbench/activity", "backups": "GET /api/workbench/backups", "latex": "GET /api/workbench/latex-documents"},
            "execution": {"request": "POST /api/v4/execute-request", "approve": "POST /api/v4/execute-approve", "deny": "POST /api/v4/execute-deny", "run": "POST /api/v4/execute-run"},
        },
        "post_token_header": "X-Workstation-Token",
    }


WORKBENCH_SETTINGS = {
    "input_style": {"label": "输入方式", "options": {"keyboard-first": "键盘优先", "touch-first": "触屏优先"}},
    "resource_policy": {"label": "资源策略", "options": {"local-first": "本地优先", "balanced": "按任务平衡"}},
    "web_policy": {"label": "联网策略", "options": {"only-when-current-or-requested": "需要最新信息或明确要求时联网", "when-beneficial": "相关任务可主动联网"}},
}


def workbench_settings(db: sqlite3.Connection) -> dict:
    saved = preferences(db)
    return {
        "fields": [
            {"key": key, "label": spec["label"], "value": saved.get(key, next(iter(spec["options"]))),
             "options": [{"value": value, "label": label} for value, label in spec["options"].items()]}
            for key, spec in WORKBENCH_SETTINGS.items()
        ],
        "fixed": {"language": saved.get("language", "zh-CN"), "file_policy": "preserve-originals",
                  "learning_policy": saved.get("learning_policy", "explicit-or-repeated"),
                  "log_prompt_content": "false", "default_agent_count": "1"},
    }


def update_workbench_settings(db: sqlite3.Connection, values: dict) -> dict:
    if not isinstance(values, dict) or set(values) != set(WORKBENCH_SETTINGS):
        raise ValueError("设置项不完整")
    for key, value in values.items():
        if not isinstance(value, str) or value not in WORKBENCH_SETTINGS[key]["options"]:
            raise ValueError("不支持的设置值")
    for key, value in values.items():
        db.execute(
            "INSERT INTO preferences(key,value,confidence,source,updated_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,confidence=excluded.confidence,source=excluded.source,updated_at=excluded.updated_at",
            (key, value, 1.0, "explicit-workbench", now()),
        )
    db.commit()
    return workbench_settings(db)


def scan_project_inbox(root: Path, project: str) -> Path:
    projects_root = (root / "Projects").resolve()
    project_root = projects_root / project
    if not project or project in {".", ".."} or Path(project).name != project or project_root.is_symlink() or not project_root.is_dir():
        raise ValueError("请选择有效的目标项目")
    inbox = project_root / "00_inbox"
    if inbox.is_symlink() or not inbox.is_dir() or inbox.resolve().parent != project_root.resolve():
        raise ValueError("该项目没有可用的 00_inbox 文件夹")
    return scan_files(root, inbox, project)




def connect(root: Path) -> sqlite3.Connection:
    import workstation_layout_state as layout_state

    state = root / "State"
    state.mkdir(parents=True, exist_ok=True)
    (state / "plans").mkdir(exist_ok=True)
    (state / "reuse").mkdir(exist_ok=True)
    (state / "ai").mkdir(exist_ok=True)
    db = sqlite3.connect(state / "workstation.db")
    db.row_factory = sqlite3.Row
    db.executescript(
        """
        PRAGMA journal_mode=WAL;
        CREATE TABLE IF NOT EXISTS projects(
          name TEXT PRIMARY KEY, path TEXT NOT NULL, status TEXT NOT NULL,
          updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tools(
          name TEXT PRIMARY KEY, found INTEGER NOT NULL, path TEXT,
          capabilities TEXT NOT NULL, checked_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS tasks(
          id TEXT PRIMARY KEY, project TEXT, title TEXT NOT NULL,
          status TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS runs(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, project TEXT,
          status TEXT NOT NULL, summary TEXT, created_at TEXT NOT NULL,
          finished_at TEXT);
        CREATE TABLE IF NOT EXISTS file_operations(
          id TEXT PRIMARY KEY, run_id TEXT NOT NULL, source TEXT NOT NULL,
          destination TEXT NOT NULL, sha256 TEXT NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL, undone_at TEXT);
        CREATE TABLE IF NOT EXISTS approvals(
          id TEXT PRIMARY KEY, action TEXT NOT NULL, scope TEXT NOT NULL,
          decision TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS preferences(
          key TEXT PRIMARY KEY, value TEXT NOT NULL, confidence REAL NOT NULL,
          source TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS routing_history(
          id TEXT PRIMARY KEY, task_type TEXT NOT NULL, resource_mode TEXT NOT NULL,
          selected_tools TEXT NOT NULL, outcome TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS watch_files(
          path TEXT PRIMARY KEY, size INTEGER NOT NULL, mtime REAL NOT NULL,
          stable_count INTEGER NOT NULL, planned_sha TEXT, updated_at TEXT NOT NULL);
        """
    )
    layout_state.ensure_schema(db)
    defaults_path = root / "Config" / "user-preferences.json"
    if defaults_path.exists():
        for key, value in read_json(defaults_path).items():
            db.execute(
                "INSERT OR IGNORE INTO preferences(key,value,confidence,source,updated_at) VALUES(?,?,?,?,?)",
                (key, str(value), 1.0, "default", now()),
            )
        db.commit()
    return db


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sync_projects(root: Path, db: sqlite3.Connection) -> int:
    projects_dir = root / "Projects"
    project_names = []
    for item in sorted(projects_dir.iterdir() if projects_dir.exists() else []):
        if not item.is_dir() or item.is_symlink():
            continue
        status_file = item / "12-status.md"
        status = "managed" if status_file.is_file() else "unmanaged"
        source = status_file if status == "managed" else item
        updated_at = datetime.fromtimestamp(source.stat().st_mtime, timezone.utc).isoformat()
        db.execute(
            "INSERT INTO projects(name,path,status,updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET path=excluded.path,status=excluded.status,updated_at=excluded.updated_at",
            (item.name, str(item), status, updated_at),
        )
        project_names.append(item.name)
    if project_names:
        placeholders = ",".join("?" for _ in project_names)
        db.execute(f"DELETE FROM projects WHERE name NOT IN ({placeholders})", project_names)
    else:
        db.execute("DELETE FROM projects")
    db.commit()
    return len(project_names)


def discover_tools(root: Path, db: sqlite3.Connection) -> list[dict]:
    registry = read_json(root / "Config" / "tools.json")
    results = []
    for spec in registry["tools"]:
        found = None
        for command in spec.get("commands", []):
            found = shutil.which(command)
            if found:
                break
        if not found:
            for pattern in spec.get("candidates", []):
                expanded = os.path.expandvars(pattern.replace("/", os.sep))
                matches = [p for p in glob.glob(expanded) if Path(p).is_file()]
                if matches:
                    found = matches[0]
                    break
        result = {
            "name": spec["name"],
            "found": bool(found),
            "path": found or "",
            "capabilities": spec.get("capabilities", []),
        }
        results.append(result)
        db.execute(
            "INSERT INTO tools(name,found,path,capabilities,checked_at) VALUES(?,?,?,?,?) "
            "ON CONFLICT(name) DO UPDATE SET found=excluded.found,path=excluded.path,capabilities=excluded.capabilities,checked_at=excluded.checked_at",
            (result["name"], int(result["found"]), result["path"], json.dumps(result["capabilities"], ensure_ascii=False), now()),
        )
    db.commit()
    return results


EXTENSIONS = {
    "literature": {".bib", ".ris", ".enw", ".nbib"},
    "data": {".csv", ".tsv", ".xlsx", ".xls", ".json", ".parquet", ".sav", ".dta", ".mat"},
    "code": {".py", ".r", ".rmd", ".ipynb", ".m", ".ps1", ".js", ".ts", ".sql"},
    "figures": {".png", ".jpg", ".jpeg", ".gif", ".svg", ".tif", ".tiff", ".webp"},
    "slides": {".ppt", ".pptx", ".odp"},
    "archives": {".zip", ".7z", ".rar", ".tar", ".gz"},
    "installers": {".exe", ".msi", ".msix", ".appx"},
    "media": {".mp3", ".wav", ".m4a", ".mp4", ".mov", ".mkv", ".avi"},
    "documents": {".doc", ".docx", ".odt", ".txt", ".md", ".qmd", ".tex", ".pdf"},
}


def extract_text(path: Path, limit: int = 65536) -> str:
    suffix = path.suffix.lower()
    text_suffixes = {".txt", ".md", ".qmd", ".csv", ".tsv", ".json", ".yaml", ".yml", ".py", ".r", ".ps1", ".tex", ".html"}
    try:
        if suffix in text_suffixes:
            return path.read_text(encoding="utf-8-sig", errors="ignore")[:limit]
        if suffix in {".docx", ".pptx", ".xlsx"}:
            prefixes = {".docx": ("word/",), ".pptx": ("ppt/slides/",), ".xlsx": ("xl/sharedStrings", "xl/worksheets/")}[suffix]
            pieces = []
            with zipfile.ZipFile(path) as package:
                for name in package.namelist():
                    if name.endswith(".xml") and any(name.startswith(prefix) for prefix in prefixes):
                        raw = package.read(name).decode("utf-8", errors="ignore")
                        pieces.extend(re.findall(r">([^<>]+)<", raw))
                        if sum(map(len, pieces)) >= limit:
                            break
            return " ".join(pieces)[:limit]
        if suffix == ".pdf":
            try:
                from pypdf import PdfReader
                pieces = []
                for page in PdfReader(str(path)).pages[:5]:
                    pieces.append(page.extract_text() or "")
                    if sum(map(len, pieces)) >= limit:
                        break
                return " ".join(pieces)[:limit]
            except (ImportError, OSError, ValueError):
                command = shutil.which("pdftotext")
                if command:
                    run = subprocess.run([command, "-f", "1", "-l", "5", str(path), "-"], capture_output=True, timeout=20)
                    return run.stdout.decode("utf-8", errors="ignore")[:limit]
                return ""
    except (OSError, UnicodeError, zipfile.BadZipFile):
        return ""
    return ""


def classify_detail(path: Path) -> dict:
    name = path.name.lower()
    content = extract_text(path).lower()
    evidence = f"{name} {content[:12000]}"
    suffix = path.suffix.lower()
    rules = [
        ("official_notice", ("通知", "公告", "申报指南", "报名通知", "official notice", "call for"), "documents"),
        ("template", ("模板", "template", "范本", "填写说明"), "documents"),
        ("patent", ("专利", "发明专利", "实用新型", "patent"), "evidence"),
        ("certificate", ("证书", "证明", "获奖", "营业执照", "certificate", "award"), "evidence"),
        ("experiment_record", ("实验记录", "实验报告", "测试报告", "原始数据", "实验数据", "lab report"), "evidence"),
        ("manuscript_final", ("终稿", "final", "定稿", "提交版", "submit"), "manuscript"),
        ("manuscript_draft", ("初稿", "草稿", "draft", "v0.", "修订版"), "manuscript"),
        ("manuscript", ("申报书", "正文", "商业计划书", "计划书", "manuscript"), "manuscript"),
        ("literature", ("论文", "paper", "article", "journal", "文献", "参考文献", "abstract", "doi"), "literature"),
        ("data_dictionary", ("数据字典", "变量说明", "codebook"), "data"),
        ("source_material", ("原始材料", "原始资料", "source", "附件", "材料"), "documents"),
    ]
    filename_rules = [
        ("manuscript_final", ("final", "终稿", "定稿", "提交版"), "manuscript"),
        ("manuscript_draft", ("draft", "初稿", "草稿", "修订版"), "manuscript"),
        ("template", ("template", "模板"), "documents"),
        ("official_notice", ("通知", "公告", "requirements"), "documents"),
    ]
    for semantic, words, primary in filename_rules:
        matched = [word for word in words if word in name]
        if matched:
            return {"primary_category": primary, "secondary_category": semantic, "reason": f"文件名命中：{', '.join(matched)}", "confidence": 0.95, "needs_review": False}
    for semantic, words, primary in rules:
        matched = [word for word in words if word in name or evidence.count(word) >= 2]
        if matched:
            confidence = 0.92 if len(matched) > 1 else 0.82
            return {"primary_category": primary, "secondary_category": semantic, "reason": f"命中关键词：{', '.join(matched[:4])}", "confidence": confidence, "needs_review": confidence < 0.85}
    if suffix in {".pdf", ".doc", ".docx", ".md", ".qmd", ".txt"}:
        if any(word in evidence for word in ("论文", "paper", "article", "journal", "文献", "参考文献", "abstract")):
            return {"primary_category": "literature", "secondary_category": "literature", "reason": "文献关键词", "confidence": 0.78, "needs_review": True}
    for category, suffixes in EXTENSIONS.items():
        if suffix in suffixes:
            semantic = "image" if category == "figures" else "video_or_audio" if category == "media" else category
            return {"primary_category": category, "secondary_category": semantic, "reason": f"扩展名匹配：{suffix}", "confidence": 0.72, "needs_review": False}
    return {"primary_category": "other", "secondary_category": "unclassified", "reason": "没有匹配规则", "confidence": 0.2, "needs_review": True}


def classify(path: Path) -> str:
    return classify_detail(path)["primary_category"]


def safe_files(source: Path, config: dict):
    ignored_suffixes = {x.lower() for x in config["ignore_suffixes"]}
    ignored_names = {x.lower() for x in config["ignore_names"]}
    for path in source.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        if path.name == ".gitkeep" or path.name.lower() in ignored_names or path.suffix.lower() in ignored_suffixes:
            continue
        yield path


def write_plan(root: Path, source: Path, project: str | None, paths: list[Path]) -> Path:
    config = read_json(root / "Config" / "organizer.json")
    mapping = config["project_categories"] if project else config["global_categories"]
    project_root = root / "Projects" / project if project else root
    entries = []
    for path in paths:
        detail = classify_detail(path)
        category = detail["primary_category"]
        secondary = detail["secondary_category"]
        destination = project_root / mapping[category] / secondary / path.name
        if destination.resolve() == path.resolve():
            continue
        entries.append({
            "source": str(path),
            "destination": str(destination),
            "category": category,
            "primary_category": category,
            "secondary_category": secondary,
            "classification_reason": detail["reason"],
            "confidence": detail["confidence"],
            "needs_review": detail["needs_review"],
            "size": path.stat().st_size,
            "sha256": sha256(path),
        })
    plan_id = datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:8]
    plan = {"id": plan_id, "created_at": now(), "source": str(source), "project": project, "mode": "copy", "entries": entries}
    plan_path = root / "State" / "plans" / f"{plan_id}.json"
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan_path


def scan_files(root: Path, source: Path, project: str | None) -> Path:
    source = source.resolve()
    if not source.is_dir():
        raise SystemExit(f"Source directory does not exist: {source}")
    home = Path.home().resolve()
    if source in {home, home.parent, Path(source.anchor)}:
        raise SystemExit("Refusing to scan a broad home or drive root. Choose a specific folder.")
    project_root = root / "Projects" / project if project else root
    if project and not project_root.is_dir():
        raise SystemExit(f"Unknown project: {project}")
    try:
        source.relative_to(root.resolve())
        if not project:
            raise SystemExit("A source inside the workstation requires --project and must be that project's 00_inbox.")
        source.relative_to((project_root / "00_inbox").resolve())
    except ValueError:
        if project and root.resolve() in source.parents:
            raise SystemExit("Inside a project, only 00_inbox can be used as an organizer source.")
    config = read_json(root / "Config" / "organizer.json")
    return write_plan(root, source, project, list(safe_files(source, config)))


def resolve_plan(root: Path, value: str) -> Path:
    candidate = Path(value)
    if candidate.is_file():
        return candidate.resolve()
    candidate = root / "State" / "plans" / f"{value}.json"
    if not candidate.is_file():
        raise SystemExit(f"Plan not found: {value}")
    return candidate


def apply_plan(root: Path, db: sqlite3.Connection, value: str) -> str:
    plan = read_json(resolve_plan(root, value))
    run_id = uuid.uuid4().hex
    project = plan.get("project")
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (run_id, "organize", project, "running", f"plan={plan['id']}", now(), None))
    copied = skipped = conflicts = 0
    manifest_rows = []
    for entry in plan["entries"]:
        source = Path(entry["source"])
        destination = Path(entry["destination"])
        status = "copied"
        try:
            destination.resolve().relative_to(root.resolve())
            destination_allowed = True
        except ValueError:
            destination_allowed = False
        if not destination_allowed:
            status = "destination_outside_workstation"
            conflicts += 1
        elif not source.is_file() or sha256(source) != entry["sha256"]:
            status = "source_changed"
            conflicts += 1
        elif destination.exists():
            status = "duplicate" if destination.is_file() and sha256(destination) == entry["sha256"] else "conflict"
            skipped += 1
        else:
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            if sha256(destination) != entry["sha256"]:
                destination.unlink(missing_ok=True)
                status = "verification_failed"
                conflicts += 1
            else:
                copied += 1
        db.execute(
            "INSERT INTO file_operations VALUES(?,?,?,?,?,?,?,?)",
            (uuid.uuid4().hex, run_id, str(source), str(destination), entry["sha256"], status, now(), None),
        )
        manifest_rows.append((now(), str(source), str(destination), entry["sha256"], entry.get("category", ""), status, run_id))
    if project and manifest_rows:
        manifest = root / "Projects" / project / "08_evidence" / "intake-manifest.csv"
        manifest.parent.mkdir(parents=True, exist_ok=True)
        new_file = not manifest.exists()
        with manifest.open("a", newline="", encoding="utf-8-sig") as stream:
            writer = csv.writer(stream)
            if new_file:
                writer.writerow(("time", "source", "destination", "sha256", "category", "status", "run_id"))
            writer.writerows(manifest_rows)
    final = "completed" if conflicts == 0 else "needs_attention"
    summary = f"copied={copied}; skipped={skipped}; conflicts={conflicts}"
    db.execute("UPDATE runs SET status=?,summary=?,finished_at=? WHERE id=?", (final, summary, now(), run_id))
    db.commit()
    print(f"run={run_id} {summary}")
    return run_id


def undo_run(db: sqlite3.Connection, run_id: str) -> tuple[int, int]:
    rows = db.execute("SELECT * FROM file_operations WHERE run_id=? AND status='copied' AND undone_at IS NULL", (run_id,)).fetchall()
    removed = protected = 0
    for row in rows:
        destination = Path(row["destination"])
        try:
            destination.resolve().relative_to(Path(db.execute("PRAGMA database_list").fetchone()[2]).parent.parent.resolve())
            destination_allowed = True
        except ValueError:
            destination_allowed = False
        if destination_allowed and destination.is_file() and sha256(destination) == row["sha256"]:
            destination.unlink()
            db.execute("UPDATE file_operations SET undone_at=? WHERE id=?", (now(), row["id"]))
            removed += 1
        else:
            protected += 1
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, "undo", None, "completed", f"target={run_id}; removed={removed}; protected={protected}", now(), now()))
    db.commit()
    return removed, protected


def add_task(db: sqlite3.Connection, project: str | None, title: str) -> str:
    task_id = uuid.uuid4().hex[:12]
    stamp = now()
    db.execute("INSERT INTO tasks VALUES(?,?,?,?,?,?)", (task_id, project, title, "todo", stamp, stamp))
    db.commit()
    return task_id


def preferences(db: sqlite3.Connection) -> dict[str, str]:
    return {row["key"]: row["value"] for row in db.execute("SELECT key,value FROM preferences")}


def set_preference(db: sqlite3.Connection, key: str, value: str, source: str = "explicit") -> None:
    db.execute(
        "INSERT INTO preferences(key,value,confidence,source,updated_at) VALUES(?,?,?,?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,confidence=excluded.confidence,source=excluded.source,updated_at=excluded.updated_at",
        (key, value, 1.0, source, now()),
    )
    db.commit()


def route_task(root: Path, db: sqlite3.Connection, text: str) -> dict:
    specs = read_json(root / "Config" / "work-types.json")["types"]
    ranked = []
    lowered = text.lower()
    for spec in specs:
        score = sum(1 for word in spec["indicators"] if word.lower() in lowered)
        ranked.append((score, spec))
    score, selected = max(ranked, key=lambda item: item[0])
    if score == 0:
        selected = next(item for item in specs if item["name"] == "general")
    prefs = preferences(db)
    preferred_tools = prefs.get(f"route.{selected['name']}.tools")
    preferred_resource = prefs.get(f"route.{selected['name']}.resource")
    suggested_tools = json.loads(preferred_tools) if preferred_tools else selected["tools"]
    discovered = {row["name"]: bool(row["found"]) for row in db.execute("SELECT name,found FROM tools")}
    unavailable_tools = [name for name in suggested_tools if discovered.get(name) is False]
    available_tools = [name for name in suggested_tools if discovered.get(name, True)]
    route_id = uuid.uuid4().hex
    result = {
        "route_id": route_id,
        "task_type": selected["name"],
        "confidence": min(1.0, 0.45 + score * 0.15),
        "tools": available_tools or suggested_tools,
        "unavailable_tools": unavailable_tools,
        "capabilities": selected["capabilities"],
        "resource_mode": preferred_resource or selected["resource"],
        "policy": prefs.get("resource_policy", "local-first"),
        "agent_count": int(prefs.get("default_agent_count", "1")),
        "web_policy": prefs.get("web_policy", "only-when-current-or-requested"),
    }
    db.execute(
        "INSERT INTO routing_history VALUES(?,?,?,?,?,?)",
        (route_id, result["task_type"], result["resource_mode"], json.dumps(result["tools"], ensure_ascii=False), None, now()),
    )
    db.commit()
    return result


def route_feedback(db: sqlite3.Connection, route_id: str, decision: str) -> dict:
    if decision not in {"accepted", "rejected"}:
        raise ValueError("decision must be accepted or rejected")
    row = db.execute("SELECT * FROM routing_history WHERE id=?", (route_id,)).fetchone()
    if not row:
        raise ValueError("route id not found")
    db.execute("UPDATE routing_history SET outcome=? WHERE id=?", (decision, route_id))
    learned = False
    if decision == "accepted":
        count = db.execute(
            "SELECT COUNT(*) FROM routing_history WHERE task_type=? AND selected_tools=? AND resource_mode=? AND outcome='accepted'",
            (row["task_type"], row["selected_tools"], row["resource_mode"]),
        ).fetchone()[0]
        if count >= 3:
            set_preference(db, f"route.{row['task_type']}.tools", row["selected_tools"], "repeated-feedback")
            set_preference(db, f"route.{row['task_type']}.resource", row["resource_mode"], "repeated-feedback")
            learned = True
    db.commit()
    return {"route_id": route_id, "decision": decision, "learned": learned}


def search_github_reuse(root: Path, db: sqlite3.Connection, query: str) -> dict:
    query = " ".join(query.split()).strip()
    if len(query) < 3:
        raise ValueError("GitHub search query is too short")
    if len(query) > 240:
        raise ValueError("GitHub search query is too long; use concise keywords")
    policy = read_json(root / "Config" / "reuse-policy.json")
    count = max(1, min(int(policy.get("max_results", 8)), 20))
    qualified = query
    if policy.get("exclude_archived", True):
        qualified += " archived:false"
    if policy.get("exclude_forks", True):
        qualified += " fork:false"
    url = "https://api.github.com/search/repositories?" + urlencode({
        "q": qualified, "sort": "stars", "order": "desc", "per_page": count,
    })
    request = Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Personal-AI-Workstation/1.0",
    })
    source = "github-public-api"
    try:
        with urlopen(request, timeout=20) as response:
            payload = json.load(response)
            rate = {
                "remaining": response.headers.get("X-RateLimit-Remaining"),
                "reset": response.headers.get("X-RateLimit-Reset"),
            }
    except HTTPError as exc:
        if exc.code not in {403, 429}:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            raise ValueError(f"GitHub API returned HTTP {exc.code}: {detail}") from exc
        source = "github-web-search-fallback"
        web_url = "https://github.com/search?" + urlencode({"q": qualified, "type": "repositories"})
        web_request = Request(web_url, headers={"User-Agent": "Mozilla/5.0 Personal-AI-Workstation/1.0"})
        try:
            with urlopen(web_request, timeout=20) as response:
                page = response.read().decode("utf-8", errors="replace")
            match = re.search(r'<script type="application/json" data-target="react-app.embeddedData">(.*?)</script>', page, re.S)
            if not match:
                raise ValueError("GitHub search page format was not recognized")
            route = json.loads(match.group(1))["payload"]["blackbirdSearchRoute"]
            web_items = []
            for entry in route.get("results", [])[:count]:
                repo = entry.get("repo", {}).get("repository", {})
                full_name = f"{repo.get('owner_login', '')}/{repo.get('name', '')}".strip("/")
                if not full_name:
                    continue
                description = html.unescape(re.sub(r"<[^>]+>", "", entry.get("hl_trunc_description") or ""))
                web_items.append({
                    "full_name": full_name,
                    "html_url": f"https://github.com/{full_name}",
                    "description": description,
                    "stargazers_count": int(entry.get("followers") or 0),
                    "language": entry.get("language") or "",
                    "license": {"spdx_id": "UNVERIFIED"},
                    "updated_at": repo.get("updated_at"),
                    "pushed_at": repo.get("updated_at"),
                    "archived": bool(entry.get("archived")),
                    "fork": False,
                })
            payload = {"items": web_items}
            rate = {"remaining": "api-rate-limited", "reset": exc.headers.get("X-RateLimit-Reset")}
        except (KeyError, TypeError, json.JSONDecodeError, URLError) as fallback_exc:
            raise ValueError(f"GitHub API was rate limited and web fallback failed: {fallback_exc}") from fallback_exc
    except URLError as exc:
        raise ValueError(f"Cannot reach GitHub API: {exc.reason}") from exc
    preferred = set(policy.get("preferred_licenses", []))
    current = datetime.now(timezone.utc)
    candidates = []
    for item in payload.get("items", []):
        license_info = item.get("license") or {}
        license_id = license_info.get("spdx_id") or "NOASSERTION"
        pushed = item.get("pushed_at") or item.get("updated_at")
        try:
            age_days = max(0, (current - datetime.fromisoformat(pushed.replace("Z", "+00:00"))).days)
        except (AttributeError, ValueError):
            age_days = 99999
        flags = []
        if license_id in {"NOASSERTION", "Other", ""}:
            flags.append("license-needs-review")
        if license_id == "UNVERIFIED":
            flags.append("license-unverified")
        if license_id.startswith(("GPL-", "AGPL-", "LGPL-")):
            flags.append("copyleft-license")
        if age_days > int(policy.get("stale_days", 730)):
            flags.append("stale")
        if item.get("archived"):
            flags.append("archived")
        if item.get("fork"):
            flags.append("fork")
        stars = int(item.get("stargazers_count", 0))
        score = min(45, stars // 100) + (25 if age_days <= 365 else 10 if age_days <= 730 else 0)
        score += 20 if license_id in preferred else 0
        score += 10 if item.get("description") else 0
        score -= 30 * len([flag for flag in flags if flag in {"archived", "license-needs-review"}])
        if score < int(policy.get("minimum_score", 10)):
            continue
        candidates.append({
            "name": item.get("full_name"),
            "url": item.get("html_url"),
            "description": (item.get("description") or "")[:500],
            "stars": stars,
            "language": item.get("language") or "",
            "license": license_id,
            "updated_at": item.get("updated_at"),
            "pushed_at": pushed,
            "age_days": age_days,
            "score": score,
            "risk_flags": flags,
            "decision": "review-required",
        })
    candidates.sort(key=lambda x: (x["score"], x["stars"]), reverse=True)
    review_id = "REUSE-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    result = {
        "id": review_id,
        "created_at": now(),
        "source": source,
        "query": query,
        "policy": "review-only; no clone, install, or execution",
        "rate_limit": rate,
        "candidates": candidates,
    }
    output = root / "State" / "reuse" / f"{review_id}.json"
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        uuid.uuid4().hex, "reuse-search", None, "completed",
        f"review={review_id}; candidates={len(candidates)}", now(), now(),
    ))
    db.commit()
    result["path"] = str(output)
    return result


def ai_status() -> dict:
    global _AI_STATUS_CACHE
    cached = _AI_STATUS_CACHE
    if cached and time.monotonic() - cached[0] < 15:
        return dict(cached[1])
    executable = shutil.which("codex")
    if not executable:
        result = {"available": False, "logged_in": False, "detail": "Codex CLI not found"}
        _AI_STATUS_CACHE = (time.monotonic(), result)
        return dict(result)
    try:
        completed = subprocess.run([executable, "login", "status"], capture_output=True, text=True, timeout=5)
    except subprocess.TimeoutExpired:
        result = {"available": True, "logged_in": False, "detail": "Codex login status timed out"}
        _AI_STATUS_CACHE = (time.monotonic(), result)
        return dict(result)
    detail = (completed.stdout or completed.stderr).strip()
    result = {
        "available": True,
        "logged_in": completed.returncode == 0 and "logged in" in detail.lower(),
        "detail": detail,
        "path": executable,
    }
    _AI_STATUS_CACHE = (time.monotonic(), result)
    return dict(result)


def ai_plan(root: Path, db: sqlite3.Connection, project: str, request_text: str) -> dict:
    project_root = (root / "Projects" / project).resolve()
    projects_root = (root / "Projects").resolve()
    if project_root.parent != projects_root or not project_root.is_dir():
        raise ValueError(f"Project does not exist: {project}")
    request_text = " ".join(request_text.split()).strip()
    if len(request_text) < 3:
        raise ValueError("AI request is too short")
    if len(request_text) > 4000:
        raise ValueError("AI request is too long")
    status = ai_status()
    if not status["logged_in"]:
        raise ValueError("Codex CLI is not logged in with ChatGPT")
    plan_id = "AI-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    output = root / "State" / "ai" / f"{plan_id}.md"
    prompt = (
        "只做只读分析，不要修改任何文件，不要执行安装、下载、上传、发布或其他外部操作。"
        "先阅读项目中的 AGENTS.md、10-README.MD、11-project.yaml 和 12-status.md（若存在）。"
        "用中文给出简洁的执行方案：目标、可复用的现有工具或GitHub搜索关键词、步骤、需要人工确认的动作、验收方法。\n\n"
        f"用户需求：{request_text}"
    )
    command = [
        status["path"], "exec", *codex_sandbox_compat_args(), "--ephemeral", "--sandbox", "read-only",
        "--cd", str(project_root), "--output-last-message", str(output), prompt,
    ]
    if not (project_root / ".git").exists():
        command.insert(2, "--skip-git-repo-check")
    started = now()
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=600)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("Codex planning timed out after 10 minutes") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown Codex error")[-2000:]
        raise ValueError(f"Codex planning failed: {detail}")
    if not output.exists():
        raise ValueError("Codex completed without producing a plan")
    response = output.read_text(encoding="utf-8", errors="replace")
    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (
        uuid.uuid4().hex, "ai-plan", project, "completed", f"plan={plan_id}", started, now(),
    ))
    db.commit()
    return {"id": plan_id, "project": project, "mode": "codex-chatgpt-read-only", "path": str(output), "response": response}


def process_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.GetExitCodeProcess.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_ulong)]
        kernel.GetExitCodeProcess.restype = ctypes.c_int
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            return bool(kernel.GetExitCodeProcess(handle, ctypes.byref(exit_code))) and exit_code.value == 259
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def watcher_status(root: Path) -> dict:
    pid_path = root / "State" / "watcher.pid"
    if not pid_path.exists():
        return {"running": False, "pid": None}
    try:
        pid = int(pid_path.read_text(encoding="ascii").strip())
        running = process_alive(pid)
        return {"running": running, "pid": pid if running else None}
    except (ValueError, OSError):
        return {"running": False, "pid": None}


def control_status(root: Path) -> dict:
    pid_path = root / "State" / "control.pid"
    if not pid_path.exists():
        return {"running": False, "pid": None}
    try:
        pid = int(pid_path.read_text(encoding="ascii").strip())
        running = process_alive(pid)
        return {"running": running, "pid": pid if running else None}
    except (ValueError, OSError):
        return {"running": False, "pid": None}


def control_launch(root: Path, port: int) -> dict:
    state = control_status(root)
    if state["running"]:
        return {**state, "url": f"http://127.0.0.1:{port}"}
    # A retiring server can release its PID file before its listener closes.
    # Never start a replacement on an occupied port: it could clear the old stop signal.
    for _ in range(20):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                busy = True
        except OSError:
            busy = False
        if not busy:
            break
        time.sleep(0.25)
    if busy:
        return {"running": False, "pid": None, "url": f"http://127.0.0.1:{port}",
                "error": "port is still in use; wait for the previous service to exit"}
    log_path = root / "Logs" / "control.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_stream = log_path.open("a", encoding="utf-8")
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--root", str(root), "serve", "--port", str(port)],
        cwd=root, stdin=subprocess.DEVNULL, stdout=log_stream, stderr=log_stream,
        close_fds=True, creationflags=flags,
    )
    log_stream.close()
    for _ in range(10):
        time.sleep(0.2)
        if control_status(root)["running"]:
            break
    return {**control_status(root), "url": f"http://127.0.0.1:{port}"}


def control_stop(root: Path) -> dict:
    (root / "State" / "control.stop").write_text(now(), encoding="utf-8")
    return {"stop_requested": True, **control_status(root)}


def watch_run(root: Path, db: sqlite3.Connection) -> None:
    config = read_json(root / "Config" / "watcher.json")
    source = Path(os.path.expandvars(config["source"])).resolve()
    if not source.is_dir():
        raise SystemExit(f"Watcher source does not exist: {source}")
    project = config.get("project")
    interval = max(3, int(config.get("interval_seconds", 10)))
    required = max(2, int(config.get("stable_checks", 2)))
    stop_path = root / "State" / "watcher.stop"
    pid_path = root / "State" / "watcher.pid"
    stop_path.unlink(missing_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="ascii")
    organizer = read_json(root / "Config" / "organizer.json")
    existing = db.execute("SELECT COUNT(*) FROM watch_files").fetchone()[0]
    if not existing and config.get("baseline_existing", True):
        for path in safe_files(source, organizer):
            stat = path.stat()
            db.execute("INSERT OR REPLACE INTO watch_files VALUES(?,?,?,?,?,?)", (str(path), stat.st_size, stat.st_mtime, required, "baseline", now()))
        db.commit()
    try:
        while not stop_path.exists():
            for path in safe_files(source, organizer):
                stat = path.stat()
                row = db.execute("SELECT * FROM watch_files WHERE path=?", (str(path),)).fetchone()
                if not row:
                    db.execute("INSERT INTO watch_files VALUES(?,?,?,?,?,?)", (str(path), stat.st_size, stat.st_mtime, 0, None, now()))
                    continue
                if row["size"] != stat.st_size or row["mtime"] != stat.st_mtime:
                    db.execute("UPDATE watch_files SET size=?,mtime=?,stable_count=0,planned_sha=NULL,updated_at=? WHERE path=?", (stat.st_size, stat.st_mtime, now(), str(path)))
                    continue
                if row["planned_sha"]:
                    continue
                stable = row["stable_count"] + 1
                db.execute("UPDATE watch_files SET size=?,mtime=?,stable_count=?,updated_at=? WHERE path=?", (stat.st_size, stat.st_mtime, stable, now(), str(path)))
                if stable >= required:
                    plan_path = write_plan(root, source, project, [path])
                    digest = sha256(path)
                    db.execute("UPDATE watch_files SET planned_sha=?,updated_at=? WHERE path=?", (digest, now(), str(path)))
                    db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,?)", (uuid.uuid4().hex, "watch-plan", project, "completed", f"plan={plan_path.stem}; file={path.name}", now(), now()))
            db.commit()
            time.sleep(interval)
    finally:
        pid_path.unlink(missing_ok=True)
        stop_path.unlink(missing_ok=True)


def watch_launch(root: Path) -> dict:
    state = watcher_status(root)
    if state["running"]:
        return state
    config = read_json(root / "Config" / "watcher.json")
    source = Path(os.path.expandvars(config["source"])).resolve()
    if not source.is_dir():
        raise ValueError(f"Watcher source does not exist: {source}")
    log_path = root / "Logs" / "watcher.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_stream = log_path.open("a", encoding="utf-8")
    flags = 0
    if os.name == "nt":
        flags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--root", str(root), "watch", "run"],
        cwd=root, stdin=subprocess.DEVNULL, stdout=log_stream, stderr=log_stream,
        close_fds=True, creationflags=flags,
    )
    log_stream.close()
    for _ in range(10):
        time.sleep(0.2)
        if watcher_status(root)["running"]:
            break
    return watcher_status(root)


def watch_stop(root: Path) -> dict:
    (root / "State" / "watcher.stop").write_text(now(), encoding="utf-8")
    return {"stop_requested": True, **watcher_status(root)}


def status_data(root: Path, db: sqlite3.Connection) -> dict:
    sync_projects(root, db)
    return {
        "generated_at": now(),
        "projects": [dict(x) for x in db.execute("SELECT * FROM projects ORDER BY name")],
        "tools": [dict(x) for x in db.execute("SELECT * FROM tools ORDER BY name")],
        "tasks": [dict(x) for x in db.execute("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT 50")],
        "runs": [dict(x) for x in db.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 30")],
        "plans": [p.stem for p in sorted((root / "State" / "plans").glob("*.json"), reverse=True)[:20]],
        "reuse_reviews": [p.stem for p in sorted((root / "State" / "reuse").glob("*.json"), reverse=True)[:20]],
        "preferences": preferences(db),
        "watcher": watcher_status(root),
        "ai": ai_status(),
    }


def project_overview_content(root: Path, project: str) -> dict:
    projects_root = (root / "Projects").resolve()
    project_root = (projects_root / project).resolve()
    if project_root.parent != projects_root or not project_root.is_dir():
        raise ValueError("unknown project")
    documents = []
    for name in ("10-README.MD", "12-status.md"):
        path = project_root / name
        if not path.is_file() or path.is_symlink() or path.resolve().parent != project_root:
            continue
        with path.open("rb") as stream:
            content = stream.read(128 * 1024 + 1)
        truncated = len(content) > 128 * 1024
        documents.append({
            "name": name,
            "content": content[:128 * 1024].decode("utf-8-sig", errors="replace"),
            "truncated": truncated,
        })
    return {"project": project, "documents": documents}


def education_status(root: Path) -> dict:
    """Read the University course catalog without opening source materials."""
    courses_root = (root / "Projects" / "University" / "courses").resolve()
    project_root = (root / "Projects" / "University").resolve()
    if courses_root.parent != project_root or not courses_root.is_dir():
        return {"project": "University", "courses": [], "total": 0, "error": "课程目录不存在"}

    courses = []
    for course_root in sorted(courses_root.iterdir(), key=lambda item: item.name.lower()):
        if not course_root.is_dir() or course_root.name.startswith("."):
            continue
        metadata = {}
        course_file = course_root / "course.yaml"
        if course_file.is_file():
            for raw_line in course_file.read_text(encoding="utf-8-sig", errors="replace").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or line.startswith("-") or ":" not in line:
                    continue
                key, value = line.split(":", 1)
                key = key.strip()
                if key not in {"id", "name", "term", "status"}:
                    continue
                value = value.strip().strip("'\"")
                metadata[key] = None if value in {"", "null", "~"} else value
        sources_root = course_root / "01_sources"
        source_count = sum(1 for item in sources_root.iterdir() if item.is_file()) if sources_root.is_dir() else 0
        lessons_root = course_root / "lessons"
        lesson_count = sum(1 for item in lessons_root.iterdir() if item.is_file()) if lessons_root.is_dir() else 0
        courses.append({
            "id": metadata.get("id") or course_root.name,
            "name": metadata.get("name") or course_root.name,
            "term": metadata.get("term"),
            "status": metadata.get("status") or "unknown",
            "source_count": source_count,
            "lesson_count": lesson_count,
            "has_mission": (course_root / "MISSION.md").is_file(),
            "has_course_yaml": course_file.is_file(),
        })
    return {
        "project": "University",
        "courses": courses,
        "total": len(courses),
        "source": "Projects/University/courses/*/course.yaml",
    }

def latex_documents(root: Path) -> list[dict]:
    documents = []
    for project_root in sorted((root / "Projects").glob("*")):
        latex_root = project_root / "06_manuscript" / "latex"
        if not project_root.is_dir() or not latex_root.is_dir():
            continue
        for document_root in sorted(latex_root.glob("*")):
            main = document_root / "main.tex"
            if document_root.is_dir() and main.is_file():
                documents.append({
                    "project": project_root.name,
                    "document": document_root.name,
                    "path": str(document_root),
                })
    return documents


def latex_document_path(root: Path, project: str, document: str | None = None) -> Path:
    projects_root = (root / "Projects").resolve()
    project_root = (projects_root / project).resolve()
    if project_root.parent != projects_root or not project_root.is_dir():
        raise ValueError(f"项目不存在：{project}")
    latex_root = (project_root / "06_manuscript" / "latex").resolve()
    if not latex_root.is_dir():
        raise ValueError(f"项目没有 LaTeX 目录：{latex_root}")
    if document:
        document_root = (latex_root / document).resolve()
    else:
        candidates = [path for path in latex_root.iterdir() if path.is_dir() and (path / "main.tex").is_file()]
        if len(candidates) != 1:
            raise ValueError(f"请指定 LaTeX 文档目录；可选数量：{len(candidates)}")
        document_root = candidates[0]
    if document_root.parent != latex_root or not document_root.is_dir():
        raise ValueError("LaTeX 文档必须是项目 06_manuscript\\latex 下的一级目录")
    if not (document_root / "main.tex").is_file():
        raise ValueError(f"主文件不存在：{document_root / 'main.tex'}")
    return document_root


def run_latex(root: Path, project: str, document: str | None, clean: bool = False) -> dict:
    document_root = latex_document_path(root, project, document)
    build = document_root / "build"
    dist = document_root / "dist"
    build.mkdir(exist_ok=True)
    dist.mkdir(exist_ok=True)
    latexmk = shutil.which("latexmk")
    if not latexmk:
        raise ValueError("未发现 latexmk，请先安装 TeX Live")
    args = [latexmk]
    args.extend(["-C", "-outdir=build"] if clean else ["-xelatex", "-file-line-error", "-interaction=nonstopmode", "-synctex=1", "-outdir=build"])
    args.append("main.tex")
    completed = subprocess.run(args, cwd=document_root, capture_output=True, text=True, timeout=600)
    output = (completed.stdout + "\n" + completed.stderr).strip()
    if completed.returncode:
        raise ValueError(f"LaTeX {'清理' if clean else '编译'}失败（退出码 {completed.returncode}）：\n{output[-4000:]}")
    result = {"status": "cleaned" if clean else "built", "project": project, "document": document_root.name, "output": output[-4000:]}
    if not clean:
        pdf = build / "main.pdf"
        if not pdf.is_file():
            raise ValueError(f"编译完成但未找到 PDF：{pdf}")
        delivery = dist / f"{document_root.name}.pdf"
        shutil.copy2(pdf, delivery)
        result.update({"pdf": str(delivery), "sha256": sha256(delivery)})
    return result


def dashboard_html(data: dict) -> str:
    projects = "".join(f"<tr><td>{html.escape(x['name'])}</td><td>{x['status']}</td><td>{html.escape(x['path'])}</td></tr>" for x in data["projects"])
    tools = "".join(f"<tr><td>{html.escape(x['name'])}</td><td><span class={'ok' if x['found'] else 'off'}>{'可用' if x['found'] else '未发现'}</span></td><td>{html.escape(x['path'] or '')}</td></tr>" for x in data["tools"])
    tasks = "".join(f"<tr><td>{html.escape(x['project'] or '-')}</td><td>{html.escape(x['title'])}</td><td>{x['status']}</td></tr>" for x in data["tasks"]) or "<tr><td colspan=3>暂无任务</td></tr>"
    runs = "".join(f"<tr><td>{x['created_at'][:19]}</td><td>{x['kind']}</td><td>{x['status']}</td><td>{html.escape(x['summary'] or '')}</td></tr>" for x in data["runs"]) or "<tr><td colspan=4>暂无运行记录</td></tr>"
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>AI Workstation</title><style>
    :root{{--bg:#0b1020;--panel:#121a2e;--line:#25314d;--text:#e7ecf5;--muted:#93a4bf;--accent:#71d6b3;--bad:#ef9a9a}}*{{box-sizing:border-box}}body{{margin:0;background:linear-gradient(135deg,#0b1020,#111b33);color:var(--text);font:15px/1.5 system-ui}}main{{max-width:1200px;margin:auto;padding:32px}}h1{{font-size:30px;margin:0}}.sub{{color:var(--muted);margin:4px 0 26px}}.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px}}.card,section{{background:rgba(18,26,46,.94);border:1px solid var(--line);border-radius:14px;padding:18px}}.num{{font-size:28px;font-weight:700;color:var(--accent)}}section{{margin-top:16px;overflow:auto}}table{{width:100%;border-collapse:collapse}}th,td{{padding:9px;border-bottom:1px solid var(--line);text-align:left;white-space:nowrap}}th{{color:var(--muted)}}.ok{{color:var(--accent)}}.off{{color:var(--bad)}}code{{color:#b9d8ff}}@media(max-width:800px){{.grid{{grid-template-columns:1fr 1fr}}}}</style></head><body><main>
    <h1>Personal AI Workstation</h1><div class="sub">本地控制中心 · {data['generated_at']}</div>
    <div class="grid"><div class="card"><div class="num">{len(data['projects'])}</div>项目</div><div class="card"><div class="num">{sum(x['found'] for x in data['tools'])}</div>可用工具</div><div class="card"><div class="num">{len(data['tasks'])}</div>任务</div><div class="card"><div class="num">{len(data['plans'])}</div>整理计划</div></div>
    <section><h2>项目</h2><table><tr><th>名称</th><th>状态</th><th>路径</th></tr>{projects}</table></section>
    <section><h2>工具</h2><table><tr><th>工具</th><th>状态</th><th>路径</th></tr>{tools}</table></section>
    <section><h2>任务</h2><table><tr><th>项目</th><th>任务</th><th>状态</th></tr>{tasks}</table></section>
    <section><h2>最近执行</h2><table><tr><th>时间</th><th>类型</th><th>状态</th><th>摘要</th></tr>{runs}</table></section>
    <p class="sub">控制台只绑定 127.0.0.1。文件整理默认复制，原件保留。</p></main></body></html>'''


def write_dashboard(root: Path, db: sqlite3.Connection) -> Path:
    output = root / "Logs" / "dashboard.html"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(dashboard_html(status_data(root, db)), encoding="utf-8")
    return output


def serve(root: Path, db_path: Path, port: int):
    import obsidian_learning as learning
    import workstation_v4 as v4
    import workstation_widget as widget
    import workstation_embeds as embeds
    import workstation_layout_state as layout_state
    terminal_sessions = embeds.TerminalSessions()
    import workstation_deskbox as deskbox

    import workstation_launcher as launcher
    token = uuid.uuid4().hex
    page_template = (root / "Dashboard" / "index.html").read_text(encoding="utf-8")
    workbench_legacy_path = root / "Projects" / "Workstation-Visual-Console" / "04_code" / "workbench" / "index.html"
    workbench_path = workbench_legacy_path.with_name("layout-prototype.html")
    class Handler(BaseHTTPRequestHandler):
        def send_json(self, data, status=200):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if self.path == "/api/health":
                self.send_json({"ok": True, "service": "personal-ai-workstation", "api_version": 1})
                return
            if self.path == "/api/workbench/capabilities":
                self.send_json(workbench_capabilities())
                return
            if self.path == "/api/workbench/latex-documents":
                self.send_json(latex_documents(root))
                return
            request_path = urlsplit(self.path).path
            if request_path in {"/api/education/network", "/api/education/progress"}:
                from education_network import network_data
                values = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(values) - {"course"} or len(values.get("course", [])) > 1:
                    self.send_json({"error": "知识网络查询参数无效"}, 400)
                    return
                course = values.get("course", [None])[0]
                try:
                    if request_path == "/api/education/progress":
                        if course is None:
                            raise ValueError('请选择课程')
                        self.send_json(learning.course_progress(root, course))
                    else:
                        self.send_json(network_data(root, course))
                except ValueError as error:
                    self.send_json({"error": str(error)}, 404 if str(error) == "未知学科" else 422)
                except (OSError, KeyError, TypeError):
                    self.send_json({"error": "课程知识网络暂不可读，请检查课程配置"}, 503)
                return
            assets = {"/workbench/deskbox-plans.js": ("deskbox-plans.js", "application/javascript; charset=utf-8"),
                      "/workbench/codex-map.js": ("codex-map.js", "application/javascript; charset=utf-8"),
                      "/workbench/codex-manager.js": ("codex-manager.js", "application/javascript; charset=utf-8"),
                      "/workbench/workflow-canvas.js": ("workflow-canvas.js", "application/javascript; charset=utf-8"),
                      "/workbench/workflow-models.js": ("workflow-models.js", "application/javascript; charset=utf-8"),
                      "/workbench/coursework-runner.js": ("coursework-runner.js", "application/javascript; charset=utf-8"),
                      "/workbench/coursework-runner.css": ("coursework-runner.css", "text/css; charset=utf-8"),
                      "/workbench/matt-flow.js": ("matt-flow.js", "application/javascript; charset=utf-8"),
                      "/workbench/matt-flow.css": ("matt-flow.css", "text/css; charset=utf-8"),
                      "/workbench/matt-graph.js": ("matt-graph.js", "application/javascript; charset=utf-8"),
                      "/workbench/matt-graph.css": ("matt-graph.css", "text/css; charset=utf-8"),
                      "/workbench/workflow-canvas.css": ("workflow-canvas.css", "text/css; charset=utf-8"),
                      "/workbench/codex-map.css": ("codex-map.css", "text/css; charset=utf-8"),
                      "/workbench/education-network.js": ("education-network.js", "application/javascript; charset=utf-8"),
                      "/workbench/education-network.css": ("education-network.css", "text/css; charset=utf-8")}
            if request_path in assets:
                filename, content_type = assets[request_path]
                body = workbench_path.with_name(filename).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            if self.path == "/api/education/status":
                body = json.dumps(education_status(root), ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.send_header("X-Content-Type-Options", "nosniff")
                self.end_headers()
                self.wfile.write(body)
                return
            local_db = sqlite3.connect(db_path)
            local_db.row_factory = sqlite3.Row
            if self.path == "/api/workbench/settings":
                result = workbench_settings(local_db)
                local_db.close()
                self.send_json(result)
                return
            if self.path == "/api/workbench/activity":
                result = {
                    "tasks": [dict(row) for row in local_db.execute("SELECT * FROM tasks ORDER BY updated_at DESC LIMIT 50")],
                    "runs": [dict(row) for row in local_db.execute("SELECT * FROM runs ORDER BY created_at DESC LIMIT 30")],
                }
                local_db.close()
                self.send_json(result)
                return
            if self.path == "/api/workbench/backups":
                v4_db = v4.connect(root)
                result = [dict(row) for row in v4_db.execute("SELECT * FROM backups ORDER BY created_at DESC LIMIT 20")]
                v4_db.close()
                local_db.close()
                self.send_json(result)
                return
            if self.path == "/api/workbench/overview":
                sync_projects(root, local_db)
                project_rows = [dict(row) for row in local_db.execute("SELECT * FROM projects ORDER BY name")]
                task_count = local_db.execute(
                    "SELECT COUNT(*) FROM tasks WHERE lower(status) NOT IN ('completed','done','closed','cancelled')"
                ).fetchone()[0]
                v4_db = v4.connect(root)
                overview = {
                    "generated_at": now(),
                    "projects": project_rows,
                    "task_count": task_count,
                    "actions": v4.list_actions(v4_db),
                }
                v4_db.close()
                local_db.close()
                self.send_json(overview)
                return
            elif self.path == "/api/status":
                body = json.dumps(status_data(root, local_db), ensure_ascii=False).encode()
                content_type = "application/json; charset=utf-8"
            elif self.path == "/api/v4/status":
                v4_db = v4.connect(root)
                body = json.dumps({
                    "models": v4.model_status(root),
                    "adapters": v4.adapter_status(root),
                    "actions": v4.list_actions(v4_db),
                    "backups": [dict(row) for row in v4_db.execute("SELECT * FROM backups ORDER BY created_at DESC LIMIT 20")],
                    "latex_documents": latex_documents(root),
                }, ensure_ascii=False).encode()
                v4_db.close()
                content_type = "application/json; charset=utf-8"
            elif self.path == "/api/launcher/apps":
                body = json.dumps(launcher.list_apps(root, discover_tools(root, local_db)), ensure_ascii=False).encode()
                content_type = "application/json; charset=utf-8"
            elif urlsplit(self.path).path in ("/", "/workbench", "/workbench/", "/workbench/layout-prototype", "/workbench/layout-prototype/"):
                body = workbench_path.read_text(encoding="utf-8").replace("__TOKEN__", token).encode()
                content_type = "text/html; charset=utf-8"
            elif urlsplit(self.path).path in ("/workbench/legacy", "/workbench/legacy/"):
                body = workbench_legacy_path.read_text(encoding="utf-8").replace("__TOKEN__", token).encode()
                content_type = "text/html; charset=utf-8"
            elif urlsplit(self.path).path in ("/dashboard", "/dashboard/"):
                body = page_template.replace("__TOKEN__", token).encode()
                content_type = "text/html; charset=utf-8"
            else:
                body = page_template.replace("__TOKEN__", token).encode()
                content_type = "text/html; charset=utf-8"
            local_db.close()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            csp = "default-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'"
            if urlsplit(self.path).path in ("/", "/workbench", "/workbench/", "/workbench/layout-prototype", "/workbench/layout-prototype/"):
                csp += "; frame-src http: https:"
            self.send_header("Content-Security-Policy", csp)
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.headers.get("X-Workstation-Token") != token:
                self.send_json({"error": "invalid control token"}, 403)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                max_length = layout_state.MAX_STATE_BYTES + 65536 if self.path == "/api/workbench/layout-state/save" else 450000 if self.path in {"/api/workbench/workflows", "/api/workbench/coursework"} else 256000 if self.path == "/api/workbench/codex-manage" else 65536
                if length <= 0 or length > max_length:
                    raise ValueError("invalid request size")
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
                local_db = sqlite3.connect(db_path)
                local_db.row_factory = sqlite3.Row
                if self.path == "/api/workbench/matt-map":
                    if payload != {}: raise ValueError('Matt总图只接受空读取请求')
                    import workstation_matt_map
                    result = workstation_matt_map.snapshot(root)
                elif self.path == "/api/workbench/coursework":
                    import workstation_coursework
                    try:
                        result = workstation_coursework.dispatch(root, payload)
                    except workstation_coursework.Conflict as error:
                        local_db.close()
                        self.send_json({"error": str(error), "conflict": True}, 409)
                        return
                elif self.path == "/api/workbench/workflows":
                    import workstation_workflows
                    import workstation_codex_manage
                    try:
                        result = workstation_workflows.dispatch(root, payload)
                    except workstation_codex_manage.Conflict as error:
                        local_db.close()
                        self.send_json({"error": str(error), "conflict": True}, 409)
                        return
                elif self.path == "/api/workbench/codex-manage":
                    import workstation_codex_manage
                    try:
                        result = workstation_codex_manage.dispatch(root, payload)
                    except workstation_codex_manage.Conflict as error:
                        local_db.close()
                        self.send_json({"error": str(error), "conflict": True}, 409)
                        return
                elif self.path == "/api/workbench/codex-map":
                    if not isinstance(payload, dict) or set(payload) - {"refresh", "project"} or type(payload.get("refresh", False)) is not bool:
                        raise ValueError("Codex映射请求字段无效")
                    import workstation_codex
                    result = workstation_codex.catalog(root, refresh=payload.get("refresh", False))
                    if 'project' in payload:
                        import workstation_matt_map
                        result = workstation_matt_map.project_projection(root, payload['project'], result)
                elif self.path == "/api/education/learning-status":
                    if not isinstance(payload, dict) or set(payload) != {"course", "node_id", "status", "revision"}:
                        raise ValueError('学习状态请求字段无效')
                    result = learning.set_status(root, str(payload['course']), str(payload['node_id']),
                                                 str(payload['status']), payload['revision'])
                elif self.path == "/api/education/open-note":
                    if not isinstance(payload, dict) or set(payload) != {"course", "node_id"}:
                        raise ValueError('打开笔记的请求字段无效')
                    result = learning.open_note(root, str(payload['course']), str(payload['node_id']))
                elif self.path == "/api/route":
                    result = route_task(root, local_db, str(payload["text"])[:4000])
                elif self.path == "/api/feedback":
                    result = route_feedback(local_db, str(payload["route_id"]), str(payload["decision"]))
                elif self.path == "/api/tasks":
                    result = {"task_id": add_task(local_db, payload.get("project"), str(payload["title"])[:500])}
                elif self.path == "/api/reuse-search":
                    result = search_github_reuse(root, local_db, str(payload["query"]))
                elif self.path == "/api/ai-plan":
                    result = ai_plan(root, local_db, str(payload["project"]), str(payload["text"]))
                elif self.path == "/api/workbench/window-draft":
                    result = widget.draft_window(root, str(payload["project"]), str(payload["child"]), str(payload["description"]),
                                                 format=payload.get("format", "form"), format_notes=payload.get("format_notes", ""),
                                                 ui_style=payload.get("ui_style", "editor"), ux_mode=payload.get("ux_mode", "direct"),
                                                 template=payload.get("template", "blank"))
                elif self.path == "/api/workbench/deskbox":
                    result = deskbox.dispatch(root, payload)
                elif self.path == "/api/workbench/layout-state/load":
                    result = layout_state.load(local_db)
                elif self.path == "/api/workbench/layout-state/save":
                    result = layout_state.save(local_db, payload["state"], payload["revision"])
                elif self.path == "/api/workbench/project-files":
                    result = embeds.list_project_files(root, str(payload["project"]), str(payload.get("relative", "")))
                elif self.path == "/api/workbench/project-file/preview":
                    result = embeds.preview_project_file(root, str(payload["project"]), str(payload["relative"]))
                elif self.path == "/api/workbench/terminal/start":
                    result = terminal_sessions.start(root, str(payload["project"]))
                elif self.path == "/api/workbench/terminal/input":
                    result = terminal_sessions.get(str(payload["session_id"])).send(str(payload["command"]))
                elif self.path == "/api/workbench/terminal/poll":
                    result = terminal_sessions.get(str(payload["session_id"])).poll(int(payload.get("cursor", 0)))
                elif self.path == "/api/workbench/terminal/close":
                    result = terminal_sessions.close(str(payload["session_id"]))
                elif self.path == "/api/scan":
                    plan_path = scan_files(root, Path(payload["source"]), payload.get("project") or None)
                    result = read_json(plan_path)
                elif self.path == "/api/workbench/intake/scan":
                    plan_path = scan_project_inbox(root, str(payload["project"]))
                    result = read_json(plan_path)
                elif self.path == "/api/workbench/settings":
                    result = update_workbench_settings(local_db, payload["values"])
                elif self.path == "/api/workbench/backup-verify":
                    result = v4.verify_backup(local_db, str(payload["id"]))
                elif self.path == "/api/apply":
                    run_id = apply_plan(root, local_db, str(payload["plan"]))
                    summary = local_db.execute("SELECT summary FROM runs WHERE id=?", (run_id,)).fetchone()[0]
                    result = {"run_id": run_id, "summary": summary}
                elif self.path == "/api/undo":
                    removed, protected = undo_run(local_db, str(payload["run"]))
                    result = {"removed": removed, "protected": protected}
                elif self.path == "/api/v4/knowledge-index":
                    result = v4.index_project(root, local_db, str(payload["project"]))
                elif self.path == "/api/v4/knowledge-search":
                    result = v4.search_knowledge(local_db, str(payload["project"]), str(payload["query"]))
                elif self.path == "/api/v4/latex-build":
                    result = run_latex(root, str(payload["project"]), str(payload.get("document") or ""), clean=False)
                elif self.path == "/api/v4/latex-clean":
                    result = run_latex(root, str(payload["project"]), str(payload.get("document") or ""), clean=True)
                elif self.path == "/api/v4/project-create":
                    result = v4.create_project(root, local_db, str(payload["name"]), str(payload.get("description", "")))
                elif self.path == "/api/v4/execute-request":
                    v4.project_path(root, str(payload["project"]))
                    result = v4.request_execution(local_db, str(payload["project"]), str(payload["text"]))
                elif self.path == "/api/v4/execute-approve":
                    result = v4.decide_action(local_db, str(payload["id"]), "approved")
                elif self.path == "/api/v4/execute-deny":
                    result = v4.decide_action(local_db, str(payload["id"]), "denied")
                elif self.path == "/api/v4/execute-run":
                    result = v4.run_execution(root, local_db, str(payload["id"]))
                elif self.path == "/api/v4/backup-create":
                    result = v4.create_backup(root, local_db, str(payload["project"]))
                elif self.path == "/api/v4/restore-request":
                    result = v4.request_restore(local_db, str(payload["backup_id"]))
                elif self.path == "/api/v4/restore-run":
                    result = v4.run_restore(root, local_db, str(payload["id"]))
                elif self.path == "/api/launcher/launch":
                    result = launcher.launch_app(root, str(payload["id"]), discover_tools(root, local_db))
                elif self.path == "/api/projects/open":
                    result = launcher.open_project_item(root, str(payload["project"]), str(payload["item"]))
                elif self.path == "/api/codex/session":
                    result = launcher.open_codex_session(root, str(payload["project"]))
                elif self.path == "/api/projects/content":
                    result = project_overview_content(root, str(payload["project"]))
                else:
                    local_db.close()
                    self.send_json({"error": "unknown endpoint"}, 404)
                    return
                local_db.close()
                self.send_json(result)
            except (layout_state.StateConflict, learning.LearningConflict) as exc:
                try:
                    local_db.close()
                except UnboundLocalError:
                    pass
                self.send_json({"error": str(exc), "conflict": True}, 409)
            except (KeyError, ValueError, OSError, sqlite3.Error, json.JSONDecodeError, SystemExit) as exc:
                try:
                    local_db.close()
                except UnboundLocalError:
                    pass
                self.send_json({"error": str(exc)}, 400)

        def log_message(self, fmt, *args):
            pass
    stop_path = root / "State" / "control.stop"
    pid_path = root / "State" / "control.pid"
    stop_path.unlink(missing_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="ascii")
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    server.timeout = 1
    print(f"Control center: http://127.0.0.1:{port} (Ctrl+C to stop)", flush=True)
    try:
        while not stop_path.exists():
            server.handle_request()
    finally:
        terminal_sessions.close_all()
        server.server_close()
        pid_path.unlink(missing_ok=True)
        stop_path.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description="Personal AI Workstation control plane")
    parser.add_argument("--root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("sync")
    sub.add_parser("tools")
    task = sub.add_parser("task")
    task_sub = task.add_subparsers(dest="task_command", required=True)
    task_add = task_sub.add_parser("add"); task_add.add_argument("title"); task_add.add_argument("--project")
    task_sub.add_parser("list")
    org = sub.add_parser("organize")
    org_sub = org.add_subparsers(dest="org_command", required=True)
    org_scan = org_sub.add_parser("scan"); org_scan.add_argument("source", type=Path); org_scan.add_argument("--project")
    org_apply = org_sub.add_parser("apply"); org_apply.add_argument("plan")
    org_undo = org_sub.add_parser("undo"); org_undo.add_argument("run")
    route = sub.add_parser("route"); route.add_argument("text")
    pref = sub.add_parser("preference")
    pref_sub = pref.add_subparsers(dest="pref_command", required=True)
    pref_sub.add_parser("list")
    pref_set = pref_sub.add_parser("set"); pref_set.add_argument("key"); pref_set.add_argument("value")
    feedback = sub.add_parser("feedback"); feedback.add_argument("route_id"); feedback.add_argument("decision", choices=("accepted", "rejected"))
    reuse = sub.add_parser("reuse-search"); reuse.add_argument("query")
    sub.add_parser("ai-status")
    ai = sub.add_parser("ai-plan"); ai.add_argument("project"); ai.add_argument("text")
    watch = sub.add_parser("watch")
    watch_sub = watch.add_subparsers(dest="watch_command", required=True)
    watch_sub.add_parser("start"); watch_sub.add_parser("run"); watch_sub.add_parser("stop"); watch_sub.add_parser("status")
    sub.add_parser("dashboard")
    server = sub.add_parser("serve"); server.add_argument("--port", type=int, default=8765)
    server_start = sub.add_parser("serve-start"); server_start.add_argument("--port", type=int, default=8765)
    sub.add_parser("serve-stop"); sub.add_parser("serve-status")
    args = parser.parse_args()
    root = args.root.resolve()
    db = connect(root)
    if args.command == "init":
        print(f"database={root / 'State' / 'workstation.db'} projects={sync_projects(root, db)} tools={len(discover_tools(root, db))}")
    elif args.command == "sync":
        print(f"projects={sync_projects(root, db)}")
    elif args.command == "tools":
        for item in discover_tools(root, db):
            print(f"{'OK' if item['found'] else '--':2} {item['name']:<12} {item['path']}")
    elif args.command == "task" and args.task_command == "add":
        print(f"task={add_task(db, args.project, args.title)}")
    elif args.command == "task" and args.task_command == "list":
        for row in db.execute("SELECT * FROM tasks ORDER BY updated_at DESC"):
            print(f"{row['id']} {row['status']:<12} {row['project'] or '-':<20} {row['title']}")
    elif args.command == "organize" and args.org_command == "scan":
        path = scan_files(root, args.source, args.project)
        plan = read_json(path)
        print(f"plan={plan['id']} files={len(plan['entries'])} path={path}")
    elif args.command == "organize" and args.org_command == "apply":
        apply_plan(root, db, args.plan)
    elif args.command == "organize" and args.org_command == "undo":
        removed, protected = undo_run(db, args.run)
        print(f"removed_copies={removed} protected={protected}")
    elif args.command == "route":
        print(json.dumps(route_task(root, db, args.text), ensure_ascii=False, indent=2))
    elif args.command == "preference" and args.pref_command == "list":
        for key, value in sorted(preferences(db).items()):
            print(f"{key}={value}")
    elif args.command == "preference" and args.pref_command == "set":
        set_preference(db, args.key, args.value)
        print(f"saved {args.key}={args.value}")
    elif args.command == "feedback":
        print(json.dumps(route_feedback(db, args.route_id, args.decision), ensure_ascii=False))
    elif args.command == "reuse-search":
        print(json.dumps(search_github_reuse(root, db, args.query), ensure_ascii=False, indent=2))
    elif args.command == "ai-status":
        print(json.dumps(ai_status(), ensure_ascii=False, indent=2))
    elif args.command == "ai-plan":
        print(json.dumps(ai_plan(root, db, args.project, args.text), ensure_ascii=False, indent=2))
    elif args.command == "watch" and args.watch_command == "start":
        print(json.dumps(watch_launch(root), ensure_ascii=False))
    elif args.command == "watch" and args.watch_command == "run":
        watch_run(root, db)
    elif args.command == "watch" and args.watch_command == "stop":
        print(json.dumps(watch_stop(root), ensure_ascii=False))
    elif args.command == "watch" and args.watch_command == "status":
        print(json.dumps(watcher_status(root), ensure_ascii=False))
    elif args.command == "dashboard":
        print(write_dashboard(root, db))
    elif args.command == "serve":
        db.commit(); db.close()
        serve(root, root / "State" / "workstation.db", args.port)
    elif args.command == "serve-start":
        print(json.dumps(control_launch(root, args.port), ensure_ascii=False))
    elif args.command == "serve-stop":
        print(json.dumps(control_stop(root), ensure_ascii=False))
    elif args.command == "serve-status":
        print(json.dumps(control_status(root), ensure_ascii=False))


if __name__ == "__main__":
    main()
