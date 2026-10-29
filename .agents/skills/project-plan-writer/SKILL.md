---
name: project-plan-writer
description: "Create, adapt, or review Chinese project plans and proposals from user materials, requirements, rubrics, or templates. Use for 项目计划书、项目申报书、立项书、商业论证、客户项目提案 and implementation plans; do not use for a simple personal task list or an academic paper with no project decision or delivery plan."
---

# Project Plan Writer

Turn project evidence and requirements into a decision-ready, reviewable, and executable plan. Default to Chinese unless the user or source template requires another language.

## Non-negotiable principles

- Treat the current official template, call text, scoring rubric, contract, or user-supplied outline as authoritative. Preserve its required order, labels, limits, and file format.
- Never invent facts, citations, partners, qualifications, prior results, market data, costs, dates, or commitments. Distinguish sourced facts, user-confirmed facts, calculations, assumptions, recommendations, and unresolved gaps.
- Write for the actual reader and decision: approval, funding, client selection, internal authorization, or execution. A persuasive claim still needs evidence and a feasible delivery path.
- Keep depth proportional to project value, complexity, risk, and submission requirements. Do not inflate a small plan into a generic long report.
- Reuse previous or exemplary plans only for structure and review criteria. Do not carry their facts, claims, budget, citations, or dates into the new plan.
- Drafting does not authorize submission, publication, purchase, contracting, or representation on the user's behalf.

## Workflow

1. **Identify the decision and constraints.** Determine the plan mode, audience, decision sought, governing template or rubric, deadline/version, output language and format, and available evidence. Ask only for missing information that would materially change the plan; otherwise proceed with clearly marked gaps.
2. **Build a requirement-and-evidence map.** Extract mandatory sections, eligibility rules, evaluation dimensions, word/page limits, required attachments, and evidence for each important claim. For detailed evidence handling, read [references/evidence-and-quality.md](references/evidence-and-quality.md).
3. **Select one primary mode.**
   - Funding application, competition entry, research/innovation proposal, or formal project declaration: read [references/application-and-competition.md](references/application-and-competition.md).
   - Investment/authorization business case or client-facing commercial proposal: read [references/business-case-and-proposal.md](references/business-case-and-proposal.md).
   - Internal initiative, software/product delivery, implementation, rollout, or operational project: read [references/delivery-plan.md](references/delivery-plan.md).
   If a supplied template spans modes, keep the template as the outer structure and borrow only the relevant reasoning from the secondary mode.
4. **Construct the logic before polishing prose.** Make the chain explicit: need or opportunity -> objectives -> considered options -> selected approach -> work packages and deliverables -> schedule, resources, and budget -> governance and risks -> outcomes, metrics, and acceptance.
5. **Draft with traceability.** Tie every objective to work, deliverables, measures, owners, timing, and resources. Use tables only when they improve comparison or verification. Prefer concrete verbs, quantities, and conditions over slogans.
6. **Handle gaps honestly.** Use visible markers such as `[待确认：负责人]`, `[待补证据：用户调研来源]`, or `[估算，假设：...]`. Provide a short missing-information list instead of silently filling gaps.
7. **Review before delivery.** Apply the quality gate in [references/evidence-and-quality.md](references/evidence-and-quality.md). When revising an existing plan, return prioritized findings first, then make edits only when requested.

## Deliverables

Honor the user's requested template, path, and format. When no format is specified:

- For an in-chat request, provide a coherent draft plus a concise gap list.
- For a file deliverable in a clear project workspace, create one primary Markdown source named `项目计划书.md`; add a separate `需求与证据追踪表.md` only when the governing requirements are numerous enough to justify it.
- Keep one editable source of truth. Produce DOCX, PDF, Slides, or Google Docs only when requested and supported by the available document tools.

Conclude with the version/date, assumptions, unresolved gaps, and the next review or approval action. Do not claim the plan is submission-ready while material evidence or mandatory fields remain unresolved.
