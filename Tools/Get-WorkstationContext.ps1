param(
    [Parameter(Mandatory=$true)][string]$StationRoot,
    [string]$Project,
    [string]$Course,
    [string]$Topic,
    [switch]$Full,
    [switch]$Guide
)

$ErrorActionPreference = 'Stop'

function Get-RequiredFiles([string]$Base, [string[]]$Names) {
    foreach ($name in $Names) {
        $path = Join-Path $Base $name
        [ordered]@{path=$path; exists=(Test-Path -LiteralPath $path -PathType Leaf)}
    }
}

function Get-ScopedDirectory([string]$Parent, [string]$Name) {
    if ([string]::IsNullOrWhiteSpace($Name) -or $Name -in @('.','..') -or $Name -match '[\\/:*?"<>|]') {
        throw '项目或课程必须是直接子目录名称。'
    }
    $path = Join-Path $Parent $Name
    if (-not (Test-Path -LiteralPath $path -PathType Container)) { throw "目录不存在：$path" }
    $item = Get-Item -LiteralPath $path
    # A junction must not redirect project/course discovery outside its parent.
    $target = $item.ResolveLinkTarget($true)
    if ($null -ne $target) { $path = $target.FullName }
    $parentPath = [System.IO.Path]::GetFullPath($Parent).TrimEnd('\','/')
    if (-not $path.StartsWith(($parentPath + [System.IO.Path]::DirectorySeparatorChar), [StringComparison]::OrdinalIgnoreCase)) {
        throw "目录超出预期范围：$Name"
    }
    return $path
}

function Get-NavigationPath([string]$Root, [string]$Relative) {
    if ([string]::IsNullOrWhiteSpace($Relative) -or [IO.Path]::IsPathRooted($Relative)) {
        throw '导航文档必须使用工作站内的相对路径。'
    }
    $path = [IO.Path]::GetFullPath((Join-Path $Root $Relative))
    $prefix = $Root.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    if (-not $path.StartsWith($prefix, [StringComparison]::OrdinalIgnoreCase)) { throw '导航文档超出工作站。' }
    return $path
}

function Get-RelativeRef([string]$Root, [string]$Path) {
    return [IO.Path]::GetRelativePath($Root, $Path).Replace('\','/')
}

function Get-ManualBlocks([string]$Root, $Requests) {
    if (@($Requests).Count -eq 0) { return }
    $path = Join-Path $Root 'USER-MANUAL.md'
    $lines = @(Get-Content -LiteralPath $path)
    $headers = @()
    $fence = $null
    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match '^\s*(`{3,}|~{3,})') {
            $marker = $Matches[1][0]
            if ($null -eq $fence) { $fence = $marker }
            elseif ($marker -eq $fence) { $fence = $null }
            continue
        }
        if ($null -ne $fence) { continue }
        if ($lines[$i] -match '^(#{2,3})\s+(.+?)\s*$') {
            $headers += [PSCustomObject]@{level=$Matches[1].Length; title=$Matches[2]; index=$i}
        }
    }
    foreach ($request in $Requests) {
        $pattern = '^' + [regex]::Escape([string]$request.section) + '\.\s'
        $section = @($headers | Where-Object { $_.level -eq 2 -and $_.title -match $pattern })
        if ($section.Count -ne 1) { throw "手册章节定位失败：$($request.section)" }
        $start = $section[0].index
        $end = $lines.Count
        $next = @($headers | Where-Object { $_.level -eq 2 -and $_.index -gt $start } | Select-Object -First 1)
        if ($next.Count -gt 0) { $end = $next[0].index }
        if ($request.subsection) {
            $subsection = @($headers | Where-Object { $_.level -eq 3 -and $_.index -gt $start -and $_.index -lt $end -and $_.title -ceq $request.subsection })
            if ($subsection.Count -ne 1) { throw "手册小节定位失败：$($request.subsection)" }
            $start = $subsection[0].index
            $next = @($headers | Where-Object { $_.index -gt $start -and $_.index -lt $end } | Select-Object -First 1)
            if ($next.Count -gt 0) { $end = $next[0].index }
        }
        [ordered]@{section=$request.section; subsection=$request.subsection; path=$path; title=$section[0].title; start_line=($start+1); line_count=($end-$start); text=($lines[$start..($end-1)] -join "`n")}
    }
}

