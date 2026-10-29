"""Behavior checks through subprocess CLI and localhost HTTP; all writes use a temp station."""
import json
import subprocess
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "matt.py"


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "AGENTS.md").write_text("test station", encoding="utf-8")
        (self.root / "Projects" / "Sandbox").mkdir(parents=True)
        (self.root / "proof.md").write_text("verified result", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def call(self, *args, ok=True):
        result = subprocess.run([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--root", str(self.root), *map(str, args)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(result.returncode, 0 if ok else 1, result.stderr)
        return json.loads(result.stdout if ok else result.stderr)

    def begin(self, task="example"):
        return self.call("begin", "--task", task, "--project", "Sandbox", "--title", "公开行为验证", "--stages", "implement,verify,review")

    def update(self, stage, status, revision, *extra, ok=True):
        return self.call("update", "--task", "example", "--stage", stage, "--status", status,
                         "--revision", revision, "--note", "实际结果与说明", *extra, ok=ok)

    def test_persistent_progress_and_completion(self):
        self.begin()
        self.update("implement", "running", 1)
        self.update("implement", "completed", 2, "--evidence", "proof.md")
        self.update("verify", "blocked", 3)
        self.assertEqual(self.call("show", "--task", "example")["status"], "blocked")
        self.update("verify", "completed", 4, "--evidence", "proof.md")
        self.update("review", "completed", 5, "--evidence", "proof.md")
        result = self.call("list")["tasks"][0]
        self.assertEqual(result["status"], "completed")
        self.assertEqual(len(result["events"]), 5)
        self.assertEqual(result["stages"][1]["evidence"], ["proof.md"])

    def test_revision_conflict_preserves_current(self):
        self.begin()
        self.update("implement", "running", 1)
        self.assertIn("修订冲突", self.update("implement", "blocked", 1, ok=False)["error"])
        self.assertEqual(self.call("show", "--task", "example")["stages"][0]["status"], "running")

    def test_predecessor_must_finish(self):
        self.begin()
        self.assertIn("前置", self.update("verify", "running", 1, ok=False)["error"])

    def test_completion_needs_existing_evidence(self):
        self.begin()
        self.assertIn("证据", self.update("implement", "completed", 1, ok=False)["error"])
        self.assertIn("不存在", self.update("implement", "completed", 1, "--evidence", "missing.txt", ok=False)["error"])

    def test_cannot_overwrite_task_or_final_stage(self):
        self.begin()
        self.call("begin", "--task", "example", "--project", "Sandbox", "--title", "duplicate", ok=False)
        self.update("implement", "completed", 1, "--evidence", "proof.md")
        self.assertIn("封存", self.update("implement", "running", 2, ok=False)["error"])

    def test_package_text_can_be_loaded_as_utf8(self):
        for path in SCRIPT.parent.parent.rglob("*"):
            if path.is_file() and path.suffix in {".md", ".json", ".yaml", ".py", ".js", ".cjs", ".css", ".html"}:
                with self.subTest(path=path.relative_to(SCRIPT.parent.parent).as_posix()):
                    text = path.read_text(encoding="utf-8-sig")
                    if path.suffix == ".json":
                        json.loads(text)

    def test_skipping_records_reason(self):
        self.begin()
        self.update("implement", "skipped", 1)
        data = self.update("verify", "running", 2)
        self.assertEqual(data["stages"][0]["note"], "实际结果与说明")

    def test_path_escape_rejected(self):
        self.call("begin", "--task", "../outside", "--project", "Sandbox", "--title", "escape", ok=False)
        self.begin()
        self.update("implement", "completed", 1, "--evidence", "../proof.md", ok=False)
        self.update("implement", "completed", 1, "--evidence", str(self.root / "proof.md"), ok=False)

    def test_two_writers_do_not_silently_overwrite(self):
        self.begin()
        def writer(status):
            return subprocess.run([sys.executable, "-B", str(SCRIPT), "--root", str(self.root), "update", "--task", "example", "--stage", "implement", "--status", status, "--revision", "1", "--note", "writer"], capture_output=True)
        with ThreadPoolExecutor() as pool:
            results = list(pool.map(writer, ["running", "blocked"]))
        self.assertEqual(sorted(result.returncode for result in results), [0, 1])
        self.assertEqual(self.call("show", "--task", "example")["revision"], 2)

    def test_corrupt_record_does_not_hide_other_tasks(self):
        self.begin()
        broken = self.root / ".scratch" / "broken"
        broken.mkdir()
        (broken / "matt-workflow.json").write_text("[]", encoding="utf-8")
        result = self.call("list")
        self.assertEqual(len(result["tasks"]), 1)
        self.assertEqual(result["warnings"][0]["task"], "broken")

    def test_http_reads_only_recorded_evidence_and_rejects_cross_site(self):
        self.begin()
        (self.root / "package.zip").write_bytes(b"PK\x03\x04archive")
        self.update("implement", "completed", 1, "--evidence", "proof.md", "--evidence", "package.zip")
        server = subprocess.Popen([sys.executable, "-X", "utf8", "-B", str(SCRIPT), "--root", str(self.root), "serve", "--port", "0"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            url = json.loads(server.stdout.readline())["url"]
            def get(path, **headers):
                return urllib.request.urlopen(urllib.request.Request(url + path, headers=headers), timeout=5)
            with get("/api/health") as response:
                self.assertTrue(json.load(response)["read_only"])
            with get("/api/workflows") as response:
                self.assertEqual(json.load(response)["tasks"][0]["task"], "example")
            with get("/evidence?task=example&stage=implement&index=0") as response:
                self.assertEqual(response.read(), b"verified result")
            with get("/evidence?task=example&stage=implement&index=1") as response:
                self.assertEqual(response.headers.get_content_type(), "application/zip")
                self.assertEqual(response.read(), b"PK\x03\x04archive")
            for path, headers, expected in [("/../AGENTS.md", {}, 404), ("/api/workflows", {"Host": "evil.example"}, 403), ("/api/workflows", {"Sec-Fetch-Site": "cross-site"}, 403), ("/evidence?task=example&stage=implement&index=-1", {}, 400)]:
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    get(path, **headers)
                self.assertEqual(raised.exception.code, expected)
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(urllib.request.Request(url + "/api/workflows", data=b"{}"))
            self.assertEqual(raised.exception.code, 405)
        finally:
            server.terminate()
            server.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
