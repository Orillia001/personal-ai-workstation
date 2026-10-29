# 响应式本机工作台

双击工作站根目录的 Start-Workbench.cmd 或 Start-Workstation.cmd，启动仅监听 127.0.0.1 的本机服务并打开正式入口 `/workbench`。当前正式页面的源码是 `layout-prototype.html`；旧版工具页源码 `index.html` 保留在 `/workbench/legacy`。站点首页 `/` 也显示正式页面，旧控制面板可从 `/dashboard` 访问。浏览器中的项目布局和内容继续使用既有 SQLite 状态库。

## 正式工作台骨架

正式入口 `http://127.0.0.1:8765/workbench` 使用 VS Code 风格：左侧「分类 → 项目 → 小项目」，中央可拖动分割内容区，右侧工作流占位。可选布局、主内容、标注、内置浏览器、项目文件、网页内 pwsh 终端和自定义预览；界面状态自动保存在本机 SQLite。中控台显示项目用时和外部网站桥接占位。旧地址 `/workbench/layout-prototype` 暂作兼容别名，读取同一页面和同一状态。

尚未迁入新骨架的资料接入、Matt 工作流、执行审批和设置等操作，可继续在 `/workbench/legacy` 使用。迁移这些功能时先确定交互设计，再接回现有具名 API。

## 旧版工具页保留的功能

- **总览**：首屏从轻量接口读取项目、任务数和待审批动作；完整状态与课程状态由 API 面板按需读取。
- **项目**：搜索并筛选项目；按需预览选中项目的 10-README.MD 与 12-status.md，或打开项目目录、状态文件和 PowerShell Codex CLI。
- **软件入口**：显示 Config/launcher.json 中登记、并由 Config/tools.json 发现的本机软件；仅传应用 ID 启动。
- **文件接入**：只选目标项目，服务端扫描该项目的 `00_inbox`，生成带 SHA-256 的计划并预览；用户确认后调用复制接口。保留原件，不覆盖目标，记录项目 intake manifest。
- **工作流**：十一个具名入口包括 Matt · Codex 工程流程、资料接入、项目进度、任务路线、Codex 审批、自检、任务、知识库、备份、现成方案检索和 LaTeX 构建。Matt 区域显示 skill 阶段、Codex 事件、审批状态和最后结果；用户可逐阶段批准、补充、继续或终止。任务路线在页内调用现有路由 API。
- **项目操作**：创建项目、添加任务并查看运行、更新和检索知识索引、创建及验证备份、检索 GitHub 复用候选、构建或清理已发现的 LaTeX 文档。恢复申请、批准和执行分开操作。文件接入页也可按运行 ID 撤销该运行创建且未变化的副本。
- **设置**：当前浏览器保存默认项目、显示密度和视觉风格；工作站状态库保存可校验的输入、资源和联网偏好。默认一个 Agent、文件保留与日志安全规则只读。
- **Codex / API**：打开项目 PowerShell Codex CLI；确认后调用 ChatGPT 套餐中的 Codex 用量进行只读分析；创建执行申请并单独批准、拒绝或执行。显示状态、模型、适配器和课程 API 响应。
- **快速开始**：复制工作站 PowerShell 命令和 Codex CLI 会话命令。

以下旧版工具仍由 `/workbench/legacy` 提供；该页面自己的主题设置不会改变正式工作台的 VS Code 风格。

所有 POST 请求都通过本地服务生成的会话令牌。正式工作台的内置终端允许用户手动输入 PowerShell 命令；其他操作使用具名 API。文件扫描先生成计划；复制、使用 Codex 用量、动作审批和项目写入各有单独确认。写入执行在工作站服务端沿用备份与审批流程。

首屏使用轻量 /api/health 与 /api/workbench/overview；项目和审批先显示，较慢的模型、完整状态、课程和软件扫描按需读取。网页顶栏“服务自检”检查在线状态和项目读取；PowerShell 深度检查命令为 .\ws.ps1 workbench-diagnose。

项目文档按用户选择后读取，每个文件最多预览 128 KiB，不递归扫描项目树。

## 布局与扩展

页面支持窄屏、窄窗口、移动设备及 Surface 触屏布局。检测到触摸指针时，按钮和导航点按区至少 44×44 CSS 像素，表单输入增大，触摸平板宽度下侧栏收成可横向滑动的顶部导航；表格可横向触摸滚动，低视口高度时导航不再固定占住垂直空间。普通鼠标设备保留原布局。新增应用在 Config/launcher.json 登记并映射到 Config/tools.json；新增工作站能力应新增具名 API，不要开放任意命令执行接口。服务托管路由与接口实现在根目录 Tools/workstation.py。

`GET /api/workbench/capabilities` 提供版本化的本地能力清单，列出项目、软件、项目 `00_inbox` 扫描、设置、工作流和执行审批的具名端点。后续客户端先读取 `schema_version` 和清单，再接入所需端点；版本 1 可增加字段，改变既有字段含义时应升版本。所有 POST 继续使用页面会话中的 `X-Workstation-Token`，可能复制文件或执行动作的入口仍须保留人工确认。新增软件只需维护 `Config/launcher.json` 与 `Config/tools.json` 的对应关系。

窗口 Demo 使用 `POST /api/workbench/window-draft`：服务端固定校验项目和小项目标识，调用已登录 Codex CLI 的只读沙箱，以 JSON Schema 限制返回结构，并再次校验字段和操作白名单。结果只在当前页面展示；需真实项目写入时应另建可审查任务。

Matt 工程流程接口：`GET /api/workbench/matt/catalog` 列出本机已登记 skill，`GET /api/workbench/matt/runs` 读取阶段和事件，`POST /api/workbench/matt/create` 创建路线申请，`POST /api/workbench/matt/intervene` 处理批准、拒绝、执行、下一阶段、配置草案写入申请、结束或终止。用户从网页明确选择一项 skill 后，服务调用已登录的 Codex CLI；`ask-matt` 的建议只作为结果，不会自行启动下一阶段。Matt 初始化先只读征询并展示草案，用户确认草案后再创建写入申请；写入阶段先备份所选项目。本机 Windows 沙箱使用已验证的官方后备模式。运行记录和最后结果保存在本机状态目录。

发布页面改动前运行 `.\ws.ps1 workbench-diagnose`。安装了 Node.js 时，自检会先静态检查内联 JavaScript 语法，再检查页面资源、健康接口和项目概览；未安装 Node.js 时会明确标记语法检查未运行。
