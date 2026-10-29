"""Durable, human-gated Codex runs for locally installed Matt Pocock skills."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

import workstation as core
import workstation_v4 as v4


SKILLS = (
    ("ask-matt", "路线选择", "只读：选择下一项 Matt skill，不自动执行推荐", "read-only"),
    ("setup-matt-pocock-skills", "工程配置", "只读征询与草案；确认后才写入项目配置", "review-then-write"),
    ("grill-with-docs", "澄清需求", "访谈并维护项目上下文；可在本阶段继续回答", "workspace-write"),
    ("to-spec", "形成规格", "将已确定的需求写成规格", "workspace-write"),
    ("to-tickets", "拆分任务", "将规格拆成有依赖关系的任务", "workspace-write"),
    ("implement", "实现", "按已确认任务实现和验证；不会自动提交", "workspace-write"),
    ("code-review", "审查", "按项目规则和需求审查结果", "read-only"),
)
SKILL_BY_ID = {item[0]: item for item in SKILLS}
ACTIVE: dict[str, subprocess.Popen] = {}
ACTIVE_LOCK = threading.Lock()


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def skill_path(skill: str) -> Path:
    if skill not in SKILL_BY_ID:
        raise ValueError("未登记的 Matt skill")
    path = Path.home() / ".agents" / "skills" / skill / "SKILL.md"
    if not path.is_file():
        raise ValueError(f"本机没有安装 {skill} skill")
    return path


def catalog() -> dict:
    return {
        "schema_version": 1,
        "executor": "codex-cli",
        "stages": [
            {"id": key, "title": title, "description": description, "sandbox": sandbox,
             "available": (Path.home() / ".agents" / "skills" / key / "SKILL.md").is_file()}
            for key, title, description, sandbox in SKILLS
        ],
        "rules": ["每阶段单独审批和启动", "下一阶段由用户选择", "用户补充内容只用于本次运行", "执行结果保存在本机"],
    }


def connect(root: Path) -> sqlite3.Connection:
    db = v4.connect(root)
    db.executescript("""
        CREATE TABLE IF NOT EXISTS matt_runs(
          id TEXT PRIMARY KEY, project TEXT NOT NULL, title TEXT NOT NULL,
          stage TEXT NOT NULL, status TEXT NOT NULL, action_id TEXT NOT NULL,
          attempt INTEGER NOT NULL, output_path TEXT, error TEXT,
          created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS matt_events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
          stage TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT NOT NULL,
          created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS matt_events_run_idx ON matt_events(run_id,id);
    """)
    return db


def event(db: sqlite3.Connection, run_id: str, stage: str, kind: str, detail: str) -> None:
    db.execute("INSERT INTO matt_events(run_id,stage,kind,detail,created_at) VALUES(?,?,?,?,?)",
               (run_id, stage, kind, detail[:240], now()))
    db.commit()


def _row(db: sqlite3.Connection, run_id: str) -> sqlite3.Row:
    row = db.execute("SELECT * FROM matt_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise ValueError("找不到工作流运行")
    return row


def _serialize(db: sqlite3.Connection, row: sqlite3.Row) -> dict:
    result = dict(row)
    result["completed_stages"] = [item[0] for item in db.execute(
        "SELECT DISTINCT stage FROM matt_events WHERE run_id=? AND kind='needs_input'", (row["id"],)
    )]
    result["events"] = [dict(item) for item in db.execute(
        "SELECT stage,kind,detail,created_at FROM matt_events WHERE run_id=? ORDER BY id DESC LIMIT 40", (row["id"],)
    )][::-1]
    action = db.execute("SELECT risk,status,payload FROM action_requests WHERE id=?", (row["action_id"],)).fetchone()
    result["approval"] = {"risk": action["risk"], "status": action["status"]} if action else None
    result["mode"] = json.loads(action["payload"]).get("mode", "run") if action else None
    output = Path(row["output_path"]) if row["output_path"] else None
    if output and output.is_file():
        result["response"] = output.read_text(encoding="utf-8", errors="replace")[-12000:]
    return result


def recover_interrupted(root: Path) -> None:
    """A restarted server cannot assume a vanished worker finished its Codex turn."""
    db = connect(root)
    try:
        rows = db.execute("SELECT id,stage,action_id FROM matt_runs WHERE status='running'").fetchall()
        for row in rows:
            detail = "服务已重启；请核查项目文件及 Codex 进程后再继续"
            db.execute("UPDATE matt_runs SET status='interrupted',error=?,updated_at=? WHERE id=?",
                       (detail, now(), row["id"]))
            db.execute("UPDATE action_requests SET status='failed',result=? WHERE id=?",
                       (detail, row["action_id"]))
            db.commit()
            event(db, row["id"], row["stage"], "interrupted", detail)
    finally:
        db.close()


def list_runs(root: Path, run_id: str | None = None) -> list[dict] | dict:
    db = connect(root)
    try:
        if run_id:
            return _serialize(db, _row(db, run_id))
        return [_serialize(db, row) for row in db.execute(
            "SELECT * FROM matt_runs ORDER BY created_at DESC LIMIT 25")]
    finally:
        db.close()


def _request(db: sqlite3.Connection, project: str, skill: str, instruction: str, mode: str = "run") -> str:
    action = v4.request_action(db, "matt-skill-execution", project, {
        "skill": skill, "instruction": instruction, "mode": mode, "scope": f"Projects/{project}"})
    return action["id"]


def create(root: Path, project: str, instruction: str) -> dict:
    v4.project_path(root, project)
    skill_path("ask-matt")
    instruction = instruction.strip()
    if not 3 <= len(instruction) <= 4000:
        raise ValueError("需求长度应为 3–4000 个字符")
    db = connect(root)
    try:
        run_id = "MATT-" + datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
        action_id = _request(db, project, "ask-matt", instruction)
        timestamp = now()
        db.execute("INSERT INTO matt_runs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                   (run_id, project, "Matt 工程流程", "ask-matt", "pending", action_id, 1,
                    None, None, timestamp, timestamp))
        db.commit()
        event(db, run_id, "ask-matt", "created", "路线选择申请已创建，等待人工批准")
        return _serialize(db, _row(db, run_id))
    finally:
        db.close()


def intervene(root: Path, run_id: str, operation: str, skill: str = "", instruction: str = "") -> dict:
    db = connect(root)
    try:
        row = _row(db, run_id)
        stage = row["stage"]
        if operation in {"approve", "deny"}:
            if row["status"] != "pending":
                raise ValueError("当前阶段没有待审批申请")
            v4.decide_action(db, row["action_id"], "approved" if operation == "approve" else "denied")
            status = "approved" if operation == "approve" else "denied"
            db.execute("UPDATE matt_runs SET status=?,updated_at=? WHERE id=?", (status, now(), run_id))
            db.commit()
            event(db, run_id, stage, status, "人工已批准本阶段" if operation == "approve" else "人工已拒绝本阶段")
        elif operation == "execute":
            if row["status"] != "approved":
                raise ValueError("请先批准本阶段")
            db.execute("UPDATE matt_runs SET status='running',error=NULL,updated_at=? WHERE id=?", (now(), run_id))
            db.commit()
            event(db, run_id, stage, "started", "Codex 已开始执行本阶段")
            threading.Thread(target=_worker, args=(root, run_id), daemon=True, name=f"matt-{run_id}").start()
        elif operation == "next":
            if row["status"] not in {"needs_input", "failed", "interrupted"}:
                raise ValueError("等待当前阶段结束后再选择下一阶段")
            skill_path(skill)
            instruction = instruction.strip()
            if not 3 <= len(instruction) <= 4000:
                raise ValueError("补充说明长度应为 3–4000 个字符")
            action_id = _request(db, row["project"], skill, instruction,
                                 "review" if skill == "setup-matt-pocock-skills" else "run")
            db.execute("UPDATE matt_runs SET stage=?,status='pending',action_id=?,attempt=attempt+1,error=NULL,updated_at=? WHERE id=?",
                       (skill, action_id, now(), run_id))
            db.commit()
            event(db, run_id, skill, "pending", "下一阶段申请已创建，等待人工批准")
        elif operation == "apply":
            if stage != "setup-matt-pocock-skills" or row["status"] != "needs_input" or not row["output_path"]:
                raise ValueError("请先完成并审阅工程配置草案")
            instruction = instruction.strip() or "用户已确认上一轮展示的完整草案，按草案写入项目配置"
            if len(instruction) > 4000:
                raise ValueError("补充说明不能超过 4000 个字符")
            action_id = _request(db, row["project"], stage, instruction, "apply")
            db.execute("UPDATE matt_runs SET status='pending',action_id=?,attempt=attempt+1,error=NULL,updated_at=? WHERE id=?",
                       (action_id, now(), run_id))
            db.commit()
            event(db, run_id, stage, "pending", "配置草案写入申请已创建，等待人工批准")
        elif operation == "finish":
            if row["status"] not in {"needs_input", "denied", "failed", "interrupted"}:
                raise ValueError("当前状态不能结束工作流")
            db.execute("UPDATE matt_runs SET status='completed',updated_at=? WHERE id=?", (now(), run_id))
            db.commit()
            event(db, run_id, stage, "completed", "人工结束工作流")
        elif operation == "cancel":
            if row["status"] == "running":
                with ACTIVE_LOCK:
                    process = ACTIVE.get(run_id)
                if process is None:
                    raise ValueError("Codex 进程尚未就绪，请稍后重试")
                db.execute("UPDATE matt_runs SET status='cancelled',updated_at=? WHERE id=?", (now(), run_id))
                db.execute("UPDATE action_requests SET status='cancelled' WHERE id=?", (row["action_id"],))
                db.commit()
                event(db, run_id, stage, "cancelled", "人工已终止 Codex 进程")
                process.terminate()
            elif row["status"] in {"pending", "approved", "needs_input", "failed", "interrupted"}:
                db.execute("UPDATE matt_runs SET status='cancelled',updated_at=? WHERE id=?", (now(), run_id))
                if row["status"] in {"pending", "approved"}:
                    db.execute("UPDATE action_requests SET status='cancelled' WHERE id=?", (row["action_id"],))
                db.commit()
                event(db, run_id, stage, "cancelled", "人工已终止工作流")
            else:
                raise ValueError("当前状态不能终止")
        else:
            raise ValueError("未知干预操作")
        return _serialize(db, _row(db, run_id))
    finally:
        db.close()


def _worker(root: Path, run_id: str) -> None:
    db = connect(root)
    process: subprocess.Popen | None = None
    timer: threading.Timer | None = None
    timed_out = threading.Event()
    try:
        row = _row(db, run_id)
        stage, project = row["stage"], row["project"]
        action = db.execute("SELECT * FROM action_requests WHERE id=?", (row["action_id"],)).fetchone()
        if not action or action["status"] != "approved":
            raise ValueError("本阶段尚未批准")
        payload = json.loads(action["payload"])
        base = v4.project_path(root, project)
        path = skill_path(stage)
        mode = payload.get("mode", "run")
        sandbox = ("read-only" if mode == "review" else "workspace-write") if stage == "setup-matt-pocock-skills" else SKILL_BY_ID[stage][3]
        status = core.ai_status()
        if not status["logged_in"]:
            raise ValueError("Codex CLI 未登录")
        if sandbox == "workspace-write":
            backup = v4.create_backup(root, db, project)
            event(db, run_id, stage, "backup", f"执行前备份：{backup['id']}")
        output = root / "State" / "ai" / f"{run_id}-{row['attempt']}.md"
        previous = Path(row["output_path"]) if row["output_path"] else None
        context = ""
        if previous and previous.is_file():
            context = "\n\n上一阶段或上一轮结果：\n" + previous.read_text(encoding="utf-8", errors="replace")[-10000:]
        setup_rule = ("本轮仅检查项目并给出下一项问题或完整草案，不修改项目文件。" if mode == "review"
                      else "用户已经审阅并确认上一轮完整配置草案；按确认后的草案写入项目配置。") if stage == "setup-matt-pocock-skills" else ""
        prompt = (
            f"用户已从网页明确选择 Matt Pocock 的 {stage} skill。先完整读取本机 {path} 并按它执行本阶段。"
            + setup_rule +
            "先阅读项目控制文件。仅在当前项目目录修改工作文件，遵守项目 AGENTS.md。"
            "保留原始资料；安装、上传、外发、发布、收费 API、Git commit/push 和更改系统配置均须另行人工确认，本次不执行。"
            "若需要用户决定或回答，请在结果中直接写出具体问题并停止本阶段。"
            f"\n\n本阶段用户指令：{payload['instruction']}" + context
        )
        command = [status["path"], "exec", *core.codex_sandbox_compat_args(), "--json",
                   "--cd", str(base), "--output-last-message", str(output), prompt]
        if sandbox == "workspace-write":
            command.insert(2, "--approve-for-me")
        else:
            command[2:2] = ["--sandbox", "read-only"]
        if not (base / ".git").exists():
            command.insert(2, "--skip-git-repo-check")
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, encoding="utf-8", errors="replace", bufsize=1)
        with ACTIVE_LOCK:
            ACTIVE[run_id] = process
        def expire() -> None:
            timed_out.set()
            if process and process.poll() is None:
                process.terminate()
        timer = threading.Timer(1800, expire)
        timer.daemon = True
        timer.start()
        event(db, run_id, stage, "codex", "Codex CLI 正在运行")
        for line in process.stdout or ():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = str(item.get("type", ""))
            if kind in {"turn.started", "turn.completed", "turn.failed", "item.started", "item.completed"}:
                item_type = str(item.get("item", {}).get("type", ""))
                event(db, run_id, stage, kind, item_type or kind)
        code = process.wait(timeout=30)
        current = _row(db, run_id)
        if current["status"] == "cancelled":
            return
        if timed_out.is_set():
            raise ValueError("Codex 阶段超过 30 分钟，已停止")
        if code != 0:
            raise ValueError(f"Codex CLI 退出码 {code}；请检查本机 Codex 诊断")
        db.execute("UPDATE action_requests SET status='completed',executed_at=?,result=? WHERE id=?",
                   (now(), str(output), row["action_id"]))
        db.execute("UPDATE matt_runs SET status='needs_input',output_path=?,updated_at=? WHERE id=?",
                   (str(output), now(), run_id))
        db.commit()
        event(db, run_id, stage, "needs_input", "本阶段完成；请选择下一阶段、继续本阶段或结束")
    except Exception as exc:
        current = _row(db, run_id)
        if current["status"] != "cancelled":
            detail = str(exc)[-1500:]
            db.execute("UPDATE matt_runs SET status='failed',error=?,updated_at=? WHERE id=?", (detail, now(), run_id))
            db.execute("UPDATE action_requests SET status='failed',executed_at=?,result=? WHERE id=?",
                       (now(), detail, current["action_id"]))
            db.commit()
            event(db, run_id, current["stage"], "failed", detail)
    finally:
        if timer:
            timer.cancel()
        with ACTIVE_LOCK:
            ACTIVE.pop(run_id, None)
        if process and process.poll() is None:
            process.kill()
        db.close()
