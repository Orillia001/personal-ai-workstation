from __future__ import annotations
from datetime import datetime
from html import escape
from pathlib import Path
import json
import sys

root = Path(sys.argv[1]).resolve()
rows = []
for project in sorted((root / "Projects").iterdir()):
    if not project.is_dir():
        continue
    status_file = project / "12-status.md"
    status = "已接管" if status_file.exists() else "未接管"
    changed = "是" if (project / ".git").exists() else "未启用"
    rows.append(f"<tr><td>{escape(project.name)}</td><td>{status}</td><td>{changed}</td><td>{escape(str(status_file))}</td></tr>")

events = []
log = root / "Logs" / "events.jsonl"
if log.exists():
    for line in log.read_text(encoding="utf-8-sig", errors="replace").splitlines()[-20:]:
        try:
            item = json.loads(line)
            events.append(f"<li><code>{escape(item.get('time',''))}</code> {escape(item.get('event', item.get('action','')))} · {escape(item.get('project',''))} · exit {escape(str(item.get('exit_code','')))}</li>")
        except json.JSONDecodeError:
            pass

html = f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>Personal AI Workstation</title>
<style>body{{font:16px/1.55 system-ui;margin:40px;max-width:1100px;color:#18212b}}h1{{margin-bottom:4px}}.muted{{color:#64748b}}table{{border-collapse:collapse;width:100%;margin:24px 0}}th,td{{padding:10px;border-bottom:1px solid #dbe3ea;text-align:left}}th{{background:#f5f7f9}}code{{background:#eef2f5;padding:2px 5px;border-radius:4px}}li{{margin:7px 0}}</style></head>
<body><h1>Personal AI Workstation</h1><div class="muted">生成时间：{datetime.now().astimezone().isoformat(timespec='seconds')} · 本地静态状态页</div>
<h2>项目</h2><table><thead><tr><th>名称</th><th>控制文件</th><th>Git</th><th>状态文件</th></tr></thead><tbody>{''.join(rows)}</tbody></table>
<h2>最近命令</h2><ul>{''.join(events) or '<li>暂无记录</li>'}</ul>
<p class="muted">此页面不联网，不包含 API 密钥或文件正文。</p></body></html>'''
output = root / "Logs" / "dashboard.html"
output.write_text(html, encoding="utf-8")
print(output)

