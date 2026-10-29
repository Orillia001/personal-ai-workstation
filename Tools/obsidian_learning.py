"""Local Obsidian properties are the completion source; mastery stays in TeachingCore."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import tempfile
import threading
from urllib.parse import urlencode, quote

STATUSES = {'not_started': '未开始', 'in_progress': '学习中', 'learned': '已学习', 'review_due': '待复习'}
MASTERY = {'not_assessed': '尚未评估', 'self_reported': '自述已会，待验证',
           'in_progress': '练习中', 'review_due': '练习通过，待延迟复测'}
KEYS = ('workstation_course', 'workstation_node', '学习状态')
MAX_NOTE = 2 * 1024 * 1024
PROPERTY = re.compile(r'''^(?P<quote>['"]?)(?P<key>workstation_course|workstation_node|学习状态)(?P=quote):\s*(?P<value>.*?)\s*$''')
_lock = threading.RLock()


class LearningConflict(ValueError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def header(text):
    """Parse only our three scalar properties, retaining all other YAML and body bytes."""
    bom = '\ufeff' if text.startswith('\ufeff') else ''
    raw = text[len(bom):]
    lines = raw.splitlines(keepends=True)
    if not lines or lines[0].strip() != '---':
        return bom, [], raw, {}
    end = next((i for i in range(1, len(lines)) if lines[i].strip() in {'---', '...'}), None)
    if end is None:
        raise LearningConflict('笔记属性区未闭合，请先在Obsidian中修正')
    props = {}
    if any(line.lstrip().startswith('{') for line in lines[1:end]):
        raise LearningConflict('JSON格式属性请先在Obsidian中保存为普通属性再绑定')
    for i, line in enumerate(lines[1:end]):
        match = PROPERTY.match(line)
        if not match:
            continue
        key, value = match.group('key'), match.group('value')
        if key in props:
            raise LearningConflict('笔记含重复的学习属性，请先修正')
        if i + 2 < end and lines[i + 2].startswith((' ', '\t')):
            raise LearningConflict('学习属性必须是单行文本')
        if value.startswith('"'):
            try:
                decoder = json.JSONDecoder()
                value, consumed = decoder.raw_decode(value)
                trailing = match.group('value')[consumed:].strip()
                if trailing and not trailing.startswith('#'):
                    raise ValueError()
            except (ValueError, TypeError):
                raise LearningConflict('学习属性的引号格式无效') from None
        elif value.startswith("'"):
            scalar = re.fullmatch(r"'((?:[^']|'')*)'\s*(?:#.*)?", value)
            if not scalar:
                raise LearningConflict('学习属性的引号格式无效')
            value = scalar.group(1).replace("''", "'")
        else:
            value = re.split(r'\s+#', value, maxsplit=1)[0].strip()
            if value.startswith(('[', '{', '|', '>', '&', '*', '!')):
                raise LearningConflict('学习属性必须是单行文本')
        if not isinstance(value, str):
            raise LearningConflict('学习属性必须是文本')
        props[key] = value
    return bom, lines[:end + 1], ''.join(lines[end + 1:]), props


def properties(text, course, node, status):
    if status not in STATUSES:
        raise ValueError('学习状态无效')
    bom, lines, body, props = header(text)
    if props.get('workstation_course', course) != course or props.get('workstation_node', node) != node:
        raise LearningConflict('笔记已经绑定到其他知识点，不能覆盖')
    newline = '\r\n' if '\r\n' in text else '\n'
    values = {'workstation_course': course, 'workstation_node': node, '学习状态': STATUSES[status]}
    if not lines:
        return bom + '---' + newline + ''.join(f'{k}: {json.dumps(v, ensure_ascii=False)}{newline}' for k, v in values.items()) + '---' + newline + body
    kept = [line for line in lines[1:-1] if not PROPERTY.match(line)]
    return bom + lines[0] + ''.join(kept) + ''.join(f'{k}: {json.dumps(v, ensure_ascii=False)}{newline}' for k, v in values.items()) + lines[-1] + body


def content_without_learning(text):
    bom, lines, body, _ = header(text)
    if not lines:
        return text
    kept = [line for line in lines[1:-1] if not PROPERTY.match(line)]
    return bom + (lines[0] + ''.join(kept) + lines[-1] if kept else '') + body


def preserve_learning(rendered, current):
    _, _, _, props = header(current)
    if not all(k in props for k in KEYS):
        return rendered
    status = next((k for k, v in STATUSES.items() if v == props['学习状态']), None)
    if status is None:
        raise LearningConflict('笔记的学习状态无效，请先修正')
    return properties(rendered, props['workstation_course'], props['workstation_node'], status)


def core_for(root):
    from teaching_core import TeachingCore
    return TeachingCore(root)


def index_path(root):
    return Path(root) / 'State/teaching/obsidian-bindings.json'


def load_index(root):
    path = index_path(root)
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {'schema': 1, 'courses': {}}


def safe_path(vault, relative):
    vault = Path(vault).resolve()
    candidate = vault / relative
    path = candidate.resolve()
    if not path.is_relative_to(vault) or path == vault or candidate.is_symlink() or path.suffix.lower() != '.md':
        raise ValueError('笔记路径不在已登记的Obsidian库内')
    # Reject links/junctions at every directory, including aliases resolving inside the vault.
    for parent in [candidate] + list(candidate.parents):
        if parent == vault:
            break
        if parent.is_symlink() or getattr(parent, 'is_junction', lambda: False)():
            raise ValueError('绑定路径不能包含目录链接')
    return path


def read_note(path):
    with path.open('rb') as stream:
        raw = stream.read(MAX_NOTE + 1)
    if len(raw) > MAX_NOTE:
        raise LearningConflict('笔记大于2MiB，暂停自动改写')
    return raw, raw.decode('utf-8')


def replace_note(root, path, before, after):
    if before == after:
        return
    if path.read_bytes() != before:
        raise LearningConflict('Obsidian笔记刚被修改，请同步后重试')
    backup = Path(root) / 'State/teaching/obsidian-revisions' / (digest(before) + '.md')
    backup.parent.mkdir(parents=True, exist_ok=True)
    if not backup.exists():
        backup.write_bytes(before)
    fd, temp = tempfile.mkstemp(prefix='.workstation-learning-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(after)
        if path.read_bytes() != before:
            raise LearningConflict('Obsidian笔记刚被修改，请同步后重试')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def note_status(props):
    status = next((k for k, v in STATUSES.items() if v == props.get('学习状态')), None)
    if status is None:
        raise LearningConflict('学习状态须为：未开始、学习中、已学习或待复习')
    return status


def resolve_note(vault, mapping, course, node):
    relative = mapping.get(node)
    if not relative:
        raise LearningConflict('该知识点尚未绑定Obsidian笔记')
    path = safe_path(vault, relative)
    if path.is_file():
        return path
    # Find a renamed note only within this course, using its stable binding IDs.
    base = safe_path(vault, relative).parent.parent
    found = []
    for count, candidate in enumerate(base.rglob('*.md')):
        if count >= 2000:
            raise LearningConflict('课程目录文件过多，请手动重新绑定')
        candidate = safe_path(vault, candidate.relative_to(vault))
        _, text = read_note(candidate)
        props = header(text)[3]
        if props.get('workstation_course') == course and props.get('workstation_node') == node:
            found.append(candidate)
    if len(found) != 1:
        raise LearningConflict('绑定笔记缺失或有重复副本，请检查Obsidian')
    return found[0]


def course_progress(root, course):
    with _lock:
        core = core_for(root)
        profile = core.subject(course)
        graph = core.graph(course)
        vault = Path(core.config.get('vault', '')).resolve()
        connected = (vault / '.obsidian').is_dir()
        mapping = load_index(root)['courses'].get(course, {}).get('nodes', {})
        state_file = core.state_path(course)
        state = json.loads(state_file.read_text(encoding='utf-8-sig')) if state_file.exists() else {}
        mastery_by_node = dict(state.get('node_states', {}))
        if state.get('current', {}).get('id'):
            mastery_by_node[state['current']['id']] = state.get('mastery', 'not_assessed')
        result = []
        for node in graph['nodes']:
            mastery = mastery_by_node.get(node['id'], 'not_assessed')
            entry = {'id': node['id'], 'status': 'not_started', 'mastery': mastery,
                     'mastery_label': MASTERY.get(mastery, '尚未评估'), 'linked': False,
                     'revision': None, 'obsidian_uri': None, 'error': None}
            if connected and mapping:
                try:
                    path = resolve_note(vault, mapping, course, node['id'])
                    raw, text = read_note(path)
                    props = header(text)[3]
                    if props.get('workstation_course') != course or props.get('workstation_node') != node['id']:
                        raise LearningConflict('笔记绑定标识不一致，已停止同步')
                    entry.update(status=note_status(props), linked=True, revision=digest(raw),
                                 obsidian_uri='obsidian://open?' + urlencode({'path': str(path)}, quote_via=quote))
                except (OSError, ValueError, UnicodeError) as error:
                    entry['error'] = str(error)
            else:
                entry['error'] = 'Obsidian库未连接' if not connected else '课程尚未绑定Obsidian'
            result.append(entry)
        return {'course': course, 'name': profile['name'], 'connected': connected and bool(mapping),
                'nodes': result, 'statuses': STATUSES,
                'counts': {key: sum(n['status'] == key and n['linked'] for n in result) for key in STATUSES},
                'linked_count': sum(n['linked'] for n in result)}


def set_status(root, course, node_id, status, revision):
    with _lock:
        if not isinstance(status, str) or status not in STATUSES:
            raise ValueError('学习状态无效')
        core = core_for(root)
        core.subject(course)
        if node_id not in {n['id'] for n in core.graph(course)['nodes']}:
            raise ValueError('知识点不存在')
        vault = Path(core.config['vault']).resolve()
        if not (vault / '.obsidian').is_dir():
            raise LearningConflict('登记的Obsidian库不可用')
        mapping = load_index(root)['courses'].get(course, {}).get('nodes', {})
        path = resolve_note(vault, mapping, course, node_id)
        raw, text = read_note(path)
        props = header(text)[3]
        if props.get('workstation_course') != course or props.get('workstation_node') != node_id:
            raise LearningConflict('笔记绑定标识不一致，已停止同步')
        if not isinstance(revision, str) or digest(raw) != revision:
            raise LearningConflict('笔记已在另一处修改，请先同步状态再重试')
        updated = properties(text, course, node_id, status).encode('utf-8')
        replace_note(root, path, raw, updated)
        return course_progress(root, course)


def sync_record(root, course, node_id, mastery):
    """An actual teaching event may update completion, never the other way around."""
    if not index_path(root).exists():
        return None
    projected = {'self_reported': 'learned', 'in_progress': 'in_progress', 'review_due': 'review_due'}
    if mastery not in projected:
        return None
    with _lock:
        info = course_progress(root, course)
        entry = next(n for n in info['nodes'] if n['id'] == node_id)
        if not entry['linked']:
            return {'ok': False, 'message': entry['error'] or '笔记未绑定'}
        set_status(root, course, node_id, projected[mastery], entry['revision'])
    return {'ok': True, 'status': projected[mastery]}


def open_note(root, course, node_id):
    info = course_progress(root, course)
    entry = next((n for n in info['nodes'] if n['id'] == node_id), None)
    if not entry or not entry['linked']:
        raise LearningConflict('该知识点的Obsidian笔记不可用')
    os.startfile(entry['obsidian_uri'])
    return {'requested': True, 'node_id': node_id}


def missing_bound_notes(root, course, vault):
    mapping = load_index(root)['courses'].get(course, {}).get('nodes', {})
    return [relative for relative in mapping.values() if not safe_path(vault, relative).is_file()]


def bind_all(root, backup_directory, dry_run=False):
    """Explicit deployment only: add metadata without replacing any note content."""
    from teaching_core import write_json
    with _lock:
        core = core_for(root)
        vault = Path(core.config['vault']).resolve()
        if not (vault / '.obsidian').is_dir():
            raise ValueError('登记位置不是已有Obsidian库')
        index = load_index(root)
        plans, counts = [], []
        for course, profile in core.config['subjects'].items():
            graph = core.graph(course)
            state = json.loads(core.state_path(course).read_text(encoding='utf-8-sig'))
            existing = index['courses'].get(course, {}).get('nodes', {})
            mapping = {}
            for node in graph['nodes']:
                relative = f'课程知识/{profile["name"]}/{"大纲" if node["kind"] == "module" else "知识点"}/{node["title"]}.md'
                path = resolve_note(vault, existing, course, node['id']) if node['id'] in existing else safe_path(vault, relative)
                raw, text = read_note(path)
                props = header(text)[3]
                mastery = state.get('node_states', {}).get(node['id'], 'not_assessed')
                if state.get('current', {}).get('id') == node['id']:
                    mastery = state.get('mastery', mastery)
                initial = {'self_reported': 'learned', 'review_due': 'review_due', 'in_progress': 'in_progress'}.get(mastery, 'not_started')
                status = note_status(props) if '学习状态' in props else initial
                updated = properties(text, course, node['id'], status).encode('utf-8')
                assert content_without_learning(updated.decode('utf-8')) == content_without_learning(text)
                plans.append((path, raw, updated))
                mapping[node['id']] = path.relative_to(vault).as_posix()
            index['courses'][course] = {'name': profile['name'], 'nodes': mapping}
            counts.append({'course': course, 'nodes': len(mapping)})
        summary = {'ok': True, 'courses': counts, 'notes': len(plans), 'changed': sum(a != b for _, a, b in plans)}
        if dry_run:
            return {**summary, 'dry_run': True, 'body_preserved': True}
        for path, raw, _ in plans:
            if path.read_bytes() != raw:
                raise LearningConflict('绑定期间有笔记被修改，请重试')
            backup = Path(backup_directory) / 'vault' / path.relative_to(vault)
            backup.parent.mkdir(parents=True, exist_ok=True)
            if not backup.exists():
                backup.write_bytes(raw)
        originals = {str(path.relative_to(vault)): digest(raw) for path, raw, _ in plans}
        for path, raw, updated in plans:
            replace_note(root, path, raw, updated)
        write_json(index_path(root), index)
        write_json(Path(backup_directory) / 'note-manifest.json', originals)
        return summary
