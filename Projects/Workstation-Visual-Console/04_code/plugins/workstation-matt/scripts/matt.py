"""Local Matt stage records and a read-only dashboard; Python standard library only."""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

STAGES = {"clarify": "澄清需求", "prototype": "界面原型", "spec": "规格", "tickets": "任务拆分",
          "implement": "实现", "verify": "验证", "review": "独立审查", "release": "安装与交付", "retro": "复盘"}
STATUSES = ("pending", "running", "blocked", "completed", "skipped")
TERMINAL = {"completed", "skipped"}
PLUGIN = Path(__file__).resolve().parent.parent
SKILLS = ("ask-matt", "implement", "code-review", "prototype", "diagnosing-bugs", "to-spec", "to-tickets", "retro")


def now():
    return datetime.now(timezone.utc).isoformat()


def inside(root, path):
    resolved = path.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("路径超出工作站目录")
    return resolved


def slug(value):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", value) or value.split(".")[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        raise ValueError("任务ID须为小写字母、数字、短横线，长度1–64")
    return value


def record_path(root, task):
    return inside(root, root / ".scratch" / slug(task) / "matt-workflow.json")


def read(root, task):
    data = json.loads(record_path(root, task).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or data.get("task") != task or data.get("schema_version") != 1:
        raise ValueError("任务记录版本或ID不匹配")
    if any(not isinstance(data.get(key), str) for key in ("title", "project", "updated_at", "created_at")) or not isinstance(data.get("revision"), int) or data.get("status") not in STATUSES:
        raise ValueError("任务记录字段无效")
    stages = data.get("stages")
    if not isinstance(stages, list) or not stages or len(stages) > len(STAGES):
        raise ValueError("阶段记录无效")
    for stage in stages:
        if not isinstance(stage, dict) or stage.get("id") not in STAGES or stage.get("status") not in STATUSES or any(not isinstance(stage.get(key), str) for key in ("title", "note")) or not isinstance(stage.get("evidence"), list) or any(not isinstance(item, str) for item in stage["evidence"]):
            raise ValueError("阶段字段无效")
    if len({stage["id"] for stage in stages}) != len(stages) or not isinstance(data.get("events"), list) or any(not isinstance(event, dict) or any(not isinstance(event.get(key), str) for key in ("stage", "status", "note", "at")) for event in data["events"]):
        raise ValueError("阶段或事件记录无效")
    return data


@contextmanager
def record_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_suffix(".lock")
    try:
        handle = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("记录正在更新；稍后重试。异常退出遗留锁时先核查进程") from None
    try:
        with handle:
            handle.write(str(os.getpid()))
        yield
    finally:
        lock.unlink(missing_ok=True)


def save(path, data):
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def overall(data):
    states = [stage["status"] for stage in data["stages"]]
    if all(state in TERMINAL for state in states):
        return "completed"
    return next((state for state in ("blocked", "running") if state in states), "pending")


def begin(root, args):
    if not args.title.strip() or len(args.title) > 120:
        raise ValueError("标题长度应为1–120")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}", args.project):
        raise ValueError("项目须为工作站中的项目目录名")
    if not inside(root, root / "Projects" / args.project).is_dir():
        raise ValueError("项目不存在")
    stages = args.stages.split(",")
    if not stages or len(set(stages)) != len(stages) or any(stage not in STAGES for stage in stages):
        raise ValueError("阶段须从已知阶段选择且不能重复")
    path = record_path(root, args.task)
    with record_lock(path):
        if path.exists():
            raise ValueError("任务已存在，请show后继续")
        data = {"schema_version": 1, "task": args.task, "project": args.project, "title": args.title.strip(),
                "revision": 1, "created_at": now(), "updated_at": now(), "status": "pending",
                "stages": [{"id": stage, "title": STAGES[stage], "status": "pending", "note": "", "evidence": [], "updated_at": None} for stage in stages], "events": []}
        save(path, data)
    return data


def update(root, args):
    if not args.note.strip() or len(args.note) > 2000:
        raise ValueError("阶段更新需要1–2000字说明")
    evidence = []
    for raw in args.evidence:
        relative = Path(raw)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("证据须使用工作站内相对路径")
        file = inside(root, root / relative)
        if not file.is_file():
            raise ValueError(f"证据文件不存在：{raw}")
        evidence.append(file.relative_to(root).as_posix())
    if args.status == "completed" and not evidence:
        raise ValueError("完成阶段需要实际证据文件")
    path = record_path(root, args.task)
    with record_lock(path):
        data = read(root, args.task)
        if data["revision"] != args.revision:
            raise ValueError(f"修订冲突，当前revision={data['revision']}；请重新读取")
        index = next((i for i, stage in enumerate(data["stages"]) if stage["id"] == args.stage), None)
        if index is None:
            raise ValueError("本任务没有该阶段")
        stage = data["stages"][index]
        if stage["status"] in TERMINAL:
            raise ValueError("终态阶段已封存；新增需求使用新任务")
        if any(previous["status"] not in TERMINAL for previous in data["stages"][:index]):
            raise ValueError("请先完成或说明跳过前置阶段")
        stage.update(status=args.status, note=args.note.strip(), evidence=evidence, updated_at=now())
        data["revision"] += 1
        data["updated_at"] = stage["updated_at"]
        data["status"] = overall(data)
        data["events"].append({"stage": args.stage, "status": args.status, "note": args.note.strip(), "at": now()})
        save(path, data)
    return data


