# 站点脚本接入

每个平台使用一个经审查的本地适配器，同时实现登录确认与作业读取。需要扫码、验证码等人工步骤时，必须返回 `user_action_required`，不得继续读取或把未加载误判为零项。运行过程不调用模型。

## 新增站点

1. 根据 `_rain_classroom_template.py` 编写站点适配器。页面选择器和字段必须来自站点页面证据；不要把密码、Cookie 或完整登录链接写进源码、测试或日志。
2. 用虚构页面或本地夹具覆盖“直接进入”“多一步操作”“需要人工验证”“空列表”和“页面未就绪”。只有确认页面已就绪后才能报告零项；页面结构改变应返回错误。
3. 审查源码后，在本机服务启动代码中显式注册适配器。网页只登记站点，不能上传或执行 Python 文件。检查操作应使用具名端点和超时控制。

## 雨课堂最近一周考试提醒

雨课堂的 Edge 扩展复用当前浏览器会话，不建立独立浏览器配置，也不修改工作站服务架构。工作台打开时，扩展检查一个已打开的雨课堂页面；如果没有，则在后台新建雨课堂首页标签。当前自动读取器仅查找页面可见文字中的“最近一周有 X 门考试”，并输出 X；确认课程页已加载且没有该文字时输出 0。

扩展把数字结果转给工作台页面。工作台使用既有令牌保护的 API 与 SQLite 保存数量及最近检查状态。成功读取会替换上次数字；登录失效或读取失败会记录原因并保留上次成功结果。重新登录后可点雨课堂卡片的“立即同步”。扩展不读取或传送 Cookie、密码、完整登录链接或整个页面。

**此接口只提供“最近一周考试提醒”，不能代表雨课堂上的全部未完成作业，也没有可靠截止日期。** 工作台不得把它标成所有待交作业或推断截止时间。

### 手动加载 Edge 扩展

首次启用需用户操作浏览器设置：

1. 在工作站根目录运行 `node .\Projects\Workstation-Visual-Console\04_code\rain-edge-extension\build-reader.cjs`，生成扩展目录中的 `rain-reader.js`。
2. Edge 打开 `edge://extensions`，由用户开启“开发人员模式”，点击“加载解压缩的扩展”，选择 `Projects\Workstation-Visual-Console\04_code\rain-edge-extension`。
3. 打开本机工作台。扩展只匹配雨课堂 HTTPS 页面和 `http://127.0.0.1:8765`。

扩展未安装或未启用时，可继续使用 Snippet 后备流程：在工作台雨课堂卡片复制 `rain_classroom_reader.js`，然后在已登录雨课堂标签页的 Edge DevTools → Sources → Snippets 中运行；复制结果后回到工作台导入。不要在工作台页运行 Snippet，因为它不共享雨课堂登录会话。

失败状态分为 `user_action_required` 与 `site_error`。前者要求用户在 Edge 中登录；后者表示网络或接口错误。失败都不会覆盖上次成功快照。

`_rain_classroom_template.py` 仍是未来 Python 适配器模板，不会被自动导入或执行。

## 课程伴侣待提交作业

`theol_homework_reader.js` 由用户保存的 GBK 页面确定选择器：`#taskUl li[data-value="homework"] h4` 提供数量，`#homeworkTask ul > li` 提供完整标题、截止时间与课程名。它只读取这些 DOM 节点，不运行网页内联脚本或请求站点 API。读取结果通过现有 Edge 扩展传给本机工作台，并由 `POST /api/workbench/site-bridges/theol-check` 再次校验字段后保存。登录跳转、页面未就绪、列表与数量冲突时记录错误，保留上次成功快照。

保存页面验证：`node Tools/site_adapters/test_theol_saved_page.cjs "C:\Users\Orillia\Downloads\THEOL在线教育综合平台-内蒙古工业大学.html"`。测试在隔离 Edge 的 `DOMParser` 中创建惰性文档，不执行附件里的脚本或加载附件资源。
