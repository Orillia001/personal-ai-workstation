"""Persist visual workflow drafts and compose registered rule references. No executor."""
from __future__ import annotations
import copy
import json
import math
import os
import re
import threading
import tomllib
import uuid
from pathlib import Path

import workstation_codex_manage as rules
import workstation_model_router as router

_lock = threading.RLock()
MAX_BYTES = 400_000
TYPES = {'input', 'skill', 'rule', 'role', 'agent', 'output'}
SOURCES = {'skill', 'rule', 'role'}
ID = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')


def text(value, maximum=120, empty=True):
    if not isinstance(value, str) or len(value) > maximum or '\x00' in value or not empty and not value.strip():
        raise ValueError('文字为空、过长或含无效字符')
    return value


def number(value, low, high):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high:
        raise ValueError('节点位置或视角超出范围')
    return value


def projects(root):
    return [p.name for p in sorted((root / 'Projects').glob('*')) if p.is_dir() and p.resolve().parent == (root / 'Projects').resolve()]


def catalog(root, home, project=None):
    value = rules.inventory(root, home)
    if project is not None:
        value['items'] = [i for i in value['items'] if not i['scope'].startswith('project:') or i['scope'] == 'project:' + project]
    for item in value['items']:
        system = Path(item['path']).resolve().is_relative_to((home / 'skills/.system').resolve())
        item['usable'] = item['active'] and (item['scope'] != 'readonly' or system)
    return {'items': value['items'], 'projects': [project] if project is not None else projects(root)}


def graph(value, root):
    if not isinstance(value, dict) or set(value) != {'name', 'project', 'nodes', 'edges', 'view'}:
        raise ValueError('流程字段无效')
    text(value['name'], empty=False)
    if value['project'] not in projects(root):
        raise ValueError('请选择已登记项目')
    nodes, edges, view = value['nodes'], value['edges'], value['view']
    if not isinstance(nodes, list) or len(nodes) > 60 or not isinstance(edges, list) or len(edges) > 160:
        raise ValueError('每张图最多60个节点、160条连线')
    if not isinstance(view, dict) or set(view) != {'x', 'y', 'scale'}:
        raise ValueError('视角字段无效')
    number(view['x'], -100000, 100000); number(view['y'], -100000, 100000); number(view['scale'], .2, 2.5)
    identifiers = set()
    for node in nodes:
        fields = {'id', 'type', 'label', 'x', 'y', 'text', 'source_id', 'source_revision'}
        if not isinstance(node, dict) or set(node) not in (fields, fields | {'routing'}):
            raise ValueError('节点字段无效')
        if not isinstance(node['id'], str) or not ID.fullmatch(node['id']) or node['id'] in identifiers or not isinstance(node['type'], str) or node['type'] not in TYPES:
            raise ValueError('节点ID重复或类型无效')
        identifiers.add(node['id'])
        text(node['label'], empty=False); text(node['text'], 12000)
        text(node['source_id'], 64); text(node['source_revision'], 64)
        number(node['x'], -10000, 10000); number(node['y'], -10000, 10000)
        if 'routing' in node:
            if node['type'] != 'agent': raise ValueError('仅Agent节点可设置模型策略')
            if node['routing'] is None: raise ValueError('模型策略不能为空值')
            router.policy(node['routing'])
    seen = set()
    for edge in edges:
        if not isinstance(edge, dict) or set(edge) != {'from', 'to'}:
            raise ValueError('连线字段无效')
        start, end = edge['from'], edge['to']
        if not isinstance(start, str) or not isinstance(end, str) or start not in identifiers or end not in identifiers or start == end or (start, end) in seen:
            raise ValueError('连线有重复、自环或缺失节点')
        seen.add((start, end))
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError('流程内容过大')
    return copy.deepcopy(value)


def ordered(value):
    nodes = {n['id']: n for n in value['nodes']}
    incoming = {ident: [] for ident in nodes}
    for edge in value['edges']:
        a, b = nodes[edge['from']], nodes[edge['to']]
        if not (a['type'] in SOURCES | {'input', 'agent'} and b['type'] == 'agent' or a['type'] == 'agent' and b['type'] == 'output'):
            raise ValueError('连线类型无效：任务/规则/Skill/角色接Agent，Agent接Agent或输出')
        incoming[b['id']].append(a['id'])
    remaining, result = set(nodes), []
    while remaining:
        ready = [n['id'] for n in value['nodes'] if n['id'] in remaining and all(p not in remaining for p in incoming[n['id']])]
        if not ready:
            raise ValueError('流程存在循环，请断开形成回路的连线')
        result.extend(ready); remaining.difference_update(ready)
    return nodes, incoming, result


