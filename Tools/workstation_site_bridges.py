"""Local site registry and a script-only assignment adapter contract.

The workbench currently registers sites only. No adapter is loaded or run by default.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from typing import Literal, Protocol, TypedDict
from urllib.parse import urlsplit, urlunsplit

from workstation_dpapi import protect_text, unprotect_text
from workstation_edge_bookmarks import find_edge_bookmark_url


MAX_SITES = 40
LOGIN_STRATEGIES = {"manual", "encrypted_link", "bookmark"}


class Assignment(TypedDict):
    external_id: str
    title: str
    course: str
    due_at: str | None
    url: str | None
    status: str


class LoginResult(TypedDict):
    status: Literal["ready", "user_action_required"]
    message: str


class AssignmentAdapter(Protocol):
    """A reviewed site script: verify login, then read assignments."""

    key: str

    def login(self, base_url: str) -> LoginResult: ...

    def check_assignments(self, base_url: str) -> list[Assignment]: ...


ADAPTERS: dict[str, AssignmentAdapter] = {}
BROWSER_ADAPTER_KEYS = {"theol_homework"}


def register_adapter(adapter: AssignmentAdapter) -> None:
    """Register a reviewed adapter in server startup code; never from web input."""
    if not adapter.key or adapter.key in ADAPTERS:
        raise ValueError("站点脚本标识无效或重复")
    if not callable(getattr(adapter, "login", None)) or not callable(getattr(adapter, "check_assignments", None)):
        raise ValueError("站点脚本必须分别实现登录确认和作业读取")
    ADAPTERS[adapter.key] = adapter


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS workbench_site_bridges(
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL COLLATE NOCASE UNIQUE,
        base_url TEXT NOT NULL DEFAULT '',
        adapter_key TEXT,
        login_strategy TEXT NOT NULL DEFAULT 'manual',
        login_url_protected BLOB,
        bookmark_query TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS workbench_site_checks(
        site_id TEXT PRIMARY KEY,
        result_json TEXT NOT NULL,
        checked_at TEXT NOT NULL,
        check_status TEXT NOT NULL DEFAULT 'checked',
        status_message TEXT NOT NULL DEFAULT '',
        result_updated_at TEXT NOT NULL DEFAULT ''
    )""")
    columns = {row[1] for row in db.execute("PRAGMA table_info(workbench_site_bridges)")}
    if "login_strategy" not in columns:
        db.execute("ALTER TABLE workbench_site_bridges ADD COLUMN login_strategy TEXT NOT NULL DEFAULT 'manual'")
    if "login_url_protected" not in columns:
        db.execute("ALTER TABLE workbench_site_bridges ADD COLUMN login_url_protected BLOB")
    if "bookmark_query" not in columns:
        db.execute("ALTER TABLE workbench_site_bridges ADD COLUMN bookmark_query TEXT NOT NULL DEFAULT ''")
    check_columns = {row[1] for row in db.execute("PRAGMA table_info(workbench_site_checks)")}
    if "check_status" not in check_columns:
        db.execute("ALTER TABLE workbench_site_checks ADD COLUMN check_status TEXT NOT NULL DEFAULT 'checked'")
    if "status_message" not in check_columns:
        db.execute("ALTER TABLE workbench_site_checks ADD COLUMN status_message TEXT NOT NULL DEFAULT ''")
    if "result_updated_at" not in check_columns:
        db.execute("ALTER TABLE workbench_site_checks ADD COLUMN result_updated_at TEXT NOT NULL DEFAULT ''")
        db.execute("UPDATE workbench_site_checks SET result_updated_at=checked_at")
    # Upgrade only the untouched Rain Classroom placeholder. User-edited rows keep their strategy.
    db.execute("""UPDATE workbench_site_bridges SET login_strategy='bookmark',bookmark_query='雨课堂'
        WHERE id='rain_classroom' AND name='雨课堂' AND base_url=''
          AND login_strategy='manual' AND login_url_protected IS NULL AND bookmark_query=''
          AND created_at=updated_at""")
    stamp = datetime.now(timezone.utc).isoformat()
    db.execute(
        "INSERT OR IGNORE INTO workbench_site_bridges(id,name,base_url,adapter_key,login_strategy,bookmark_query,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?)",
        ("rain_classroom", "雨课堂", "", "rain_classroom", "bookmark", "雨课堂", stamp, stamp),
    )
    # Attach the reviewed browser reader to the user's existing THEOL entry.
    db.execute("""UPDATE workbench_site_bridges SET adapter_key='theol_homework'
        WHERE adapter_key IS NULL AND base_url LIKE 'http://eol.imut.edu.cn/meol/personal/%'""")
    db.commit()


