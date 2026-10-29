# 工具定位

从根目录 `ws.ps1` 调用现有命令；需要修改实现时再读下列文件和命中函数。

| 任务 | 入口文件 |
| --- | --- |
| 统一教学、进度卡、知识查询与发布 | `teaching_core.py`；日常规程见 `../Config/teaching-guide.md` |
| 精简上下文、主题手册 | `Get-WorkstationContext.ps1`；映射在 `../Config/context-map.json` |
| 项目同步、任务、路由、偏好、本机 HTTP | `workstation.py` |
| 模型/适配器、知识索引、审批、备份 | `workstation_v4.py` |
| 网页连接检查、启动 | `workbench_diagnostics.py`、`open_workbench.py` |
| 教材识别、待校验提纲 | `textbook_ocr.py`、`textbook_outline.py` |
| LaTeX项目创建、构建 | `New-LaTeXProject.ps1`、`Invoke-LaTeXProject.ps1` |
| 项目内 Codex CLI | `open-codex-session.ps1` |
| 工作流的Codex技能、规则、任务与子Agent只读文件映射 | `workstation_codex.py`；范围见 `../Projects/Workstation-Visual-Console/docs/codex-data-map.md` |
| 工作流规则管理：编辑、新建、安装、入口启停与备份恢复 | `workstation_codex_manage.py`；仅登记源目录可写，系统与插件缓存只读 |
| 工作流节点编排、JSON草稿保存、规则组合预览 | `workstation_workflows.py`；不包含执行器，接口回归 `test_workstation_workflows.py` |

先 `rg -n` 定位命令或函数，再读取附近实现。具体软件可用性由现有 tools/adapter-status 命令核验；此表不代表已运行或可绕过权限。

教育网图与Obsidian学习状态：education_network.py提供知识投影；obsidian_learning.py负责原生属性绑定、状态读取/更新、修订保护及笔记打开。前端位于Projects/Workstation-Visual-Console/04_code/workbench/education-network.js与.css。

### 工作流模型选择

`workstation_model_router.py`是工作流的离线元数据池与效果优先筛选器，由`workstation_workflows.dispatch`复用本地受保护接口，不调用外部API。测试：`Runtime/Python/python.exe -m unittest discover -s Tools -p test_workstation_model_router.py -v`。固定持久化`State/model-router/catalog.json`，只接受元数据，无密钥/URL/env字段；独立修订保存。完整边界见项目`docs/codex-data-map.md`，回归证据`WORKFLOW-MODEL-ROUTER-20261022-01`。

### Matt总图与项目工具入口

`workstation_matt_map.py`是只读方法/显式阶段记录投影，受token保护的`/api/workbench/matt-map`不执行命令。项目上下文用于workflows的服务端所属校验和模型池固定分目录；旧API兼容。界面和边界见项目`docs/codex-data-map.md`。

回归：`Runtime/Python/python.exe -m unittest discover -s Tools -p test_workstation_matt_map.py -v`；UI组件依赖顺序及跨项目响应检查为新证据目录`project-state-check.cjs`，真实连线/指针检查`matt-graph-check.cjs`，独立异步焦点检查`standards-project-async-check.cjs`。没有Git/CI，这些检查需显式运行。

### 金融学可执行流程与证据控制

`workstation_coursework.py`提供项目内金融九阶段的运行快照、Codex CLI角色调度、并行审稿、三个版本绑定人工关卡和本地交付；`workstation_evidence.py`提供逐字证据提取、版本核对及本地词法RAG。入口`POST /api/workbench/coursework`；不改变`workstation_workflows.py`的编排预览边界。前端`coursework-runner.js/.css`由项目工具“运行与证据”挂载。测试分别为`test_workstation_coursework.py`、`test_workstation_evidence.py`。不安装Dify、不自动联网抓全文、不任意执行模型生成代码；外部实际计算结果需作为可追踪资料提供。