try {
    $root = (Resolve-Path -LiteralPath $StationRoot).ProviderPath
    $mapPath = Join-Path $root 'Config/context-map.json'
    $map = Get-Content -LiteralPath $mapPath -Raw | ConvertFrom-Json -AsHashtable
    if ($map.schema_version -ne 1) { throw '导航映射版本无效。' }
    if (-not $Topic) { $Topic = if ($Project) { 'project' } else { 'navigation' } }
    if (-not $map.topics.Contains($Topic)) { throw ('未知主题：' + $Topic + '；可用：' + ($map.topics.Keys -join ', ')) }
    $topicSpec = $map.topics[$Topic]
    if ($topicSpec.project -and -not $Project -and -not $Guide) { $Project = $topicSpec.project }
    $manualBlocks = @(Get-ManualBlocks $root $topicSpec.manual)
    if ($Guide) {
        if ($Full -or $Course -or $Project) { throw 'Guide 只读取主题手册，请仅传 Topic 与 Guide。' }
        if ($manualBlocks.Count -eq 0) { throw '该主题无手册章节，请按 context 的 read_before_action 读取。' }
        $manualBlocks | ForEach-Object { $_.text; '' }
        exit 0
    }
    if ($Topic -eq 'teaching' -and -not $Full) {
        if ($Project -ne 'University') { throw '教学主体当前归属University。' }
        $teachingArgs = @('--root', $root, 'progress')
        if ($Course) { $teachingArgs += $Course }
        $teachingOutput = & (Join-Path $root 'Runtime/Python/python.exe') -X utf8 -B (Join-Path $root 'Tools/teaching_core.py') @teachingArgs
        if ($LASTEXITCODE -ne 0) { throw ($teachingOutput -join '') }
        $teachingProgress = ($teachingOutput -join '') | ConvertFrom-Json
        $teachingReady = Test-Path -LiteralPath (Join-Path $root 'Config/teaching-guide.md') -PathType Leaf
        [ordered]@{schema_version=2;ready=$teachingReady;station_root=$root;paths_relative_to='station_root';read_only=$true;topic='teaching';project=[ordered]@{id='University'};progress=$teachingProgress;read_before_action=@('Config/teaching-guide.md');warnings=@()} | ConvertTo-Json -Depth 12 -Compress
        if ($teachingReady) { exit 0 } else { exit 1 }
    }
    $warnings = [System.Collections.Generic.List[string]]::new()
    $rootFiles = @(Get-RequiredFiles $root @('AGENTS.md','README.md','USER-MANUAL.md','ws.ps1','Config/context-map.json'))
    $missingRoot = @($rootFiles | Where-Object { -not $_.exists })
    if ($missingRoot.Count -gt 0) { throw ('工作站根目录缺少必要文件：' + ($missingRoot.path -join ', ')) }
    $projectsRoot = Join-Path $root 'Projects'
    if (-not (Test-Path -LiteralPath $projectsRoot -PathType Container)) { throw '工作站缺少 Projects 目录。' }
    $projectNames = @(Get-ChildItem -LiteralPath $projectsRoot -Directory | Where-Object { -not $_.Name.StartsWith('.') } | Sort-Object Name | Select-Object -ExpandProperty Name)
    $projectControls = @('AGENTS.md','10-README.MD','11-project.yaml','12-status.md')
    $projects = @(foreach ($name in $projectNames) {
        $projectPath = Get-ScopedDirectory $projectsRoot $name
        $files = @(Get-RequiredFiles $projectPath $projectControls)
        $missing = @($files | Where-Object { -not $_.exists })
        if ($missing.Count -gt 0) { $warnings.Add("项目 $name 的入口文件不完整。") }
        [ordered]@{id=$name; path=$projectPath; ready=($missing.Count -eq 0); control_files=$files}
    })
    $required = @(@($map.default_read) + @($topicSpec.read) | ForEach-Object { Get-NavigationPath $root $_ })
    $selectedProject = $null
    $selectedCourse = $null
    $courses = @()
    if ($Course -and -not $Project) { throw '指定课程前必须指定项目。' }
    if ($Project) {
        $projectPath = Get-ScopedDirectory $projectsRoot $Project
        $selectedProject = @($projects | Where-Object { $_.id -eq $Project })[0]
        $required += @($selectedProject.control_files.path)
        if ($Project -eq 'University') {
            $educationFiles = @(Get-RequiredFiles $root @('Projects/University/EDUCATION.md'))
            $required += @($educationFiles.path)
            foreach ($file in $educationFiles) { if (-not $file.exists) { $warnings.Add("缺少教育规则：$($file.path)") } }
            $coursesRoot = Join-Path $projectPath 'courses'
            $courses = @(Get-ChildItem -LiteralPath $coursesRoot -Directory | Where-Object { -not $_.Name.StartsWith('.') } | Sort-Object Name | ForEach-Object { $_.Name })
        } elseif ($Course) { throw '课程参数当前只适用于 University 项目。' }
        if ($Course) {
            $coursePath = Get-ScopedDirectory $coursesRoot $Course
            $courseFiles = @(Get-RequiredFiles $coursePath @('course.yaml','RESOURCES.md','NOTES.md'))
            $required += @($courseFiles.path)
            foreach ($file in $courseFiles) { if (-not $file.exists) { $warnings.Add("缺少课程文件：$($file.path)") } }
            foreach ($optional in @('AGENTS.md','MISSION.md')) {
                $optionalPath = Join-Path $coursePath $optional
                if (Test-Path -LiteralPath $optionalPath -PathType Leaf) { $required += $optionalPath }
            }
            $sourcesRoot = Join-Path $coursePath '01_sources'
            $sources = @(if (Test-Path -LiteralPath $sourcesRoot -PathType Container) { Get-ChildItem -LiteralPath $sourcesRoot -File | Sort-Object Name | Select-Object -ExpandProperty FullName })
            $manifestPath = Join-Path $coursePath 'reference/textbook/manifest.json'
            $ocr = $null
            if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
                $manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
                $ocr = [ordered]@{manifest=$manifestPath; reported_pages=$manifest.available_pages; source_pages=$manifest.source_pages; generated_at=$manifest.generated_at; quality_verified=$false}
            }
            $selectedCourse = [ordered]@{id=$Course; path=$coursePath; control_files=$courseFiles; sources=$sources; ocr=$ocr}
        }
    }
    $contextReady = @($required | Where-Object { -not (Test-Path -LiteralPath $_ -PathType Leaf) }).Count -eq 0
    $report = [ordered]@{
        schema_version=1
        ready=$contextReady
        station_root=$root
        invocation_directory=(Get-Location).ProviderPath
        read_only=$true
        permission_scope='由调用方沙箱决定；路径定位不授予额外权限。'
        layers=[ordered]@{entry=(Join-Path $root 'ws.ps1'); rules=(Join-Path $root 'AGENTS.md'); configuration=(Join-Path $root 'Config'); projects=$projectsRoot; tools=(Join-Path $root 'Tools'); state=(Join-Path $root 'State'); logs=(Join-Path $root 'Logs'); backups=(Join-Path $root 'Backups')}
        projects=$projects
        selected_project=$selectedProject
        courses=$courses
        selected_course=$selectedCourse
        read_before_action=@($required | Select-Object -Unique)
        warnings=@($warnings.ToArray())
    }
    if ($Full) {
        $report.topic = $Topic
        $report.manual = @($manualBlocks | ForEach-Object { [ordered]@{section=$_.section; subsection=$_.subsection; path=$_.path; start_line=$_.start_line; line_count=$_.line_count} })
        $report | ConvertTo-Json -Depth 10
    } else {
        $compact = [ordered]@{schema_version=2; ready=$contextReady; station_root=$root; paths_relative_to='station_root'; read_only=$true; topic=$Topic}
        if ((Get-Location).ProviderPath -ne $root) { $compact.invocation_directory = (Get-Location).ProviderPath }
        if ($Project) { $compact.project = [ordered]@{id=$Project; path=(Get-RelativeRef $root $projectPath)} }
        else { $compact.projects = @($projectNames); $compact.available_topics = @($map.topics.Keys) }
        if ($courses.Count -gt 0 -and -not $Course) { $compact.courses = $courses }
        if ($selectedCourse) {
            $compact.course = [ordered]@{id=$Course; path=(Get-RelativeRef $root $selectedCourse.path); sources=@($selectedCourse.sources | ForEach-Object { Get-RelativeRef $root $_ })}
            if ($selectedCourse.ocr) { $compact.course.ocr = [ordered]@{reported_pages=$selectedCourse.ocr.reported_pages; source_pages=$selectedCourse.ocr.source_pages; quality_verified=$false} }
        }
        $compact.read_before_action = @($required | Select-Object -Unique | ForEach-Object { Get-RelativeRef $root $_ })
        if ($manualBlocks.Count -gt 0) { $compact.manual = @($manualBlocks | ForEach-Object { [ordered]@{path='USER-MANUAL.md'; section=$_.section; subsection=$_.subsection; start_line=$_.start_line; line_count=$_.line_count} }) }
        $compact.warnings = @($warnings.ToArray())
        $compact | ConvertTo-Json -Depth 8 -Compress
    }
    if ($contextReady) { exit 0 } else { exit 1 }
} catch {
    [ordered]@{schema_version=1; read_only=$true; error=$_.Exception.Message} | ConvertTo-Json
    exit 1
}