def normalize_url(value: str) -> str:
    """Derive a public address; HTTP is limited to links without credentials or parameters."""
    value = value.strip()
    if not value:
        return ""
    if len(value) > 500:
        raise ValueError("网站地址不能超过 500 字")
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as exc:
        raise ValueError("网站地址无效") from exc
    scheme = parsed.scheme.lower()
    if (scheme not in {"http", "https"} or not parsed.hostname or any(char.isspace() for char in value)
            or "\\" in value
            or port is not None and not 1 <= port <= 65535
            ):
        raise ValueError("请填写有效的 HTTP 或 HTTPS 网站地址")
    if scheme == "http" and (parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment):
        raise ValueError("HTTP 地址不能包含账号或参数；完整登录链接请使用 HTTPS")
    host = parsed.hostname.lower()
    if ":" in host:
        host = f"[{host}]"
    if port is not None:
        host += f":{port}"
    return urlunsplit((scheme, host, parsed.path.rstrip("/"), "", ""))


def list_sites(db: sqlite3.Connection) -> dict:
    ensure_schema(db)
    rows = db.execute(
        "SELECT s.id,s.name,s.base_url,s.adapter_key,s.login_strategy,s.login_url_protected,s.bookmark_query,"
        "c.result_json,c.checked_at,c.check_status,c.status_message,c.result_updated_at "
        "FROM workbench_site_bridges s LEFT JOIN workbench_site_checks c ON c.site_id=s.id "
        "ORDER BY CASE WHEN id='rain_classroom' THEN 0 ELSE 1 END, created_at, name"
    ).fetchall()
    def present(row: tuple) -> dict:
        saved = json.loads(row[7]) if row[7] else None
        count_only = isinstance(saved, dict) and saved.get("format") == "workstation.rain.visible-count.v1"
        theol_result = isinstance(saved, dict) and saved.get("format") == "workstation.theol.pending-homework.v1"
        assignments = saved.get("assignments", []) if theol_result else saved if isinstance(saved, list) else []
        return {
        "id": row[0], "name": row[1], "url": row[2], "adapter_key": row[3],
        "adapter_ready": bool(row[3] and row[3] in (ADAPTERS.keys() | BROWSER_ADAPTER_KEYS)),
        "login_strategy": row[4], "has_login_url": bool(row[5]), "bookmark_query": row[6],
        "assignment_status": "checked" if row[11] else "not_checked",
        "assignment_count": saved["count"] if count_only or theol_result else len(assignments) if row[11] else None,
        "check_method": "visible_count" if count_only else "details" if row[11] else None,
        "assignments": assignments, "checked_at": row[8],
        "last_check_status": row[9] or ("checked" if row[11] else "not_checked"),
        "last_check_message": row[10] or "", "result_updated_at": row[11] or None,
        }
    return {"sites": [present(row) for row in rows]}


def import_rain_count(db: sqlite3.Connection, result: object) -> dict:
    """Save only the visible exam count; never store page text or credentials."""
    ensure_schema(db)
    if not isinstance(result, dict) or result.get("format") != "workstation.rain.visible-count.v1" or result.get("status") != "checked":
        raise ValueError("雨课堂页面计数结果格式无效")
    count = result.get("count")
    if type(count) is not int or not 0 <= count <= 1000:
        raise ValueError("雨课堂考试数量无效")
    stamp = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO workbench_site_checks(site_id,result_json,checked_at,check_status,status_message,result_updated_at) "
               "VALUES(?,?,?,'checked','',?) ON CONFLICT(site_id) DO UPDATE SET "
               "result_json=excluded.result_json,checked_at=excluded.checked_at,check_status='checked',status_message='',"
               "result_updated_at=excluded.result_updated_at",
               ("rain_classroom", json.dumps({"format": "workstation.rain.visible-count.v1", "count": count}), stamp, stamp))
    db.commit()
    return list_sites(db)


