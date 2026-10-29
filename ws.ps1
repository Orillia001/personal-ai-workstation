param(
    [Parameter(Position=0)][ValidateSet('help','context','open','edit','latex-create','latex-build','latex-clean','doctor','projects','status','diff','render','dashboard','control','control-start','control-status','control-stop','workbench-diagnose','new','project-create','router','state','v4-init','tools','tasks','route','reuse-search','ai-status','ai-plan','knowledge-index','knowledge-search','model-status','model-route','adapter-status','permission-list','execute-request','execute-approve','execute-deny','execute-run','backup-create','backup-list','backup-verify','restore-request','restore-run','local-prompt','cloud-prompt','ocr','textbook-ocr','teach-progress','teach-context','teach-lookup','teach-select','teach-record','teach-validate','teach-publish','preferences','preference-set','watch-start','watch-status','watch-stop','organize-scan','organize-apply','organize-undo')][string]$Action = 'help',
    [Parameter(Position=1)][string]$Project = 'Sandbox',
    [Parameter(Position=2)][string]$Target,
    [string]$Topic,
    [switch]$Full,
    [switch]$Guide,
    [string]$Intent = 'progress',
    [string]$Node,
    [string]$Data,
    [int]$Budget = 6000
)
$ErrorActionPreference = 'Stop'
# Context discovery is read-only: skip environment setup, SQLite and event logging.
if ($Action -eq 'context') {
    $contextArgs = @{ StationRoot = $PSScriptRoot }
    if ($PSBoundParameters.ContainsKey('Project')) { $contextArgs.Project = $Project }
    if ($Target) { $contextArgs.Course = $Target }
    if ($Topic) { $contextArgs.Topic = $Topic }
    $contextArgs.Full = $Full
    $contextArgs.Guide = $Guide
    & (Join-Path $PSScriptRoot 'Tools\Get-WorkstationContext.ps1') @contextArgs
    exit $LASTEXITCODE
}
if ($Topic -or $Full -or $Guide) { throw 'Topic、Full、Guide 仅适用于 context 命令。' }

# Teaching has a small, local, database-free interface.
if ($Action -like 'teach-*') {
    $teachingCourse = if ($Project -eq 'University' -and $Target) { $Target } elseif ($Project -ne 'Sandbox') { $Project } else { $null }
    $teachingArgs = @('--root', $PSScriptRoot, $Action.Substring(6))
    if ($teachingCourse) { $teachingArgs += $teachingCourse }
    switch ($Action) {
        'teach-context' {
            $teachingArgs += @('--intent', $Intent, '--max-chars', [string]$Budget)
            if ($Node) { $teachingArgs += @('--node', $Node) }
            if ($Data) { $teachingArgs += @('--submission', $Data) }
        }
        'teach-lookup' { if (-not $Target) { throw '需要知识点关键词。' }; $teachingArgs += $Target }
        'teach-select' { if (-not $Target) { throw '需要知识点ID。' }; $teachingArgs += $Target }
        'teach-record' { if (-not $Target) { throw '需要事件JSON文件。' }; $teachingArgs += $Target }
        'teach-publish' {
            $teachingConfig = Get-Content -LiteralPath (Join-Path $PSScriptRoot 'Config/teaching.json') -Raw | ConvertFrom-Json
            $teachingArgs += @('--vault', $teachingConfig.vault)
        }
    }
    & (Join-Path $PSScriptRoot 'Runtime/Python/python.exe') -X utf8 -B (Join-Path $PSScriptRoot 'Tools/teaching_core.py') @teachingArgs
    exit $LASTEXITCODE
}

. (Join-Path $PSScriptRoot 'Runtime\environment.ps1')
$StationRoot = $PSScriptRoot
$ProjectRoot = Join-Path $StationRoot "Projects\$Project"
$Core = Join-Path $StationRoot 'Tools\workstation.py'
$CoreV4 = Join-Path $StationRoot 'Tools\workstation_v4.py'
$ExitCode = 0
$GitExitCode = 0

