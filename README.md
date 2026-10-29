# Personal AI Workstation

Windows 本机工作站源码：项目与分割工作区、中控台、计划事项、教育知识网络，以及 Codex 工作流工具。界面与后端来自当前工作站的源码快照（2026-10-28），包含最新的 DeskBox 联动适配和简约图标按钮。

## 运行

需要 Windows、Python 3.12+；Node.js 用于可选脚本检查。核心 HTTP 服务使用 Python 标准库。

```powershell
python Tools/workstation.py --root . init
python Tools/workstation.py --root . dashboard
python Tools/open_workbench.py
```

或双击 `Start-Workbench.cmd`。打开 http://127.0.0.1:8765/workbench 。停止服务使用 `python Tools/workstation.py --root . serve-stop`。服务仅监听本机。

`ws.ps1` 等完整工作站命令原本使用 `Runtime/Python/python.exe`；使用它们前需自行配置该路径的 Python 运行时。源码仓库不携带解释器、SDK、应用安装包或浏览器登录环境。

## 目录与配置

- `Tools/`：Python/PowerShell 后端与现有检查。
- `Projects/Workstation-Visual-Console/04_code/`：正式网页、可选原生壳与插件源码。
- `Config/`：通用配置及空白个人配置模板；学习科目、笔记库和下载监控需在本机配置。
- `Templates/`、`Agents/`、`.agents/skills/`、`docs/agents/`：项目模板及开发流程参考。
- `integrations/deskbox/`：DeskBox v1.5.7 本机联动补丁；DeskBox 运行中编辑需要使用该补丁版。

Codex、LaTeX、OCR、Obsidian 和办公软件功能按需依赖本机已安装软件及登录配置，仓库不会替你登录或调用付费 API。API 密钥使用环境变量，参考 `Config/env.example`。

## 本次公开范围

这是程序源码版本，不是个人工作资料备份。不含实际项目文稿、教材和课程记录、SQLite 状态、待办、聊天与登录凭据、用户笔记、截图证据、日志、备份、大型下载和编译产物。首次运行会生成自己的本机状态。不要将上述文件重新加入公开提交。

## DeskBox 与第三方内容

DeskBox 上游为 https://github.com/Tianyu199509/DeskBox ，补丁和对应许可证见 `integrations/deskbox/`。其他插件和组件保留各自已有许可证；本次上传没有另行授予整个项目新的开源许可证。
