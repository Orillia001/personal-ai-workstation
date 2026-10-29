"""Start the local control center and open the integrated workbench page."""

from __future__ import annotations

import subprocess
import json
import socket
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

from workbench_diagnostics import diagnose


ROOT = Path(__file__).resolve().parent.parent
BASE_URL = "http://127.0.0.1:8765"


def port_is_open() -> bool:
    try:
        with socket.create_connection(("127.0.0.1", 8765), timeout=0.4):
            return True
    except OSError:
        return False


def health_is_ready() -> bool:
    request = urllib.request.Request(f"{BASE_URL}/api/health")
    try:
        with urllib.request.urlopen(request, timeout=1.0) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("ok") is True
    except (OSError, urllib.error.URLError, json.JSONDecodeError):
        return False


def open_page() -> int:
    if webbrowser.open(f"{BASE_URL}/workbench", new=2):
        print(f"已打开工作台：{BASE_URL}/workbench")
        return 0
    print(f"浏览器未能自动打开，请手动访问：{BASE_URL}/workbench")
    return 1


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if health_is_ready():
        ok, report = diagnose(ROOT, deep=False)
        print(report)
        if not ok:
            return 1
        return open_page()

    if port_is_open():
        _, report = diagnose(ROOT, deep=False)
        print(report)
        print("请按诊断建议处理现有监听进程后，再重新打开工作台。")
        return 1

    control = ROOT / "Tools" / "workstation.py"
    try:
        started = subprocess.run(
            [sys.executable, str(control), "--root", str(ROOT), "serve-start"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except subprocess.TimeoutExpired:
        print("启动工作站服务超时。")
        _, report = diagnose(ROOT, deep=False)
        print(report)
        return 1
    if started.returncode != 0:
        print(started.stderr.strip() or started.stdout.strip() or "无法启动工作站控制台")
        _, report = diagnose(ROOT, deep=False)
        print(report)
        return started.returncode or 1

    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        if health_is_ready():
            ok, report = diagnose(ROOT, deep=False)
            print(report)
            if not ok:
                return 1
            return open_page()
        time.sleep(0.25)

    print("工作站服务未能在 12 秒内通过轻量健康检查。")
    _, report = diagnose(ROOT, deep=False)
    print(report)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
