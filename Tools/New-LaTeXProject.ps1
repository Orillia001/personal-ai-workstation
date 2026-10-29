param(
    [Parameter(Mandatory=$true)][string]$ProjectRoot,
    [Parameter(Mandatory=$true)][ValidatePattern('^[A-Za-z0-9][A-Za-z0-9_-]{1,59}$')][string]$Name,
    [string]$Title = 'New LaTeX Document'
)
$ErrorActionPreference = 'Stop'
$latexRoot = Join-Path $ProjectRoot '06_manuscript\latex'
$destination = Join-Path $latexRoot $Name
if (Test-Path -LiteralPath $destination) { throw "LaTeX 文档目录已存在：$destination" }
New-Item -ItemType Directory -Force -Path $destination,$destination\content,$destination\figures,$destination\assets,$destination\references,$destination\build,$destination\dist | Out-Null

$main = @"
% !TeX program = xelatex
% Build with: .\ws.ps1 latex-build <项目> $Name
\documentclass[lang=cn,11pt,scheme=chinese,color=blue,oneside]{elegantbook}
\usepackage{graphicx}
\usepackage{booktabs}
\usepackage{longtable}
\title{$Title}
\author{}
\date{\today}
\begin{document}
\maketitle
\tableofcontents
\input{content/01-introduction.tex}
\end{document}
"@
$intro = @"
\section{Introduction}

Start writing here.
"@
$readme = @(
    "# $Name", "", "LaTeX 文档项目。源文件和生成文件分开保存：", "",
    '- `main.tex`：唯一编译入口', '- `content/`：章节正文', '- `figures/`：TikZ/PGFPlots 图形源',
    '- `assets/`：图片、封面和其他引用资源', '- `references/`：BibTeX 文献库',
    '- `build/`：编译辅助文件，不作为交付物', '- `dist/`：最终 PDF', "",
    '在工作站根目录执行：', "", '```powershell', ".\ws.ps1 latex-build <项目> $Name", ".\ws.ps1 latex-clean <项目> $Name", '```'
) -join "`r`n"
$ignore = "build/*`r`n!build/.gitkeep`r`n"
Set-Content -LiteralPath (Join-Path $destination 'main.tex') -Value $main -Encoding utf8
Set-Content -LiteralPath (Join-Path $destination 'content\01-introduction.tex') -Value $intro -Encoding utf8
Set-Content -LiteralPath (Join-Path $destination 'README.md') -Value $readme -Encoding utf8
Set-Content -LiteralPath (Join-Path $destination '.gitignore') -Value $ignore -Encoding utf8
Set-Content -LiteralPath (Join-Path $destination 'build\.gitkeep') -Value '' -Encoding utf8
Set-Content -LiteralPath (Join-Path $destination 'references\references.bib') -Value "% Add BibTeX entries here.`r`n" -Encoding utf8
Write-Output "已创建 LaTeX 项目：$destination"
