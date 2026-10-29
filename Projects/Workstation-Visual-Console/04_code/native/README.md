# Workstation 原生 Windows 应用

此项目通过 WinForms 提供一个备选原生桌面版本，并复用工作站现有 `ws.ps1`、本地 Python 控制服务及白名单 `/api/*` 接口。用户反馈窗口仍有明显布局冲突后，默认入口切回响应式网页；原生版核心功能现也已接入网页工作台。根目录 `Start-Workstation.cmd` 不启动本项目。

## 功能

- 独立后台托盘模式：启动时自动检查并启动本机服务，打开网页工作台；异常断开后自动重连。
- 双击托盘图标打开工作台；右键菜单可检查/启动/停止服务、运行连接自检、打开工作站文件夹或退出托盘程序。
- 总览和项目目录/状态文件入口。
- 从 `Config/launcher.json` 列出本机软件并启动可用应用。
- 选择具体来源目录，调用 `/api/scan` 生成整理计划；不会自动复制或覆盖来源文件。
- PowerShell Codex CLI 项目会话。
- Codex 只读分析、执行申请、批准/拒绝/运行，以及本地状态、模型和适配器 API。

## 安全与扩展

- 软件启动只提交固定应用 ID，服务端按 `Config/tools.json` 的已发现 `.exe` 解析，不接收路径、启动参数或任意 shell 文本。
- 扫描按工作站规则拒绝磁盘根目录和过宽目录；复制计划继续经现有审查流程。
- Codex 只读分析会在调用前显示额度确认；写入任务遵守创建申请、人工批准、执行三步闭环。
- 新软件通过 `Config/launcher.json` 声明并关联工具名；新增操作应继续接入现有具名 API，不添加通用命令执行入口。

## 编译

工作区本地 SDK：`Tools/dotnet-sdk/dotnet.exe`（.NET 10.0.203）。运行 `04_code/native/Build-Workstation.ps1` 从微软公开 NuGet 镜像恢复 Windows 运行时包，生成自包含 Windows x64 单文件 `09_output/responsive/Workstation.exe`。该备选程序需要此工作站目录及现有 Python/PowerShell 工作站工具；根目录 `Start-Workstation.cmd` 已改为打开网页工作台。

运行 `04_code/native/Build-Workstation.ps1 -Background` 可单独生成 `09_output/background/Workstation.exe`。带 `--tray` 启动它会进入托盘后台模式，不弹主窗口；桌面“个人 AI 工作站”快捷方式使用此模式。关闭托盘图标不会停止服务；右键菜单可单独停止后台服务，或选择“停止服务并退出”。后台进程每 5 秒检查健康接口，服务意外退出后按间隔自动重启。

托盘程序和工作站服务均为当前用户进程，只监听本机 `127.0.0.1:8765`。桌面入口不会注册 Windows 登录启动项；若要开机自动驻留，需之后单独确认。

桌面窗口按当前显示器工作区限制初始尺寸；页面内容随窗口宽度重新排版，按钮与卡片自动换行，页面可纵向滚动。应用启用 Per-Monitor V2 高 DPI 支持。
