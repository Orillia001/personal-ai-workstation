# 工作站 · Matt 工作流

本地Codex插件初版，包含一个可发现的`matt-workflow`技能、阶段记录CLI和深色只读看板。需要Python 3.10+，以及本机已有的Matt skills。本包不复制Matt第三方技能，不需要OpenAI API key，不另起付费模型服务。

安装后，在新的Codex会话中使用：

> 用 $matt-workflow 完成这项开发，并打开进度看板。

Codex按工作站规则选择并实际执行Matt技能，在进入、受阻和完成阶段时记录结果；看板每3秒读取。它显示最后写入的事实，不自动监听其他会话或进程。已运行的聊天可能需要新会话才能发现插件。

## 本地安装

工作站根目录已有`.agents/plugins/marketplace.json`。本机CLI支持以下命令：

```powershell
codex plugin marketplace add 'C:\Users\ok\Desktop\workstation'
codex plugin add workstation-matt@personal-workstation --json
```

也可重启Codex后在插件目录的“个人工作站”来源中安装。实际插件缓存以CLI返回为准；检查`codex plugin list`。官方格式与发行规则见[Package your plugin](https://developers.openai.com/plugins/build/plugins)。源码中的兼容manifest支持旧客户端。ZIP中没有用户任务、凭据、第三方技能或Python运行时。

## 看板

在工作站目录使用现有Python：

```powershell
& .\Runtime\Python\python.exe -X utf8 -B .\Projects\Workstation-Visual-Console\04_code\plugins\workstation-matt\scripts\matt.py --root . doctor
& .\Runtime\Python\python.exe -X utf8 -B .\Projects\Workstation-Visual-Console\04_code\plugins\workstation-matt\scripts\matt.py --root . serve --port 8786
```

打开实际返回的URL；若端口占用，选其他空闲端口。在Codex浏览器面板或工作站内容区的内置浏览器输入该URL即可查看。停止服务不影响任务数据。浏览器只读，不提供启动代码或任意命令接口。

数据保存在真实station_root的`.scratch/<任务>/matt-workflow.json`，与原任务单共存。阶段完成要求证据路径存在；证据真实性仍由实际验证和审查判断。证据预览只允许记录中的站内文件，最大2MB；HTML等作为纯文本展示。后续编辑证据文件会反映到预览，原始验收快照应保存到项目08_evidence。

阶段更新使用修订号，冲突后重新show再判断。进程异常留下`.lock`时，先确认同任务没有写入进程，再手工处理对应锁文件；原记录不会被自动覆盖。终态阶段封存，后续需求创建新的任务。

## 验证与移除

```powershell
python -X utf8 -B -m unittest discover -s ./tests -p test_cli.py -v
```

浏览器回归`tests/browser.cjs`使用既有Playwright与Edge，可通过`MATT_PYTHON`、`MATT_PLAYWRIGHT`、`MATT_BROWSER`、`MATT_TEST_OUTPUT`指定测试环境；只写临时工作站。不会修改真实任务状态。

卸载使用`codex plugin remove workstation-matt@personal-workstation`，保留本地任务和证据。仅在不再需要该市场时才运行`codex plugin marketplace remove personal-workstation`。未添加系统开机任务、MCP常驻服务或Codex原生侧栏。
