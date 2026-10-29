"""Offline, explainable selection from user-declared metadata. Never calls a provider."""
from __future__ import annotations
import copy
import json
import math
import re
from decimal import Decimal

import workstation_codex_manage as files

CAPABILITIES = {'text', 'code', 'reasoning', 'vision', 'tools'}
DEFAULT_POLICY = dict(mode='auto', model_id='', strategy='quality', capabilities=['text'],
                      local_only=False, budget_usd=1, input_tokens=1000, output_tokens=2000)
MODEL_FIELDS = {'id', 'provider', 'model', 'enabled', 'local', 'capabilities', 'quality',
                'context_tokens', 'max_output_tokens', 'input_usd_per_million', 'output_usd_per_million'}
IDENT = re.compile(r'^[a-zA-Z0-9_-]{1,64}$')
MAX_BYTES = 120_000


def numeric(value, low, high, *, integer=False):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not low <= value <= high or integer and not isinstance(value, int):
        raise ValueError('模型数值超出范围或格式无效')


def identifier(value, *, empty=False):
    if not isinstance(value, str) or not (empty and value == '' or IDENT.fullmatch(value)):
        raise ValueError('模型登记ID无效')


def capabilities(value):
    if not isinstance(value, list) or not value or any(not isinstance(c, str) or c not in CAPABILITIES for c in value) or len(set(value)) != len(value):
        raise ValueError('模型能力必须从已知能力中选择，至少一项且不重复')


def policy(value=None):
    value = copy.deepcopy(DEFAULT_POLICY if value is None else value)
    if not isinstance(value, dict) or set(value) != set(DEFAULT_POLICY):
        raise ValueError('模型选择策略字段无效')
    if value['mode'] not in ('auto', 'manual') or value['strategy'] != 'quality' or not isinstance(value['local_only'], bool):
        raise ValueError('模型选择模式无效')
    identifier(value['model_id'], empty=True)
    capabilities(value['capabilities'])
    numeric(value['budget_usd'], 0, 1_000_000)
    numeric(value['input_tokens'], 1, 10_000_000, integer=True)
    numeric(value['output_tokens'], 1, 1_000_000, integer=True)
    return value


def models(value):
    if not isinstance(value, list) or len(value) > 100:
        raise ValueError('模型池最多登记100项')
    seen = set()
    for model in value:
        if not isinstance(model, dict) or set(model) != MODEL_FIELDS:
            raise ValueError('模型池仅接受指定元数据字段，不接受密钥或连接参数')
        identifier(model['id'])
        if model['id'] in seen:
            raise ValueError('模型登记ID重复')
        seen.add(model['id'])
        for field in ('provider', 'model'):
            text = model[field]
            if not isinstance(text, str) or not text.strip() or len(text) > 160 or any(ord(c) < 32 for c in text):
                raise ValueError('请填写提供商和模型名称（最多160字，无控制字符）')
        if any(not isinstance(model[k], bool) for k in ('enabled', 'local')):
            raise ValueError('启用和本地状态必须为布尔值')
        capabilities(model['capabilities'])
        numeric(model['quality'], 0, 100)
        numeric(model['context_tokens'], 1, 10_000_000, integer=True)
        numeric(model['max_output_tokens'], 1, 1_000_000, integer=True)
        for field in ('input_usd_per_million', 'output_usd_per_million'):
            if model[field] is not None:
                numeric(model[field], 0, 1_000_000)
    if len(json.dumps(value, ensure_ascii=False).encode()) > MAX_BYTES:
        raise ValueError('模型池内容超过120KB')
    return copy.deepcopy(value)


def path(root, project=None):
    if project is not None:
        import workstation_matt_map as matt
        matt.project_name(root, project)
    value = root / 'State/model-router' / (f'projects/{project}/catalog.json' if project is not None else 'catalog.json')
    files.safe(value, root)
    if not files.writable(value, root):
        raise ValueError('模型池不能存储在链接路径')
    return value


def catalog(root, project=None):
    location = path(root, project)
    if not location.exists():
        return dict(models=[], revision='new', updated_at=None)
    if location.stat().st_size > MAX_BYTES + 2000:
        raise ValueError('模型池文件过大')
    raw = location.read_bytes(); data = json.loads(raw)
    if not isinstance(data, dict) or set(data) != {'schema_version', 'models', 'updated_at'} or data['schema_version'] != 1:
        raise ValueError('模型池文件格式无效')
    return dict(models=models(data['models']), revision=files.digest(raw), updated_at=data['updated_at'])


