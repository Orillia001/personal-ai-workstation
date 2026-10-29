"""Focused checks for durable workbench revisions."""

import sqlite3
import unittest

import workstation_layout_state as layout_state


class LayoutStateTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        layout_state.ensure_schema(self.db)
        self.snapshot = {"version": 1, "selection": {"project": "console"}, "boards": []}

    def tearDown(self):
        self.db.close()

    def test_round_trip_and_revision(self):
        self.assertEqual(layout_state.load(self.db)["revision"], 0)
        saved = layout_state.save(self.db, self.snapshot, 0)
        self.assertEqual(saved["revision"], 1)
        self.assertEqual(layout_state.load(self.db)["state"], self.snapshot)
        self.assertEqual(layout_state.save(self.db, self.snapshot, 1)["revision"], 2)

    def test_stale_tab_cannot_overwrite(self):
        layout_state.save(self.db, self.snapshot, 0)
        with self.assertRaises(layout_state.StateConflict):
            layout_state.save(self.db, {**self.snapshot, "boards": [["x", []]]}, 0)
        self.assertEqual(layout_state.load(self.db)["state"], self.snapshot)

    def test_rejects_oversized_snapshot(self):
        oversized = {**self.snapshot, "selection": {"text": "x" * layout_state.MAX_STATE_BYTES}}
        with self.assertRaises(ValueError):
            layout_state.save(self.db, oversized, 0)
        self.assertEqual(layout_state.load(self.db)["revision"], 0)


if __name__ == "__main__":
    unittest.main()
