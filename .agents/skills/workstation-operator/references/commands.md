# Workstation commands

Run from `C:\Users\ok\Desktop\workstation`.

```powershell
.\ws.ps1 state
.\ws.ps1 tools
.\ws.ps1 projects
.\ws.ps1 tasks
.\ws.ps1 route '整理下载的研究资料'
.\ws.ps1 reuse-search 'python pdf table extraction'
.\ws.ps1 ai-status
.\ws.ps1 ai-plan Sandbox '检查项目并给出下一步方案'
.\ws.ps1 knowledge-index Sandbox
.\ws.ps1 knowledge-search Sandbox '关键词'
.\ws.ps1 model-status
.\ws.ps1 adapter-status
.\ws.ps1 execute-request Sandbox '具体任务'
.\ws.ps1 execute-approve ACT_ID
.\ws.ps1 execute-run ACT_ID
.\ws.ps1 backup-create Sandbox
.\ws.ps1 preferences
.\ws.ps1 preference-set resource_policy local-first
.\ws.ps1 watch-start
.\ws.ps1 watch-status
.\ws.ps1 watch-stop
.\ws.ps1 dashboard
.\ws.ps1 control
```

Safe file organization is two-stage:

```powershell
.\ws.ps1 organize-scan ProjectName C:\specific\source\folder
.\ws.ps1 organize-apply ProjectName PLAN_ID
.\ws.ps1 organize-undo ProjectName RUN_ID
```

`organize-scan` reads and hashes files and writes a JSON plan. `organize-apply` creates verified copies without overwriting. `organize-undo` removes only unchanged copies from that run; originals remain untouched.

`reuse-search` uses GitHub's public repository search API and stores a scored review in `State\reuse`. It never clones, installs, or runs a candidate.

`ai-plan` uses the Codex CLI authenticated with ChatGPT. It runs ephemerally in a read-only sandbox and writes only the final plan to `State\ai`; it does not modify the selected project.
