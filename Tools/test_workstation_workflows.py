"""Public draft/composition API checks; all writes use isolated fixtures."""
import copy
import tempfile
import unittest
from pathlib import Path
import workstation_workflows as flows
import workstation_codex_manage as rules


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root, self.home = self.base / 'station', self.base / 'profile/.codex'
        (self.root / 'Projects/demo').mkdir(parents=True)
        self.home.mkdir(parents=True)
        self.skill = self.home / 'skills/selected/SKILL.md'
        self.skill.parent.mkdir(parents=True)
        self.skill.write_text('---\nname: selected\ndescription: Describe samples.\n---\nSELECTED SKILL INSTRUCTION', encoding='utf-8')
        self.rule = self.home / 'AGENTS.md'; self.rule.write_text('SELECTED RULE INSTRUCTION', encoding='utf-8')
        role = self.home / 'agents/reviewer.toml'; role.parent.mkdir()
        role.write_text('name="reviewer"\ndescription="Review"\ndeveloper_instructions="ROLE INSTRUCTION"\n', encoding='utf-8')
        self.sources = {r['kind']: r for r in self.call('catalog')['items']}
        def node(ident, kind, body=''):
            src = self.sources.get(kind, {})
            return {'id': ident, 'type': kind, 'label': ident, 'x': 10, 'y': 20, 'text': body,
                    'source_id': src.get('id', ''), 'source_revision': src.get('revision', '')}
        self.graph = {'name': 'Example graph', 'project': 'demo', 'nodes': [node('task', 'input', 'TASK CONTENT'),
            node('skill', 'skill'), node('rule', 'rule'), node('role', 'role'), node('first', 'agent', 'FIRST STEP'),
            node('second', 'agent', 'SECOND STEP'), node('out', 'output', 'Expected report')],
            'edges': [{'from': 'task', 'to': 'first'}, {'from': 'skill', 'to': 'first'}, {'from': 'rule', 'to': 'first'},
                {'from': 'role', 'to': 'first'}, {'from': 'first', 'to': 'second'}, {'from': 'second', 'to': 'out'}],
            'view': {'x': 79, 'y': -52, 'scale': .7}}

    def call(self, action, **kwargs):
        return flows.dispatch(self.root, {'action': action, **kwargs}, home=self.home)

    def test_saved_graph_roundtrip_keeps_content_view_and_positions(self):
        result = self.call('save', id='', revision='new', graph=self.graph)
        loaded = self.call('load', id=result['id'])
        self.assertEqual(loaded['graph'], self.graph)
        self.assertEqual(result['revision'], loaded['revision'])
        self.assertEqual(self.call('list')['items'][0]['name'], 'Example graph')

    def test_stale_page_cannot_overwrite(self):
        first = self.call('save', id='', revision='new', graph=self.graph)
        newer = copy.deepcopy(self.graph); newer['name'] = 'NEWER'
        self.call('save', id=first['id'], revision=first['revision'], graph=newer)
        with self.assertRaises(rules.Conflict): self.call('save', id=first['id'], revision=first['revision'], graph=self.graph)
        self.assertEqual(self.call('load', id=first['id'])['graph']['name'], 'NEWER')

    def test_preview_composes_only_connected_rules_and_result_placeholders(self):
        before = self.skill.read_bytes(), self.rule.read_bytes()
        result = self.call('preview', graph=self.graph)
        first, second = result['blocks']
        for expected in ['SELECTED SKILL INSTRUCTION', 'SELECTED RULE INSTRUCTION', 'ROLE INSTRUCTION', 'TASK CONTENT']:
            self.assertIn(expected, first['content'])
        self.assertNotIn('developer_instructions=', first['content'])
        self.assertIn('{{result:first}}', second['content'])
        self.assertNotIn('SELECTED RULE INSTRUCTION', second['content'])
        self.assertEqual(result['outputs'][0]['from'], ['second'])
        self.assertFalse(result['executed'])
        self.assertEqual(before, (self.skill.read_bytes(), self.rule.read_bytes()))

    def test_disconnected_source_is_reported_unused(self):
        self.graph['edges'] = [e for e in self.graph['edges'] if e['from'] != 'skill']
        result = self.call('preview', graph=self.graph)
        self.assertNotIn('SELECTED SKILL INSTRUCTION', result['markdown'])
        self.assertIn('skill：没有下游使用此节点', result['warnings'])

    def test_changed_source_requires_rebinding(self):
        self.skill.write_text('UPDATED', encoding='utf-8')
        with self.assertRaises(rules.Conflict): self.call('preview', graph=self.graph)
        self.graph['nodes'][1]['source_revision'] = next(r['revision'] for r in self.call('catalog')['items'] if r['kind'] == 'skill')
        self.assertIn('UPDATED', self.call('preview', graph=self.graph)['markdown'])

    def test_disabled_source_is_not_composed(self):
        self.skill.rename(self.skill.with_name('SKILL.md.disabled'))
        with self.assertRaisesRegex(ValueError, '停用'): self.call('preview', graph=self.graph)

    def test_unknown_plugin_cache_is_not_usable(self):
        entry = self.home / 'plugins/cache/vendor/plugin/1/skills/cached/SKILL.md'
        entry.parent.mkdir(parents=True); entry.write_text('---\nname: cached\ndescription: Sample\n---\n', encoding='utf-8')
        cached = next(r for r in self.call('catalog')['items'] if r['scope'] == 'readonly')
        self.assertFalse(cached['usable'])
        self.graph['nodes'][1].update(source_id=cached['id'], source_revision=cached['revision'])
        with self.assertRaises(ValueError): self.call('preview', graph=self.graph)

    def test_cycle_and_wrong_link_types_rejected(self):
        for edge in [{'from': 'second', 'to': 'first'}, {'from': 'skill', 'to': 'out'}]:
            graph = copy.deepcopy(self.graph); graph['edges'].append(edge)
            with self.subTest(edge=edge), self.assertRaises(ValueError): self.call('preview', graph=graph)

    def test_draft_can_be_saved_before_semantic_completion(self):
        self.graph['edges'] = []
        saved = self.call('save', id='', revision='new', graph=self.graph)
        self.assertEqual(self.call('load', id=saved['id'])['graph']['edges'], [])
        with self.assertRaises(ValueError): self.call('preview', graph=self.graph)

    def test_graph_and_request_boundaries(self):
        for action, fields in [('load', {'id': '../outside'}), ('list', {'path': 'C:/anything'}), ('run', {}), ('save', {'id': [], 'revision': 'new', 'graph': self.graph})]:
            with self.subTest(action=action), self.assertRaises(ValueError): self.call(action, **fields)
        for value in [float('nan'), 100001, 'x']:
            graph = copy.deepcopy(self.graph); graph['view']['x'] = value
            with self.subTest(value=value), self.assertRaises(ValueError): self.call('save', id='', revision='new', graph=graph)
        graph = copy.deepcopy(self.graph); graph['nodes'][0]['type'] = []
        with self.assertRaises(ValueError): self.call('preview', graph=graph)


if __name__ == '__main__': unittest.main()
