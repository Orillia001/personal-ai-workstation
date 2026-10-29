param(
    [Parameter(Mandatory = $true)]
    [string]$ProjectName
)

$ErrorActionPreference = 'Stop'
if ([string]::IsNullOrWhiteSpace($ProjectName) -or $ProjectName -in @('.', '..') -or $ProjectName -match '[\\/:*?"<>|]') {
    throw '项目名必须是 Projects 下的单个文件夹名称。'
}
$workspaceRoot = Split-Path -Parent $PSScriptRoot
$projectsRoot = Join-Path $workspaceRoot 'Projects'
$projectPath = [System.IO.Path]::GetFullPath((Join-Path $projectsRoot $ProjectName))
if (-not $projectPath.StartsWith(($projectsRoot.TrimEnd('\') + '\'), [System.StringComparison]::OrdinalIgnoreCase)) {
    throw '项目路径超出 Projects 目录。'
}
if (-not (Test-Path -LiteralPath (Join-Path $projectPath '10-README.MD') -PathType Leaf)) {
    throw "不是已登记的工作站项目：$ProjectName"
}
$codex = Get-Command 'codex' -ErrorAction Stop
Set-Location -LiteralPath $projectPath
Write-Host "Codex CLI 已在项目 $ProjectName 中启动。项目规则与工作站权限继续适用。" -ForegroundColor Green
& $codex.Source
