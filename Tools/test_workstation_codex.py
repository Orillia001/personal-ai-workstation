"""Behavior checks for the local-file projection; no real Codex data is changed."""
import hashlib
import json
import os
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path

import workstation_codex as subject


class CodexFileMappingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="workstation-codex-map-")
        self.base = Path(self.temp.name).resolve()
        self.root, self.home = self.base / "station", self.base / "profile" / ".codex"
        self.root.mkdir(); self.home.mkdir(parents=True)
        self.database = self.home / "state_5.sqlite"
        self.db = sqlite3.connect(self.database)
        self.db.executescript('CREATE TABLE threads(id TEXT,rollout_path TEXT,updated_at INTEGER,source TEXT,cwd TEXT,archived INTEGER,name TEXT,title TEXT,agent_path TEXT,first_user_message TEXT); CREATE TABLE thread_spawn_edges(parent_thread_id TEXT,child_thread_id TEXT,status TEXT);')
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.assertTrue(self.base.name.startswith("workstation-codex-map-"))
        self.assertEqual(self.base.parent, Path(tempfile.gettempdir()).resolve())
        self.temp.cleanup()

    def file(self, path, content):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def thread(self, ident, events=(), name="A task", path=None, agent_path=""):
        path = path or self.home / "sessions" / f"{ident}.jsonl"
        self.file(path, '\n'.join(json.dumps(event) for event in events))
        self.db.execute('INSERT INTO threads VALUES(?,?,?,?,?,?,?,?,?,?)', (ident,str(path),100,'vscode',str(self.root),0,name,'PROMPT_PRIVATE',agent_path,'SECRET_FIRST_MESSAGE'))
        self.db.commit()
        return path

    def event(self, kind):
        return {"type":"event_msg","timestamp":"2026-10-21T05:00:00Z","payload":{"type":kind}}

    def catalog(self):
        return subject.catalog(self.root, home=self.home)

    def test_file_skill_and_plugin_cache_have_distinct_sources_and_exact_hash(self):
        skill=self.file(self.home/'skills/anysearch/SKILL.md','\ufeff---\nname: anysearch\ndescription: Search the web\n---\nInstructions')
        self.file(self.home/'plugins/cache/example/plug/1.0/skills/read/SKILL.md','---\nname: read\n---\n')
        result=self.catalog()
        self.assertEqual(result['local']['skills'][0]['name'],'anysearch')
        self.assertEqual(result['local']['skills'][0]['sha256'],hashlib.sha256(skill.read_bytes()).hexdigest())
        self.assertEqual(result['plugin_cache'][0]['scope'],'plugin-cache')
        self.assertNotIn('enabled',result['plugin_cache'][0])

    def test_projection_does_not_export_prompts_or_role_secrets(self):
        self.thread('root_1234')
        self.file(self.home/'agents/reviewer.toml','name="reviewer"\ndescription="Reviews code"\napi_key="NEVER_EXPORT"\ndeveloper_instructions="PROMPT_PRIVATE"\n')
        self.file(self.home/'auth.json','AUTH_PRIVATE')
        self.file(self.home/'.env','ENV_PRIVATE')
        encoded=json.dumps(self.catalog())
        for secret in ('SECRET_FIRST_MESSAGE','PROMPT_PRIVATE','NEVER_EXPORT','AUTH_PRIVATE','ENV_PRIVATE'):
            self.assertNotIn(secret,encoded)
        self.assertIn('reviewer',encoded)

    def test_parent_child_edges_and_completed_log_are_mapped(self):
        self.thread('root_1234',[self.event('task_started')],agent_path='/root')
        self.thread('child_1234',[self.event('task_started'),self.event('task_complete')],agent_path='/root/review')
        self.db.execute('INSERT INTO thread_spawn_edges VALUES(?,?,?)',('root_1234','child_1234','open'));self.db.commit()
        self.file(self.root/'State/codex-map/context.json',json.dumps({'root_thread_id':'root_1234'}))
        agents=self.catalog()['agent_tree']['agents']
        self.assertEqual([(a['id'],a['parent'])for a in agents],[('root_1234',None),('child_1234','root_1234')])
        self.assertEqual(agents[1]['status'],'completed')
        self.assertFalse(agents[1]['runtime_verified'])

    def test_open_edge_alone_is_not_a_running_status(self):
        self.thread('root_1234')
        self.assertEqual(self.catalog()['local']['threads'][0]['status'],'unknown')

    def test_stale_started_log_is_unknown_and_tool_text_is_not_a_status_event(self):
        path=self.thread('root_1234',[self.event('task_started'),{'type':'event_msg','payload':{'type':'item_completed','text':'task_complete'}}])
        os.utime(path,(time.time()-180,time.time()-180))
        self.assertEqual(self.catalog()['local']['threads'][0]['status'],'unknown')

    def test_rollout_outside_sessions_is_never_read_for_status(self):
        self.thread('root_1234',[self.event('task_complete')],path=self.base/'outside.jsonl')
        self.assertEqual(self.catalog()['local']['threads'][0]['status'],'unknown')

    def test_read_only_database_and_metadata_files_are_unchanged(self):
        self.thread('root_1234',[self.event('task_complete')])
        before=hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.catalog(); self.catalog()
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(),before)

    def test_schema_mismatch_reports_warning_and_preserves_file_skills(self):
        self.db.execute('DROP TABLE threads');self.db.commit()
        self.file(self.home/'skills/example/SKILL.md','---\nname: example\n---\n')
        result=self.catalog()
        self.assertEqual(result['local']['skills'][0]['name'],'example')
        self.assertTrue(result['local']['warnings'])

    def test_file_changes_are_visible_on_next_read_without_a_codex_process(self):
        path=self.file(self.home/'skills/example/SKILL.md','---\nname: example\ndescription: First\n---\n')
        before=self.catalog()['local']['skills'][0]
        self.file(path,'---\nname: example\ndescription: Updated\n---\n')
        after=self.catalog()['local']['skills'][0]
        self.assertEqual(after['description'],'Updated')
        self.assertNotEqual(after['sha256'],before['sha256'])

    def test_temporary_database_failure_keeps_previous_task_data_and_timestamp(self):
        self.thread('root_1234',[self.event('task_complete')])
        before=self.catalog()
        self.db.execute('ALTER TABLE threads RENAME TO unavailable_threads');self.db.commit()
        failed=self.catalog()
        self.assertEqual(failed['local']['threads'],before['local']['threads'])
        self.assertEqual(failed['local']['task_collected_at'],before['local']['task_collected_at'])
        self.assertTrue(failed['local']['tasks_stale'])
        self.assertTrue(failed['local']['warnings'])
        self.db.execute('ALTER TABLE unavailable_threads RENAME TO threads');self.db.commit()
        recovered=self.catalog()
        self.assertFalse(recovered['local']['tasks_stale'])
        self.assertFalse(recovered['local']['warnings'])


if __name__ == '__main__':
    unittest.main()
