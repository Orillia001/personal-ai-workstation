param(
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [ValidateSet('build','clean')][string]$Mode = 'build',
    [string]$Document
)
$ErrorActionPreference = 'Stop'
$latexRoot = (Join-Path $ProjectRoot '06_manuscript\latex')
if (-not (Test-Path -LiteralPath $latexRoot)) { throw "项目没有 LaTeX 目录：$latexRoot" }

if ($Document) {
    $docRoot = Join-Path $latexRoot $Document
    if ((Split-Path $Document -Leaf) -match '\.tex$') { $docRoot = Split-Path (Join-Path $latexRoot $Document) -Parent }
} else {
    $candidates = @(Get-ChildItem -LiteralPath $latexRoot -Directory | Where-Object { Test-Path -LiteralPath (Join-Path $_.FullName 'main.tex') })
    if ($candidates.Count -ne 1) { throw "请指定 LaTeX 文档目录；可选数量：$($candidates.Count)" }
    $docRoot = $candidates[0].FullName
}
$docRoot = [IO.Path]::GetFullPath($docRoot)
$latexRootFull = [IO.Path]::GetFullPath($latexRoot)
if (-not ($docRoot.StartsWith($latexRootFull + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase))) { throw 'LaTeX 文档路径必须位于项目的 06_manuscript\latex 目录内' }
$main = Join-Path $docRoot 'main.tex'
if (-not (Test-Path -LiteralPath $main)) { throw "主文件不存在：$main" }
$build = Join-Path $docRoot 'build'
$dist = Join-Path $docRoot 'dist'
New-Item -ItemType Directory -Force -Path $build,$dist | Out-Null
$latexmk = (Get-Command latexmk -ErrorAction Stop).Source
Push-Location $docRoot
try {
    if ($Mode -eq 'clean') {
        & $latexmk -C -outdir=build main.tex
        if ($LASTEXITCODE) { throw "LaTeX 清理失败，退出码：$LASTEXITCODE" }
        Write-Output (ConvertTo-Json @{status='cleaned';document=$docRoot;build=$build} -Compress)
    } else {
        & $latexmk -xelatex -file-line-error -interaction=nonstopmode -synctex=1 -outdir=build main.tex
        if ($LASTEXITCODE) { throw "LaTeX 编译失败，退出码：$LASTEXITCODE" }
        $pdf = Join-Path $build 'main.pdf'
        if (-not (Test-Path -LiteralPath $pdf)) { throw "编译完成但未找到 PDF：$pdf" }
        $delivery = Join-Path $dist ((Split-Path $docRoot -Leaf) + '.pdf')
        Copy-Item -LiteralPath $pdf -Destination $delivery -Force
        $hash = (Get-FileHash -LiteralPath $delivery -Algorithm SHA256).Hash
        Write-Output (ConvertTo-Json @{status='built';document=$docRoot;pdf=$delivery;sha256=$hash} -Compress)
    }
} finally { Pop-Location }