def import_rain_result(db: sqlite3.Connection, result: object) -> dict:
    """Save only the small, user-transferred exam list, never browser credentials."""
    ensure_schema(db)
    if not isinstance(result, dict) or result.get("format") != "workstation.rain.upcoming-exams.v1" or result.get("status") != "checked":
        raise ValueError("请粘贴雨课堂脚本复制的成功读取结果")
    source = result.get("assignments")
    if not isinstance(source, list) or len(source) > 100:
        raise ValueError("雨课堂考试提醒列表无效或过长")
    assignments: list[Assignment] = []
    for item in source:
        if not isinstance(item, dict):
            raise ValueError("雨课堂考试提醒格式无效")
        external_id, title, course = item.get("external_id"), item.get("title"), item.get("course")
        if (not isinstance(external_id, str) or not 1 <= len(external_id) <= 80
                or not isinstance(title, str) or not 1 <= len(title.strip()) <= 300
                or not isinstance(course, str) or len(course) > 200
                or item.get("status") != "upcoming_exam" or item.get("url") is not None
                or item.get("due_at") is not None):
            raise ValueError("雨课堂考试提醒字段无效")
        assignments.append({"external_id": external_id, "title": title.strip(), "course": course.strip(),
                            "due_at": None, "url": None, "status": "upcoming_exam"})
    if not db.execute("SELECT 1 FROM workbench_site_bridges WHERE id='rain_classroom'").fetchone():
        raise ValueError("雨课堂网站尚未登记")
    stamp = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO workbench_site_checks(site_id,result_json,checked_at,check_status,status_message,result_updated_at) "
               "VALUES(?,?,?,'checked','',?) ON CONFLICT(site_id) DO UPDATE SET "
               "result_json=excluded.result_json,checked_at=excluded.checked_at,check_status='checked',status_message='',"
               "result_updated_at=excluded.result_updated_at",
               ("rain_classroom", json.dumps(assignments, ensure_ascii=False), stamp, stamp))
    db.commit()
    return list_sites(db)


def record_rain_check(db: sqlite3.Connection, result: object) -> dict:
    """Persist a read-only browser check state; failures keep the last successful snapshot."""
    if not isinstance(result, dict) or result.get("format") not in {"workstation.rain.upcoming-exams.v1", "workstation.rain.visible-count.v1"}:
        raise ValueError("雨课堂检查结果格式无效")
    status = result.get("status")
    if status == "checked":
        return import_rain_count(db, result) if result["format"] == "workstation.rain.visible-count.v1" else import_rain_result(db, result)
    messages = {
        "user_action_required": "雨课堂需要登录；请在 Edge 中打开课程页后重试。",
        "site_error": "雨课堂课程页未能读取，请在 Edge 打开课程页后重试。",
    }
    reasons = {
        "wrong_site": "当前页面不是雨课堂 HTTPS 页面。",
        "login_page": "雨课堂停留在登录页，请完成登录。",
        "login_redirect": "雨课堂跳转到了登录站点，请完成登录。",
        "course_page_not_ready": "课程页在等待时间内未显示“我听的课”和“搜索课程”。",
        "reader_not_available": "雨课堂标签尚未注入读取脚本，请刷新该标签页。",
        "reader_failed": "雨课堂页面读取脚本执行失败。",
        "page_load_timeout": "雨课堂标签页未在等待时间内加载完成。",
        "open_failed": "Edge 未能打开雨课堂标签页。",
    }
    if status not in messages:
        raise ValueError("雨课堂检查状态无效")
    reason = result.get("reason")
    message = reasons.get(reason, messages[status]) if isinstance(reason, str) else messages[status]
    ensure_schema(db)
    if not db.execute("SELECT 1 FROM workbench_site_bridges WHERE id='rain_classroom'").fetchone():
        raise ValueError("雨课堂网站尚未登记")
    stamp = datetime.now(timezone.utc).isoformat()
    db.execute("INSERT INTO workbench_site_checks(site_id,result_json,checked_at,check_status,status_message,result_updated_at) "
               "VALUES('rain_classroom','[]',?,?,?,'') ON CONFLICT(site_id) DO UPDATE SET "
               "checked_at=excluded.checked_at,check_status=excluded.check_status,status_message=excluded.status_message",
               (stamp, status, message))
    db.commit()
    return list_sites(db)


