from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import uuid
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

import workstation as core


TEXT_EXTENSIONS = {".md", ".qmd", ".txt", ".tex", ".py", ".r", ".ps1", ".json", ".yaml", ".yml", ".csv", ".tsv", ".bib", ".docx", ".pptx", ".xlsx", ".pdf"}
EXCLUDED_PARTS = {".git", "99_archive", "__pycache__", ".venv", "node_modules"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(root: Path) -> sqlite3.Connection:
    db = core.connect(root)
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS action_requests(
          id TEXT PRIMARY KEY, kind TEXT NOT NULL, project TEXT,
          payload TEXT NOT NULL, risk TEXT NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL, decided_at TEXT, executed_at TEXT,
          result TEXT);
        CREATE TABLE IF NOT EXISTS knowledge_documents(
          path TEXT PRIMARY KEY, project TEXT NOT NULL, sha256 TEXT NOT NULL,
          title TEXT NOT NULL, content TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_fts USING fts5(
          path UNINDEXED, project UNINDEXED, title, content, tokenize='unicode61');
        CREATE TABLE IF NOT EXISTS usage_events(
          id TEXT PRIMARY KEY, provider TEXT NOT NULL, model TEXT,
          task_type TEXT, input_units INTEGER, output_units INTEGER,
          cost REAL, currency TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS backups(
          id TEXT PRIMARY KEY, scope TEXT NOT NULL, path TEXT NOT NULL,
          sha256 TEXT NOT NULL, files INTEGER NOT NULL, status TEXT NOT NULL,
          created_at TEXT NOT NULL);
        """
    )
    db.commit()
    return db


def project_path(root: Path, project: str) -> Path:
    projects = (root / "Projects").resolve()
    path = (projects / project).resolve()
    if path.parent != projects or not path.is_dir():
        raise ValueError(f"Project does not exist: {project}")
    return path


def risk_for(text: str) -> str:
    lowered = text.lower()
    high = ["删除", "覆盖", "上传", "发布", "付款", "付费", "恢复", "restore", "push", "commit", "install", "安装", "密钥", "api key"]
    medium = ["修改", "重命名", "移动", "下载", "联网", "执行", "运行", "execute"]
    if any(word in lowered for word in high):
        return "high"
    if any(word in lowered for word in medium):
        return "medium"
    return "standard"


def request_action(db: sqlite3.Connection, kind: str, project: str | None, payload: dict) -> dict:
    action_id = "ACT-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    serialized = json.dumps(payload, ensure_ascii=False)
    risk = risk_for(kind + " " + serialized)
    db.execute("INSERT INTO action_requests VALUES(?,?,?,?,?,?,?,?,?,?)", (action_id, kind, project, serialized, risk, "pending", now(), None, None, None))
    db.commit()
    return {"id": action_id, "kind": kind, "project": project, "risk": risk, "status": "pending", "payload": payload}


def decide_action(db: sqlite3.Connection, action_id: str, decision: str) -> dict:
    if decision not in {"approved", "denied"}:
        raise ValueError("Decision must be approved or denied")
    row = db.execute("SELECT * FROM action_requests WHERE id=?", (action_id,)).fetchone()
    if not row:
        raise ValueError("Action request not found")
    if row["status"] != "pending":
        raise ValueError(f"Action is already {row['status']}")
    db.execute("UPDATE action_requests SET status=?,decided_at=? WHERE id=?", (decision, now(), action_id))
    db.execute("INSERT INTO approvals VALUES(?,?,?,?,?)", (uuid.uuid4().hex, row["kind"], action_id, decision, now()))
    db.commit()
    return {"id": action_id, "status": decision, "risk": row["risk"]}


def list_actions(db: sqlite3.Connection) -> list[dict]:
    rows = db.execute("SELECT id,kind,project,risk,status,created_at,decided_at,executed_at,result FROM action_requests ORDER BY created_at DESC LIMIT 50")
    return [dict(row) for row in rows]


def knowledge_files(path: Path):
    for item in path.rglob("*"):
        if not item.is_file() or item.suffix.lower() not in TEXT_EXTENSIONS:
            continue
        if any(part in EXCLUDED_PARTS for part in item.parts):
            continue
        if item.stat().st_size > 25 * 1024 * 1024:
            continue
        yield item


def index_project(root: Path, db: sqlite3.Connection, project: str) -> dict:
    base = project_path(root, project)
    changed = skipped = failed = 0
    seen = set()
    for path in knowledge_files(base):
        relative = path.relative_to(base).as_posix()
        seen.add(relative)
        digest = core.sha256(path)
        row = db.execute("SELECT sha256 FROM knowledge_documents WHERE path=?", (f"{project}/{relative}",)).fetchone()
        if row and row[0] == digest:
            skipped += 1
            continue
        try:
            content = core.extract_text(path)[:1_000_000]
        except Exception:
            failed += 1
            continue
        key = f"{project}/{relative}"
        db.execute("DELETE FROM knowledge_fts WHERE path=?", (key,))
        db.execute(
            "INSERT INTO knowledge_documents(path,project,sha256,title,content,updated_at) VALUES(?,?,?,?,?,?) "
            "ON CONFLICT(path) DO UPDATE SET sha256=excluded.sha256,title=excluded.title,content=excluded.content,updated_at=excluded.updated_at",
            (key, project, digest, path.name, content, now()),
        )
        db.execute("INSERT INTO knowledge_fts(path,project,title,content) VALUES(?,?,?,?)", (key, project, path.name, content))
        changed += 1
    prefix = project + "/%"
    for row in db.execute("SELECT path FROM knowledge_documents WHERE project=?", (project,)).fetchall():
        relative = row["path"][len(project) + 1:]
        if relative not in seen:
            db.execute("DELETE FROM knowledge_documents WHERE path=?", (row["path"],))
            db.execute("DELETE FROM knowledge_fts WHERE path=?", (row["path"],))
    db.commit()
    return {"project": project, "indexed": changed, "unchanged": skipped, "failed": failed, "total": len(seen)}


def search_knowledge(db: sqlite3.Connection, project: str, query: str) -> list[dict]:
    terms = [term.replace('"', "") for term in query.split() if term.strip()]
    if not terms:
        raise ValueError("Search query is empty")
    fts_query = " OR ".join(f'"{term}"' for term in terms[:12])
    rows = db.execute(
        "SELECT path,title,snippet(knowledge_fts,3,'[',']',' … ',24) AS snippet,bm25(knowledge_fts) AS rank "
        "FROM knowledge_fts WHERE knowledge_fts MATCH ? AND project=? ORDER BY rank LIMIT 20",
        (fts_query, project),
    )
    return [dict(row) for row in rows]


def probe_url(url: str) -> bool:
    try:
        with urlopen(Request(url, headers={"User-Agent": "Personal-AI-Workstation/1.0"}), timeout=1.5) as response:
            return response.status == 200
    except (OSError, URLError):
        return False


def model_status(root: Path) -> list[dict]:
    config = core.read_json(root / "Config" / "model-providers.json")
    results = []
    codex = core.ai_status()
    for provider in config["providers"]:
        kind = provider["kind"]
        if kind == "codex":
            available = codex["logged_in"]
            detail = codex["detail"]
        elif kind.startswith("local"):
            available = probe_url(provider["url"])
            detail = provider["url"]
        else:
            available = bool(os.environ.get(provider["env"], ""))
            detail = f"{provider['env']}={'configured' if available else 'not-configured'}"
        results.append({**provider, "available": available, "detail": detail})
    return results


def model_route(root: Path, task_type: str) -> dict:
    providers = {item["id"]: item for item in model_status(root)}
    if task_type in {"classification", "summary", "extraction"}:
        for local in ("ollama", "lm-studio"):
            if providers[local]["available"]:
                return {"provider": local, "reason": "local model is available for a bounded task", "billing": "local"}
    if providers["codex-chatgpt"]["available"]:
        return {"provider": "codex-chatgpt", "reason": "uses the signed-in ChatGPT Codex allowance", "billing": "chatgpt-plan"}
    for cloud in ("openai-api", "deepseek-api"):
        if providers[cloud]["available"]:
            return {"provider": cloud, "reason": "configured fallback; paid API approval required", "billing": "separate-api"}
    return {"provider": None, "reason": "no model provider is currently available", "billing": None}


def adapter_status(root: Path) -> list[dict]:
    tool_db = core.connect(root)
    try:
        tools = {item["name"]: item for item in core.discover_tools(root, tool_db)}
    finally:
        tool_db.close()
    return [
        {"adapter": "office", "available": all(tools.get(x, {}).get("found") for x in ("Word", "Excel", "PowerPoint")), "mode": "installed-app + OpenXML content"},
        {"adapter": "zotero", "available": tools.get("Zotero", {}).get("found", False), "mode": "installed-app; Better BibTeX export path pending project binding"},
        {"adapter": "browser", "available": tools.get("Browser", {}).get("found", False), "mode": "installed-browser; external actions require confirmation"},
        {"adapter": "ocr", "available": tools.get("Tesseract OCR", {}).get("found", False), "mode": "local executable"},
        {"adapter": "pdf-text", "available": tools.get("PDF Text", {}).get("found", False), "mode": "local executable"},
    ]


def create_backup(root: Path, db: sqlite3.Connection, project: str) -> dict:
    source = project_path(root, project)
    backup_dir = root / "Backups"
    backup_dir.mkdir(exist_ok=True)
    backup_id = "BACKUP-" + project + "-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    output = backup_dir / f"{backup_id}.zip"
    manifest = []
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in source.rglob("*"):
            if not path.is_file() or any(part in EXCLUDED_PARTS for part in path.parts):
                continue
            relative = path.relative_to(source).as_posix()
            archive.write(path, relative)
            manifest.append({"path": relative, "size": path.stat().st_size, "sha256": core.sha256(path)})
        archive.writestr(".workstation-backup-manifest.json", json.dumps({"project": project, "created_at": now(), "files": manifest}, ensure_ascii=False, indent=2))
    digest = core.sha256(output)
    with zipfile.ZipFile(output) as archive:
        bad = archive.testzip()
    if bad:
        raise ValueError(f"Backup verification failed at {bad}")
    db.execute("INSERT INTO backups VALUES(?,?,?,?,?,?,?)", (backup_id, project, str(output), digest, len(manifest), "verified", now()))
    db.commit()
    return {"id": backup_id, "project": project, "path": str(output), "sha256": digest, "files": len(manifest), "status": "verified"}


def verify_backup(db: sqlite3.Connection, backup_id: str) -> dict:
    row = db.execute("SELECT * FROM backups WHERE id=?", (backup_id,)).fetchone()
    if not row:
        raise ValueError("Backup not found")
    path = Path(row["path"])
    if not path.is_file():
        return {"id": backup_id, "valid": False, "reason": "archive-missing"}
    if core.sha256(path) != row["sha256"]:
        return {"id": backup_id, "valid": False, "reason": "sha256-mismatch"}
    with zipfile.ZipFile(path) as archive:
        bad = archive.testzip()
    return {"id": backup_id, "valid": bad is None, "reason": None if bad is None else f"corrupt-entry:{bad}"}


def request_restore(db: sqlite3.Connection, backup_id: str) -> dict:
    row = db.execute("SELECT * FROM backups WHERE id=?", (backup_id,)).fetchone()
    if not row:
        raise ValueError("Backup not found")
    return request_action(db, "backup-restore", row["scope"], {"backup_id": backup_id, "archive": row["path"], "scope": row["scope"]})


def run_restore(root: Path, db: sqlite3.Connection, action_id: str) -> dict:
    action = db.execute("SELECT * FROM action_requests WHERE id=?", (action_id,)).fetchone()
    if not action or action["kind"] != "backup-restore":
        raise ValueError("Restore request not found")
    if action["status"] != "approved":
        raise ValueError("Restore must be explicitly approved")
    payload = json.loads(action["payload"])
    verification = verify_backup(db, payload["backup_id"])
    if not verification["valid"]:
        raise ValueError(f"Backup is invalid: {verification['reason']}")
    target = project_path(root, payload["scope"])
    safety = create_backup(root, db, payload["scope"])
    archive_path = Path(payload["archive"])
    restored = 0
    with zipfile.ZipFile(archive_path) as archive:
        for member in archive.infolist():
            if member.is_dir() or member.filename == ".workstation-backup-manifest.json":
                continue
            destination = (target / member.filename).resolve()
            if target not in destination.parents:
                raise ValueError(f"Unsafe backup entry: {member.filename}")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open("wb") as output:
                shutil.copyfileobj(source, output)
            restored += 1
    result = {"id": action_id, "status": "completed", "restored": restored, "safety_backup": safety["id"]}
    db.execute("UPDATE action_requests SET status='completed',executed_at=?,result=? WHERE id=?", (now(), json.dumps(result), action_id))
    db.commit()
    return result


def create_project(root: Path, db: sqlite3.Connection, name: str, description: str) -> dict:
    if not __import__("re").fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{1,63}", name):
        raise ValueError("Project name must use 2-64 letters, numbers, dots, underscores, or hyphens")
    base = root / "Projects" / name
    if base.exists():
        raise ValueError("Project already exists")
    folders = ["00_inbox", "01_sources", "02_literature", "03_data", "04_code", "05_figures", "06_manuscript", "07_slides", "08_evidence", "09_output", "99_archive"]
    for folder in folders:
        (base / folder).mkdir(parents=True, exist_ok=True)
    clean_description = " ".join(description.split())[:1000]
    (base / "10-README.MD").write_text(f"# {name}\n\n{clean_description}\n", encoding="utf-8")
    (base / "11-project.yaml").write_text(f"name: {name}\nstatus: active\ncreated: {datetime.now().date().isoformat()}\n", encoding="utf-8")
    (base / "12-status.md").write_text("# Status\n\n- 当前阶段：已建立项目\n- 下一步：整理需求与来源材料\n", encoding="utf-8")
    project_agent_rules = """# Project Agent Rules

开始工作前阅读 `10-README.MD`、`11-project.yaml` 和 `12-status.md`。

`C:\\Users\\ok\\Desktop\\workstation\\USER-MANUAL.md` 是工作站运行手册。收到自然语言需求后，判断是否对应手册功能或工作流；若对应，只读取相关章节并自动调用现有工具完成可逆步骤。用户无需复述命令或指定软件。手册不扩大权限；删除、移动、覆盖原始资料、安装软件、更改系统配置、上传、外发、发布、收费 API、Git commit/push 必须先取得人工确认。

保留来源文件，修改后验证产物并更新 `12-status.md`。
"""
    (base / "AGENTS.md").write_text(project_agent_rules, encoding="utf-8")
    git = shutil.which("git")
    if git:
        subprocess.run([git, "init", str(base)], capture_output=True, text=True, timeout=30)
    core.sync_projects(root, db)
    return {"name": name, "path": str(base), "folders": len(folders), "status": "created"}


def local_prompt(root: Path, db: sqlite3.Connection, prompt: str) -> dict:
    providers = {item["id"]: item for item in model_status(root)}
    if not providers["ollama"]["available"]:
        raise ValueError("Ollama local service is not available")
    models_request = Request("http://127.0.0.1:11434/api/tags", headers={"User-Agent": "Personal-AI-Workstation/1.0"})
    with urlopen(models_request, timeout=3) as response:
        models = json.load(response).get("models", [])
    if not models:
        raise ValueError("Ollama is running but has no local model")
    model = models[0]["name"]
    body = json.dumps({"model": model, "prompt": prompt[:4000], "stream": False}).encode()
    request = Request("http://127.0.0.1:11434/api/generate", data=body, headers={"Content-Type": "application/json", "User-Agent": "Personal-AI-Workstation/1.0"})
    with urlopen(request, timeout=600) as response:
        result = json.load(response)
    db.execute("INSERT INTO usage_events VALUES(?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, "ollama", model, "local-prompt", result.get("prompt_eval_count"), result.get("eval_count"), 0.0, "LOCAL", now()))
    db.commit()
    return {"provider": "ollama", "model": model, "response": result.get("response", ""), "input_units": result.get("prompt_eval_count"), "output_units": result.get("eval_count"), "cost": 0}


def cloud_prompt(root: Path, db: sqlite3.Connection, provider_id: str, prompt: str) -> dict:
    providers = {item["id"]: item for item in core.read_json(root / "Config" / "model-providers.json")["providers"]}
    if provider_id not in {"openai-api", "deepseek-api"}:
        raise ValueError("Cloud provider must be openai-api or deepseek-api")
    provider = providers[provider_id]
    api_key = os.environ.get(provider["env"], "")
    model = os.environ.get(provider["model_env"], "")
    if not api_key or not model:
        raise ValueError(f"Configure {provider['env']} and {provider['model_env']} before use")
    prompt = prompt.strip()[:8000]
    if provider_id == "openai-api":
        body = {"model": model, "input": prompt}
    else:
        body = {"model": model, "messages": [{"role": "user", "content": prompt}], "stream": False}
    request = Request(provider["url"], data=json.dumps(body).encode(), headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json", "User-Agent": "Personal-AI-Workstation/1.0",
    })
    try:
        with urlopen(request, timeout=600) as response:
            result = json.load(response)
    except Exception as exc:
        raise ValueError(f"{provider_id} request failed: {exc}") from exc
    if provider_id == "openai-api":
        text = result.get("output_text", "")
        if not text:
            pieces = []
            for item in result.get("output", []):
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        pieces.append(content.get("text", ""))
            text = "\n".join(pieces)
        usage = result.get("usage", {})
        input_units, output_units = usage.get("input_tokens"), usage.get("output_tokens")
    else:
        text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        usage = result.get("usage", {})
        input_units, output_units = usage.get("prompt_tokens"), usage.get("completion_tokens")
    db.execute("INSERT INTO usage_events VALUES(?,?,?,?,?,?,?,?,?)", (uuid.uuid4().hex, provider_id, model, "approved-cloud-prompt", input_units, output_units, None, None, now()))
    db.commit()
    return {"provider": provider_id, "model": model, "response": text, "input_units": input_units, "output_units": output_units, "cost": "see-provider-billing"}


def request_execution(db: sqlite3.Connection, project: str, text: str) -> dict:
    return request_action(db, "codex-project-execution", project, {"request": " ".join(text.split())[:4000], "scope": f"Projects/{project}"})


def run_execution(root: Path, db: sqlite3.Connection, action_id: str) -> dict:
    row = db.execute("SELECT * FROM action_requests WHERE id=?", (action_id,)).fetchone()
    if not row or row["kind"] != "codex-project-execution":
        raise ValueError("Codex execution request not found")
    if row["status"] != "approved":
        raise ValueError("Action must be explicitly approved before execution")
    project = row["project"]
    base = project_path(root, project)
    backup = create_backup(root, db, project)
    payload = json.loads(row["payload"])
    output = root / "State" / "ai" / f"{action_id}-result.md"
    status = core.ai_status()
    if not status["logged_in"]:
        raise ValueError("Codex CLI is not logged in")
    prompt = (
        "完成下面的项目任务。先阅读项目控制文件，优先复用现有工具和成熟依赖。"
        "只在当前项目目录写入；不要删除原始资料、上传、发布、安装软件、使用付费API、git commit或push。"
        "完成后运行合适的验证并更新12-status.md，说明改动和验证结果。\n\n"
        + payload["request"]
    )
    command = [status["path"], "exec", *core.codex_sandbox_compat_args(), "--ephemeral", "--approve-for-me", "--cd", str(base), "--output-last-message", str(output), prompt]
    if not (base / ".git").exists():
        command.insert(2, "--skip-git-repo-check")
    completed = subprocess.run(command, capture_output=True, text=True, timeout=1800)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "unknown error")[-2000:]
        db.execute("UPDATE action_requests SET status='failed',executed_at=?,result=? WHERE id=?", (now(), detail, action_id))
        db.commit()
        raise ValueError(f"Codex execution failed: {detail}")
    result_text = output.read_text(encoding="utf-8", errors="replace") if output.exists() else "completed"
    db.execute("UPDATE action_requests SET status='completed',executed_at=?,result=? WHERE id=?", (now(), str(output), action_id))
    db.commit()
    return {"id": action_id, "status": "completed", "backup": backup, "result_path": str(output), "response": result_text}


def run_ocr(root: Path, source: Path, output: Path) -> dict:
    tesseract = shutil.which("tesseract")
    if not tesseract:
        candidate = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR" / "tesseract.exe"
        tesseract = str(candidate) if candidate.is_file() else None
    if not tesseract:
        raise ValueError("Tesseract OCR is not installed; adapter is ready but unavailable")
    source = source.resolve()
    output = output.resolve()
    if not source.is_file():
        raise ValueError("OCR source file does not exist")
    output.parent.mkdir(parents=True, exist_ok=True)
    base = output.with_suffix("")
    bundled_tessdata = root / "Assets" / "tessdata"
    tessdata = bundled_tessdata if (bundled_tessdata / "eng.traineddata").exists() else Path(tesseract).parent / "tessdata"
    languages = "chi_sim+eng" if (tessdata / "chi_sim.traineddata").exists() else "eng"
    completed = subprocess.run([tesseract, str(source), str(base), "--tessdata-dir", str(tessdata), "-l", languages], capture_output=True, text=True, timeout=600)
    if completed.returncode != 0:
        raise ValueError(completed.stderr[-1000:])
    generated = base.with_suffix(".txt")
    return {"source": str(source), "output": str(generated), "languages": languages, "sha256": core.sha256(generated)}


def main():
    parser = argparse.ArgumentParser(description="Personal AI Workstation V4 backend")
    parser.add_argument("--root", type=Path, required=True)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    knowledge = sub.add_parser("knowledge-index"); knowledge.add_argument("project")
    search = sub.add_parser("knowledge-search"); search.add_argument("project"); search.add_argument("query")
    sub.add_parser("model-status")
    route = sub.add_parser("model-route"); route.add_argument("task_type")
    sub.add_parser("adapter-status")
    sub.add_parser("permission-list")
    req = sub.add_parser("execute-request"); req.add_argument("project"); req.add_argument("text")
    approve = sub.add_parser("execute-approve"); approve.add_argument("id")
    deny = sub.add_parser("execute-deny"); deny.add_argument("id")
    run = sub.add_parser("execute-run"); run.add_argument("id")
    backup = sub.add_parser("backup-create"); backup.add_argument("project")
    sub.add_parser("backup-list")
    verify = sub.add_parser("backup-verify"); verify.add_argument("id")
    restore = sub.add_parser("restore-request"); restore.add_argument("backup_id")
    restore_run = sub.add_parser("restore-run"); restore_run.add_argument("id")
    project = sub.add_parser("project-create"); project.add_argument("name"); project.add_argument("description")
    local = sub.add_parser("local-prompt"); local.add_argument("prompt")
    cloud = sub.add_parser("cloud-prompt"); cloud.add_argument("provider"); cloud.add_argument("prompt")
    ocr = sub.add_parser("ocr"); ocr.add_argument("source", type=Path); ocr.add_argument("output", type=Path)
    args = parser.parse_args()
    root = args.root.resolve()
    db = connect(root)
    if args.command == "init":
        print(json.dumps({"database": str(root / "State" / "workstation.db"), "v4": "ready"}, ensure_ascii=False))
    elif args.command == "knowledge-index":
        print(json.dumps(index_project(root, db, args.project), ensure_ascii=False, indent=2))
    elif args.command == "knowledge-search":
        print(json.dumps(search_knowledge(db, args.project, args.query), ensure_ascii=False, indent=2))
    elif args.command == "model-status":
        print(json.dumps(model_status(root), ensure_ascii=False, indent=2))
    elif args.command == "model-route":
        print(json.dumps(model_route(root, args.task_type), ensure_ascii=False, indent=2))
    elif args.command == "adapter-status":
        print(json.dumps(adapter_status(root), ensure_ascii=False, indent=2))
    elif args.command == "permission-list":
        print(json.dumps(list_actions(db), ensure_ascii=False, indent=2))
    elif args.command == "execute-request":
        project_path(root, args.project)
        print(json.dumps(request_execution(db, args.project, args.text), ensure_ascii=False, indent=2))
    elif args.command == "execute-approve":
        print(json.dumps(decide_action(db, args.id, "approved"), ensure_ascii=False, indent=2))
    elif args.command == "execute-deny":
        print(json.dumps(decide_action(db, args.id, "denied"), ensure_ascii=False, indent=2))
    elif args.command == "execute-run":
        print(json.dumps(run_execution(root, db, args.id), ensure_ascii=False, indent=2))
    elif args.command == "backup-create":
        print(json.dumps(create_backup(root, db, args.project), ensure_ascii=False, indent=2))
    elif args.command == "backup-list":
        print(json.dumps([dict(row) for row in db.execute("SELECT * FROM backups ORDER BY created_at DESC")], ensure_ascii=False, indent=2))
    elif args.command == "backup-verify":
        print(json.dumps(verify_backup(db, args.id), ensure_ascii=False, indent=2))
    elif args.command == "restore-request":
        print(json.dumps(request_restore(db, args.backup_id), ensure_ascii=False, indent=2))
    elif args.command == "restore-run":
        print(json.dumps(run_restore(root, db, args.id), ensure_ascii=False, indent=2))
    elif args.command == "project-create":
        print(json.dumps(create_project(root, db, args.name, args.description), ensure_ascii=False, indent=2))
    elif args.command == "local-prompt":
        print(json.dumps(local_prompt(root, db, args.prompt), ensure_ascii=False, indent=2))
    elif args.command == "cloud-prompt":
        print(json.dumps(cloud_prompt(root, db, args.provider, args.prompt), ensure_ascii=False, indent=2))
    elif args.command == "ocr":
        print(json.dumps(run_ocr(root, args.source, args.output), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


