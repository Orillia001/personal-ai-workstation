param(
    [switch]$NoRestore,
    [switch]$Background
)

$ErrorActionPreference = 'Stop'
$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..')).Path
$workspaceRoot = (Resolve-Path (Join-Path $projectRoot '..\..')).Path
$dotnet = Join-Path $workspaceRoot 'Tools\dotnet-sdk\dotnet.exe'
$projectFile = Join-Path $PSScriptRoot 'WorkstationDesktop.csproj'
$outputProfile = if ($Background) { 'background' } else { 'responsive' }
$outputDirectory = Join-Path $projectRoot "09_output\$outputProfile"

if (-not (Test-Path -LiteralPath $dotnet -PathType Leaf)) {
    throw "工作区本地 .NET SDK 不存在：$dotnet"
}

New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
Push-Location $PSScriptRoot
try {
    $arguments = @(
        'publish', $projectFile,
        '--configuration', 'Release',
        '--runtime', 'win-x64',
        '--self-contained', 'true',
        '--output', $outputDirectory,
        '--source', 'https://pkgs.dev.azure.com/dnceng/public/_packaging/dotnet-public/nuget/v3/index.json',
        '-p:PublishSingleFile=true',
        '-p:IncludeNativeLibrariesForSelfExtract=true',
        '-p:EnableCompressionInSingleFile=true',
        '-p:DebugType=None',
        '-p:DebugSymbols=false',
        '-p:RestoreIgnoreFailedSources=true'
    )
    if ($NoRestore) { $arguments += '--no-restore' }

    & $dotnet @arguments
    if ($LASTEXITCODE -ne 0) { throw ".NET 发布失败，退出码：$LASTEXITCODE" }
}
finally {
    Pop-Location
}

$exe = Join-Path $outputDirectory 'Workstation.exe'
if (-not (Test-Path -LiteralPath $exe -PathType Leaf)) {
    throw "发布命令成功，但没有找到目标程序：$exe"
}
$artifact = Get-Item -LiteralPath $exe
Write-Output "已生成：$($artifact.FullName)"
Write-Output "文件大小：$([Math]::Round($artifact.Length / 1MB, 1)) MB"
if ($Background) { Write-Output '后台模式：Workstation.exe --tray' }
