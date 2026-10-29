# 统一教学入口

日常教学先运行 `./ws.ps1 context University <课程ID> -Topic teaching`，默认只读进度卡。未变化的规则复用上下文。

- 安排下一步：只使用返回的进度，不预读教材、整张知识图或历史记录。
- 讲解知识：先用 `./ws.ps1 teach-lookup <课程ID> 关键词` 定位，再用 `./ws.ps1 teach-context <课程ID> -Intent teach -Node 知识点ID` 读取必要知识和有限来源片段。原页疑字、公式或条件不足时显式补查。
- 评阅作答：`teach-context <课程ID> -Intent assess -Node ID -Data 题目作答JSON`；需要实际题目和作答。文件读取结果仍属于模型上下文，不承诺整个Codex请求只有进度。
- 调整位置：`teach-select <课程ID> ID`。评阅后以`teach-record <课程ID> 事件JSON`记入本科；自述已有基础只记self_reported，单次通过只记review_due，长期掌握须另有延迟复测证据。
- 新建课件或首次使用教学方法时按Teach技能执行，使命沿用课程已确认目标；任务完成、掌握和计划健康分别记录。
- Obsidian知识正文、大纲和Canvas由`teach-publish <课程ID>`增量发布；保留绑定ID与学习状态属性，其他笔记或连线修改先合并。学习完成标记由Obsidian「学习状态」和工作站节点详情双向编辑；不全盘导入后台，发布清单、日志、OCR和证据留工作站。
- 修改架构、接入教材、调整课程规则时改用`-Topic education`读取完整分支；入口和实现见`Tools/README.md`。

主体实现：`Tools/teaching_core.py`；共享配置：`Config/teaching.json`；状态：`State/teaching/`；每科资源：`courses/<ID>/knowledge/graph.json`。前台不展示这些路径或运行信息。

记录学习事件前读取 `Config/teaching-event-format.md`。本模块只准备必要上下文和保存记录，实际讲解与评阅由当前对话完成；不调用额外模型。

双向学习状态：实现见 Tools/obsidian_learning.py。实际 teach-record 完成后会投影学习状态到已绑定笔记；同步失败会返回 obsidian_sync 提示，学习证据仍保留。自述只能记self_reported，网页或笔记的「已学习」不能当作通过测验或长期掌握。查询显示状态可读 GET /api/education/progress?course=<课程ID>；纯进度默认入口仍不读取知识正文或整个Vault。
