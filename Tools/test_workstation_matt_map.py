"""Public read-only map and project workflow interfaces, isolated filesystem."""
import json
import tempfile
import unittest
from pathlib import Path

import workstation_matt_map as matt
import workstation_workflows as flows


class MattMapTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'station';self.home=Path(self.tmp.name)/'home'
        for project in ('A','B'):(self.root/'Projects'/project).mkdir(parents=True)
        self.home.mkdir()

    def call(self,action,project='A',**kw):
        return flows.dispatch(self.root,dict(action=action,project=project,**kw),home=self.home)

    def graph(self,project):
        return dict(name='draft',project=project,nodes=[],edges=[],view=dict(x=12,y=7,scale=.8))

    def test_map_has_codex_full_main_flow_branches_and_no_false_execution(self):
        value=matt.snapshot(self.root,home=self.home)
        self.assertEqual(value['actor']['id'],'codex');self.assertEqual(len(value['stages']),9)
        self.assertEqual(value['router']['skills'],['ask-matt'])
        names={s['id'] for s in value['skills']}
        for name in ['wayfinder','triage','diagnosing-bugs','handoff','tdd','pr','retro','grill-with-docs']:
            self.assertIn(name,names)
        self.assertTrue(all(not s['available'] for s in value['skills']))
        self.assertEqual(value['tasks'],[]);self.assertFalse((self.root/'.scratch').exists())

    def test_only_explicit_valid_records_and_installed_sources_are_mapped(self):
        folder=self.root/'.scratch/example';folder.mkdir(parents=True)
        record=dict(schema_version=1,task='example',project='A',title='fixture',status='running',updated_at='2026-10-22T00:00:00Z',
                    stages=[dict(id='implement',status='running',note='record only',evidence=[],updated_at='2026-10-22T00:00:00Z')])
        path=folder/'matt-workflow.json';raw=json.dumps(record);path.write_text(raw,encoding='utf-8')
        skill=self.home/'skills/ask-matt/SKILL.md';skill.parent.mkdir(parents=True);skill.write_text('---\nname: ask-matt\ndescription: fixture\n---\n',encoding='utf-8')
        value=matt.snapshot(self.root,home=self.home)
        self.assertEqual(path.read_text(encoding='utf-8'),raw)
        self.assertEqual(value['tasks'][0]['stages'][0]['status'],'running')
        self.assertTrue(next(s for s in value['skills'] if s['id']=='ask-matt')['available'])
        self.assertEqual(len(value['tasks'][0]['stages']),1)
        record['task']='different';path.write_text(json.dumps(record),encoding='utf-8')
        value=matt.snapshot(self.root,home=self.home);self.assertEqual(value['tasks'],[]);self.assertTrue(value['warnings'])

    def test_records_reject_unknown_stage_and_outside_evidence(self):
        folder=self.root/'.scratch/example';folder.mkdir(parents=True)
        base=dict(schema_version=1,task='example',project='A',title='fixture',status='completed',updated_at='today')
        path=folder/'matt-workflow.json'
        for stage in [dict(id='execute-secret',status='completed',note='',evidence=[]),dict(id='spec',status='completed',note='',evidence=['../../outside'])]:
            path.write_text(json.dumps(base|dict(stages=[stage])),encoding='utf-8')
            value=matt.snapshot(self.root,home=self.home);self.assertEqual(value['tasks'],[]);self.assertTrue(value['warnings'])

    def test_project_workflow_binding_and_old_unscoped_compatibility(self):
        saved=self.call('save',id='',revision='new',graph=self.graph('A'))
        self.assertEqual(len(self.call('list')['items']),1);self.assertEqual(self.call('list',project='B')['items'],[])
        with self.assertRaises(ValueError):self.call('load',project='B',id=saved['id'])
        with self.assertRaises(ValueError):self.call('save',id='',revision='new',graph=self.graph('B'))
        loaded=flows.dispatch(self.root,dict(action='load',id=saved['id']),home=self.home)
        self.assertEqual(loaded['graph']['project'],'A')
        with self.assertRaises(ValueError):self.call('models',project='../A')

    def test_project_model_pool_and_rule_catalog_do_not_mix(self):
        model=dict(id='test',provider='fixture',model='offline',enabled=True,local=True,capabilities=['text'],quality=70,
                   context_tokens=4000,max_output_tokens=2000,input_usd_per_million=0,output_usd_per_million=0)
        self.call('save-models',revision='new',models=[model])
        self.assertEqual(len(self.call('models')['models']),1);self.assertEqual(self.call('models',project='B')['models'],[])
        self.assertEqual(flows.dispatch(self.root,dict(action='models'),home=self.home)['models'],[])
        for p in ('A','B'):(self.root/'Projects'/p/'AGENTS.md').write_text(p,encoding='utf-8')
        items=self.call('catalog')['items'];self.assertTrue(any(i['scope']=='project:A' for i in items));self.assertFalse(any(i['scope']=='project:B' for i in items))


if __name__=='__main__':unittest.main()