def record_theol_check(db: sqlite3.Connection, result: object) -> dict:
    """Store only THEOL's homework count and pending rows; retain the last good snapshot on failure."""
    ensure_schema(db)
    if not isinstance(result, dict) or result.get("format") != "workstation.theol.pending-homework.v1":
        raise ValueError("课程伴侣检查结果格式无效")
    row = db.execute("SELECT id FROM workbench_site_bridges WHERE adapter_key='theol_homework' ORDER BY created_at LIMIT 1").fetchone()
    if not row:
        raise ValueError("请先在网站桥接中登记课程伴侣个人页面")
    site_id = row[0]
    status = result.get("status")
    stamp = datetime.now(timezone.utc).isoformat()
    if status == "checked":
        count, source = result.get("count"), result.get("assignments")
        if type(count) is not int or not 0 <= count <= 999 or not isinstance(source, list) or len(source) > 100 or len(source) != count:
            raise ValueError("课程伴侣作业数量与列表无效")
        assignments: list[Assignment] = []
        for item in source:
            if not isinstance(item, dict):
                raise ValueError("课程伴侣作业条目无效")
            external_id, title, course, due_at = (item.get(key) for key in ("external_id", "title", "course", "due_at"))
            if (not isinstance(external_id, str) or not re.fullmatch(r"theol-[1-9]\d{0,2}", external_id)
                    or not isinstance(title, str) or not 1 <= len(title.strip()) <= 300
                    or not isinstance(course, str) or not 1 <= len(course.strip()) <= 200
                    or not isinstance(due_at, str) or not re.fullmatch(r"\d{4}/\d{2}/\d{2} \d{2}:\d{2}", due_at)
                    or item.get("status") != "pending_homework" or item.get("url") is not None):
                raise ValueError("课程伴侣作业字段无效")
            try:
                datetime.strptime(due_at, "%Y/%m/%d %H:%M")
            except ValueError as exc:
                raise ValueError("课程伴侣截止时间无效") from exc
            assignments.append({"external_id": external_id, "title": title.strip(), "course": course.strip(),
                                "due_at": due_at, "url": None, "status": "pending_homework"})
        saved = {"format": result["format"], "count": count, "assignments": assignments}
        db.execute("INSERT INTO workbench_site_checks(site_id,result_json,checked_at,check_status,status_message,result_updated_at) "
                   "VALUES(?,?,?,'checked','',?) ON CONFLICT(site_id) DO UPDATE SET "
                   "result_json=excluded.result_json,checked_at=excluded.checked_at,check_status='checked',status_message='',"
                   "result_updated_at=excluded.result_updated_at",
                   (site_id, json.dumps(saved, ensure_ascii=False), stamp, stamp))
    elif status in {"user_action_required", "site_error"}:
        messages = {"tab_not_open": "请在 Edge 中打开课程伴侣个人页面。", "login_redirect": "课程伴侣需要登录后才能读取个人页面。",
                    "reminder_not_ready": "课程伴侣任务提醒尚未加载。", "incomplete_list": "课程伴侣作业数量与可见列表不一致。",
                    "invalid_count": "课程伴侣作业数量格式已变化。", "invalid_assignment": "课程伴侣作业条目格式已变化。",
                    "reader_not_available": "课程伴侣读取脚本尚未注入，请刷新标签页。", "reader_failed": "课程伴侣页面读取失败。",
                    "page_load_timeout": "课程伴侣页面加载超时。", "open_failed": "Edge 无法打开课程伴侣页面。"}
        message = messages.get(result.get("reason"), "课程伴侣需要登录。" if status == "user_action_required" else "课程伴侣读取失败。")
        db.execute("INSERT INTO workbench_site_checks(site_id,result_json,checked_at,check_status,status_message,result_updated_at) "
                   "VALUES(?,'[]',?,?,?,'') ON CONFLICT(site_id) DO UPDATE SET "
                   "checked_at=excluded.checked_at,check_status=excluded.check_status,status_message=excluded.status_message",
                   (site_id, stamp, status, message))
    else:
        raise ValueError("课程伴侣检查状态无效")
    db.commit()
    return list_sites(db)


