param(
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{1,49}$')][string]$Name,
    [Parameter(Mandatory=$true)][string]$StationRoot
)
$ErrorActionPreference = 'Stop'
$destination = Join-Path (Join-Path $StationRoot 'Projects') $Name
$template = Join-Path $StationRoot 'Templates\Project'
if (Test-Path -LiteralPath $destination) { throw "目标已存在：$destination" }
if (-not (Test-Path -LiteralPath $template)) { throw "模板不存在：$template" }
Copy-Item -LiteralPath $template -Destination $destination -Recurse
Get-ChildItem -LiteralPath $destination -Recurse -File | ForEach-Object {
    $content = Get-Content -LiteralPath $_.FullName -Raw
    if ($content -match '__PROJECT_NAME__') {
        Set-Content -LiteralPath $_.FullName -Value ($content.Replace('__PROJECT_NAME__', $Name)) -Encoding utf8
    }
}
& git -C $destination init --quiet
Write-Output "已创建项目：$destination"

