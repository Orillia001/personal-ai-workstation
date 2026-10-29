"""Public workflow dispatch tests. Fictitious metadata, isolated files, no providers."""
import copy
import tempfile
import unittest
from pathlib import Path

import workstation_workflows as flows
import workstation_codex_manage as rules


def model(ident, score, price=1, **changes):
    return dict(id=ident, provider='fixture', model=ident, enabled=True, local=False,
                capabilities=['text', 'code'], quality=score, context_tokens=100000,
                max_output_tokens=8000, input_usd_per_million=price,
                output_usd_per_million=price, **changes)


class ModelRouterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'station'; self.home = Path(self.tmp.name) / 'profile'
        (self.root / 'Projects/demo').mkdir(parents=True); self.home.mkdir()
        self.g = dict(name='routing', project='demo', view=dict(x=9,y=3,scale=.8), nodes=[
            dict(id=i, type=t, label=i, x=0,y=0,text=body,source_id='',source_revision='')
            for i,t,body in [('task','input','Write a small program'),('agent','agent',''),('out','output','')]],
            edges=[dict(from_='task',to='agent'),dict(from_='agent',to='out')])
        for e in self.g['edges']: e['from']=e.pop('from_')

    def call(self, action, **kw):
        return flows.dispatch(self.root,dict(action=action,**kw),home=self.home)

    def pool(self, items):
        return self.call('save-models', revision=self.call('models')['revision'], models=items)

    def route(self): return self.call('preview',graph=self.g)['blocks'][0]['routing']

    def policy(self, **kw):
        self.g['nodes'][1]['routing']=dict(mode='auto',model_id='',strategy='quality',capabilities=['text'],
            local_only=False,budget_usd=1,input_tokens=1000,output_tokens=2000) | kw

    def test_empty_pool_is_honest_and_old_graph_roundtrips(self):
        self.assertEqual(self.call('models')['models'],[])
        self.assertFalse((self.root/'State/model-router').exists())
        saved=self.call('save',id='',revision='new',graph=self.g)
        self.assertEqual(self.call('load',id=saved['id'])['graph'],self.g)
        result=self.call('preview',graph=self.g)
        self.assertEqual(result['blocks'][0]['routing']['status'],'blocked')
        self.assertIn('模型池为空',result['markdown']); self.assertFalse(result['executed'])

    def test_quality_first_not_cheapest_with_stable_ties(self):
        self.pool([model('cheap',30,.01),model('best-b',95,5),model('best-a',95,5)])
        self.assertEqual(self.route()['selected']['id'],'best-a')
        self.assertIn('评分',self.route()['reason'])

    def test_over_budget_and_unknown_prices_excluded_before_ranking(self):
        self.policy(budget_usd=.01)
        unknown=model('unknown',100);unknown['input_usd_per_million']=None
        self.pool([model('too-expensive',100,100),unknown,model('fits',60,1)])
        result=self.route();self.assertEqual(result['selected']['id'],'fits')
        self.assertIn('超出',str(result['candidates']));self.assertIn('单价未知',str(result['candidates']))

    def test_all_hard_constraints_and_manual_do_not_bypass_them(self):
        self.policy(mode='manual',model_id='cloud',local_only=True,capabilities=['text','vision'])
        cloud=model('cloud',99);small=model('small',80);small.update(local=True,capabilities=['text','vision'],context_tokens=500)
        disabled=model('disabled',99);disabled['enabled']=False
        limited=model('limited',99);limited.update(local=True,capabilities=['text','vision'],max_output_tokens=500)
        self.pool([cloud,small,disabled,limited])
        result=self.route();self.assertEqual(result['status'],'blocked')
        for reason in ['仅本地','缺少能力','上下文','未启用','输出上限']:
            self.assertIn(reason,str(result['candidates']))

    def test_exact_budget_boundary_no_rounding_bypass(self):
        self.policy(input_tokens=1000,output_tokens=2000,budget_usd=.003)
        self.pool([model('exact',90,1)])
        self.assertEqual(self.route()['status'],'selected')
        self.policy(input_tokens=1000,output_tokens=2000,budget_usd=.002999999)
        self.assertEqual(self.route()['status'],'blocked')

    def test_composed_rules_and_previous_output_count_toward_context(self):
        self.policy(input_tokens=1,output_tokens=10)
        self.g['nodes'][0]['text']='中文'*100
        self.pool([model('small',95)]);p=self.call('models')['models'][0];p['context_tokens']=300
        self.pool([p]);self.assertEqual(self.route()['status'],'blocked')
        p['context_tokens']=20000;self.pool([p])
        n=copy.deepcopy(self.g['nodes'][1]);n['id']='later';n['routing']['input_tokens']=1
        self.g['nodes'].insert(2,n);self.g['edges']=[{'from':'task','to':'agent'},{'from':'agent','to':'later'},{'from':'later','to':'out'}]
        result=self.call('preview',graph=self.g)
        self.assertGreaterEqual(result['blocks'][1]['routing']['input_tokens'],10)
        p['enabled']=False;self.pool([p]);result=self.call('preview',graph=self.g)
        self.assertIn('上游',result['blocks'][1]['routing']['reason'])

    def test_revision_conflict_preserves_newer_pool(self):
        old=self.call('models')['revision'];self.pool([model('newer',80)])
        with self.assertRaises(rules.Conflict):self.call('save-models',revision=old,models=[])
        self.assertEqual(self.call('models')['models'][0]['id'],'newer')

    def test_explicit_policy_roundtrip_and_valid_manual_selection(self):
        self.pool([model('high',95,1),model('manual-choice',70,1)])
        self.policy(mode='manual',model_id='manual-choice',capabilities=['text','code'])
        saved=self.call('save',id='',revision='new',graph=self.g)
        loaded=self.call('load',id=saved['id'])['graph']
        self.assertEqual(loaded,self.g)
        selected=self.call('preview',graph=loaded)['blocks'][0]['routing']
        self.assertEqual(selected['selected']['id'],'manual-choice')
        self.assertFalse(selected['verified'])

    def test_registry_rejects_secrets_duplicates_invalid_and_unknown_fields(self):
        for changes in [{'api_key':'secret'},{'quality':float('nan')},{'enabled':'true'},
                        {'capabilities':['bogus']},{'context_tokens':True},{'output_usd_per_million':-1}]:
            p=model('x',80);p.update(changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.pool([p])
        with self.assertRaises(ValueError):self.pool([model('x',80),model('x',90)])
        with self.assertRaises(ValueError):self.call('models',path='../outside')
        for changes in [{'mode':'execute'},{'budget_usd':None},{'local_only':1},{'model_id':[]}]:
            self.policy(**changes)
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.call('save',id='',revision='new',graph=self.g)
        self.policy();self.g['nodes'][0]['routing']=self.g['nodes'][1]['routing']
        with self.assertRaises(ValueError):self.call('preview',graph=self.g)
        del self.g['nodes'][0]['routing'];self.g['nodes'][1]['routing']=None
        with self.assertRaises(ValueError):self.call('save',id='',revision='new',graph=self.g)


if __name__=='__main__':unittest.main()
