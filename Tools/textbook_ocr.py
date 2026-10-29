from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def executable(name: str, fallback: Path | None = None) -> str:
    found = shutil.which(name)
    if found:
        return found
    if fallback and fallback.is_file():
        return str(fallback)
    raise RuntimeError(f"缺少必需工具：{name}")


def page_count(pdfinfo: str, source: Path) -> int:
    result = subprocess.run(
        [pdfinfo, str(source)], capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=60,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "无法读取 PDF 信息")
    match = re.search(r"^Pages:\s+(\d+)", result.stdout, re.MULTILINE)
    if not match:
        raise RuntimeError("无法确定 PDF 页数")
    return int(match.group(1))


def parse_pages(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    pages: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            start, end = (int(value) for value in part.split("-", 1))
            pages.update(range(start, end + 1))
        else:
            pages.add(int(part))
    invalid = [page for page in pages if page < 1 or page > total]
    if invalid:
        raise ValueError(f"页码超出范围：{invalid}")
    return sorted(pages)


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
    cleaned: list[str] = []
    blanks = 0
    for line in lines:
        if line:
            blanks = 0
            cleaned.append(line)
        elif blanks == 0:
            blanks = 1
            cleaned.append("")
    return "\n".join(cleaned).strip()


def refine_local(text: str) -> tuple[str, str]:
    with urlopen(Request("http://127.0.0.1:11434/api/tags"), timeout=3) as response:
        models = json.load(response).get("models", [])
    if not models:
        raise RuntimeError("Ollama 没有可用本地模型")
    model = models[0]["name"]
    prompt = (
        "你是教材 OCR 排版器。只修复明显的断行、空格和段落边界；可把明确的章节标题改成 Markdown 标题。"
        "不得总结、补写、纠正专业事实、猜测公式或删除不确定文字。遇到公式、表格或乱码，原样保留并在其后添加 [待校验]。"
        "只输出整理后的正文，不要解释。\n\n" + text[:7000]
    )
    body = json.dumps({"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0}}).encode()
    request = Request("http://127.0.0.1:11434/api/generate", data=body, headers={"Content-Type": "application/json"})
    with urlopen(request, timeout=600) as response:
        result = json.load(response)
    return result.get("response", "").strip() or text, model


def find_course(root: Path, course_id: str) -> Path:
    courses = (root / "Projects" / "University" / "courses").resolve()
    course = (courses / course_id).resolve()
    if course.parent != courses or not course.is_dir():
        raise ValueError(f"课程不存在：{course_id}")
    return course


def convert(root: Path, course_id: str, pages_spec: str | None, use_model: bool, extract_outline: bool) -> dict:
    course = find_course(root, course_id)
    sources = sorted((course / "01_sources").glob("*.pdf"))
    if len(sources) != 1:
        raise ValueError(f"课程必须恰好有一本 PDF 教材；当前找到 {len(sources)} 本")
    source = sources[0]
    pdftoppm = executable("pdftoppm")
    pdfinfo = executable("pdfinfo")
    tesseract = executable("tesseract", Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Tesseract-OCR" / "tesseract.exe")
    tessdata = root / "Assets" / "tessdata"
    languages = "chi_sim+eng" if (tessdata / "chi_sim.traineddata").is_file() else "eng"
    total = page_count(pdfinfo, source)
    pages = parse_pages(pages_spec, total)
    output = course / "reference" / "textbook"
    page_dir = output / "pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    failures: list[dict] = []
    processed = cached = 0
    model_name = None

    for page in pages:
        page_file = page_dir / f"page-{page:04d}.md"
        if page_file.is_file() and page_file.stat().st_size > 40:
            cached += 1
            continue
        try:
            with tempfile.TemporaryDirectory(prefix="textbook-ocr-") as temp:
                image_base = Path(temp) / "page"
                render = subprocess.run(
                    [pdftoppm, "-f", str(page), "-l", str(page), "-r", "300", "-png", "-singlefile", str(source), str(image_base)],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                )
                if render.returncode:
                    raise RuntimeError(render.stderr.strip()[-1000:])
                ocr_base = Path(temp) / "ocr"
                ocr = subprocess.run(
                    [tesseract, str(image_base.with_suffix(".png")), str(ocr_base), "--tessdata-dir", str(tessdata), "-l", languages, "--psm", "3"],
                    capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
                )
                if ocr.returncode:
                    raise RuntimeError(ocr.stderr.strip()[-1000:])
                text = normalize_text(ocr_base.with_suffix(".txt").read_text(encoding="utf-8", errors="replace"))
                if use_model and text:
                    text, model_name = refine_local(text)
                page_file.write_text(f"<!-- source-page: {page} -->\n\n{text}\n", encoding="utf-8")
                processed += 1
        except Exception as exc:
            failures.append({"page": page, "error": str(exc)})

    available = sorted(page_dir.glob("page-*.md"))
    combined = "\n\n---\n\n".join(path.read_text(encoding="utf-8") for path in available)
    header = (
        f"# {source.stem}\n\n"
        f"> OCR 派生文本；来源：`01_sources/{source.name}`。请以原教材页面为准。\n\n"
    )
    book = output / "textbook.md"
    book.write_text(header + combined + "\n", encoding="utf-8")
    manifest = {
        "schema": 1, "course": course_id, "source": f"01_sources/{source.name}",
        "source_sha256": sha256(source), "source_pages": total, "available_pages": len(available),
        "requested_pages": pages, "languages": languages, "dpi": 300,
        "local_model": model_name, "generated_at": datetime.now(timezone.utc).isoformat(),
        "failures": failures, "output_sha256": sha256(book),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report = (
        "# 教材 OCR 报告\n\n"
        f"- 来源页数：{total}\n- 已生成页：{len(available)}\n- 本次新识别：{processed}\n"
        f"- 命中缓存：{cached}\n- 失败页：{len(failures)}\n- 语言：{languages}\n"
        f"- 本地模型：{model_name or '未启用'}\n\n"
        "公式、表格、图注和低清晰度页面必须对照原教材抽样校验；阅读覆盖不构成掌握证据。\n"
    )
    (output / "ocr-report.md").write_text(report, encoding="utf-8")
    result = {"course": course_id, "source": str(source), "total_pages": total, "available_pages": len(available), "processed": processed, "cached": cached, "failures": failures, "output": str(book), "manifest": str(output / "manifest.json")}
    if extract_outline and len(available) == total and not failures:
        outline = subprocess.run(
            [executable("python"), str(root / "Tools" / "textbook_outline.py"), "--root", str(root), course_id],
            capture_output=True, text=True, timeout=7200,
        )
        if outline.returncode:
            result["outline_error"] = outline.stderr.strip() or outline.stdout.strip()
        else:
            result["outline"] = json.loads(outline.stdout)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="将 University 课程扫描教材转换为可追溯 Markdown")
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("course")
    parser.add_argument("--pages", help="例如 1-5,8")
    parser.add_argument("--local-model", action="store_true", help="使用 Ollama 保守整理 OCR 文本")
    parser.add_argument("--extract-outline", action="store_true", help="全书识别成功后生成待校验知识点大纲和教学队列")
    args = parser.parse_args()
    print(json.dumps(convert(args.root.resolve(), args.course, args.pages, args.local_model, args.extract_outline), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
