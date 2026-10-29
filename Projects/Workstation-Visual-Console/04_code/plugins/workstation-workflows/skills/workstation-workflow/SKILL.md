---
name: workstation-workflow
description: 在 Personal AI Workstation 中选择项目并执行资料接入、项目操作或 Matt Pocock 工程工作流。用户要求从 Codex 运行并查看工作流时使用。
---

# 工作站工作流

工作站根目录是 `C:\Users\Orillia\workstation`。先读取根目录与目标项目的 `AGENTS.md`，再读取项目的 `10-README.MD`、`11-project.yaml` 和 `12-status.md`。项目文件是事实来源。

按用户的目标选择一个具名流程：

- **资料接入**：读取目标项目 `00_inbox`，调用 `ws.ps1 organize-scan <项目> <项目路径\00_inbox>` 生成计划并报告计划 ID、数量和冲突风险。仅在用户批准该具体计划后调用 `organize-apply`。
- **项目进度**：读取项目说明和状态，核对当前产物，指出下一步；需要修改项目时执行可逆编辑并更新 `12-status.md`。
- **任务路线**：调用 `ws.ps1 route '<任务描述>'`，结合已安装工具和项目事实选择工作方式。
- **任务与知识库**：按项目添加具体任务；建立或增量更新项目索引后检索内容，报告命中的文件与片段。
- **备份与恢复**：创建并验证本地备份，报告备份 ID。恢复先创建动作申请，审查并批准后再执行，执行前保留当前项目备份。
- **复用与文档构建**：非简单功能先检索 GitHub 和官方生态并记录候选判断；对已有 LaTeX 文档使用项目中的构建流程，报告 PDF 与校验结果。清理辅助文件前确认具体文档。
- **Codex 规划或执行**：只读方案使用 `ws.ps1 ai-plan`；实际修改使用可审查的 Codex 任务。工作站的执行申请、批准、执行是独立步骤。
- **Matt 工程流程**：当前从本机 `/workbench/legacy` 的“工作流”页选择项目并创建路线申请，待新工作台右栏接入后再迁移入口。`ask-matt` 只建议下一项 skill；首次使用可能需要 `setup-matt-pocock-skills` 配置项目。网页通过 `GET /api/workbench/matt/catalog`、`GET /api/workbench/matt/runs`、`POST /api/workbench/matt/create` 与 `POST /api/workbench/matt/intervene` 显示阶段、审批、事件和结果。每阶段由用户分别批准、启动，并根据结果继续当前 skill 或选择下一 skill。Codex CLI 在本机执行已安装的 skill；不要把 skill 推荐当作自动执行授权。

用户要在网页操作时，项目布局与内容区使用正式 `/workbench`；尚未迁入新骨架的资料接入、Matt、审批等功能使用 `/workbench/legacy`。网页工作流只调用具名本地 API。文件复制、审批和执行继续经过各自的确认步骤；安装、外发、发布和系统配置变更遵守根目录 `AGENTS.md`。

完成后验证可观察结果，报告计划 ID 或运行 ID；项目发生阶段变化时更新 `12-status.md`。