def save(root, revision, value, project=None):
    value = models(value)
    current = catalog(root, project)
    if not isinstance(revision, str) or revision != current['revision']:
        raise files.Conflict('模型池已变化，草稿已保留。请先导出草稿，再明确重新载入模型池。')
    data = dict(schema_version=1, updated_at=files.mapping.utc_now(), models=value)
    raw = json.dumps(data, ensure_ascii=False, indent=2).encode()
    files.atomic_write(path(root, project), raw, root)
    return dict(saved=True, models=value, revision=files.digest(raw), updated_at=data['updated_at'])


def select(pool, settings, prompt, *, previous_tokens=0, upstream_blocked=False):
    """Filter first; rank by declared quality, cost, stable ID. No hidden fallback."""
    settings = policy(settings)
    input_tokens = max(settings['input_tokens'], len(prompt.encode('utf-8')) + previous_tokens)
    output_tokens = settings['output_tokens']
    candidates, eligible = [], []
    for model in pool['models']:
        reasons = []
        if not model['enabled']: reasons.append('未启用')
        missing = sorted(set(settings['capabilities']) - set(model['capabilities']))
        if missing: reasons.append('缺少能力：' + ', '.join(missing))
        if settings['local_only'] and not model['local']: reasons.append('仅本地要求不满足')
        if input_tokens + output_tokens > model['context_tokens']: reasons.append('上下文容量不足')
        if output_tokens > model['max_output_tokens']: reasons.append('输出上限不足')
        cost = None
        if any(model[k] is None for k in ('input_usd_per_million', 'output_usd_per_million')):
            reasons.append('单价未知，无法核对预算')
        else:
            cost = (Decimal(str(model['input_usd_per_million'])) * input_tokens + Decimal(str(model['output_usd_per_million'])) * output_tokens) / 1_000_000
            if cost > Decimal(str(settings['budget_usd'])): reasons.append('预计费用超出每次调用预算')
        if settings['mode'] == 'manual' and settings['model_id'] != model['id']: reasons.append('未被手动指定')
        row = dict(id=model['id'], provider=model['provider'], model=model['model'], quality=model['quality'],
                   estimated_usd=str(cost) if cost is not None else None, reasons=reasons, eligible=not reasons)
        candidates.append(row)
        if not reasons: eligible.append((model, cost, row))
    eligible.sort(key=lambda c: (-c[0]['quality'], c[1], c[0]['id']))
    chosen = eligible[0][2] if eligible and not upstream_blocked else None
    reason = ('上游步骤未选出合格模型，请先处理上游约束' if upstream_blocked else
              '模型池为空，请先登记并保存模型元数据' if not pool['models'] else
              '手动指定项缺失或不满足约束' if not chosen and settings['mode'] == 'manual' else
              '没有满足全部约束的模型，请查看候选排除原因' if not chosen else
              '手动指定项通过全部约束' if settings['mode'] == 'manual' else
              '效果优先：合格项中用户评分最高，同分先选预计费用较低项，再按登记ID排序')
    return dict(status='selected' if chosen else 'blocked', selected=copy.deepcopy(chosen), reason=reason,
                input_tokens=input_tokens, output_tokens=output_tokens, budget_usd=settings['budget_usd'],
                policy=settings, candidates=candidates, pool_revision=pool['revision'], verified=False)


def describe(result):
    chosen = result['selected']
    lines = ['### 模型选择预览 · 未调用', result['reason'],
             f"输入预留/估算 {result['input_tokens']} token，输出上限 {result['output_tokens']} token；每次调用预算 USD {result['budget_usd']}。",
             '能力、评分、启用状态和价格均来自用户登记，未联网验证；纯文本按UTF-8字节及前序输出上限保守估算，并非实际分词/账单。预算是每次调用，不是整个流程总额。',
             f"模型池修订：{result['pool_revision']}（重新预览读取最新已保存池）"]
    if chosen:
        lines.append(f"选中：{chosen['provider']} / {chosen['model']}；用户评分 {chosen['quality']}；预计 USD {chosen['estimated_usd']}。")
    for row in result['candidates']:
        state = '；'.join(row['reasons']) or ('已选中' if chosen and chosen['id'] == row['id'] else '符合约束，按评分/费用/ID顺序候补')
        lines.append(f"- {row['provider']} / {row['model']} [{row['id']}]：{state}；预计 USD {row['estimated_usd'] if row['estimated_usd'] is not None else '未知'}；用户评分 {row['quality']}")
    return '\n'.join(lines)
