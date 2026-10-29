import tempfile
import unittest
from pathlib import Path

from workstation_evidence import EvidenceStore


class EvidenceStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'Projects' / 'Finance'
        self.project.mkdir(parents=True)
        self.run = self.project / '08_evidence' / 'coursework-runs' / 'run-1'
        self.source = self.project / '01_sources' / 'report.md'
        self.source.parent.mkdir()
        self.source.write_text('# 模拟年报\n\n2025年收入同比增长20%，金额为120百万元。\n\n同期借款利率下降1个百分点，但未建立因果关系。', encoding='utf-8')
        self.store = EvidenceStore(self.project, self.run)

    def test_registered_exact_quote_can_be_retrieved_with_provenance_after_reopen(self):
        source = self.store.ingest({'path': '01_sources/report.md', 'title': '模拟年报'})
        card = self.store.extract(source['id'], '2025年收入同比增长20%，金额为120百万元。', '收入段', '收入增长20%')
        restored = EvidenceStore(self.project, self.run)
        result = restored.search('收入增长')
        self.assertEqual([item['id'] for item in result], [card['id']])
        self.assertIn('L3', result[0]['locator'])
        self.assertEqual(restored.packet([card['id']])['sources'][0]['id'], source['id'])
        self.assertEqual(restored.search('区块链保险衍生品'), [])

    def test_changed_source_invalidates_quote_search_and_packet(self):
        source = self.store.ingest({'path': '01_sources/report.md'})
        card = self.store.extract(source['id'], '2025年收入同比增长20%，金额为120百万元。', '收入段', '收入增长20%')
        self.source.write_text('Changed original source', encoding='utf-8')
        for operation in [self.store.validate, lambda: self.store.search('收入'), lambda: self.store.packet([card['id']])]:
            with self.assertRaises(ValueError):
                operation()

    def test_metadata_or_unverified_quotes_never_become_evidence(self):
        source = self.store.ingest({'text': '标题提示：金融政策与企业收入\n作者和正文均未知。', 'url': 'https://example.org/metadata'})
        self.assertFalse(source['remote_fetched'])
        self.assertEqual(source['access_scope'], 'pasted_excerpt')
        self.assertEqual(self.store.search('金融政策'), [])
        with self.assertRaises(ValueError):
            self.store.extract(source['id'], '收入增长达到32%，政策产生显著效果。', '虚构位置', '增长32%')
        with self.assertRaises(ValueError):
            self.store.extract(source['id'], '标题提示：金融政策与企业收入\n作者和正文均未知。', '全文', '政策影响收入')
        with self.assertRaises(ValueError):
            self.store.packet(['E9999'])

    def test_rejects_external_paths_other_run_and_unsupported_text_formats(self):
        outside = self.project.parent / 'outside.md'
        outside.write_text('out of project private material', encoding='utf-8')
        invalid_sources = [
            {'path': '../outside.md'}, {'path': str(outside)},
            {'path': '01_sources/report.md', 'text': 'ambiguous'},
            {'path': '01_sources/no.pdf'},
        ]
        for source in invalid_sources:
            with self.assertRaises(ValueError):
                self.store.ingest(source)
        with self.assertRaises(ValueError):
            EvidenceStore(self.project, self.project.parent / 'other' / 'run')

    def test_extraction_raw_context_reports_scope_instead_of_silent_truncation(self):
        source = self.store.ingest({'text': '原文第一段包含正式收入统计。\n' + '利率调整资料。' * 20000})
        self.assertEqual(self.store.evidence(), [])
        with self.assertRaisesRegex(ValueError, 'nothing was silently truncated'):
            self.store.raw_context()
        card = self.store.extract(source['id'], '原文第一段包含正式收入统计。', '第1段', '包含收入统计')
        self.assertEqual(card['locator'], 'L1-L1; chars 1-14')

    def test_malformed_index_is_reported_as_bounded_validation_error(self):
        # Public constructor must refuse a corrupt persisted run, rather than
        # exposing raw programming exceptions to its controller/UI caller.
        directory = self.run / 'evidence-store'
        (directory / 'index.json').write_text('[]', encoding='utf-8')
        with self.assertRaises(ValueError):
            EvidenceStore(self.project, self.run).validate()

    def test_original_relative_paths_cannot_escape_through_symlinks(self):
        outside = self.project.parent / 'private.md'
        outside.write_text('Private source outside project; must not be imported.', encoding='utf-8')
        linked = self.source.parent / 'linked.md'
        try:
            linked.symlink_to(outside)
        except OSError as error:
            self.skipTest(f'Symlink creation not available on this host: {error}')
        with self.assertRaises(ValueError):
            self.store.ingest({'path': '01_sources/linked.md'})
        self.assertEqual(self.store.sources(), [])

    def test_registered_source_copy_changes_are_detected_without_original_mutation(self):
        source = self.store.ingest({'text': '第一段是待提取内容，收入增长20%。\n第二段提供背景。'})
        self.store.extract(source['id'], '第一段是待提取内容，收入增长20%。', '第一段', '收入增长20%')
        (self.run / source['body_path']).write_text('篡改后的数据。', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.store.packet()

    def test_run_bound_index_cannot_be_replayed_in_another_project(self):
        import shutil
        source = self.store.ingest({'text': '第一段包含正式金融数据。\n第二段是其他说明。'})
        self.store.extract(source['id'], '第一段包含正式金融数据。', '第一段', '金融数据')
        other_project = self.project.parent / 'Other'
        other_project.mkdir()
        other_run = other_project / '08_evidence' / 'coursework-runs' / 'run-1'
        shutil.copytree(self.run, other_run)
        with self.assertRaises(ValueError):
            EvidenceStore(other_project, other_run).sources()

    def test_query_and_input_bounds_are_actionable_errors(self):
        with self.assertRaises(ValueError):
            self.store.ingest({'text': '文' * 700000})
        with self.assertRaises(ValueError):
            self.store.search('收入', limit=1000000)
        with self.assertRaises(ValueError):
            self.store.ingest({'text': '正文资料含收入统计。', 'url': 'file:///private.txt'})
        self.assertEqual(self.store.raw_context(), [])

    def test_quote_size_limit_includes_whitespace_not_just_visible_text(self):
        quote = ' ' * 3000 + '收入统计显示增长20%。'
        source = self.store.ingest({'text': '# Scope\n' + quote + '\nother information'})
        with self.assertRaises(ValueError):
            self.store.extract(source['id'], quote, '第二行', '增长20%')


if __name__ == '__main__':
    unittest.main()
