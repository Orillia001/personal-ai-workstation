import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from teaching_core import TeachingCore,write_json,read_json

class TeachingTests(unittest.TestCase):
    def setUp(self):
        test_area=Path(__file__).resolve().parent/'tmp-tests';test_area.mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=test_area)
        assert Path(self.temp.name).resolve().is_relative_to(test_area.resolve())
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name);self.vault=self.root/'vault';(self.vault/'.obsidian').mkdir(parents=True)
        self.course='a';self.graph_path=self.root/'Projects/University/courses/a/knowledge/graph.json'
        config={'subjects':{},'vault':str(self.vault)}
        for c in ['a','b']:
            config['subjects'][c]={'name':'学科'+c,'graph':f'Projects/University/courses/{c}/knowledge/graph.json','legacy_course':f'Projects/University/courses/{c}','standard':{'practice_threshold':.85,'concept_threshold':.9}}
            write_json(self.root/f'State/teaching/{c}.json',{'current':{'id':'x','title':'甲'},'mastery':'not_assessed','next_action':'诊断','last_error':None})
        write_json(self.root/'Config/teaching.json',config)
        self.graph={'course':'a','nodes':[{'id':'m','title':'模块','kind':'module','body':'知识范围','sources':[]},{'id':'x','title':'甲','kind':'concept','body':'知识正文','overview':True,'sources':[{'path':'Projects/University/courses/a/reference/page.md','pdf_page':1}]},{'id':'y','title':'乙','kind':'concept','body':'必要先修','sources':[]}],'edges':[{'from':'m','to':'x','kind':'contains'},{'from':'y','to':'x','kind':'prerequisite'}]}
        write_json(self.graph_path,self.graph)
        p=self.root/'Projects/University/courses/a/reference/page.md';p.parent.mkdir(parents=True);p.write_text('<!-- source-page: 1 -->\n来源文字与适用条件',encoding='utf-8')
        self.core=TeachingCore(self.root)

    def test_progress_does_not_read_graph_or_sources(self):
        with patch.object(self.core,'graph',side_effect=AssertionError('must not load content')):
            result=self.core.context('a')
        self.assertEqual(set(result),{'mode','course','name','current','mastery','last_error','next_action'})
        self.assertNotIn('知识正文',json.dumps(result,ensure_ascii=False))

    def test_explicit_teach_scopes_knowledge_and_sources(self):
        result=self.core.context('a','teach','x',max_chars=2000)
        self.assertEqual([x['id'] for x in result['knowledge']],['x','y'])
        self.assertIn('适用条件',result['source_excerpts'][0]['excerpt'])
        self.assertLessEqual(len(json.dumps(result,ensure_ascii=False)),2000)

    def test_progress_rejects_implicit_content_request(self):
        with self.assertRaises(ValueError):self.core.context('a',node_id='x')

    def test_source_excerpt_locates_current_concept(self):
        p=self.root/'Projects/University/courses/a/reference/page.md'
        p.write_text('无关前文'*1000+'\n甲\n适用条件与当前知识',encoding='utf-8')
        result=self.core.context('a','teach','x')
        self.assertIn('适用条件与当前知识',result['source_excerpts'][0]['excerpt'])
        self.assertLess(len(result['source_excerpts'][0]['excerpt']),1100)

    def test_assessment_requires_actual_question_and_answer(self):
        with self.assertRaises(ValueError):self.core.context('a','assess','x')
        result=self.core.context('a','assess','x',{'question':'题目','answer':'实际作答'})
        self.assertEqual(result['submission']['answer'],'实际作答')

    def test_budget_is_enforced_without_cutting_conditions(self):
        g=copy.deepcopy(self.graph);g['nodes'][1]['body']='知识'*4000;write_json(self.graph_path,g)
        with self.assertRaises(ValueError):self.core.context('a','teach','x',max_chars=600)

    def test_source_cannot_escape_course_reference(self):
        g=copy.deepcopy(self.graph);g['nodes'][1]['sources'][0]['path']='Config/teaching.json';write_json(self.graph_path,g)
        with self.assertRaises(ValueError):self.core.context('a','teach','x')

    def test_graph_rejects_dangling_links_cycles_and_bad_names(self):
        for extra in [{'from':'x','to':'missing','kind':'applies'},{'from':'x','to':'y','kind':'prerequisite'}]:
            g=copy.deepcopy(self.graph);g['edges'].append(extra)
            with self.assertRaises(ValueError):TeachingCore.validate_graph(g,'a')
        g=copy.deepcopy(self.graph);g['nodes'][1]['title']='../非法'
        with self.assertRaises(ValueError):TeachingCore.validate_graph(g,'a')

    def test_course_state_is_isolated_and_claim_is_not_mastery(self):
        before=self.core.progress('b');self.core.record('a',{'node_id':'x','kind':'self_report'})
        self.assertEqual(self.core.progress('a')['mastery'],'self_reported')
        self.assertEqual(self.core.progress('b'),before)

    def test_single_passing_practice_never_verifies_mastery(self):
        event={'node_id':'x','kind':'practice','assessment_type':'calculation','question':'题','answer':'答','feedback':'独立作答','score':1}
        self.assertEqual(self.core.record('a',event)['mastery'],'review_due')
        with self.assertRaises(ValueError):self.core.record('a',{'node_id':'x','kind':'practice','score':1})

    def test_concept_and_calculation_use_distinct_thresholds(self):
        event={'node_id':'x','kind':'practice','assessment_type':'concept','question':'题','answer':'答','feedback':'概念需继续补足','score':.87}
        self.assertEqual(self.core.record('a',event)['mastery'],'in_progress')
        event['assessment_type']='calculation'
        self.assertEqual(self.core.record('a',event)['mastery'],'review_due')

    def test_switching_knowledge_restores_its_error_and_next_action(self):
        event={'node_id':'x','kind':'practice','assessment_type':'calculation','question':'题','answer':'答','feedback':'单位错误','error':'单位换算','score':.4}
        before=self.core.record('a',event)
        self.core.select('a','y');resumed=self.core.select('a','x')
        self.assertEqual(resumed['last_error'],before['last_error'])
        self.assertEqual(resumed['next_action'],before['next_action'])

    def test_render_contains_only_learning_files_and_valid_canvas_paths(self):
        files=self.core.render('a')
        self.assertTrue(all(p.endswith(('.md','.canvas')) for p in files))
        self.assertFalse(any('source-page' in t or 'State/' in t for t in files.values()))
        canvas=json.loads(files['知识地图.canvas'])
        self.assertTrue(all(n['file'].startswith('课程知识/学科a/') for n in canvas['nodes']))
        self.assertIn('先修知识',files['知识点/甲.md'])

    def test_publish_is_idempotent(self):
        self.assertTrue(self.core.publish('a',self.vault)['published'])
        self.assertEqual(self.core.publish('a',self.vault)['changed_files'],0)

    def test_user_text_edit_blocks_writes_and_is_preserved(self):
        self.core.publish('a',self.vault)
        p=self.vault/'课程知识/学科a/知识点/甲.md';p.write_text('用户笔记',encoding='utf-8')
        result=self.core.publish('a',self.vault)
        self.assertFalse(result['published']);self.assertEqual(p.read_text(encoding='utf-8'),'用户笔记')

    def test_canvas_layout_and_groups_survive(self):
        self.core.publish('a',self.vault)
        p=self.vault/'课程知识/学科a/知识地图.canvas';canvas=read_json(p);canvas['nodes'][0]['x']=909
        canvas['nodes'].append({'id':'user-group','type':'group','x':0,'y':0,'width':10,'height':10,'label':'用户分组'})
        write_json(p,canvas);self.assertTrue(self.core.publish('a',self.vault)['published'])
        after=read_json(p);self.assertEqual(after['nodes'][0]['x'],909);self.assertEqual(after['nodes'][-1]['id'],'user-group')

    def test_user_connection_change_is_conflict(self):
        self.core.publish('a',self.vault);p=self.vault/'课程知识/学科a/知识地图.canvas';canvas=read_json(p)
        canvas['edges'][0]['label']='用户含义';write_json(p,canvas)
        self.assertFalse(self.core.publish('a',self.vault)['published'])

    def test_wrong_vault_and_untracked_collision_are_rejected(self):
        other=self.root/'other';(other/'.obsidian').mkdir(parents=True)
        with self.assertRaises(ValueError):self.core.publish('a',other)
        p=self.vault/'课程知识/学科a/大纲.md';p.parent.mkdir(parents=True);p.write_text('已有文件',encoding='utf-8')
        self.assertFalse(self.core.publish('a',self.vault)['published'])

if __name__=='__main__':unittest.main()