def preview(root, home, value, project=None):
    value = graph(value, root)
    nodes, incoming, order = ordered(value)
    if not any(n['type'] == 'agent' for n in nodes.values()) or not any(n['type'] == 'output' for n in nodes.values()):
        raise ValueError('请添加Agent步骤和输出，并连接任务与规则')
    resources = {r['id']: r for r in catalog(root, home, project)['items']}
    pool = router.catalog(root, project)
    selections = {}
    blocks, warnings, used, snapshots, has_task = [], [], set(), {}, {}
    for ident in order:
        node = nodes[ident]
        parents = [nodes[p] for p in incoming[ident]]
        if node['type'] == 'agent':
            tasks = [p for p in parents if p['type'] == 'input']
            previous = [p for p in parents if p['type'] == 'agent']
            if not tasks and not any(has_task.get(p['id']) for p in previous):
                raise ValueError(f"{node['label']}：缺少上游任务，请连接任务节点")
            if any(not p['text'].strip() for p in tasks):
                raise ValueError(f"{node['label']}：上游任务内容为空")
            has_task[ident] = True
            parts = [f"## Agent：{node['label']} [{ident}]", '本页仅组合预览，尚未运行。规则作为附加约束，不覆盖系统权限和项目约定。']
            parts += [f"### 任务：{p['label']}\n{p['text']}" for p in tasks]
            if node['text'].strip(): parts.append('### 本步骤要求\n' + node['text'])
            for p in parents:
                used.add(p['id'])
                if p['type'] not in SOURCES:
                    continue
                source = resources.get(p['source_id'])
                if not source or source['kind'] != p['type'] or not source['usable']:
                    raise ValueError(f"{p['label']}：源文件缺失、已停用或仅为未核验插件缓存")
                if source['revision'] != p['source_revision']:
                    raise rules.Conflict(f"{p['label']}：源文件已变化，请在节点中更新引用后重新预览")
                read = rules.read_file(root, home, source['id'])
                if read['revision'] != p['source_revision'] or read['active'] != source['active'] or read['path'] != source['path']:
                    raise rules.Conflict(f"{p['label']}：读取期间源文件变化，请重试")
                content = read['content']
                if p['type'] == 'role':
                    fields = tomllib.loads(content)
                    content = fields.get('developer_instructions')
                    if not isinstance(content, str) or not content.strip():
                        raise ValueError(f"{p['label']}：角色缺少developer_instructions")
                parts.append(f"### {p['label']}\n来源：{source['path']}\nSHA-256：{read['revision']}\n\n{content}" + ('\n\n节点附加要求：\n' + p['text'] if p['text'].strip() else ''))
                snapshots[source['id']] = {'id': source['id'], 'path': source['path'], 'revision': read['revision']}
            parts += [f"### 前置结果（未运行，占位符）\n{{{{result:{p['id']}}}}} · {p['label']}" for p in previous]
            selection = router.select(pool, node.get('routing'), '\n\n'.join(parts),
                previous_tokens=sum(router.policy(p.get('routing'))['output_tokens'] for p in previous),
                upstream_blocked=any(selections[p['id']]['status'] == 'blocked' for p in previous))
            selections[ident] = selection
            parts.append(router.describe(selection))
            blocks.append({'id': ident, 'label': node['label'], 'content': '\n\n'.join(parts), 'routing': selection})
        if node['type'] == 'output':
            if not parents:
                raise ValueError(f"{node['label']}：输出没有连接Agent")
            used.update(p['id'] for p in parents)
    for node in nodes.values():
        if node['id'] not in used and node['type'] != 'output':
            warnings.append(f"{node['label']}：没有下游使用此节点")
    outputs = [{'id': n['id'], 'label': n['label'], 'from': incoming[n['id']], 'requirement': n['text']} for n in nodes.values() if n['type'] == 'output']
    markdown = f"# {value['name']}\n\n项目：{value['project']} · 编排预览，未执行\n\n" + '\n\n'.join(b['content'] for b in blocks)
    markdown += '\n\n## 输出映射\n' + '\n'.join(f"- {o['label']} ← {', '.join(o['from'])}\n  {o['requirement']}" for o in outputs)
    if len(markdown.encode()) > 600_000:
        raise ValueError('组合正文超过600KB，请拆分流程或减少规则')
    return {'blocks': blocks, 'outputs': outputs, 'sources': list(snapshots.values()), 'warnings': warnings, 'markdown': markdown, 'executed': False}


