# 知识点直接打开Obsidian

运行ID：`EDU-MINDMAP-OBSIDIAN-OPEN-20261019-01`；2026-10-19。

入口：[深色A版Demo](http://127.0.0.1:8774/workbench?variant=A&education=machine-design&revision=dark)。刷新页面 → 点开章节下的知识点 → 在详情标题下点击“在 Obsidian 中打开”。按钮高度至少44px，支持鼠标、触控和键盘Enter，打开时保持画布缩放、位置与内容面板。

## 实现

复用现有 `Tools/obsidian_learning.py:open_note`，按课程ID与知识点ID解析真实笔记绑定和frontmatter，调用已注册的Obsidian本机协议；不按标题猜测文件名。快照中五科274个节点均已绑定。数学竞赛现有图谱只有章节，接口验证采用其已有章节笔记，不在本轮虚构二级知识点。

8774的 `preview.py` 新增唯一启动入口POST `/api/education/open-note`。页面获取每次服务启动生成的令牌，请求校验本机Host、同源Origin、令牌、JSON长度和课程/节点字符串；不接受路径、URI或命令。启动前由既有绑定解析器重新检查当前笔记，笔记缺失或绑定冲突时返回错误。没有开放学习状态写入，其他POST继续405。CSP连接范围从none改为self，适配应用内浏览器，避免依赖浏览器对外部协议链接的处理。

按钮请求期间禁用，防重复启动；成功提示“已请求在 Obsidian 打开”，失败保留中文错误并允许重试。尚未绑定的快照节点显示禁用按钮。直接以文件方式打开HTML不提供本机启动服务，会提示从预览页面操作。

## 验证

- `inspect-obsidian-open.py`：14项通过。使用真实绑定解析器、临时端口及进程内替代的应用启动函数，验证五科对应笔记URI，以及缺失节点、外站、令牌、非字符串、任意路径和其他写入入口均不启动应用。未将令牌写入报告。
- `inspect-obsidian-open.cjs`：11项通过。覆盖触控目标、当前节点请求、禁用防重复、视角保留、错误重试、键盘、切换知识点、窄屏，以及真实页面按钮调用本机启动服务。
- 实际通过按钮打开机械设计“静强度”笔记；Obsidian主窗口标题为“静强度 - 考研 - Obsidian 1.14.4”。该笔记打开前后SHA-256均为 `10f88524ae7607d9d4f2e47dae3ebd58ecb25846219296df6d18dd9db09fef26`。
- 原有 `surface-regression.cjs` 25项仍通过；页面脚本错误0。已目视检查桌面与390px截图 `obsidian-open-detail.png`、`obsidian-open-narrow.png`。Surface手势回归采用Edge输入模拟，没有新增Surface硬件验收结论。

快照和页面已重新编译，8774预览服务已从旧进程切换到新代码。现有正式8765网图、教材和学习记录不变；正式HTML前后SHA-256均为 `4EDAB86815E08A0B871242B185BA636742457AC5390176702AEF8E7B8C5BAF28`。无新增依赖，无Git提交。旧版文件保留在 `Backups/EDU-MINDMAP-OBSIDIAN-OPEN-20261019-01/`。
