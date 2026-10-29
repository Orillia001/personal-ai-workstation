import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from teaching_core import TeachingCore, write_json, read_json
import obsidian_learning as bridge


class PropertyTests(unittest.TestCase):
    def test_body_other_properties_bom_and_crlf_survive(self):
        text='\ufeff---\r\ntags:\r\n  - 保留\r\ncustom: 用户原文\r\n---\r\n# 强度\r\n\r\n用户笔记 [[链接]]\r\n'
        result=bridge.properties(text,'a','x','learned')
        self.assertEqual(bridge.content_without_learning(result),text)
        self.assertEqual(bridge.note_status(bridge.header(result)[3]),'learned')
        self.assertEqual(bridge.properties(result,'a','x','learned'),result)

    def test_plain_body_is_exactly_preserved(self):
        text='# 知识\n\n原笔记\n'
        result=bridge.properties(text,'a','x','not_started')
        self.assertEqual(bridge.content_without_learning(result),text)
        self.assertEqual(bridge.content_without_learning(bridge.properties(result,'a','x','review_due')),text)

    def test_invalid_duplicate_and_unclosed_metadata_rejected(self):
        for text in ['---\n学习状态: 已学习\n学习状态: 未开始\n---\n正文',
                     '---\n学习状态: [已学习]\n---\n正文','---\n学习状态: 已学习\n正文',
                     '---\n{"学习状态":"已学习"}\n---\n正文']:
            with self.subTest(text=text),self.assertRaises(bridge.LearningConflict):
                bridge.properties(text,'a','x','learned')


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.vault=self.root/'vault'
        (self.vault/'.obsidian').mkdir(parents=True)
        config={'vault':str(self.vault),'subjects':{}}
        for c in ['a','b']:
            config['subjects'][c]={'name':'学科'+c,'graph':f'{c}.json','legacy_course':'legacy',
                                   'standard':{'concept_threshold':.9,'practice_threshold':.85}}
            graph={'course':c,'nodes':[{'id':'m','title':'模块','kind':'module','body':'范围','sources':[]},
                    {'id':'x','title':'知识','kind':'concept','body':'正文','sources':[]}],
                   'edges':[{'from':'m','to':'x','kind':'contains'}]}
            write_json(self.root/f'{c}.json',graph)
            write_json(self.root/f'State/teaching/{c}.json',{'current':{'id':'x','title':'知识'},'mastery':'not_assessed',
                       'node_states':{},'next_action':'诊断','last_error':None})
        write_json(self.root/'Config/teaching.json',config)
        self.core=TeachingCore(self.root)
        for c in ['a','b']:self.core.publish(c,self.vault)
        self.note=self.vault/'课程知识/学科a/知识点/知识.md'
        self.before=self.note.read_bytes()
        self.bound=bridge.bind_all(self.root,self.root/'backup')

    def item(self,course='a',node='x'):
        return next(n for n in bridge.course_progress(self.root,course)['nodes'] if n['id']==node)

    def test_binding_preserves_body_and_backups_and_is_idempotent(self):
        self.assertEqual(self.bound['notes'],4)
        self.assertEqual(bridge.content_without_learning(self.note.read_text()),self.before.decode())
        self.assertEqual((self.root/'backup/vault/课程知识/学科a/知识点/知识.md').read_bytes(),self.before)
        self.assertEqual(bridge.bind_all(self.root,self.root/'backup2')['changed'],0)

    def test_web_completion_updates_note_without_grading_or_cross_course_changes(self):
        state=(self.root/'State/teaching/a.json').read_bytes();other=self.item('b')
        bridge.set_status(self.root,'a','x','learned',self.item()['revision'])
        self.assertEqual(self.item()['status'],'learned');self.assertEqual(self.item()['mastery'],'not_assessed')
        self.assertIn('已学习',self.note.read_text())
        self.assertEqual((self.root/'State/teaching/a.json').read_bytes(),state)
        self.assertEqual(self.item('b'),other)

    def test_obsidian_change_is_visible_without_a_write_request(self):
        text=self.note.read_text();self.note.write_text(text.replace('"未开始"','"待复习"'),encoding='utf-8')
        self.assertEqual(self.item()['status'],'review_due')
        self.assertEqual(self.item()['mastery'],'not_assessed')

    def test_stale_revision_preserves_user_edit(self):
        revision=self.item()['revision'];self.note.write_text(self.note.read_text()+'\n新笔记',encoding='utf-8')
        changed=self.note.read_bytes()
        with self.assertRaises(bridge.LearningConflict):bridge.set_status(self.root,'a','x','learned',revision)
        self.assertEqual(self.note.read_bytes(),changed)

    def test_metadata_only_change_survives_publishing(self):
        bridge.set_status(self.root,'a','x','learned',self.item()['revision'])
        self.assertTrue(self.core.publish('a',self.vault)['published'])
        self.assertEqual(self.item()['status'],'learned')
        self.assertEqual(self.core.publish('a',self.vault)['changed_files'],0)

    def test_user_body_edit_still_blocks_publish(self):
        self.note.write_text(self.note.read_text()+'\n个人补充',encoding='utf-8')
        original=self.note.read_bytes();self.assertFalse(self.core.publish('a',self.vault)['published'])
        self.assertEqual(self.note.read_bytes(),original)

    def test_teaching_record_flows_to_note_and_passing_practice_still_requires_review(self):
        result=self.core.record('a',{'node_id':'x','kind':'self_report'})
        self.assertTrue(result['obsidian_sync']['ok']);self.assertEqual(self.item()['status'],'learned')
        result=self.core.record('a',{'node_id':'x','kind':'practice','assessment_type':'concept','score':1,
                                   'question':'真实题目','answer':'实际作答','feedback':'逐项核验通过'})
        self.assertEqual(result['mastery'],'review_due');self.assertEqual(self.item()['status'],'review_due')
        self.assertEqual(self.item()['mastery'],'review_due')
        self.assertNotIn('实际作答',self.note.read_text())

    def test_renamed_bound_note_remains_linked(self):
        renamed=self.note.with_name('个人重命名.md');self.note.rename(renamed)
        self.assertTrue(self.item()['linked'])
        bridge.set_status(self.root,'a','x','learned',self.item()['revision'])
        self.assertIn('已学习',renamed.read_text());self.assertFalse(self.note.exists())
        self.assertFalse(self.core.publish('a',self.vault)['published'])
        self.assertFalse(self.note.exists())

    def test_unknown_and_misbound_notes_are_rejected(self):
        for course,node in [('unknown','x'),('a','../x'),('a','missing')]:
            with self.assertRaises(ValueError):bridge.set_status(self.root,course,node,'learned','bad')
        self.note.write_text(self.note.read_text().replace('workstation_node: "x"','workstation_node: "m"'),encoding='utf-8')
        entry=self.item();self.assertFalse(entry['linked'])
        with self.assertRaises(bridge.LearningConflict):bridge.set_status(self.root,'a','x','learned',bridge.digest(self.note.read_bytes()))

    def test_open_note_uses_only_generated_obsidian_uri(self):
        with patch.object(bridge.os,'startfile',create=True) as open_file:
            bridge.open_note(self.root,'a','x')
            uri=open_file.call_args.args[0]
            self.assertTrue(uri.startswith('obsidian://open?path='));self.assertNotIn(' ',uri)


if __name__=='__main__':unittest.main()
