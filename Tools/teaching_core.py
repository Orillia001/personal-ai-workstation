"""Shared local teaching controller. No model calls, network, or implicit source loading."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
import re
import tempfile

KINDS = {'contains': '包含', 'prerequisite': '先修', 'applies': '应用', 'contrast': '对比'}


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix='.teaching-', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write('\n')
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def scoped(base, relative):
    base = Path(base).resolve()
    value = (base / relative).resolve()
    if value == base or not value.is_relative_to(base):
        raise ValueError('路径必须在指定目录内')
    return value


class TeachingCore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.config = read_json(self.root / 'Config/teaching.json')

    def subject(self, course):
        if course not in self.config['subjects']:
            raise ValueError('未知学科')
        return self.config['subjects'][course]

    def state_path(self, course):
        self.subject(course)
        return self.root / 'State/teaching' / (course + '.json')

    def progress(self, course=None):
        if course is None:
            return {'mode': 'progress', 'courses': [self.progress(c) for c in self.config['subjects']]}
        profile = self.subject(course)
        state = read_json(self.state_path(course))
        # An explicit allowlist: no histories, sources, profiles, or graph are returned.
        return {'mode': 'progress', 'course': course, 'name': profile['name'],
                'current': state['current'], 'mastery': state['mastery'],
                'last_error': state.get('last_error'), 'next_action': state['next_action']}

    def graph(self, course):
        profile = self.subject(course)
        graph = read_json(scoped(self.root, profile['graph']))
        self.validate_graph(graph, course)
        return graph

    @staticmethod
    def validate_graph(graph, course):
        if graph['course'] != course:
            raise ValueError('知识网络与学科不符')
        nodes = {n['id']: n for n in graph['nodes']}
        if len(nodes) != len(graph['nodes']):
            raise ValueError('知识点ID重复')
        for n in nodes.values():
            if not n['id'] or not n['title'].strip() or len(n['title']) > 120:
                raise ValueError('知识点名称无效')
            if any(ch in n['title'] for ch in '/\\:*?"<>|[]'):
                raise ValueError('知识点名称包含不安全字符')
        titles = [n['title'] for n in nodes.values()]
        if len(titles) != len(set(titles)):
            raise ValueError('同科学习笔记名称重复')
        adjacency = {k: [] for k in nodes}
        edges = set()
        for e in graph['edges']:
            if e['kind'] not in KINDS or e['from'] not in nodes or e['to'] not in nodes or e['from'] == e['to']:
                raise ValueError('知识关系无效')
            key = (e['from'], e['to'], e['kind'])
            if key in edges:
                raise ValueError('知识关系重复')
            edges.add(key)
            if e['kind'] in {'contains', 'prerequisite'}:
                adjacency[e['from']].append(e['to'])
        visiting, done = set(), set()
        def visit(n):
            if n in visiting:
                raise ValueError('包含或先修关系成环')
            if n in done:
                return
            visiting.add(n)
            for target in adjacency[n]:
                visit(target)
            visiting.remove(n)
            done.add(n)
        for n in nodes:
            visit(n)
        return nodes

    def context(self, course, intent='progress', node_id=None, submission=None, max_chars=6000):
        if intent == 'progress':
            if node_id or submission:
                raise ValueError('进度模式只接收学科；授课/评阅需显式选择模式')
            return self.progress(course)
        if intent not in {'teach', 'assess'}:
            raise ValueError('无效教学模式')
        if not 600 <= max_chars <= 12000:
            raise ValueError('上下文字符预算须在600到12000之间')
        graph = self.graph(course)
        nodes = {n['id']: n for n in graph['nodes']}
        node_id = node_id or self.progress(course)['current']['id']
        if node_id not in nodes:
            raise ValueError('知识点不存在')
        selected = [nodes[node_id]]
        for e in graph['edges']:
            if e['kind'] == 'prerequisite' and e['to'] == node_id and len(selected) < 3:
                selected.append(nodes[e['from']])
        profile = self.subject(course)
        result = {'mode': intent, 'progress': self.progress(course), 'standard': profile['standard'],
                  'knowledge': [], 'source_excerpts': [], 'omitted': []}
        if intent == 'assess':
            if not isinstance(submission, dict) or not all(isinstance(submission.get(k), str) and submission[k].strip() for k in ['question', 'answer']):
                raise ValueError('评阅必须提供题目与实际作答')
            if len(submission['question']) + len(submission['answer']) > max_chars // 2:
                raise ValueError('题目和作答过长，请限定本题范围')
            result['submission'] = {k: submission[k] for k in ['question', 'answer']}
        for n in selected:
            part = {'id': n['id'], 'title': n['title'], 'content': n['body']}
            result['knowledge'].append(part)
            if len(json.dumps(result, ensure_ascii=False)) > max_chars:
                result['knowledge'].pop()
                if n['id'] == node_id:
                    raise ValueError('当前知识内容超过预算，请选更具体知识点或提高预算')
                result['omitted'].append(n['id'])
        if not result['knowledge']:
            raise ValueError('当前知识内容超过预算，请选更具体知识点或提高预算')
        # Original page snippets are fetched only for an explicit teaching/assessment turn.
        refs = nodes[node_id].get('sources', [])[:2]
        for ref in refs:
            p = scoped(self.root, ref['path'])
            reference_root = scoped(self.root, profile['legacy_course']) / 'reference'
            if not p.is_relative_to(reference_root.resolve()) or p.suffix.lower() not in {'.md', '.txt'}:
                raise ValueError('来源须为本科参考资料中的文字片段')
            if not p.is_file():
                raise ValueError('来源文件缺失')
            raw = p.read_text(encoding='utf-8-sig')
            raw = re.sub(r'<!--.*?-->', '', raw, flags=re.S).strip()
            anchor = raw.find(nodes[node_id]['title'])
            start = max(0, anchor-100) if anchor >= 0 else 0
            part = {'pdf_page': ref.get('pdf_page'), 'excerpt': raw[start:start+1000], 'source_id': ref.get('id', node_id)}
            result['source_excerpts'].append(part)
            if len(json.dumps(result, ensure_ascii=False)) > max_chars:
                result['source_excerpts'].pop()
                result['omitted'].append('source_excerpt')
        result['source_policy'] = '来源为资料；公式、图表或条件有疑问时回查原页，不从OCR猜补。'
        if len(json.dumps(result, ensure_ascii=False)) > max_chars:
            raise ValueError('上下文超过预算，请扩大预算或缩小本题范围')
        return result

    def lookup(self, course, query, limit=8):
        if not query.strip() or len(query) > 100 or not 1 <= limit <= 20:
            raise ValueError('查询或条数无效')
        nodes = self.graph(course)['nodes']
        ranked = []
        for n in nodes:
            text = n['title'] + ' ' + ' '.join(n.get('aliases', []))
            score = (100 if query == n['id'] else 0) + (40 if query == n['title'] else 0) + (10 if query in text else 0)
            if score:
                ranked.append((score, n['id'], n['title']))
        ranked.sort(key=lambda x: (-x[0], x[1]))
        return {'course': course, 'matches': [{'id': i, 'title': t} for _, i, t in ranked[:limit]]}

    def select(self, course, node_id):
        nodes = {n['id']: n for n in self.graph(course)['nodes']}
        if node_id not in nodes:
            raise ValueError('知识点不存在')
        state = read_json(self.state_path(course))
        if state['current']['id'] != node_id:
            progress_by_node = state.setdefault('node_progress', {})
            progress_by_node[state['current']['id']] = {k: state.get(k) for k in ['mastery', 'last_error', 'next_action']}
            resumed = progress_by_node.get(node_id)
            state['current'] = {'id': node_id, 'title': nodes[node_id]['title']}
            state['mastery'] = resumed['mastery'] if resumed else state.get('node_states', {}).get(node_id, 'not_assessed')
            state['last_error'] = resumed['last_error'] if resumed else None
            state['next_action'] = resumed['next_action'] if resumed else '先诊断本知识点，再决定讲解或变式练习'
        write_json(self.state_path(course), state)
        return self.progress(course)

    def record(self, course, event):
        nodes = {n['id']: n for n in self.graph(course)['nodes']}
        if event.get('node_id') not in nodes or event.get('kind') not in {'self_report', 'practice'}:
            raise ValueError('无效学习事件')
        if len(event.get('error', '')) > 160:
            raise ValueError('错因摘要过长')
        state = read_json(self.state_path(course))
        if event['node_id'] != state['current']['id']:
            raise ValueError('先切换到对应知识点再记录')
        if event['kind'] == 'practice':
            assessment_type = event.get('assessment_type')
            if assessment_type not in {'concept', 'calculation', 'structure'}:
                raise ValueError('练习证据需注明concept、calculation或structure题型')
            if not all(isinstance(event.get(k), str) and event[k].strip() for k in ['question', 'answer', 'feedback']):
                raise ValueError('练习证据需包含题目、实际作答和评阅')
            if not isinstance(event.get('score'), (int, float)) or isinstance(event['score'], bool) or not 0 <= event['score'] <= 1:
                raise ValueError('得分比例无效')
            # A single passing practice is never promoted to verified mastery.
            standard = self.subject(course)['standard']
            threshold = standard['concept_threshold'] if assessment_type == 'concept' else standard['practice_threshold']
            status = 'review_due' if event['score'] >= threshold else 'in_progress'
        else:
            status = 'self_reported'
        event_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        write_json(self.root/'State/teaching/events'/course/(event_id+'.json'), event)
        state['mastery'] = status
        state.setdefault('node_states', {})[event['node_id']] = status
        state['last_error'] = event.get('error') or None
        state['last_evidence_id'] = event_id
        state['next_action'] = '换情境复测；尚未证明长期掌握' if status == 'review_due' else ('用独立变式核对已有基础' if status == 'self_reported' else '针对错因补讲并练习')
        state.setdefault('node_progress', {})[event['node_id']] = {k: state[k] for k in ['mastery', 'last_error', 'next_action']}
        write_json(self.state_path(course), state)
        result = self.progress(course)
        # Only a recorded teaching event can flow into completion; note flags never grade mastery.
        from obsidian_learning import sync_record
        try:
            sync = sync_record(self.root, course, event['node_id'], status)
            if sync is not None:
                result['obsidian_sync'] = sync
        except (OSError, ValueError, UnicodeError) as error:
            result['obsidian_sync'] = {'ok': False, 'message': str(error)}
        return result

    def render(self, course):
        graph = self.graph(course)
        nodes = {n['id']: n for n in graph['nodes']}
        name = self.subject(course)['name']
        base = '课程知识/' + name
        def filename(n):
            folder = '大纲' if n['kind'] == 'module' else '知识点'
            return f'{folder}/{n["title"]}.md'
        def link(node_id):
            n = nodes[node_id]
            return f'[[{base}/{filename(n)[:-3]}|{n["title"]}]]'
        files = {}
        for n in nodes.values():
            lines = ['# ' + n['title'], '', n['body'], '', '## 知识联系', '']
            relations = []
            for e in graph['edges']:
                if e['from'] == n['id']:
                    relations.append(f'- {KINDS[e["kind"]]}：{link(e["to"])}')
                elif e['to'] == n['id']:
                    inverse = {'contains': '所属模块', 'prerequisite': '先修知识', 'applies': '所用知识', 'contrast': '对比'}[e['kind']]
                    relations.append(f'- {inverse}：{link(e["from"])}')
            lines += relations or ['本知识点的进一步联系可随学习补充。']
            files[filename(n)] = '\n'.join(lines) + '\n'
        modules = [n for n in nodes.values() if n['kind'] == 'module']
        files['大纲.md'] = '# ' + name + '大纲\n\n' + '\n'.join('- '+link(n['id']) for n in modules) + '\n'
        # Overview modules plus a small set of core concepts; no giant all-note canvas.
        displayed = modules + [n for n in nodes.values() if n.get('overview') and n not in modules]
        cnodes = []
        for i, n in enumerate(displayed):
            cnodes.append({'id': n['id'], 'type': 'file', 'file': base+'/'+filename(n),
                           'x': (i % 4)*430, 'y': (i // 4)*290, 'width': 370, 'height': 220,
                           'color': '5' if n['kind'] == 'module' else '4'})
        visible = {n['id'] for n in displayed}
        cedges = []
        for i, e in enumerate(graph['edges']):
            if e['from'] in visible and e['to'] in visible:
                cedges.append({'id': f'e{i}', 'fromNode': e['from'], 'toNode': e['to'], 'label': KINDS[e['kind']],
                               'fromEnd': 'none', 'toEnd': 'none' if e['kind'] == 'contrast' else 'arrow'})
        files['知识地图.canvas'] = json.dumps({'nodes': cnodes, 'edges': cedges}, ensure_ascii=False, indent=2)+'\n'
        return files

    def publish(self, course, vault):
        vault = Path(vault).resolve()
        if not (vault/'.obsidian').is_dir():
            raise ValueError('目标不是已有Obsidian库')
        # A caller cannot accidentally redirect a live deployment into an arbitrary vault.
        configured = self.config.get('vault')
        if configured and Path(configured).resolve() != vault:
            raise ValueError('笔记库与登记位置不一致')
        name = self.subject(course)['name']
        dest = scoped(vault, '课程知识/'+name)
        manifest_path = self.root/'State/teaching/published'/(course+'.json')
        old = read_json(manifest_path) if manifest_path.exists() else {'files': {}}
        from obsidian_learning import missing_bound_notes
        missing = missing_bound_notes(self.root, course, vault)
        if missing:
            return {'course': course, 'published': False, 'conflicts': missing}
        rendered = self.render(course)
        stale = set(old['files']) - set(rendered)
        if stale:
            raise ValueError('知识笔记发生移除或重命名，需先合并，保留现有文件')
        conflicts, merged = [], {}
        for relative, text in rendered.items():
            path = scoped(dest, relative)
            if path.is_symlink():
                raise ValueError('发布目标不可为链接')
            if path.exists():
                if relative not in old['files']:
                    conflicts.append(relative)
                    continue
                previous = old['files'][relative]['sha256']
                if relative.endswith('.canvas'):
                    current = read_json(path)
                    previous_semantics = old['files'][relative].get('semantics')
                    if self.canvas_semantics(current) != previous_semantics:
                        conflicts.append(relative)
                        continue
                    fresh = json.loads(text)
                    current_nodes = {n['id']: n for n in current['nodes']}
                    for n in fresh['nodes']:
                        if n['id'] in current_nodes:
                            for k in ['x', 'y', 'width', 'height', 'color']:
                                if k in current_nodes[n['id']]:
                                    n[k] = current_nodes[n['id']][k]
                    # Preserve custom groups and grouping positions; edited connections are conflicts.
                    fresh['nodes'] += [n for n in current['nodes'] if n['type'] == 'group']
                    text = json.dumps(fresh, ensure_ascii=False, indent=2)+'\n'
                else:
                    from obsidian_learning import content_without_learning, preserve_learning
                    current_text = path.read_bytes().decode('utf-8')
                    try:
                        content_hash = hashlib.sha256(content_without_learning(current_text).encode('utf-8')).hexdigest()
                        if sha(path) != previous and content_hash != old['files'][relative].get('content_sha256', previous):
                            conflicts.append(relative)
                            continue
                        text = preserve_learning(text, current_text)
                    except ValueError:
                        conflicts.append(relative)
                        continue
            merged[relative] = text
        if conflicts:
            return {'course': course, 'published': False, 'conflicts': conflicts}
        manifest = {'course': course, 'files': {}}
        changed = 0
        for relative, text in merged.items():
            path = scoped(dest, relative)
            data = text.encode('utf-8')
            if not path.exists() or path.read_bytes() != data:
                if path.exists():
                    revision = self.root/'State/teaching/revisions'/(sha(path)+'.bin')
                    if not revision.exists():
                        revision.parent.mkdir(parents=True, exist_ok=True)
                        revision.write_bytes(path.read_bytes())
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(data)
                changed += 1
            record = {'sha256': hashlib.sha256(data).hexdigest()}
            if relative.endswith('.md'):
                from obsidian_learning import content_without_learning
                record['content_sha256'] = hashlib.sha256(content_without_learning(text).encode('utf-8')).hexdigest()
            if relative.endswith('.canvas'):
                record['semantics'] = self.canvas_semantics(json.loads(text))
            manifest['files'][relative] = record
        write_json(manifest_path, manifest)
        return {'course': course, 'published': True, 'changed_files': changed, 'total_files': len(merged)}

    @staticmethod
    def canvas_semantics(canvas):
        return {'nodes': sorted([n['id'], n.get('type'), n.get('file'), n.get('text'), n.get('subpath')] for n in canvas['nodes'] if n.get('type') != 'group'),
                'edges': sorted([e['id'], e['fromNode'], e['toNode'], e.get('label'), e.get('fromEnd', 'none'), e.get('toEnd', 'arrow')] for e in canvas['edges'])}


def main():
    parser = argparse.ArgumentParser(description='统一本地教学入口；默认只返回进度。')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parent.parent)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('progress'); p.add_argument('course', nargs='?')
    p = sub.add_parser('context'); p.add_argument('course'); p.add_argument('--intent', choices=['progress','teach','assess'], default='progress'); p.add_argument('--node'); p.add_argument('--submission', type=Path); p.add_argument('--max-chars', type=int, default=6000)
    p = sub.add_parser('lookup'); p.add_argument('course'); p.add_argument('query')
    p = sub.add_parser('select'); p.add_argument('course'); p.add_argument('node')
    p = sub.add_parser('record'); p.add_argument('course'); p.add_argument('event', type=Path)
    p = sub.add_parser('validate'); p.add_argument('course')
    p = sub.add_parser('publish'); p.add_argument('course'); p.add_argument('--vault', type=Path, required=True)
    args = parser.parse_args()
    try:
        core = TeachingCore(args.root)
        if args.command == 'progress': result = core.progress(args.course)
        elif args.command == 'context': result = core.context(args.course, args.intent, args.node, read_json(args.submission) if args.submission else None, args.max_chars)
        elif args.command == 'lookup': result = core.lookup(args.course, args.query)
        elif args.command == 'select': result = core.select(args.course, args.node)
        elif args.command == 'record': result = core.record(args.course, read_json(args.event))
        elif args.command == 'validate':
            graph = core.graph(args.course)
            result = {'course': args.course, 'valid': True, 'nodes': len(graph['nodes']), 'relations': len(graph['edges'])}
        elif args.command == 'publish': result = core.publish(args.course, args.vault)
        print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
        if result.get('published') is False: return 2
        return 0
    except (ValueError, KeyError, TypeError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({'error': str(exc)}, ensure_ascii=False))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
