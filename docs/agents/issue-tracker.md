# Issue tracker：本地 Markdown

工作站任务与规格保存在 station_root 下的 `.scratch/`。所有路径相对实际工作站根目录，使用桌面转发目录时也写入这里。

## 约定

- 一个功能一个目录：`.scratch/<feature-slug>/`。
- 规格为 `spec.md`；实现任务为 `issues/<NN>-<slug>.md`，从01开始按依赖编号，每票一个文件。
- 任务写明所属项目、完整行为、验收条件、Status及Blocked by；沿用技能模板，读取时兼容普通和加粗字段名。
- 分流角色使用 [triage-labels.md](triage-labels.md) 的五种标签。执行时可用 `claimed` / `resolved` 表示认领和完成；它们不增加新的分流角色。
- 评论与验证结果追加到任务文件的 `## Comments`。验收通过后标记 resolved，并链接实际证据；前置依赖未解决时先处理依赖。

技能要求“发布到 issue tracker”时创建对应 Markdown 文件；要求“获取任务”时读取明确引用的本地文件。编号只在功能目录内唯一，引用时带上功能目录。已有明确范围的小功能可以在同一上下文直接实现，无需为套用流程制造拆票。

## Wayfinding

决策地图使用 `.scratch/<effort>/map.md`，每个问题在 `issues/NN-<slug>.md` 中记录 Type、Status、Blocked by。先认领再处理，解决后在 `## Answer` 记录答案，并在地图中链接。执行前沿为前置依赖均已解决且尚未认领的任务。

此配置使用本地文件；未来选择远程平台时再更新本文件及相关授权。
