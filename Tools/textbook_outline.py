from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def ollama_model() -> str:
    with urlopen(Request("http://127.0.0.1:11434/api/tags"), timeout=5) as response:
        models = json.load(response).get("models", [])
    if not models:
        raise RuntimeError("Ollama 没有可用本地模型")
    return models[0]["name"]


def ask_json(model: str, prompt: str) -> list[dict]:
    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json",
        "options": {"temperature": 0},
    }).encode()
    request = Request(
        "http://127.0.0.1:11434/api/generate",
        data=body,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=900) as response:
        raw = json.load(response).get("response", "")
    parsed = json.loads(raw)
    items = parsed.get("knowledge_points", parsed if isinstance(parsed, list) else [])
    return items if isinstance(items, list) else []


def page_number(path: Path) -> int:
    return int(re.search(r"(\d+)$", path.stem).group(1))


def extract(course: Path, chunk_pages: int = 20) -> dict:
    textbook = course / "reference" / "textbook"
    manifest_path = textbook / "manifest.json"
    if not manifest_path.is_file():
        raise RuntimeError("缺少 OCR manifest.json；请先完成教材 OCR")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest["available_pages"] != manifest["source_pages"] or manifest.get("failures"):
        raise RuntimeError("教材 OCR 尚未完整成功，暂不生成知识点大纲")

    paths = sorted((textbook / "pages").glob("page-*.md"))
    model = ollama_model()
    points: list[dict] = []
    failures: list[dict] = []
    for start in range(0, len(paths), chunk_pages):
        group = paths[start:start + chunk_pages]
        first, last = page_number(group[0]), page_number(group[-1])
        source = "\n\n".join(path.read_text(encoding="utf-8", errors="replace") for path in group)
        prompt = (
            "你是大学教材知识结构提取器。以下是带 source-page 标记的中文 OCR 文本。"
            "只提取文本明确支持的知识点，不补充外部知识，不纠正疑似 OCR 错误。"
            "每个知识点应当小到能用一节短课教学，最多返回 8 个。"
            "仅输出 JSON 对象，格式为 {\"knowledge_points\":[{\"title\":\"...\","
            "\"source_pages\":[1,2],\"learning_objective\":\"学习者能够...\","
            "\"uncertainties\":[\"疑似错误或需要核对之处\"]}]}。"
            "source_pages 只能使用本段出现的页码；若本段没有可教学正文则返回空数组。\n\n"
            + source[:28000]
        )
        try:
            for item in ask_json(model, prompt):
                title = str(item.get("title", "")).strip()
                pages = sorted({int(p) for p in item.get("source_pages", []) if first <= int(p) <= last})
                objective = str(item.get("learning_objective", "")).strip()
                if title and pages and objective:
                    points.append({
                        "id": f"KP-{len(points) + 1:04d}",
                        "title": title,
                        "source_pages": pages,
                        "learning_objective": objective,
                        "uncertainties": [str(x) for x in item.get("uncertainties", [])],
                        "validation": "pending",
                    })
        except Exception as exc:
            failures.append({"pages": [first, last], "error": str(exc)})

    generated = datetime.now(timezone.utc).isoformat()
    payload = {
        "schema": 1,
        "course": course.name,
        "source_sha256": manifest["source_sha256"],
        "model": model,
        "generated_at": generated,
        "status": "draft-requires-human-validation",
        "knowledge_points": points,
        "failures": failures,
    }
    json_path = textbook / "knowledge-outline.draft.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "# 教材知识点大纲（待校验）", "",
        "> 本文件由本地模型从 OCR 文本提取。只有对照原教材核验后，知识点才能进入教学。", "",
    ]
    for point in points:
        pages = "、".join(str(p) for p in point["source_pages"])
        lines.extend([
            f"## {point['id']} {point['title']}", "",
            f"- 学习目标：{point['learning_objective']}",
            f"- 来源页：{pages}",
            f"- 校验状态：待校验", "",
        ])
    if failures:
        lines.extend(["## 提取失败分段", ""] + [f"- PDF 页 {x['pages'][0]}–{x['pages'][1]}：{x['error']}" for x in failures] + [""])
    md_path = textbook / "knowledge-outline.draft.md"
    md_path.write_text("\n".join(lines), encoding="utf-8")

    queue = {
        "schema": 1,
        "course": course.name,
        "generated_at": generated,
        "rule": "校验通过后进入短课；短课完成不等于掌握，只有检索、解题或迁移证据写入 learning-records。",
        "items": [{"knowledge_point": p["id"], "status": "pending_validation"} for p in points],
    }
    queue_path = course / "teaching-queue.json"
    queue_path.write_text(json.dumps(queue, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"course": course.name, "points": len(points), "failures": failures,
            "outline": str(md_path), "queue": str(queue_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="从完整教材 OCR 中提取待校验知识点和教学队列")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("course")
    parser.add_argument("--chunk-pages", type=int, default=20)
    args = parser.parse_args()
    course = (args.root.resolve() / "Projects" / "University" / "courses" / args.course).resolve()
    courses = (args.root.resolve() / "Projects" / "University" / "courses").resolve()
    if course.parent != courses or not course.is_dir():
        raise ValueError(f"课程不存在：{args.course}")
    print(json.dumps(extract(course, args.chunk_pages), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
