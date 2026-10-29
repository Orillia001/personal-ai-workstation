"""Focused tests for site registration and the future script seam."""

import sqlite3
import json
import tempfile
import unittest
from pathlib import Path

import workstation_site_bridges as bridges
from workstation_edge_bookmarks import find_edge_bookmark_url


class SiteBridgeTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        bridges.ADAPTERS.clear()

    def tearDown(self):
        bridges.ADAPTERS.clear()
        self.db.close()

    def test_builtin_placeholder_does_not_claim_to_check_homework(self):
        sites = bridges.list_sites(self.db)["sites"]
        self.assertEqual([site["name"] for site in sites], ["雨课堂"])
        self.assertEqual(sites[0]["login_strategy"], "bookmark")
        self.assertEqual(sites[0]["bookmark_query"], "雨课堂")
        self.assertEqual(sites[0]["assignment_status"], "not_checked")
        self.assertIsNone(sites[0]["assignment_count"])
        self.assertFalse(sites[0]["adapter_ready"])
        self.assertEqual(bridges.check_assignments(self.db, "rain_classroom")["status"], "adapter_not_configured")

    def test_import_rain_exams_persists_only_exam_fields(self):
        original = {"format": "workstation.rain.upcoming-exams.v1", "status": "checked", "cookie": "never-save",
                    "assignments": [{"external_id": "17", "title": "实验报告", "course": "2026秋-机24-3",
                                     "due_at": None, "url": None, "status": "upcoming_exam", "token": "never-save"}]}
        sites = bridges.import_rain_result(self.db, original)["sites"]
        rain = sites[0]
        self.assertEqual(rain["assignment_status"], "checked")
        self.assertEqual(rain["assignment_count"], 1)
        self.assertEqual(rain["assignments"][0]["title"], "实验报告")
        self.assertNotIn("never-save", str(sites))
        self.assertNotIn("never-save", self.db.execute("SELECT result_json FROM workbench_site_checks").fetchone()[0])
        self.assertEqual(bridges.list_sites(self.db)["sites"][0]["assignment_count"], 1)
        empty = bridges.import_rain_result(self.db, {"format": original["format"], "status": "checked", "assignments": []})["sites"][0]
        self.assertEqual(empty["assignment_count"], 0)

    def test_visible_count_keeps_number_without_page_text(self):
        result = {"format": "workstation.rain.visible-count.v1", "status": "checked", "count": 2,
                  "page_text": "never-save"}
        rain = bridges.record_rain_check(self.db, result)["sites"][0]
        self.assertEqual(rain["assignment_count"], 2)
        self.assertEqual(rain["check_method"], "visible_count")
        self.assertEqual(rain["assignments"], [])
        self.assertNotIn("never-save", self.db.execute("SELECT result_json FROM workbench_site_checks").fetchone()[0])
        failed = bridges.record_rain_check(self.db, {"format": result["format"], "status": "site_error"})["sites"][0]
        self.assertEqual(failed["assignment_count"], 2)
        self.assertEqual(failed["last_check_status"], "site_error")
        not_ready = bridges.record_rain_check(self.db, {"format": result["format"], "status": "site_error",
                                                         "reason": "course_page_not_ready"})["sites"][0]
        self.assertIn("我听的课", not_ready["last_check_message"])

    def test_theol_homework_uses_existing_site_and_saves_only_pending_fields(self):
        site = bridges.save_site(self.db, "课程伴侣", "http://eol.imut.edu.cn/meol/personal/stuPersonal.do")["sites"][1]
        self.assertEqual(site["adapter_key"], "theol_homework")
        self.assertTrue(site["adapter_ready"])
        result = {"format": "workstation.theol.pending-homework.v1", "status": "checked", "count": 1,
                  "cookie": "never-save", "assignments": [{"external_id": "theol-1", "title": "练习一",
                  "course": "控制基础", "due_at": "2026/10/01 00:00", "url": None,
                  "status": "pending_homework", "password": "never-save"}]}
        saved = bridges.record_theol_check(self.db, result)["sites"][1]
        self.assertEqual(saved["assignment_count"], 1)
        self.assertEqual(saved["assignments"][0]["due_at"], "2026/10/01 00:00")
        self.assertNotIn("never-save", str(saved))
        self.assertNotIn("never-save", self.db.execute("SELECT result_json FROM workbench_site_checks WHERE site_id=?", (site["id"],)).fetchone()[0])
        failed = bridges.record_theol_check(self.db, {"format": result["format"], "status": "site_error",
                                                 "reason": "reminder_not_ready"})["sites"][1]
        self.assertEqual(failed["assignment_count"], 1)
        self.assertEqual(failed["last_check_status"], "site_error")

    def test_theol_rejects_inconsistent_count_and_bad_due_date(self):
        bridges.save_site(self.db, "课程伴侣", "http://eol.imut.edu.cn/meol/personal/stuPersonal.do")
        base = {"format": "workstation.theol.pending-homework.v1", "status": "checked", "count": 1,
                "assignments": [{"external_id": "theol-1", "title": "练习一", "course": "控制基础",
                                 "due_at": "2026/10/01 00:00", "url": None, "status": "pending_homework"}]}
        for bad in ({**base, "count": 0}, {**base, "assignments": []},
                    {**base, "assignments": [{**base["assignments"][0], "due_at": "2026/19/91 25:70"}]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                bridges.record_theol_check(self.db, bad)

    def test_rain_import_rejects_failure_without_overwriting_previous_result(self):
        bridge_format = "workstation.rain.upcoming-exams.v1"
        bridges.import_rain_result(self.db, {"format": bridge_format, "status": "checked", "assignments": []})
        for invalid in ({"format": bridge_format, "status": "user_action_required", "assignments": []},
                        {"format": bridge_format, "status": "checked", "assignments": [{"title": "missing id"}]},
                        {"format": bridge_format, "status": "checked", "assignments": [{"external_id": "1", "title": "x", "course": "c", "status": "upcoming_exam", "url": "https://example.com"}]}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                bridges.import_rain_result(self.db, invalid)
        self.assertEqual(bridges.list_sites(self.db)["sites"][0]["assignment_count"], 0)

    def test_register_new_site_and_configure_builtin_address(self):
        sites = bridges.save_site(self.db, "课程平台", "https://school.example.edu/assignments/")["sites"]
        self.assertEqual(sites[1]["url"], "https://school.example.edu/assignments")
        sites = bridges.save_site(self.db, "雨课堂", "https://school.example.edu", "rain_classroom")["sites"]
        self.assertEqual(sites[0]["url"], "https://school.example.edu")
        self.assertFalse(sites[0]["adapter_ready"])

    def test_accept_full_login_link_without_persisting_plaintext_credentials(self):
        login_url = "https://student:private@example.com/courses?ticket=private#home"
        sites = bridges.save_site(self.db, "学习平台", login_url, login_strategy="encrypted_link")["sites"]
        self.assertEqual(sites[1]["url"], "https://example.com/courses")
        self.assertNotIn("private", repr(sites))
        protected = self.db.execute("SELECT login_url_protected FROM workbench_site_bridges WHERE name='学习平台'").fetchone()[0]
        self.assertNotIn(b"private", protected)
        self.assertEqual(bridges.login_url(self.db, sites[1]["id"])["url"], login_url)
        bridges.save_site(self.db, "学习平台", sites[1]["url"], sites[1]["id"], "encrypted_link")
        self.assertEqual(bridges.login_url(self.db, sites[1]["id"])["url"], login_url)

    def test_manual_login_uses_public_address(self):
        self.assertEqual(bridges.list_sites(self.db)["sites"][0]["login_strategy"], "bookmark")
        sites = bridges.save_site(self.db, "学习平台", "https://student:private@example.com/login?ticket=private", login_strategy="manual")["sites"]
        self.assertEqual(bridges.login_url(self.db, sites[1]["id"])["url"], "https://example.com/login")

    def test_migrate_previous_site_registry_schema(self):
        self.db.execute("CREATE TABLE workbench_site_bridges(id TEXT PRIMARY KEY,name TEXT UNIQUE,base_url TEXT,adapter_key TEXT,created_at TEXT,updated_at TEXT)")
        self.db.execute("INSERT INTO workbench_site_bridges VALUES('rain_classroom','雨课堂','','rain_classroom','t','t')")
        sites = bridges.list_sites(self.db)["sites"]
        self.assertEqual(sites[0]["login_strategy"], "bookmark")
        self.assertEqual(sites[0]["bookmark_query"], "雨课堂")
        self.assertFalse(sites[0]["has_login_url"])

    def test_rain_bookmark_upgrade_preserves_user_configured_site(self):
        bridges.list_sites(self.db)
        bridges.save_site(self.db, "雨课堂", "https://school.example.edu", "rain_classroom", "manual")
        self.assertEqual(bridges.list_sites(self.db)["sites"][0]["login_strategy"], "manual")
        self.assertEqual(bridges.list_sites(self.db)["sites"][0]["url"], "https://school.example.edu")

    def test_reject_invalid_address_and_duplicate_name(self):
        for url in ("https://exa mple.com", "https://example.com\\@another.example"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                bridges.save_site(self.db, "新站点", url)
        with self.assertRaisesRegex(ValueError, "同名"):
            bridges.save_site(self.db, "雨课堂", "")

    def test_http_intranet_address_can_be_saved_for_bookmark_login(self):
        site = bridges.save_site(self.db, "课程伴侣(内网)", "http://campus.example.edu/meol/index.do",
                                 login_strategy="bookmark")["sites"][1]
        self.assertEqual(site["url"], "http://campus.example.edu/meol/index.do")
        self.assertEqual(site["login_strategy"], "bookmark")
        self.assertFalse(site["has_login_url"])

    def test_http_address_rejects_embedded_credentials_and_encrypted_link_strategy(self):
        for url in ("http://student:secret@campus.example.edu/", "http://campus.example.edu/?ticket=secret"):
            with self.subTest(url=url), self.assertRaisesRegex(ValueError, "HTTPS"):
                bridges.save_site(self.db, "课程平台", url, login_strategy="bookmark")
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            bridges.save_site(self.db, "课程平台", "http://campus.example.edu/", login_strategy="encrypted_link")

    def test_explicit_python_adapter_contract(self):
        class StubAdapter:
            key = "rain_classroom"

            def login(self, base_url):
                self.login_url = base_url
                return {"status": "ready", "message": ""}

            def check_assignments(self, base_url):
                self.last_url = base_url
                return [{"external_id": "a1", "title": "练习", "course": "课程", "due_at": None, "url": None, "status": "open"}]

        adapter = StubAdapter()
        bridges.register_adapter(adapter)
        self.assertTrue(bridges.list_sites(self.db)["sites"][0]["adapter_ready"])
        self.assertEqual(bridges.check_assignments(self.db, "rain_classroom")["status"], "adapter_not_configured")
        bridges.save_site(self.db, "雨课堂", "https://school.example.edu", "rain_classroom")
        result = bridges.check_assignments(self.db, "rain_classroom")
        self.assertEqual(adapter.login_url, "https://school.example.edu")
        self.assertEqual(adapter.last_url, "https://school.example.edu")
        self.assertEqual(result["login_status"], "ready")
        self.assertEqual(result["assignments"][0]["title"], "练习")

    def test_adapter_waits_for_user_action_before_reading_assignments(self):
        class NeedsActionAdapter:
            key = "rain_classroom"

            def login(self, base_url):
                return {"status": "user_action_required", "message": "请先完成站点验证"}

            def check_assignments(self, base_url):
                raise AssertionError("作业读取不应在登录未完成时运行")

        bridges.register_adapter(NeedsActionAdapter())
        bridges.save_site(self.db, "雨课堂", "https://school.example.edu", "rain_classroom")
        result = bridges.check_assignments(self.db, "rain_classroom")
        self.assertEqual(result["status"], "user_action_required")
        self.assertEqual(result["assignments"], [])

    def test_adapter_import_requires_both_steps(self):
        class IncompleteAdapter:
            key = "rain_classroom"

            def check_assignments(self, base_url):
                return []

        with self.assertRaisesRegex(ValueError, "登录确认"):
            bridges.register_adapter(IncompleteAdapter())
        self.assertFalse(bridges.list_sites(self.db)["sites"][0]["adapter_ready"])


class EdgeBookmarkTests(unittest.TestCase):
    def test_find_matching_edge_favorite_without_database_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            user_data = Path(directory)
            profile = user_data / "Default"
            profile.mkdir()
            favorites = {"roots": {"bookmark_bar": {"children": [
                {"type": "url", "name": "课程入口", "url": "https://school.example.edu/course?ticket=private"},
                {"type": "url", "name": "课程入口", "url": "https://other.example.edu/"},
            ]}}}
            (profile / "Bookmarks").write_text(json.dumps(favorites), encoding="utf-8")
            self.assertEqual(find_edge_bookmark_url("课程入口", "https://school.example.edu", user_data=user_data),
                             "https://school.example.edu/course?ticket=private")
            with self.assertRaisesRegex(ValueError, "多个"):
                find_edge_bookmark_url("课程入口", user_data=user_data)

    def test_http_intranet_favorite_can_match_by_host_when_title_differs(self):
        with tempfile.TemporaryDirectory() as directory:
            user_data = Path(directory)
            profile = user_data / "Default"
            profile.mkdir()
            favorites = {"roots": {"bookmark_bar": {"children": [
                {"type": "url", "name": "学校课程首页", "url": "http://campus.example.edu/meol/index.do"},
            ]}}}
            (profile / "Bookmarks").write_text(json.dumps(favorites), encoding="utf-8")
            self.assertEqual(find_edge_bookmark_url("课程伴侣(内网)", "http://campus.example.edu/meol/index.do",
                                                     user_data=user_data), "http://campus.example.edu/meol/index.do")


if __name__ == "__main__":
    unittest.main()