function Write-Event([string]$Event, [int]$Code) {
    $record = [ordered]@{time=(Get-Date).ToUniversalTime().ToString('o');event=$Event;project=$Project;exit_code=$Code} | ConvertTo-Json -Compress
    Add-Content -LiteralPath (Join-Path $StationRoot 'Logs\events.jsonl') -Value $record -Encoding utf8
}
function Invoke-Git([string[]]$Arguments) {
    if (-not (Test-Path -LiteralPath (Join-Path $ProjectRoot '.git'))) { throw "项目尚未初始化 Git：$ProjectRoot" }
    & git -c "safe.directory=$($ProjectRoot.Replace('\','/'))" -C $ProjectRoot @Arguments
    $script:GitExitCode = $LASTEXITCODE
}
function Invoke-Core([string[]]$Arguments) {
    & python $Core --root $StationRoot @Arguments
    $script:ExitCode = $LASTEXITCODE
}
function Invoke-CoreV4([string[]]$Arguments) {
    & python $CoreV4 --root $StationRoot @Arguments
    $script:ExitCode = $LASTEXITCODE
}
try {
    switch ($Action) {
        help { @'
Personal AI Workstation

  .\ws.ps1 context [项目] [课程ID]       精简定位；-Topic 主题，-Guide 章节，-Full 详情
  .\ws.ps1 teach-progress [课程ID]       统一教学入口：只读进度卡
  .\ws.ps1 teach-context <课程ID>        默认进度；-Intent teach/assess按需取内容
  .\ws.ps1 teach-lookup <课程ID> <关键词> 定位知识点；teach-publish增量更新Obsidian
  .\ws.ps1 open                         在 VS Code 打开工作站
  .\ws.ps1 edit <项目> [相对路径]         在 VS Code 编辑项目文件或打开项目目录
  .\ws.ps1 latex-create <项目> <文档名>   创建分类存放的 LaTeX 文档项目
  .\ws.ps1 latex-build <项目> [文档名]   编译 LaTeX 到文档目录的 build/dist
  .\ws.ps1 latex-clean <项目> [文档名]   清理 LaTeX 编译辅助文件
  .\ws.ps1 doctor                       检查基础设施
  .\ws.ps1 state                        初始化/同步状态中心
  .\ws.ps1 tools                        自动发现本机工具
  .\ws.ps1 projects                     列出项目
  .\ws.ps1 status [项目]                 查看状态和 Git 变更
  .\ws.ps1 diff [项目]                   查看未提交差异
  .\ws.ps1 render [项目] [qmd文件]       渲染 Quarto
  .\ws.ps1 new <项目名>                  创建项目
  .\ws.ps1 tasks                         查看任务队列
  .\ws.ps1 route '<自然语言任务>'         判断工作类型、工具和节省资源模式
  .\ws.ps1 reuse-search '<关键词>'        搜索GitHub现成方案并生成评审清单
  .\ws.ps1 ai-status                    检查Codex的ChatGPT登录状态
  .\ws.ps1 ai-plan <项目> '<需求>'       使用订阅额度生成只读执行方案
  .\ws.ps1 knowledge-index <项目>        建立/更新本地项目知识索引
  .\ws.ps1 knowledge-search <项目> '<词>' 搜索本地项目知识
  .\ws.ps1 model-status                 检查Codex、本地模型和API配置
  .\ws.ps1 adapter-status               检查Office/Zotero/浏览器/OCR适配器
  .\ws.ps1 execute-request <项目> '<需求>' 创建待审批的AI执行请求
  .\ws.ps1 execute-approve <动作ID>      批准具体执行请求
  .\ws.ps1 execute-run <动作ID>          备份后执行已批准请求
  .\ws.ps1 backup-create <项目>          创建并校验项目备份
  .\ws.ps1 local-prompt '<需求>'         调用可用的Ollama本地模型
  .\ws.ps1 textbook-ocr University <课程ID> 将扫描教材转为可追溯Markdown
  .\ws.ps1 cloud-prompt <提供商> '<需求>' 调用已配置并明确选择的付费API
  .\ws.ps1 preferences                   查看已保存习惯
  .\ws.ps1 preference-set <键> <值>      保存明确的长期偏好
  .\ws.ps1 watch-start                   后台监控新下载，只生成计划
  .\ws.ps1 watch-status                  查看下载监控状态
  .\ws.ps1 watch-stop                    安全停止下载监控
  .\ws.ps1 dashboard                    生成静态控制台
  .\ws.ps1 control                      启动动态控制台（Ctrl+C停止）
  .\ws.ps1 control-start                后台启动动态控制台
  .\ws.ps1 control-status               查看控制台状态
  .\ws.ps1 control-stop                 安全停止后台控制台
  .\ws.ps1 workbench-diagnose           自检本机网页、项目读取和接口耗时
  .\ws.ps1 organize-scan [项目] <目录>   扫描并生成复制计划
  .\ws.ps1 organize-apply [项目] <计划>  执行复制计划，保留原件
  .\ws.ps1 organize-undo [项目] <运行ID> 删除未改变的整理副本
  .\ws.ps1 router                       检查模型路由配置（不联网）
'@ }
        open { & code (Join-Path $StationRoot 'workstation.code-workspace'); $ExitCode=$LASTEXITCODE }
        edit {
            if(-not(Test-Path -LiteralPath $ProjectRoot)){throw "项目不存在：$ProjectRoot"}
            if($Target){
                $EditTarget=Join-Path $ProjectRoot $Target
                if(-not(Test-Path -LiteralPath $EditTarget)){throw "文件或目录不存在：$EditTarget"}
            } else {$EditTarget=$ProjectRoot}
            & code --reuse-window $EditTarget
            $ExitCode=$LASTEXITCODE
        }
        'latex-create' {
            if(-not(Test-Path -LiteralPath $ProjectRoot)){throw "项目不存在：$ProjectRoot"}
            if(-not$Target){throw '请提供 LaTeX 文档名'}
            & (Join-Path $StationRoot 'Tools\New-LaTeXProject.ps1') -ProjectRoot $ProjectRoot -Name $Target -Title $Target
            $ExitCode=$LASTEXITCODE
        }
        'latex-build' {
            if(-not(Test-Path -LiteralPath $ProjectRoot)){throw "项目不存在：$ProjectRoot"}
            & (Join-Path $StationRoot 'Tools\Invoke-LaTeXProject.ps1') -ProjectRoot $ProjectRoot -Mode build -Document $Target
            $ExitCode=$LASTEXITCODE
        }
        'latex-clean' {
            if(-not(Test-Path -LiteralPath $ProjectRoot)){throw "项目不存在：$ProjectRoot"}
            & (Join-Path $StationRoot 'Tools\Invoke-LaTeXProject.ps1') -ProjectRoot $ProjectRoot -Mode clean -Document $Target
            $ExitCode=$LASTEXITCODE
        }
        doctor {
            Invoke-Core @('init')
            foreach($name in @('python','quarto','git','xelatex','pdflatex','bibtex','code','codex')) {
                $tool=Get-Command $name -ErrorAction SilentlyContinue
                if($tool){"OK      {0,-10} {1}" -f $name,$tool.Source}else{"MISSING $name";$ExitCode=1}
            }
            'DEFERRED Zotero/Better BibTeX integration'
        }
        state { Invoke-Core @('init') }
        'v4-init' { Invoke-CoreV4 @('init') }
        tools { Invoke-Core @('tools') }
        projects { Invoke-Core @('sync'); Get-ChildItem -LiteralPath (Join-Path $StationRoot 'Projects') -Directory | Select-Object -ExpandProperty Name }
        status {
            if(-not(Test-Path -LiteralPath $ProjectRoot)){throw "项目不存在：$Project"}
            Get-Content -LiteralPath (Join-Path $ProjectRoot '12-status.md') -ErrorAction SilentlyContinue
            if(Test-Path -LiteralPath (Join-Path $ProjectRoot '.git')){Write-Output "`nGit changes:";Invoke-Git @('status','--short');$ExitCode=$GitExitCode}
        }
        diff { Invoke-Git @('diff','--'); $ExitCode=$GitExitCode }
        render {
            if($Target){$source=Join-Path $ProjectRoot $Target;& quarto render $source}
            else{$sources=@(Get-ChildItem -LiteralPath $ProjectRoot -Recurse -Filter '*.qmd' -File|Where-Object{$_.FullName-notmatch'\\99_archive\\'});foreach($source in $sources){& quarto render $source.FullName;if($LASTEXITCODE){break}}}
            $ExitCode=$LASTEXITCODE
        }
        dashboard { Invoke-Core @('dashboard') }
        control { Invoke-Core @('serve') }
        'control-start' { Invoke-Core @('serve-start') }
        'control-status' { Invoke-Core @('serve-status') }
        'control-stop' { Invoke-Core @('serve-stop') }
        'workbench-diagnose' { & python (Join-Path $StationRoot 'Tools\workbench_diagnostics.py') --root $StationRoot --deep; $ExitCode=$LASTEXITCODE }
        new { if($Project-eq'Sandbox'){throw '请提供项目名'};& (Join-Path $StationRoot 'Tools\New-Project.ps1') -Name $Project -StationRoot $StationRoot;$ExitCode=$LASTEXITCODE;if(-not$ExitCode){Invoke-Core @('sync')} }
        router { & python (Join-Path $StationRoot 'Tools\check_router.py') (Join-Path $StationRoot 'Config\model-router.json');$ExitCode=$LASTEXITCODE }
        tasks { Invoke-Core @('task','list') }
        route { Invoke-Core @('route',$Project) }
        'reuse-search' { Invoke-Core @('reuse-search',$Project) }
        'ai-status' { Invoke-Core @('ai-status') }
        'ai-plan' { if(-not$Target){throw '请提供需求'};Invoke-Core @('ai-plan',$Project,$Target) }
        'knowledge-index' { Invoke-CoreV4 @('knowledge-index',$Project) }
        'knowledge-search' { if(-not$Target){throw '请提供搜索词'};Invoke-CoreV4 @('knowledge-search',$Project,$Target) }
        'model-status' { Invoke-CoreV4 @('model-status') }
        'model-route' { Invoke-CoreV4 @('model-route',$Project) }
        'adapter-status' { Invoke-CoreV4 @('adapter-status') }
        'permission-list' { Invoke-CoreV4 @('permission-list') }
        'execute-request' { if(-not$Target){throw '请提供执行需求'};Invoke-CoreV4 @('execute-request',$Project,$Target) }
        'execute-approve' { Invoke-CoreV4 @('execute-approve',$Project) }
        'execute-deny' { Invoke-CoreV4 @('execute-deny',$Project) }
        'execute-run' { Invoke-CoreV4 @('execute-run',$Project) }
        'backup-create' { Invoke-CoreV4 @('backup-create',$Project) }
        'backup-list' { Invoke-CoreV4 @('backup-list') }
        'backup-verify' { Invoke-CoreV4 @('backup-verify',$Project) }
        'restore-request' { Invoke-CoreV4 @('restore-request',$Project) }
        'restore-run' { Invoke-CoreV4 @('restore-run',$Project) }
        'project-create' { if(-not$Target){throw '请提供项目说明'};Invoke-CoreV4 @('project-create',$Project,$Target) }
        'local-prompt' { Invoke-CoreV4 @('local-prompt',$Project) }
        'cloud-prompt' { if(-not$Target){throw '请提供请求内容'};Invoke-CoreV4 @('cloud-prompt',$Project,$Target) }
        ocr { if(-not$Target){throw '请提供输出文本路径'};Invoke-CoreV4 @('ocr',$Project,$Target) }
        'textbook-ocr' {
            if($Project -ne 'University'){throw '教材 OCR 当前仅适用于 University 项目'}
            if(-not$Target){throw '请提供课程 ID'}
            & python (Join-Path $StationRoot 'Tools\textbook_ocr.py') --root $StationRoot $Target --extract-outline
            $ExitCode=$LASTEXITCODE
        }
        preferences { Invoke-Core @('preference','list') }
        'preference-set' { if(-not$Target){throw '请提供偏好值'};Invoke-Core @('preference','set',$Project,$Target) }
        'watch-start' { Invoke-Core @('watch','start') }
        'watch-status' { Invoke-Core @('watch','status') }
        'watch-stop' { Invoke-Core @('watch','stop') }
        'organize-scan' { if(-not$Target){throw '请提供要扫描的具体文件夹'};Invoke-Core @('organize','scan',$Target,'--project',$Project) }
        'organize-apply' { if(-not$Target){throw '请提供计划ID'};Invoke-Core @('organize','apply',$Target) }
        'organize-undo' { if(-not$Target){throw '请提供运行ID'};Invoke-Core @('organize','undo',$Target) }
    }
} catch { Write-Error $_.Exception.Message; $ExitCode=1 }
finally { Write-Event $Action $ExitCode }
exit $ExitCode
