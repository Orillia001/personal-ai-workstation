"""Public controller tests; fake only the external model process boundary."""
import json
from pathlib import Path
import tempfile
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

import workstation_coursework as runtime


class CourseworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.project = self.root / 'Projects/P'
        self.project.mkdir(parents=True)
        state = self.root / 'State/workflows'
        state.mkdir(parents=True)
        self.workflow_id = 'a' * 32
        nodes = [dict(id='task', type='input', label='Task', text='Task', x=0, y=0, source_id='', source_revision='')]
        nodes += [dict(id=f'g{i}', type='agent', label=f'G{i}', text='Stage instructions', x=i, y=0, source_id='', source_revision='') for i in range(1,10)]
        nodes += [dict(id='out', type='output', label='Output', text='', x=10, y=0, source_id='', source_revision='')]
        chain = ['task'] + [f'g{i}' for i in range(1,10)] + ['out']
        self.graph = dict(name='Finance', project='P', nodes=nodes, edges=[{'from':a,'to':b} for a,b in zip(chain,chain[1:])], view=dict(x=0,y=0,scale=1))
        (state / (self.workflow_id+'.json')).write_text(json.dumps({'updated_at':'test','graph':self.graph}), encoding='utf-8')
        self.calls = []
        self.model = patch.object(runtime, 'run_model', self.fake_model)
        self.model.start()
        self.addCleanup(self.model.stop)

    def api(self, action, **values):
        return runtime.dispatch(self.root, dict(action=action, project='P', **values))

    def create(self, paths=None):
        return self.api('create', workflow_id=self.workflow_id, task={'title':'大学金融案例','requirements':'分析营业收入与局限','source_paths':paths or [],'mode':'new'})

    def fake_model(self, request, cancel):
        self.calls.append(request['stage'])
        result = {'content':'研究问题及执行计划：依据材料分析营业收入，标注局限。','claims':[], 'extractions':[], 'passed':True,'issues':[], 'blocked_reason':''}
        if request['stage'] == 'g3':
            result['extractions'] = [{'source_id':'S0001','quote':'营业收入由100增加至120','locator':'教学案例第1行','claim':'教学材料记载收入变化'}]
        if request['stage'] in {'g5','g6','g8'}:
            result['content'] = '教学材料记载营业收入由100增加至120[E0001]。\n\n自主分析：模拟资料无法用于识别因果关系。'
            result['claims'] = [{'id':'C001','text':'教学材料记载营业收入由100增加至120','type':'source','evidence_ids':['E0001']},
                                {'id':'C002','text':'自主分析：模拟资料无法用于识别因果关系','type':'analysis','evidence_ids':[]}]
        return result

    def settled(self, run):
        deadline = time.monotonic()+5
        while time.monotonic()<deadline:
            run = self.api('get', id=run['id'])
            if run['status'] != 'running':
                return run
            time.sleep(.01)
        self.fail('worker did not settle')

    def start(self, run):
        return self.settled(self.api('start', id=run['id'],revision=run['revision']))

    def approve(self, run):
        return self.api('approve',id=run['id'],revision=run['revision'],request_id=run['pending_approval']['request_id'],decision='approve',note='Test fixture explicit user action')

    def test_plan_is_persisted_and_cannot_advance_without_human_approval(self):
        run = self.start(self.create())
        self.assertEqual(run['status'], 'awaiting_approval')
        self.assertEqual(run['pending_approval']['kind'], 'plan')
        self.assertEqual(self.calls, ['g1'])
        with self.assertRaises(ValueError):
            self.api('start', id=run['id'],revision=run['revision'])
        self.assertEqual(self.api('get',id=run['id'])['pending_approval'],run['pending_approval'])

    def test_no_evidence_blocks_before_writing_and_source_addition_resumes(self):
        run = self.start(self.approve(self.start(self.create())))
        self.assertEqual(run['status'],'blocked')
        self.assertEqual(run['current_stage'],'g2')
        self.assertNotIn('g6',self.calls)
        run = self.api('add-source',id=run['id'],revision=run['revision'],source={'title':'虚构教学材料','text':'教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。'})
        self.assertEqual(run['status'],'ready')
        self.assertEqual(len(run['sources']),1)
        self.assertEqual(run['stages'][0]['status'],'passed')

    def test_evidence_driven_pipeline_stops_at_method_then_final_release(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。', encoding='utf-8')
        run = self.start(self.approve(self.start(self.create(['source.md']))))
        self.assertEqual(run['pending_approval']['kind'],'method')
        self.assertEqual(run['evidence'][0]['id'],'E0001')
        cards = self.api('retrieve',id=run['id'],query='营业收入')
        self.assertEqual(cards['items'][0]['source_id'],'S0001')
        self.assertNotIn('g5',self.calls)
        run = self.start(self.approve(run))
        self.assertEqual(run['pending_approval']['kind'],'release')
        self.assertEqual(self.calls.count('g7'),2)
        self.assertEqual(run['status'],'awaiting_approval')
        run = self.approve(run)
        self.assertEqual(run['status'],'released')
        self.assertTrue(any('本地交付' in row['label'] for row in run['artifacts']))

    def test_modified_original_invalidates_method_confirmation(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。', encoding='utf-8')
        run = self.start(self.approve(self.start(self.create(['source.md']))))
        source.write_text('已被修改的原始材料',encoding='utf-8')
        with self.assertRaises(runtime.Conflict): self.approve(run)
        current = self.api('get',id=run['id'])
        self.assertEqual(current['status'],'blocked')
        self.assertIsNone(current['pending_approval'])
        self.assertEqual(current['stages'][1]['status'],'invalidated')

    def test_unlisted_fact_paragraph_and_unknown_evidence_cannot_reach_humanizer(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        run = self.start(self.approve(self.start(self.create(['source.md']))))
        original = self.fake_model
        def bad_writer(request, cancel):
            result = original(request,cancel)
            if request['stage'] == 'g6': result['content'] += '\n\n企业利润也随之翻倍，而且政策独自造成全部增长。'
            return result
        with patch.object(runtime,'run_model',bad_writer): run = self.start(self.approve(run))
        self.assertEqual(run['current_stage'],'g6')
        self.assertEqual(run['status'],'blocked')
        self.assertNotIn('g8',self.calls)

    def test_reviewer_failure_preserves_findings_and_blocks_polish(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        run = self.start(self.approve(self.start(self.create(['source.md']))))
        original = self.fake_model
        def dissent(request,cancel):
            result = original(request,cancel)
            if request['stage'] == 'g7' and '证据与方法' in request['role']:
                result.update(passed=False,issues=['模拟材料不支持因果识别'],content='证据审查发现：模拟材料不支持因果识别。')
            return result
        with patch.object(runtime,'run_model',dissent): run = self.start(self.approve(run))
        self.assertEqual(run['current_stage'],'g7')
        self.assertEqual(run['status'],'blocked')
        self.assertNotIn('g8',self.calls)
        self.assertIn('不支持因果识别',self.api('artifact',id=run['id'],path=run['stages'][6]['output_path'])['content'])

    def test_humanizer_cannot_change_verified_numbers(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        run = self.start(self.approve(self.start(self.create(['source.md']))))
        original = self.fake_model
        def bad_polish(request,cancel):
            result = original(request,cancel)
            if request['stage'] == 'g8':
                result['content'] = result['content'].replace('120','150')
                result['claims'][0]['text'] = result['claims'][0]['text'].replace('120','150')
            return result
        with patch.object(runtime,'run_model',bad_polish): run = self.start(self.approve(run))
        self.assertEqual(run['current_stage'],'g8')
        self.assertEqual(run['status'],'blocked')
        self.assertNotIn('g9',self.calls)

    def test_source_addition_invalidates_method_gate_and_stale_confirmation(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        run = self.start(self.approve(self.start(self.create(['source.md']))))
        old = run
        run = self.api('add-source',id=run['id'],revision=run['revision'],source={'title':'补充材料','text':'补充教学材料记录另一个限制，需要重新完成原文阅读与方法设计。'})
        self.assertIsNone(run['pending_approval'])
        self.assertEqual(run['current_stage'],'g2')
        self.assertEqual(run['stages'][3]['status'],'pending')
        with self.assertRaises(runtime.Conflict): self.approve(old)

    def test_user_stop_interrupts_model_and_never_marks_stage_passed(self):
        def slow(request,cancel):
            cancel.wait(4)
            return self.fake_model(request,cancel)
        with patch.object(runtime,'run_model',slow):
            run = self.api('start',id=(created:=self.create())['id'],revision=created['revision'])
            run = self.api('get',id=run['id'])
            self.api('stop',id=run['id'],revision=run['revision'])
            run = self.settled(run)
        self.assertEqual(run['status'],'interrupted')
        self.assertNotEqual(run['stages'][0]['status'],'passed')
        self.assertIsNone(run['pending_approval'])

    def test_orphan_after_server_restart_becomes_interrupted(self):
        run = self.create()
        code = "import sys,time; from pathlib import Path; import workstation_coursework as r; r.run_model=lambda request,cancel: (cancel.wait(30),{})[1]; s=r.dispatch(Path(sys.argv[1]),{'action':'get','project':'P','id':sys.argv[2]}); r.dispatch(Path(sys.argv[1]),{'action':'start','project':'P','id':s['id'],'revision':s['revision']}); time.sleep(.1)"
        subprocess.run([sys.executable,'-c',code,str(self.root),run['id']],cwd=Path(__file__).parent,check=True,timeout=5)
        run = self.api('get',id=run['id'])
        self.assertEqual(run['status'],'interrupted')
        self.assertNotEqual(run['stages'][0]['status'],'passed')

    def test_graph_edits_cannot_reuse_an_earlier_approval(self):
        run = self.start(self.create())
        path = self.root / 'State/workflows' / (self.workflow_id+'.json')
        graph = json.loads(path.read_text(encoding='utf-8'))
        graph['graph']['nodes'][1]['text'] = 'Changed plan scope'
        path.write_text(json.dumps(graph),encoding='utf-8')
        with self.assertRaises(runtime.Conflict): self.approve(run)
        self.assertEqual(self.api('get',id=run['id'])['status'],'blocked')

    def test_model_cannot_emit_approval_fields(self):
        def injection(request,cancel):
            return dict(self.fake_model(request,cancel),approval='approved')
        with patch.object(runtime,'run_model',injection): run = self.start(self.create())
        self.assertEqual(run['status'],'blocked')
        self.assertIsNone(run['pending_approval'])

    def test_rejected_plan_is_not_bypassed_by_adding_a_source(self):
        run = self.start(self.create())
        run = self.api('approve',id=run['id'],revision=run['revision'],request_id=run['pending_approval']['request_id'],decision='reject',note='Plan not accepted')
        run = self.api('add-source',id=run['id'],revision=run['revision'],source={'title':'材料','text':'教学材料只能补充信息，不能代替人类对研究问题与计划的确认。'})
        self.assertEqual(run['status'],'awaiting_approval')
        self.assertEqual(run['pending_approval']['kind'],'plan')

    def test_path_escape_and_cross_project_artifact_reads_are_rejected(self):
        with self.assertRaises(ValueError): self.create(['../../outside.md'])
        run = self.create()
        with self.assertRaises(ValueError): self.api('artifact',id=run['id'],path='../../state.json')
        with self.assertRaises(ValueError):
            runtime.dispatch(self.root,{'action':'get','project':'../P','id':run['id']})

    def test_malformed_actions_are_value_errors(self):
        for payload in ({'action':[],'project':'P'},{'action':'start','project':'P','id':'x','revision':None}, {'action':'status','project':'P','approval':True}):
            with self.subTest(payload=payload), self.assertRaises(ValueError): runtime.dispatch(self.root,payload)

    def test_review_only_preserves_sources_and_skips_writing_and_humanizer(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        run = self.api('create',workflow_id=self.workflow_id,task={'title':'原稿审查','requirements':'审核证据与论证','mode':'review','source_paths':['source.md']})
        run = self.start(self.approve(self.start(run)))
        run = self.start(self.approve(run))
        self.assertEqual(run['pending_approval']['kind'],'release')
        self.assertNotIn('g6',self.calls)
        self.assertNotIn('g8',self.calls)
        self.assertIn('未改写',self.api('artifact',id=run['id'],path=run['stages'][7]['output_path'])['content'])
        self.assertEqual(source.read_text(encoding='utf-8'),'教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。')

    def test_review_only_can_deliver_completed_audit_of_a_flawed_draft(self):
        source = self.project / 'source.md'
        original_text = '教学案例：营业收入由100增加至120。原稿错误声称政策是唯一原因，但资料无法识别因果关系。'
        source.write_text(original_text,encoding='utf-8')
        original = self.fake_model
        def audit(request,cancel):
            result = original(request,cancel)
            if request['stage'] in {'g7','g9'}:
                result.update(content='审校已完成：原稿存在因果措辞问题，需作者修订。',passed=False,issues=['原稿存在因果措辞问题'])
            return result
        with patch.object(runtime,'run_model',audit):
            run = self.api('create',workflow_id=self.workflow_id,task={'title':'原稿审查','requirements':'只给问题清单','mode':'review','source_paths':['source.md']})
            run = self.start(self.approve(self.start(run)))
            run = self.start(self.approve(run))
        self.assertEqual(run['status'],'awaiting_approval')
        self.assertEqual(run['pending_approval']['kind'],'release')
        self.assertIn('因果措辞',self.api('artifact',id=run['id'],path=run['stages'][6]['output_path'])['content'])
        self.assertEqual(source.read_text(encoding='utf-8'),original_text)
        self.assertNotIn('g8',self.calls)

    def test_negated_empirical_keywords_do_not_block_a_conceptual_assignment(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        run = self.api('create',workflow_id=self.workflow_id,task={'title':'收入案例','requirements':'只做课程案例解释，不要求实证或回归分析','mode':'new','source_paths':['source.md']})
        run = self.start(self.approve(self.start(run)))
        run = self.start(self.approve(run))
        self.assertEqual(run['pending_approval']['kind'],'release')
        self.assertIn('g5',self.calls)

    def test_external_empirical_output_requires_real_input_method_and_output_evidence(self):
        source = self.project / 'source.md'
        source.write_text('输入记录：营业收入由100增加至120。\n方法记录：用户在本地运行脚本finance.py，输入仅两个年度，采用差额计算。\n输出记录：本地日志显示收入变动为20，不能进行因果识别。',encoding='utf-8')
        original = self.fake_model
        def empirical(request,cancel):
            result = original(request,cancel)
            if request['stage'] == 'g3':
                result['extractions'] = [
                    {'source_id':'S0001','quote':'营业收入由100增加至120','locator':'输入记录','claim':'输入数据'},
                    {'source_id':'S0001','quote':'用户在本地运行脚本finance.py，输入仅两个年度，采用差额计算','locator':'方法记录','claim':'外部方法与执行范围'},
                    {'source_id':'S0001','quote':'本地日志显示收入变动为20，不能进行因果识别','locator':'输出记录','claim':'外部输出与局限'}]
            if request['stage'] in {'g4','g5'}:
                result['analysis'] = {'kind':'external-output','input_evidence_ids':['E0001'],'method_evidence_ids':['E0002'],'output_evidence_ids':['E0003'],'limitations':'用户提供外部运行记录，控制器没有执行或复现。'}
            if request['stage'] == 'g5':
                result['content'] = '输入收入为100和120[E0001]。\n\n用户提供本地脚本与差额方法记录[E0002]。\n\n用户提供输出变动为20，不能识别因果关系[E0003]。'
                result['claims'] = [{'id':'C001','text':'输入收入为100和120','type':'source','evidence_ids':['E0001']}, {'id':'C002','text':'用户提供本地脚本与差额方法记录','type':'source','evidence_ids':['E0002']}, {'id':'C003','text':'用户提供输出变动为20，不能识别因果关系','type':'source','evidence_ids':['E0003']}]
            return result
        with patch.object(runtime,'run_model',empirical):
            run = self.api('create',workflow_id=self.workflow_id,task={'title':'收入实证记录分析','requirements':'依据已提供实际计算输出解释收入，不要求本次运行代码','mode':'new','source_paths':['source.md']})
            run = self.start(self.approve(self.start(run)))
            run = self.start(self.approve(run))
        self.assertEqual(run['pending_approval']['kind'],'release')
        self.assertIn('g5',self.calls)

    def test_editing_verified_card_content_invalidates_old_method_confirmation(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        run = self.start(self.approve(self.start(self.create(['source.md']))))
        index = self.project / '08_evidence/coursework-runs' / run['id'] / 'evidence-store/index.json'
        data = json.loads(index.read_text(encoding='utf-8'))
        data['evidence'][0]['text'] = '该数据只是模拟资料，无法识别因果关系。'
        data['evidence'][0]['claim'] = 'A changed claim'
        index.write_text(json.dumps(data,ensure_ascii=False),encoding='utf-8')
        with self.assertRaises(runtime.Conflict): self.approve(run)
        self.assertIsNone(self.api('get',id=run['id'])['pending_approval'])

    def test_linked_reference_body_is_provided_to_read_only_model(self):
        skill = self.project / '.agents/skills/demo'
        (skill / 'references').mkdir(parents=True)
        path = skill / 'SKILL.md'
        path.write_text('---\nname: demo\ndescription: Test policy references.\n---\nRead references/contract.md',encoding='utf-8')
        (skill / 'references/contract.md').write_text('UNIQUE_REFERENCE_POLICY: every fact needs an original locator.',encoding='utf-8')
        catalog = runtime.flows.dispatch(self.root,{'action':'catalog','project':'P'})
        resource = next(r for r in catalog['items'] if Path(r['path']) == path)
        self.graph['nodes'].append(dict(id='policy',type='skill',label='demo',text='Extra node policy',x=0,y=1,source_id=resource['id'],source_revision=resource['revision']))
        self.graph['edges'].append({'from':'policy','to':'g1'})
        workflow = self.root / 'State/workflows' / (self.workflow_id+'.json')
        workflow.write_text(json.dumps({'updated_at':'test','graph':self.graph}),encoding='utf-8')
        observed = []
        def capture(request,cancel):
            observed.append(request)
            return self.fake_model(request,cancel)
        with patch.object(runtime,'run_model',capture): run = self.start(self.create())
        self.assertEqual(run['status'],'awaiting_approval')
        self.assertIn('UNIQUE_REFERENCE_POLICY',json.dumps(observed[0],ensure_ascii=False))
        self.assertIn('Extra node policy',json.dumps(observed[0],ensure_ascii=False))

    def test_cli_error_is_not_masked_by_descendant_retaining_stderr_or_temp_file(self):
        real_popen = subprocess.Popen
        children = []
        directories = []
        def process_boundary(command,**kwargs):
            directory = Path(command[command.index('--output-schema')+1]).parent
            directories.append(directory)
            # This represents an external CLI child that outlives its parent,
            # retains stderr, and on Windows temporarily holds a temp log open.
            child_code = 'import sys,time; f=open(sys.argv[1],"wb"); time.sleep(.8); f.close()'
            parent_code = 'import subprocess,sys; sys.stdin.buffer.read(); subprocess.Popen([sys.executable,"-c",sys.argv[1],sys.argv[2]],stderr=sys.stderr); sys.stderr.write("stream idle timeout\\n"); sys.stderr.flush(); raise SystemExit(3)'
            process = real_popen([sys.executable,'-c',parent_code,child_code,str(directory/'process.log')],**kwargs)
            children.append(process)
            return process
        request = {'stage':'g1','project_dir':str(self.project)}
        with patch.object(runtime,'cli_status',return_value={'logged_in':True,'path':sys.executable}), patch.object(runtime.subprocess,'Popen',process_boundary):
            with self.assertRaisesRegex(ValueError,'流连接等待超时'):
                # Restore only the real external adapter for this process test.
                CourseworkTests.real_model_runner(request,threading.Event())
        time.sleep(.9)
        for directory in directories:
            if directory.exists():
                import shutil
                shutil.rmtree(directory)

    def test_cli_that_never_reads_large_stdin_still_obeys_timeout(self):
        real_popen = subprocess.Popen
        def no_read_boundary(command,**kwargs):
            if command[0] == 'taskkill': return real_popen(command,**kwargs)
            return real_popen([sys.executable,'-c','import time; time.sleep(30)'],**kwargs)
        request = {'stage':'g1','project_dir':str(self.project),'large_policy':'x'*300000}
        before = time.monotonic()
        with patch.object(runtime,'cli_status',return_value={'logged_in':True,'path':sys.executable}), patch.object(runtime.subprocess,'Popen',no_read_boundary), patch.object(runtime,'PLAN_TIMEOUT_SECONDS',.25):
            with self.assertRaisesRegex(ValueError,'超过0.25秒'):
                CourseworkTests.real_model_runner(request,threading.Event())
        self.assertLess(time.monotonic()-before,4)

    def test_required_calculation_without_output_stays_blocked_after_method_gate(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        original = self.fake_model
        def missing_execution(request,cancel):
            result = original(request,cancel)
            if request['stage'] == 'g4':
                result['analysis'] = {'kind':'execution-required','input_evidence_ids':['E0001'],'method_evidence_ids':[],'output_evidence_ids':[],'limitations':'没有实际回归运行记录。'}
            return result
        with patch.object(runtime,'run_model',missing_execution):
            run = self.api('create',workflow_id=self.workflow_id,task={'title':'实证练习','requirements':'实际运行回归并报告结果','mode':'new','source_paths':['source.md']})
            run = self.start(self.approve(self.start(run)))
            run = self.start(self.approve(run))
        self.assertEqual(run['status'],'blocked')
        self.assertEqual(run['current_stage'],'g5')
        self.assertNotIn('g6',self.calls)
        self.assertIn('实际计算',run['error'])

    def test_review_itself_missing_evidence_still_blocks_audit_delivery(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        original = self.fake_model
        def incomplete_audit(request,cancel):
            result = original(request,cancel)
            if request['stage'] == 'g7': result.update(passed=False,issues=['无法核对待审稿件'],blocked_reason='未提供完整原稿，审校未完成。')
            return result
        with patch.object(runtime,'run_model',incomplete_audit):
            run = self.api('create',workflow_id=self.workflow_id,task={'title':'原稿审查','requirements':'检查全部原稿','mode':'review','source_paths':['source.md']})
            run = self.start(self.approve(self.start(run)))
            run = self.start(self.approve(run))
        self.assertEqual(run['status'],'blocked')
        self.assertEqual(run['current_stage'],'g7')
        self.assertNotIn('g9',self.calls)

    def test_approved_method_evidence_is_kept_when_lexical_query_does_not_match_it(self):
        source = self.project / 'source.md'
        source.write_text('收入输入记录：营业收入由100增加至120。\nModel: ordinary least squares; recorded command and version.\n收入输出记录：已经运行，系数为0.2。',encoding='utf-8')
        original = self.fake_model
        packets = {}
        def empirical(request,cancel):
            result = original(request,cancel)
            if request['stage'] == 'g3':
                result['extractions'] = [
                    {'source_id':'S0001','quote':'收入输入记录：营业收入由100增加至120','locator':'L1','claim':'收入资料'},
                    {'source_id':'S0001','quote':'Model: ordinary least squares; recorded command and version.','locator':'L2','claim':'method specification'},
                    {'source_id':'S0001','quote':'收入输出记录：已经运行，系数为0.2','locator':'L3','claim':'收入资料'}]
            if request['stage'] in {'g4','g5'}:
                result['analysis'] = {'kind':'external-output','input_evidence_ids':['E0001'],'method_evidence_ids':['E0002'],'output_evidence_ids':['E0003'],'limitations':'外部提供输出，未在本控制器复现。'}
            if request['stage'] in {'g5','g6'}:
                packets[request['stage']] = request['extra']
                result['content'] = '输入收入为100和120[E0001]。\n\n外部提供最小二乘方法记录[E0002]。\n\n外部提供输出系数为0.2[E0003]。'
                result['claims'] = [{'id':'C001','text':'输入收入为100和120','type':'source','evidence_ids':['E0001']}, {'id':'C002','text':'外部提供最小二乘方法记录','type':'source','evidence_ids':['E0002']}, {'id':'C003','text':'外部提供输出系数为0.2','type':'source','evidence_ids':['E0003']}]
            if request['stage'] == 'g8':
                result['content'] = '输入收入为100和120[E0001]。\n\n外部提供最小二乘方法记录[E0002]。\n\n外部提供输出系数为0.2[E0003]。'
                result['claims'] = [{'id':'C001','text':'输入收入为100和120','type':'source','evidence_ids':['E0001']}, {'id':'C002','text':'外部提供最小二乘方法记录','type':'source','evidence_ids':['E0002']}, {'id':'C003','text':'外部提供输出系数为0.2','type':'source','evidence_ids':['E0003']}]
            return result
        with patch.object(runtime,'run_model',empirical):
            run = self.api('create',workflow_id=self.workflow_id,task={'title':'收入实证','requirements':'收入实证：讨论已有资料。','mode':'new','source_paths':['source.md']})
            run = self.start(self.approve(self.start(run)))
            run = self.start(self.approve(run))
        self.assertEqual(run['status'],'awaiting_approval')
        self.assertEqual(run['pending_approval']['kind'],'release')
        for stage in ('g5','g6'):
            self.assertIn('E0002',[row['id'] for row in packets[stage]['evidence_packet']['evidence']])
            self.assertNotIn('E0002',packets[stage]['retrieval']['ranked_evidence_ids'])
            self.assertIn('E0002',packets[stage]['retrieval']['required_evidence_ids'])

    def test_unknown_method_dependency_is_not_silently_dropped_by_retrieval(self):
        source = self.project / 'source.md'
        source.write_text('教学案例：营业收入由100增加至120。该数据只是模拟资料，无法识别因果关系。',encoding='utf-8')
        original = self.fake_model
        def unknown_method(request,cancel):
            result = original(request,cancel)
            if request['stage'] == 'g4':
                result['analysis'] = {'kind':'external-output','input_evidence_ids':['E0001'],'method_evidence_ids':['E9999'],'output_evidence_ids':['E0001'],'limitations':'测试未知依赖不得静默忽略。'}
            return result
        with patch.object(runtime,'run_model',unknown_method):
            run = self.start(self.approve(self.start(self.create(['source.md']))))
            run = self.start(self.approve(run))
        self.assertEqual(run['status'],'blocked')
        self.assertEqual(run['current_stage'],'g5')
        self.assertNotIn('g5',self.calls)


CourseworkTests.real_model_runner = staticmethod(runtime.run_model)


if __name__ == '__main__':
    unittest.main()
