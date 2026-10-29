"""Behavior checks use isolated source files, never the signed-in user's rules."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import workstation_codex_manage as manager

SKILL = '---\nname: sample\ndescription: Summarize a sample when asked.\n---\n\nRead the sample.\n'
ROLE = 'name = "sample"\ndescription = "Review samples"\ndeveloper_instructions = "Check the provided sample."\n'


class RuleManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root, self.home = self.base / 'station', self.base / 'profile/.codex'
        self.root.mkdir(); self.home.mkdir(parents=True)
        (self.root / 'Projects/demo').mkdir(parents=True)
        self.file = self.home / 'skills/sample/SKILL.md'
        self.file.parent.mkdir(parents=True)
        self.file.write_bytes(SKILL.encode())

    def call(self, action, **kwargs):
        return manager.dispatch(self.root, {'action': action, **kwargs}, home=self.home)

    def item(self):
        return next(r for r in self.call('inventory')['items'] if r['name'] == 'sample')

    def preview(self, text):
        row = self.item()
        return self.call('preview', id=row['id'], revision=row['revision'], content=text)

    def save(self, text):
        preview = self.preview(text)
        return self.call('save', preview_id=preview['preview_id'], content=text, confirmed=True)

    def mutate(self, operation):
        row = self.item()
        return self.call(operation, id=row['id'], revision=row['revision'], active=row['active'], confirmed=True)

    def test_inventory_and_full_read(self):
        row = self.item()
        self.assertTrue(row['writable'])
        self.assertEqual(self.call('read', id=row['id'])['content'], SKILL)
        self.assertIn('project:demo', [r['id'] for r in self.call('inventory')['scopes']])

    def test_save_preserves_original_bytes_and_restore(self):
        original = b'\xef\xbb\xbf' + SKILL.replace('\n', '\r\n').encode()
        self.file.write_bytes(original)
        result = self.save(SKILL + 'New instruction.\n')
        self.assertTrue(self.file.read_bytes().startswith(b'\xef\xbb\xbf'))
        self.assertIn(b'New instruction.\r\n', self.file.read_bytes())
        backup = self.root / 'Backups/Codex-Rules' / result['backup_id'] / 'content'
        self.assertEqual(backup.read_bytes(), original)
        self.call('restore', backup_id=result['backup_id'], revision=self.item()['revision'], active=self.item()['active'], confirmed=True)
        self.assertEqual(self.file.read_bytes(), original)

    def test_preview_binds_content_and_revision(self):
        changed = SKILL + 'Change\n'
        preview = self.preview(changed)
        with self.assertRaises(manager.Conflict):
            self.call('save', preview_id=preview['preview_id'], content=changed + 'Other\n', confirmed=True)
        self.file.write_text(SKILL + 'External\n', encoding='utf-8')
        with self.assertRaises(manager.Conflict):
            self.call('save', preview_id=preview['preview_id'], content=changed, confirmed=True)
        self.assertIn('External', self.file.read_text())

    def test_preview_rejects_entry_state_changed_after_preview(self):
        changed = SKILL + 'Change\n'
        preview = self.preview(changed)
        self.mutate('toggle')
        with self.assertRaises(manager.Conflict):
            self.call('save', preview_id=preview['preview_id'], content=changed, confirmed=True)
        self.assertFalse(self.file.exists())
        self.assertEqual(self.file.with_name('SKILL.md.disabled').read_text(), SKILL)

    def test_new_skill_and_role_and_no_overwrite(self):
        for kind, name, content in [('skill', 'new-skill', SKILL), ('role', 'new-role', ROLE)]:
            preview = self.call('preview', kind=kind, name=name, scope='project:demo', content=content)
            result = self.call('save', preview_id=preview['preview_id'], content=content, confirmed=True)
            self.assertEqual(self.call('read', id=result['id'])['content'], content)
            with self.assertRaises(manager.Conflict):
                self.call('preview', kind=kind, name=name, scope='project:demo', content=content)
        existing_folder = self.home / 'skills/occupied'
        existing_folder.mkdir()
        with self.assertRaises(manager.Conflict):
            self.call('preview', kind='skill', name='occupied', scope='user', content=SKILL)

    def test_toggle_stable_id_and_disabled_edit(self):
        original_id = self.item()['id']
        self.mutate('toggle')
        self.assertFalse(self.file.exists())
        self.assertFalse(self.item()['active'])
        result = self.save(SKILL + 'Disabled change\n')
        self.assertEqual(result['id'], original_id)
        self.assertFalse(self.call('read', id=result['id'])['active'])
        self.mutate('toggle')
        self.assertTrue(self.file.is_file())

    def test_archive_and_restore_entire_skill(self):
        reference = self.file.parent / 'references/example.txt'
        reference.parent.mkdir(); reference.write_text('reference', encoding='utf-8')
        result = self.mutate('archive')
        self.assertFalse(self.file.parent.exists())
        self.assertTrue(self.call('history')['items'][0]['available'])
        self.call('restore', backup_id=result['backup_id'], revision='missing', confirmed=True)
        self.assertEqual(reference.read_text(), 'reference')
        self.assertEqual(self.file.read_text(), SKILL)

    def test_restore_rejects_destination_and_changed_revision(self):
        result = self.save(SKILL + 'saved\n')
        old_revision = self.item()['revision']
        self.file.write_text(SKILL + 'external\n', encoding='utf-8')
        with self.assertRaises(manager.Conflict):
            self.call('restore', backup_id=result['backup_id'], revision=old_revision, active=True, confirmed=True)
        archived = self.mutate('archive')
        self.file.parent.mkdir(); self.file.write_text('unregistered', encoding='utf-8')
        with self.assertRaises((manager.Conflict, ValueError)):
            self.call('restore', backup_id=archived['backup_id'], revision='missing', confirmed=True)
        self.assertEqual(self.file.read_text(), 'unregistered')

    def test_corrupt_archive_rejected(self):
        result = self.mutate('archive')
        payload = self.root / 'Backups/Codex-Rules' / result['backup_id'] / 'payload/SKILL.md'
        payload.write_text('corrupt', encoding='utf-8')
        with self.assertRaises(ValueError):
            self.call('restore', backup_id=result['backup_id'], revision='missing', confirmed=True)
        self.assertFalse(self.file.exists())

    def test_no_arbitrary_paths_commands_or_unconfirmed_mutations(self):
        row = self.item()
        for action, fields in [('read', {'path': str(self.file)}), ('exec', {'command': 'anything'}), ('toggle', {'id': row['id'], 'revision': row['revision']}), ('archive', {'id': row['id'], 'confirmed': True})]:
            with self.subTest(action=action), self.assertRaises(ValueError): self.call(action, **fields)
        self.assertEqual(self.file.read_text(), SKILL)

    def test_names_scopes_and_content_validation(self):
        for name in ['../escape', 'CON', 'nul', 'a/b', 'a\\b']:
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.call('preview', kind='skill', name=name, scope='user', content=SKILL)
        for kind, content in [('skill', '# no metadata'), ('role', 'name = "x"'), ('role', 'broken ]')]:
            with self.subTest(kind=kind), self.assertRaises(ValueError):
                self.call('preview', kind=kind, name='new-entry', scope='user', content=content)
        with self.assertRaises(ValueError): self.call('preview', kind='skill', name='new-entry', scope='readonly', content=SKILL)

    def test_conflicting_entry_is_readonly(self):
        self.file.with_name('SKILL.md.disabled').write_text(SKILL, encoding='utf-8')
        self.assertFalse(self.item()['writable'])
        with self.assertRaises(ValueError): self.mutate('toggle')

    def test_old_entry_state_cannot_toggle_or_archive_again(self):
        row = self.item()
        self.mutate('toggle')
        for operation in ['toggle', 'archive']:
            with self.subTest(operation=operation), self.assertRaises(manager.Conflict):
                self.call(operation, id=row['id'], revision=row['revision'], active=True, confirmed=True)
        self.assertFalse(self.item()['active'])

    def test_project_skill_visible_in_mapping_and_system_source_readonly(self):
        project_skill = self.root / 'Projects/demo/.agents/skills/project-skill/SKILL.md'
        project_skill.parent.mkdir(parents=True); project_skill.write_text(SKILL, encoding='utf-8')
        self.assertIn(str(project_skill), [r['path'] for r in manager.mapping.discover_skills(self.root, self.home)[0]])
        system = self.home / 'skills/.system/builtin/SKILL.md'
        system.parent.mkdir(parents=True); system.write_text(SKILL, encoding='utf-8')
        row = next(r for r in self.call('inventory')['items'] if r['path'] == str(system))
        self.assertFalse(row['writable'])
        with self.assertRaises(ValueError): self.call('preview', id=row['id'], revision=row['revision'], content=SKILL)

    def test_install_preview_is_bounded_and_nonmutating(self):
        arguments = dict(repo='openai/skills', ref='main', subpath='skills/.curated/pdf', name='downloaded', scope='user')
        result = self.call('install-preview', **arguments)
        self.assertEqual(Path(result['path']), self.home / 'skills/downloaded')
        self.assertFalse(Path(result['path']).exists())
        for key, value in [('subpath', '../outside'), ('subpath', 'C:/outside'), ('repo', 'https://example.com/x'), ('ref', '--option')]:
            with self.subTest(key=key), self.assertRaises(ValueError): self.call('install-preview', **{**arguments, key: value})

    def test_install_uses_official_helper_without_shell(self):
        def download(command, **options):
            self.assertNotIn('shell', options)
            self.assertEqual(command[command.index('--method') + 1], 'download')
            destination = Path(command[command.index('--dest') + 1]) / 'downloaded'
            destination.mkdir(parents=True)
            (destination / 'SKILL.md').write_text(SKILL, encoding='utf-8')
            return type('Result', (), {'returncode': 0})()
        with patch.object(manager.subprocess, 'run', side_effect=download):
            self.call('install', repo='openai/skills', ref='main', subpath='skills/sample', name='downloaded', scope='user', confirmed=True)
        self.assertEqual((self.home / 'skills/downloaded/SKILL.md').read_text(), SKILL)

    def test_invalid_download_never_enters_source_directory(self):
        def download(command, **options):
            folder = Path(command[command.index('--dest') + 1]) / 'downloaded'
            folder.mkdir(parents=True)
            (folder / 'SKILL.md').write_text('Invalid metadata', encoding='utf-8')
            return type('Result', (), {'returncode': 0})()
        with patch.object(manager.subprocess, 'run', side_effect=download), self.assertRaises(ValueError):
            self.call('install', repo='openai/skills', ref='main', subpath='skills/sample', name='downloaded', scope='user', confirmed=True)
        self.assertFalse((self.home / 'skills/downloaded').exists())

    def test_linked_target_cannot_write_outside(self):
        outside = self.base / 'outside'; outside.mkdir()
        link = self.home / 'skills/linked'
        try: link.symlink_to(outside, target_is_directory=True)
        except OSError: self.skipTest('Windows symlink privilege unavailable')
        with self.assertRaises(ValueError):
            self.call('preview', kind='skill', name='linked', scope='user', content=SKILL)
        self.assertFalse((outside / 'SKILL.md').exists())


if __name__ == '__main__':
    unittest.main()
