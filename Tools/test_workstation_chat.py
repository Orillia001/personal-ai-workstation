"""Read-only project chat contract without invoking Codex."""

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import workstation_chat as chat


class ChatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "Projects" / "Alpha").mkdir(parents=True)
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_chat_scoped_to_project_and_child_and_uses_read_only_cli(self):
        def fake_run(command, **kwargs):
            self.assertIn("read-only", command)
            self.assertIn("--ephemeral", command)
            self.assertEqual(command[-1], "-")
            self.assertIn('"child": "lesson"', kwargs["input"])
            self.assertIn("你好", kwargs["input"])
            Path(command[command.index("--output-last-message") + 1]).write_text("你好，我可以帮你查看项目。", encoding="utf-8")
            return SimpleNamespace(returncode=0)

        with patch.object(chat.core, "ai_status", return_value={"path": "codex", "logged_in": True, "detail": "Logged in using ChatGPT"}), patch.object(chat.subprocess, "run", side_effect=fake_run):
            result = chat.send(self.root, self.db, "Alpha", "lesson", "你好")
        self.assertEqual([row["role"] for row in result["messages"]], ["user", "assistant"])
        self.assertEqual(chat.history(self.root, self.db, "Alpha", "overview")["messages"], [])
        self.assertEqual(len(chat.history(self.root, self.db, "Alpha", "lesson")["messages"]), 2)

    def test_rejects_invalid_context_and_message_before_codex(self):
        with self.assertRaises(ValueError):
            chat.history(self.root, self.db, "../Alpha", "overview")
        with self.assertRaises(ValueError):
            chat.history(self.root, self.db, "Alpha", "../../other")
        with self.assertRaises(ValueError):
            chat.send(self.root, self.db, "Alpha", "overview", " ")


if __name__ == "__main__":
    unittest.main()
