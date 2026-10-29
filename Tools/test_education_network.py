import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from education_network import network_data


class NetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'Config').mkdir()
        self.config = {'subjects': {c: {'name': c, 'graph': f'{c}.json'} for c in ['alpha', 'beta']}}
        (self.root / 'Config/teaching.json').write_text(json.dumps(self.config), encoding='utf-8')
        for c in self.config['subjects']:
            graph = {'course': c, 'nodes': [
                {'id': 'module', 'title': f'{c}模块', 'kind': 'module', 'body': '说明', 'sources': []},
                {'id': 'node', 'title': f'{c}知识', 'body': '<script>数据</script>',
                 'sources': [{'path': 'never-open.pdf', 'pdf_page': 8}, {'pdf_page': 8}, {'pdf_page': 3}]}
            ], 'edges': [{'from': 'module', 'to': 'node', 'kind': 'contains'}]}
            (self.root / f'{c}.json').write_text(json.dumps(graph), encoding='utf-8')

    def test_catalog_does_not_open_graphs_or_sources(self):
        original = Path.read_text
        reads = []
        def read(path, *args, **kwargs):
            reads.append(path.name)
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            self.assertEqual(len(network_data(self.root)['courses']), 2)
        self.assertEqual(reads, ['teaching.json'])

    def test_subject_isolation_and_page_projection(self):
        a = network_data(self.root, 'alpha')
        self.assertTrue(all(n['title'].startswith('alpha') for n in a['nodes']))
        self.assertEqual(a['nodes'][1]['pages'], [3, 8])
        self.assertNotIn('sources', a['nodes'][1])
        self.assertEqual(a['nodes'][1]['body'], '<script>数据</script>')
        self.assertEqual(a['edges'][0]['kind'], 'contains')

    def test_unknown_subject_and_traversal_are_rejected(self):
        for course in ['../beta', '', 'unknown', 'alpha/../../Config/teaching']:
            with self.subTest(course=course), self.assertRaises(ValueError):
                network_data(self.root, course)

    def test_invalid_graph_is_rejected(self):
        path = self.root / 'alpha.json'
        graph = json.loads(path.read_text())
        graph['edges'][0]['to'] = 'missing'
        path.write_text(json.dumps(graph), encoding='utf-8')
        with self.assertRaises(ValueError):
            network_data(self.root, 'alpha')

    def test_graph_access_cannot_escape_station(self):
        self.config['subjects']['alpha']['graph'] = '../outside.json'
        (self.root / 'Config/teaching.json').write_text(json.dumps(self.config), encoding='utf-8')
        with self.assertRaises(ValueError):
            network_data(self.root, 'alpha')


if __name__ == '__main__':
    unittest.main()