def storage(root):
    path = root / 'State/workflows'
    rules.safe(path, root)
    if not rules.writable(path, root):
        raise ValueError('流程存储目录不能是链接')
    return path


def file_path(root, ident):
    if not isinstance(ident, str) or not re.fullmatch(r'[a-f0-9]{32}', ident):
        raise ValueError('流程ID无效')
    path = storage(root) / f'{ident}.json'
    if not rules.writable(path, root): raise ValueError('流程文件不能是链接')
    return path


def load(root, ident):
    path = file_path(root, ident)
    if path.stat().st_size > MAX_BYTES + 2000: raise ValueError('流程文件过大')
    raw = path.read_bytes()
    value = json.loads(raw)
    return {'id': ident, 'revision': rules.digest(raw), 'updated_at': value['updated_at'], 'graph': graph(value['graph'], root)}


def dispatch(root, payload, *, home=None):
    root = Path(root).resolve()
    home = Path(home or os.environ.get('CODEX_HOME') or Path.home() / '.codex').resolve()
    project = None
    if isinstance(payload, dict) and 'project' in payload:
        payload = dict(payload)
        import workstation_matt_map as matt
        project = matt.project_name(root, payload.pop('project'))
    allowed = {'catalog': {'action'}, 'list': {'action'}, 'load': {'action', 'id'},
        'save': {'action', 'id', 'revision', 'graph'}, 'preview': {'action', 'graph'},
        'models': {'action'}, 'save-models': {'action', 'revision', 'models'}}
    if not isinstance(payload, dict) or not isinstance(payload.get('action'), str) or payload['action'] not in allowed or set(payload) != allowed[payload['action']]:
        raise ValueError('流程动作或字段无效')
    with _lock:
        action = payload['action']
        if action == 'models': return router.catalog(root, project)
        if action == 'save-models': return router.save(root, payload['revision'], payload['models'], project)
        if action == 'catalog': return catalog(root, home, project)
        if action in {'save','preview'} and project is not None and (not isinstance(payload['graph'],dict) or payload['graph'].get('project') != project):
            raise ValueError('流程不属于当前项目')
        if action == 'preview': return preview(root, home, payload['graph'], project)
        if action == 'load':
            value = load(root, payload['id'])
            if project is not None and value['graph']['project'] != project: raise ValueError('流程不属于当前项目')
            return value
        if action == 'list':
            rows = []
            for path in storage(root).glob('*.json'):
                try:
                    item = load(root, path.stem)
                    if project is not None and item['graph']['project'] != project: continue
                    rows.append({k: item[k] for k in ('id', 'updated_at')} | {'name': item['graph']['name'], 'project': item['graph']['project']})
                except (ValueError, OSError, KeyError): pass
            return {'items': sorted(rows, key=lambda r: r['updated_at'], reverse=True)}
        value = graph(payload['graph'], root)
        if not isinstance(payload['id'], str): raise ValueError('流程ID无效')
        ident = payload['id'] or uuid.uuid4().hex
        path = file_path(root, ident)
        if not isinstance(payload['revision'], str): raise ValueError('缺少修订号')
        if path.exists():
            if project is not None and load(root, ident)['graph']['project'] != project: raise ValueError('不能改写其他项目的流程')
            if payload['revision'] != rules.digest(path.read_bytes()):
                raise rules.Conflict('流程已在其他页面修改，请先导出草稿再重新载入')
        elif payload['revision'] != 'new':
            raise rules.Conflict('流程文件已不在原位置，请另存为新流程')
        updated = rules.mapping.utc_now()
        raw = json.dumps({'schema_version': 1, 'updated_at': updated, 'graph': value}, ensure_ascii=False, indent=2).encode()
        rules.atomic_write(path, raw, root)
        return {'id': ident, 'revision': rules.digest(raw), 'updated_at': updated, 'saved': True}
