"""Read-only connectivity and latency checks for the local workbench."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_ROOT = Path(__file__).resolve().parent.parent
SLOW_MS = 1500


def _get(base_url: str, route: str, timeout: float = 3.0) -> tuple[dict | list | None, int | None, int, str | None]:
    started = time.perf_counter()
    request = Request(base_url + route, headers={"User-Agent": "Personal-AI-Workstation-Diagnostics/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            data = json.loads(response.read().decode("utf-8"))
        return data, status, int((time.perf_counter() - started) * 1000), None
    except HTTPError as exc:
        return None, exc.code, int((time.perf_counter() - started) * 1000), f"HTTP {exc.code}"
    except (OSError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        reason = "timeout" if isinstance(exc, TimeoutError) else type(exc).__name__
        return None, None, int((time.perf_counter() - started) * 1000), reason


def _get_workbench_page(base_url: str, timeout: float = 3.0) -> tuple[bool, int | None, int, str | None]:
    started = time.perf_counter()
    request = Request(base_url + "/workbench", headers={"User-Agent": "Personal-AI-Workstation-Diagnostics/1.0"})
    try:
        with urlopen(request, timeout=timeout) as response:
            page_header = response.read(512).decode("utf-8", errors="replace")
            ok = response.status == 200 and "<html" in page_header.lower() and "<title>工作台" in page_header
            return ok, response.status, int((time.perf_counter() - started) * 1000), None if ok else "invalid workbench page"
    except HTTPError as exc:
        return False, exc.code, int((time.perf_counter() - started) * 1000), f"HTTP {exc.code}"
    except (OSError, URLError, TimeoutError) as exc:
        reason = "timeout" if isinstance(exc, TimeoutError) else type(exc).__name__
        return False, None, int((time.perf_counter() - started) * 1000), reason


def _required_files(root: Path) -> list[str]:
    required = (
        "Tools/workstation.py",
        "Tools/open_workbench.py",
        "Projects/Workstation-Visual-Console/04_code/workbench/layout-prototype.html",
        "Config/launcher.json",
        "Config/tools.json",
        "Projects",
    )
    return [item for item in required if not (root / item).exists()]


def _check_workbench_script(root: Path) -> tuple[bool | None, str]:
    """Check inline JavaScript when Node is available; never execute page code."""
    node = shutil.which("node")
    if not node:
        return None, "页面脚本：未检查（未发现 Node.js）"
    page = root / "Projects/Workstation-Visual-Console/04_code/workbench/layout-prototype.html"
    if not page.is_file():
        return False, "页面脚本：失败（工作台页面不存在）"
    scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script\s*>", page.read_text(encoding="utf-8"), re.I | re.S)
    if not scripts:
        return False, "页面脚本：失败（未找到内联脚本）"
    try:
        result = subprocess.run(
            [node, "--check", "-"], input="\n".join(scripts), text=True,
            encoding="utf-8", capture_output=True, timeout=5, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, f"页面脚本：失败（{type(exc).__name__}）"
    if result.returncode:
        reason = next((line.strip() for line in result.stderr.splitlines() if "SyntaxError:" in line), "语法检查失败")
        return False, f"页面脚本：失败（{reason}）"
    return True, "页面脚本：正常"


def diagnose(root: Path = DEFAULT_ROOT, port: int = 8765, deep: bool = False) -> tuple[bool, str]:
    root = root.resolve()
    base_url = f"http://127.0.0.1:{port}"
    lines = ["Personal AI Workstation · 本机工作台自检"]
    missing = _required_files(root)
    if missing:
        lines.append("工作区文件：失败")
        lines.extend(f"  缺少：{item}" for item in missing)
    else:
        lines.append("工作区文件：正常")
    script_ok, script_report = _check_workbench_script(root)
    lines.append(script_report)

    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            lines.append(f"本机端口 {port}：可连接")
    except OSError:
        lines.append(f"本机端口 {port}：无监听")
        lines.append("建议：运行 Start-Workstation.cmd 启动工作台。")
        lines.append("结论：服务未启动或端口未监听。")
        return False, "\n".join(lines)

    health, health_status, health_ms, health_error = _get(base_url, "/api/health")
    if health_error or health_status != 200 or not isinstance(health, dict) or not health.get("ok"):
        health_reason = health_error or f"HTTP {health_status}"
        lines.append(f"健康接口：失败（{health_reason}，{health_ms} ms）")
        if health_status == 404 or (health_status == 200 and health_error == "JSONDecodeError"):
            lines.append("检测到旧版工作站页面或其他服务占用了工作台端口；请运行 .\\ws.ps1 control-stop 后重新启动工作台。")
        else:
            lines.append("端口有响应，但不是可用的工作站服务；请检查端口冲突和 Logs/control.log。")
        lines.append("结论：网页服务未通过健康检查。")
        return False, "\n".join(lines)
    lines.append(f"健康接口：正常（{health_ms} ms）")

    page_ok, page_status, page_ms, page_error = _get_workbench_page(base_url)
    if not page_ok:
        page_reason = page_error or f"HTTP {page_status}"
        lines.append(f"网页资源：失败（{page_reason}，{page_ms} ms）")
        lines.append("建议：检查工作台 HTML 文件和 Logs/control.log。")
        lines.append("结论：服务在线，但工作台网页资源无法正常提供。")
        return False, "\n".join(lines)
    lines.append(f"网页资源：正常（{page_ms} ms）")

    overview, overview_status, overview_ms, overview_error = _get(base_url, "/api/workbench/overview")
    if overview_error or overview_status != 200 or not isinstance(overview, dict) or not isinstance(overview.get("projects"), list):
        overview_reason = overview_error or f"HTTP {overview_status}"
        lines.append(f"项目接口：失败（{overview_reason}，{overview_ms} ms）")
        lines.append("建议：运行 .\\ws.ps1 control-stop，再运行 Start-Workstation.cmd。")
        lines.append("结论：服务在线，但项目读取接口不可用。")
        return False, "\n".join(lines)
    project_count = len(overview["projects"])
    project_slow = overview_ms >= SLOW_MS
    lines.append(f"项目接口：{'偏慢' if project_slow else '正常'}（{project_count} 个项目，{overview_ms} ms）")
    if project_slow:
        lines.append(f"项目概览超过 {SLOW_MS} ms 阈值，首屏读取可能出现明显等待。")
    if project_count == 0:
        lines.append("提示：Projects 目录下没有可显示的项目文件夹。")

    warnings = []
    if missing:
        warnings.extend(missing)
    if deep:
        routes = (
            ("/api/status", "完整状态"),
            ("/api/v4/status", "模型/适配器状态"),
            ("/api/education/status", "课程状态"),
            ("/api/launcher/apps", "软件发现"),
        )
        for route, label in routes:
            _, status, elapsed, error = _get(base_url, route, timeout=8.0)
            if error or status != 200:
                warnings.append(f"{label}接口异常")
                reason = error or f"HTTP {status}"
                lines.append(f"{label}：失败（{reason}，{elapsed} ms）")
            elif elapsed >= SLOW_MS:
                warnings.append(f"{label}接口耗时较长")
                lines.append(f"{label}：偏慢（{elapsed} ms）")
            else:
                lines.append(f"{label}：正常（{elapsed} ms）")

    if script_ok is False:
        lines.append("结论：页面脚本无法执行，工作台交互不可用。")
        return False, "\n".join(lines)
    if project_slow or missing:
        lines.append("结论：核心项目读取链路未达到响应时间目标。")
        return False, "\n".join(lines)
    if warnings:
        lines.append("结论：项目读取链路正常，但有可选状态接口异常或偏慢。")
    else:
        lines.append("结论：工作台连接与项目读取正常。")
    return True, "\n".join(lines)


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="检查本机工作台连接、项目读取和可选 API 延迟")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--deep", action="store_true", help="逐项测量完整状态、模型、课程和软件接口")
    args = parser.parse_args()
    ok, report = diagnose(args.root, args.port, args.deep)
    print(report)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
