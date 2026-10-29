---
name: matt-workflow
description: 在Personal AI Workstation中执行Matt开发流程并记录可视化阶段，或查看Matt任务的进度和证据。用于Matt看板/流程跟踪，不用于日常教学。
---

# Matt 工作流与看板

插件根目录为本文件所在目录向上两级；执行其`scripts/matt.py`，不要依赖当前目录是插件源码目录。需要Python 3.10+及本机Matt技能。

## 定位与查看

在工作目录运行`./ws.ps1 context [项目] -Topic development`，确认ready、warnings与station_root，读取read_before_action。没有ws.ps1时让用户指定工作站目录。下文ROOT为返回的真实station_root。

调用`python <插件根>/scripts/matt.py --root ROOT doctor`检查技能依赖；可用工作站自带Python替换python。本包不包含Matt第三方技能正文，也不自动安装它们。

仅查看时调用`list`。看板使用`serve --port 8786`，返回真实URL后在Codex浏览器或工作站内置浏览器打开。先检查该URL的`/api/health`，已有匹配root的服务可复用，端口被其他服务占用时另选端口。后台进程保持隐藏。

## 执行并记录

1. 读取本机`ask-matt/SKILL.md`，路径由doctor返回。结合项目workflow规则选择所需技能并读取实际SKILL.md。选路或读取本身不代表执行完成；缺少必需技能时报告缺项，继续不依赖它的工作。
2. 从`clarify,prototype,spec,tickets,implement,verify,review,release,retro`中仅保留本次需要的阶段。已有明确需求无需重访谈。实现按implement执行，独立两轴审查按code-review执行，缺陷按diagnosing-bugs进入。
3. `begin --task <功能slug> --project <项目目录名> --title <标题> --stages spec,implement,verify,review,release`创建跟踪；已存在时用`show --task ...`继续原记录。已有任务单按项目规则维护，阶段记录不替代规格。
4. 实际进入、受阻或完成时调用`update --task ... --stage ... --status running|blocked|completed|skipped --revision <show返回的修订号> --note <结果或原因>`。完成附一个或多个`--evidence <ROOT内相对文件路径>`，引用真实产物或验收报告。跳过需原因。冲突后重读事实；每次命令返回新修订号。
5. 跨会话继续时读取show、关联任务和证据，核验原running阶段是否仍执行；中断不确定时标blocked并说明。看板显示阶段记录，不自动侦测其他聊天或Codex内部思考。
6. 收尾区分代码完成、已验证和已安装/部署。release仅在当前授权范围执行并记录结果，没有该范围时路线到review为止。保留备份、更新项目状态并报告运行ID与看板URL。

CLI支持`--help`。终态阶段保留记录，新增需求创建新task。当前Codex任务负责执行；本插件通过CLI记录事实，不用旧`/api/workbench/matt/*`另起Codex进程。
