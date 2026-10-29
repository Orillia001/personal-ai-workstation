param([Parameter(Mandatory=$true)][string]$StationRoot)
$ErrorActionPreference = 'Stop'
$projectRoot = Join-Path $StationRoot 'Projects\Guochuang2026-BizPlan'
$source = Join-Path $projectRoot '09_output\guochuang-business-plan-final.tex'
$destination = Join-Path $projectRoot '06_manuscript\latex\guochuang-business-plan'
if (-not (Test-Path -LiteralPath $source)) { throw "源文件不存在：$source" }
if (Test-Path -LiteralPath $destination) { throw "目标目录已存在：$destination" }

New-Item -ItemType Directory -Force -Path $destination,$destination\content,$destination\figures,$destination\assets,$destination\references,$destination\build,$destination\dist | Out-Null
$lines = @(Get-Content -LiteralPath $source)
$begin = [Array]::IndexOf($lines, '\begin{document}')
$end = [Array]::IndexOf($lines, '\end{document}')
$toc = -1
for($i=$begin; $i -lt $end; $i++){ if($lines[$i] -eq '\tableofcontents'){$toc=$i;break} }
$sections = @()
for($i=$toc+1; $i -lt $end; $i++){ if($lines[$i] -match '^\\section\{'){ $sections += $i } }
if($begin -lt 0 -or $end -lt 0 -or $toc -lt 0 -or $sections.Count -eq 0){ throw '无法识别 LaTeX 文档结构' }

$mainLines = @($lines[0..($begin-1)] | ForEach-Object { $_ -replace '\\cover\{guochuang-cover-art\.pdf\}', '\cover{assets/guochuang-cover-art.pdf}' })
$mainLines += $lines[$begin..$toc]
$mainLines += '\input{content/00-frontmatter.tex}'
for($n=0; $n -lt $sections.Count; $n++){ $mainLines += ('\input{{content/{0:D2}-section.tex}}' -f ($n+1)) }
$mainLines += '\end{document}'
Set-Content -LiteralPath (Join-Path $destination 'main.tex') -Value ($mainLines -join "`r`n") -Encoding utf8

$frontEnd = $sections[0]-1
Set-Content -LiteralPath (Join-Path $destination 'content\00-frontmatter.tex') -Value (($lines[($toc+1)..$frontEnd]) -join "`r`n") -Encoding utf8
for($n=0; $n -lt $sections.Count; $n++){
    $start = $sections[$n]
    $stop = if($n+1 -lt $sections.Count){$sections[$n+1]-1}else{$end-1}
    Set-Content -LiteralPath (Join-Path $destination ('content\{0:D2}-section.tex' -f ($n+1))) -Value (($lines[$start..$stop]) -join "`r`n") -Encoding utf8
}

$assetSource = Join-Path $projectRoot '09_output\assets'
if(Test-Path -LiteralPath $assetSource){ Get-ChildItem -LiteralPath $assetSource -File | Copy-Item -Destination (Join-Path $destination 'assets') }
Copy-Item -LiteralPath (Join-Path $projectRoot '09_output\guochuang-cover-art.pdf') -Destination (Join-Path $destination 'assets\guochuang-cover-art.pdf')
Copy-Item -LiteralPath (Join-Path $projectRoot '09_output\guochuang-cover-art.tex') -Destination (Join-Path $destination 'figures\guochuang-cover-art.tex')
Copy-Item -LiteralPath (Join-Path $projectRoot '09_output\guochuang-business-plan-final.pdf') -Destination (Join-Path $destination 'dist\guochuang-business-plan.pdf')
Set-Content -LiteralPath (Join-Path $destination 'build\.gitkeep') -Value '' -Encoding utf8
Set-Content -LiteralPath (Join-Path $destination 'references\README.md') -Value "将 BibTeX 文献库放在此目录。`r`n" -Encoding utf8
Set-Content -LiteralPath (Join-Path $destination '.gitignore') -Value "build/*`r`n!build/.gitkeep`r`n" -Encoding utf8
$readme = @(
    '# Guochuang Business Plan LaTeX', '', '已从现有最终版复制并拆分。原 `09_output` 文件保持不变。', '',
    '- `main.tex`：编译入口', '- `content/`：前置内容与 15 个章节', '- `figures/`：图形源',
    '- `assets/`：封面和图片资源', '- `references/`：文献资源', '- `build/`：编译辅助文件', '- `dist/`：交付 PDF', '',
    '编译：`.\ws.ps1 latex-build Guochuang2026-BizPlan guochuang-business-plan`'
) -join "`r`n"
Set-Content -LiteralPath (Join-Path $destination 'README.md') -Value $readme -Encoding utf8
Write-Output "已整理 LaTeX 项目：$destination"