def listing(root):
    tasks, warnings = [], []
    scratch = inside(root, root / ".scratch")
    if scratch.is_dir():
        for path in scratch.glob("*/matt-workflow.json"):
            try:
                tasks.append(read(root, path.parent.name))
            except (ValueError, OSError, KeyError, TypeError) as error:
                warnings.append({"task": path.parent.name, "error": str(error)[:180]})
    tasks.sort(key=lambda task: task["updated_at"], reverse=True)
    return {"tasks": tasks, "warnings": warnings, "read_at": now()}


def doctor(root):
    codex_home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
    bases = [codex_home / "skills", Path.home() / ".agents" / "skills"]
    found = {name: next((str(base / name / "SKILL.md") for base in bases if (base / name / "SKILL.md").is_file()), None) for name in SKILLS}
    return {"station_root": str(root), "python": sys.version.split()[0], "skills": found,
            "ready": all(found[name] for name in ("ask-matt", "implement", "code-review")),
            "mode": "current-codex-task; explicit stage records; read-only dashboard"}


def make_server(root, port):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, body, content_type="application/json; charset=utf-8"):
            if not isinstance(body, bytes):
                body = json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; object-src 'none'; base-uri 'none'; form-action 'none'")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            authority = self.headers.get("Host", "")
            if authority not in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"} or self.headers.get("Sec-Fetch-Site") == "cross-site":
                self.reply(403, {"error": "仅允许本机同站点访问"})
                return
            url = urlsplit(self.path)
            try:
                if url.path == "/api/health":
                    self.reply(200, {"plugin": "workstation-matt", "version": "0.1.0", "station_root": str(root), "read_only": True})
                elif url.path == "/api/workflows":
                    self.reply(200, listing(root))
                elif url.path == "/evidence":
                    query = parse_qs(url.query)
                    data = read(root, query["task"][0])
                    stage = next(stage for stage in data["stages"] if stage["id"] == query["stage"][0])
                    index = int(query["index"][0])
                    if index < 0:
                        raise ValueError("证据索引无效")
                    path = inside(root, root / stage["evidence"][index])
                    if path.stat().st_size > 2_000_000:
                        raise ValueError("证据大于2MB，请从项目目录查看")
                    kind = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".zip": "application/zip"}.get(path.suffix.lower(), "text/plain; charset=utf-8")
                    self.reply(200, path.read_bytes(), kind)
                elif url.path in ("/", "/dashboard.js", "/dashboard.css"):
                    name, kind = {"/": ("index.html", "text/html"), "/dashboard.js": ("dashboard.js", "text/javascript"), "/dashboard.css": ("dashboard.css", "text/css")}[url.path]
                    self.reply(200, (PLUGIN / "dashboard" / name).read_bytes(), kind + "; charset=utf-8")
                else:
                    self.reply(404, {"error": "页面不存在"})
            except (ValueError, OSError, KeyError, TypeError, IndexError, StopIteration) as error:
                self.reply(400, {"error": str(error)[:200]})

        def do_POST(self):
            self.reply(405, {"error": "看板只读；由Codex通过CLI更新阶段"})

    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="ws.ps1 context返回的station_root")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor")
    commands.add_parser("list")
    show = commands.add_parser("show")
    show.add_argument("--task", required=True)
    create = commands.add_parser("begin")
    create.add_argument("--task", required=True)
    create.add_argument("--project", required=True)
    create.add_argument("--title", required=True)
    create.add_argument("--stages", default="spec,implement,verify,review")
    change = commands.add_parser("update")
    change.add_argument("--task", required=True)
    change.add_argument("--stage", choices=STAGES, required=True)
    change.add_argument("--status", choices=STATUSES, required=True)
    change.add_argument("--revision", type=int, required=True)
    change.add_argument("--note", required=True)
    change.add_argument("--evidence", action="append", default=[])
    server = commands.add_parser("serve")
    server.add_argument("--port", type=int, default=8786)
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        if not (root / "AGENTS.md").is_file():
            raise ValueError("目录没有AGENTS.md，请通过ws.ps1 context确认工作站")
        if args.command == "serve":
            with make_server(root, args.port) as service:
                print(json.dumps({"url": f"http://127.0.0.1:{service.server_port}", "station_root": str(root)}, ensure_ascii=False), flush=True)
                service.serve_forever()
            return
        result = {"doctor": lambda: doctor(root), "list": lambda: listing(root), "show": lambda: read(root, args.task),
                  "begin": lambda: begin(root, args), "update": lambda: update(root, args)}[args.command]()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
