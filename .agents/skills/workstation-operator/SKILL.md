---
name: workstation-operator
description: Operate the local Personal AI Workstation when the user asks to create or continue projects, discover tools, manage tasks, inspect status, or organize downloaded and existing files. Use for work under C:\Users\ok\Desktop\workstation; keep destructive or external actions behind confirmation.
---

# Workstation Operator

Use `C:\Users\ok\Desktop\workstation\ws.ps1` and the project control files as the stable interface. Translate the user's outcome into workstation actions; do not require them to choose PowerShell, Python, Quarto, Office, or another tool first.

Classify the request by work type before choosing tools: file organization, research, writing, data, coding, slides, literature, planning, or general. Use `ws.ps1 route '<request>'` when the type or cheapest suitable path is unclear. Prefer deterministic local processing, cached results, and one agent. Add web access, larger models, OCR, external APIs, or parallel agents only when the task requires them or validation of the cheaper path fails.

Read saved preferences with `ws.ps1 preferences`. Apply an explicit durable preference immediately when the user says “以后都这样” or equivalent. Treat one-off choices as local to the task. Promote an inferred habit only after it repeats consistently; do not store prompt bodies, sensitive content, or speculative traits.

Before implementing a nontrivial new capability, search for maintained reusable projects on GitHub and in the relevant official ecosystem. Use `ws.ps1 reuse-search '<concise keywords>'` for the local review record, and use web research when README, releases, documentation, or current compatibility must be inspected. Compare fit, recent maintenance, license, dependency weight, Windows support, and security posture. Prefer a small maintained dependency or native capability when it reduces code and operating cost. Search and inspection are automatic; cloning, installing, or executing third-party code still requires confirmation.

Use `ws.ps1 ai-plan <project> '<request>'` when the user wants a standalone project assessment backed by their ChatGPT-authenticated Codex allowance. This route is ephemeral and read-only. Do not describe it as OpenAI API access and do not use it to modify files.

When the user accepts or rejects a suggested route in the control center, preserve that feedback. Three consistent acceptances for the same work type may become its default tool and resource route. A rejection is evidence against that route but does not invent a replacement preference.

Before changing a project, read its `AGENTS.md`, `10-README.MD`, `11-project.yaml`, and `12-status.md`. Run `ws.ps1 tools` when tool availability matters. Prefer installed local tools and open formats.

For file organization, always scan first. Show the generated plan and counts before applying it unless the user has explicitly authorized applying the specific plan. Organization copies files and preserves originals. Use `organize-undo` only for a run created by this workstation; it removes a copied file only when its hash is unchanged.

The download watcher is plan-only. It baselines files that already exist when first started and creates plans only for new or changed files after their size and modification time remain stable. Starting it does not authorize applying plans.

Never broaden a scan to a drive root or the whole user profile. Require a specific source folder. Do not delete, move, overwrite, upload, publish, install software, incur API charges, commit, or push without authorization for that action.

After execution, verify observable results, update project status when appropriate, and report plan IDs or run IDs needed for review and undo.

Read [references/commands.md](references/commands.md) when command syntax is needed.
