"""Read-only projection of the shared teaching graphs for the workbench."""
from pathlib import Path
from teaching_core import TeachingCore, KINDS


def network_data(root: Path, course: str | None = None) -> dict:
    core = TeachingCore(root)
    if course is None:
        return {"courses": [{"id": key, "name": profile["name"]}
                            for key, profile in core.config["subjects"].items()]}
    profile = core.subject(course)
    graph = core.graph(course)
    return {
        "course": course,
        "name": profile["name"],
        "nodes": [{"id": node["id"], "title": node["title"],
                   "kind": node.get("kind", "topic"), "body": node.get("body", ""),
                   "pages": sorted({s["pdf_page"] for s in node.get("sources", [])
                                    if isinstance(s.get("pdf_page"), int)})}
                  for node in graph["nodes"]],
        "edges": graph["edges"],
        "relations": KINDS,
        "notice": "知识结构随学习细化；教材公式、图表和语义仍需校验。浏览网图不计为掌握证据。",
    }