def save_site(db: sqlite3.Connection, name: str, url: str, site_id: str = "",
              login_strategy: str | None = None, bookmark_query: str | None = None) -> dict:
    ensure_schema(db)
    name = name.strip()
    if not 1 <= len(name) <= 60:
        raise ValueError("请输入 1–60 字的网站名称")
    base_url = normalize_url(url)
    if bookmark_query is not None:
        bookmark_query = bookmark_query.strip()
        if len(bookmark_query) > 80 or "://" in bookmark_query or any(ord(char) < 32 for char in bookmark_query):
            raise ValueError("收藏夹搜索词无效")
    stamp = datetime.now(timezone.utc).isoformat()
    duplicate = db.execute("SELECT id FROM workbench_site_bridges WHERE name=? COLLATE NOCASE", (name,)).fetchone()
    if duplicate and duplicate[0] != site_id:
        raise ValueError("已有同名网站")
    if site_id:
        current = db.execute("SELECT base_url,login_strategy,login_url_protected,bookmark_query FROM workbench_site_bridges WHERE id=?", (site_id,)).fetchone()
        if not current:
            raise ValueError("网站不存在")
        strategy = login_strategy or current[1]
        if strategy not in LOGIN_STRATEGIES:
            raise ValueError("登录方式无效")
        if strategy == "encrypted_link" and base_url.startswith("http://"):
            raise ValueError("加密登录链接请使用 HTTPS")
        protected = (None if not base_url or base_url.startswith("http://") else
                     current[2] if url.strip() == current[0] else protect_text(url.strip()))
        db.execute(
            "UPDATE workbench_site_bridges SET name=?,base_url=?,login_strategy=?,login_url_protected=?,bookmark_query=?,updated_at=? WHERE id=?",
            (name, base_url, strategy, protected, bookmark_query if bookmark_query is not None else current[3], stamp, site_id),
        )
    else:
        strategy = login_strategy or "manual"
        if strategy not in LOGIN_STRATEGIES:
            raise ValueError("登录方式无效")
        if strategy == "encrypted_link" and base_url.startswith("http://"):
            raise ValueError("加密登录链接请使用 HTTPS")
        count = db.execute("SELECT COUNT(*) FROM workbench_site_bridges").fetchone()[0]
        if count >= MAX_SITES:
            raise ValueError("最多可登记 40 个网站")
        db.execute(
            "INSERT INTO workbench_site_bridges(id,name,base_url,adapter_key,login_strategy,login_url_protected,bookmark_query,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            ("site_" + uuid.uuid4().hex, name, base_url, None, strategy,
             protect_text(url.strip()) if base_url.startswith("https://") else None,
             bookmark_query or "", stamp, stamp),
        )
    db.commit()
    return list_sites(db)


def login_url(db: sqlite3.Connection, site_id: str) -> dict:
    """Reveal one login URL only for a token-authenticated user action."""
    ensure_schema(db)
    row = db.execute(
        "SELECT name,base_url,login_strategy,login_url_protected,bookmark_query FROM workbench_site_bridges WHERE id=?", (site_id,)
    ).fetchone()
    if row is None:
        raise ValueError("网站不存在")
    if row[2] == "bookmark":
        return {"url": find_edge_bookmark_url(row[4] or row[0], row[1]), "strategy": row[2]}
    if not row[1]:
        raise ValueError("请先设置网站地址")
    if row[2] == "encrypted_link" and row[3]:
        full_url = unprotect_text(row[3])
        if normalize_url(full_url) != row[1]:
            raise ValueError("加密登录链接与网站地址不一致")
        return {"url": full_url, "strategy": row[2]}
    return {"url": row[1], "strategy": row[2]}


def check_assignments(db: sqlite3.Connection, site_id: str) -> dict:
    """Run a reviewed adapter's login step before reading assignments.

    This is not exposed by the web API until a site adapter and time limit are in place.
    """
    ensure_schema(db)
    row = db.execute("SELECT id,base_url,adapter_key FROM workbench_site_bridges WHERE id=?", (site_id,)).fetchone()
    if row is None:
        raise ValueError("网站不存在")
    adapter = ADAPTERS.get(row[2] or "")
    if not row[1] or adapter is None:
        return {"site_id": row[0], "status": "adapter_not_configured", "assignments": []}
    login = adapter.login(row[1])
    if login["status"] not in {"ready", "user_action_required"}:
        raise ValueError("站点脚本返回的登录状态无效")
    if login["status"] != "ready":
        return {"site_id": row[0], "status": login["status"], "message": login["message"], "assignments": []}
    assignments = adapter.check_assignments(row[1])
    return {"site_id": row[0], "status": "checked", "login_status": login["status"], "assignments": assignments}
