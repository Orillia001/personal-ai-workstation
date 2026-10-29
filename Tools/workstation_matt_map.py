"""Read-only Matt method map and bounded explicit stage records; no executor."""
from __future__ import annotations
import copy
import hashlib
import itertools
import json
import os
import re
from pathlib import Path

import workstation_codex as metadata
import workstation_codex_manage as files

STAGES = [
    dict(id='clarify', title='澄清需求', skills=['grill-with-docs','grill-me','grilling'], when='需求仍有影响方案的未决问题', output='目标、范围、验收；按需维护术语与决策'),
    dict(id='prototype', title='原型验证', skills=['prototype','handoff'], when='需要可运行界面或逻辑才能决定；可选', output='可验证原型、结论与正式实现边界'),
    dict(id='spec', title='形成规格', skills=['to-spec'], when='跨会话工作或需要明确规格；小功能可直接用验收条件', output='项目规格与范围'),
    dict(id='tickets', title='拆分任务', skills=['to-tickets','wayfinder'], when='规格已确定且需要拆分；大方向不明先走wayfinder', output='任务、依赖及验收条件'),
    dict(id='implement', title='实现', skills=['implement','implement-spec','tdd'], when='需求及适用接口已明确，按任务规模选择实现方式', output='代码与有意义的行为回归'),
    dict(id='verify', title='验证', skills=['tdd','implement'], when='针对实际变更验证公共接口、界面及必要边界', output='验证结果、截图与可复跑证据'),
    dict(id='review', title='独立双轴审查', skills=['code-review'], when='实现完成后分别审查规范和需求', output='Standards / Spec报告及问题关闭依据'),
    dict(id='release', title='安装与交付', skills=['pr'], when='仅执行已有授权范围；PR、安装、外发等按项目约定', output='本地可用结果或适用的PR/交付记录'),
    dict(id='retro', title='复盘改进', skills=['retro','writing-for-agents'], when='复杂实现、缺陷修复或流程遗漏后', output='落实到导航、检查或规范的改进'),
]
BRANCHES = [
    dict(id='uncertain',title='方向尚不明确',skills=['wayfinder','grill-with-docs','to-questionnaire'],target='澄清 → 规格',description='先解决决策问题，再进入规格与任务拆分'),
    dict(id='bug',title='已有故障',skills=['diagnosing-bugs'],target='诊断 → 实现 → 验证 → 审查 → 复盘',description='从可复现问题进入修复路线'),
    dict(id='intake',title='外部问题待分流',skills=['triage'],target='分流 → 实现',description='用于外部提交的问题，不重新分流已写好的任务单'),
    dict(id='health',title='架构与代码健康',skills=['improve-codebase-architecture','codebase-design'],target='发现机会 → 选定方案 → 实现',description='形成可验证的改进范围'),
]
SUPPORT = [
    dict(id='context',title='上下文与领域',skills=['handoff','domain-modeling','codebase-design','writing-for-agents','setup-matt-pocock-skills']),
    dict(id='learning',title='研究与辅助',skills=['research','teach','wait-what','wizard','ask-matt']),
]
STATUSES = {'pending','running','blocked','completed','skipped'}
TASK_ID = re.compile(r'^[a-z0-9][a-z0-9-]{0,63}$')


def projects(root):
    boundary=(root/'Projects').resolve()
    return [p.name for p in sorted(boundary.glob('*')) if p.is_dir() and p.resolve().parent==boundary]


def project_name(root, value):
    if not isinstance(value,str) or value not in projects(root):
        raise ValueError('请选择已登记项目')
    return value


def read_record(root, path):
    if not files.writable(path, root): raise ValueError('阶段记录路径不能是链接')
    with path.open('rb') as stream: raw=stream.read(120001)
    if len(raw)>120000: raise ValueError('阶段记录超过120KB')
    value=json.loads(raw)
    task=path.parent.name
    if not TASK_ID.fullmatch(task) or not isinstance(value,dict) or value.get('schema_version')!=1 or value.get('task')!=task:
        raise ValueError('阶段记录ID或版本不匹配')
    project_name(root,value.get('project'))
    if value.get('status') not in STATUSES or any(not isinstance(value.get(k),str) for k in ('title','updated_at')):
        raise ValueError('阶段记录字段无效')
    stages=value.get('stages'); seen=set(); result=[]
    if not isinstance(stages,list) or not 1<=len(stages)<=len(STAGES): raise ValueError('阶段列表无效')
    for stage in stages:
        if not isinstance(stage,dict) or stage.get('id') not in {s['id'] for s in STAGES} or stage['id'] in seen or stage.get('status') not in STATUSES:
            raise ValueError('阶段类型、状态或重复记录无效')
        if not isinstance(stage.get('note'),str) or not isinstance(stage.get('evidence'),list) or len(stage['evidence'])>40:
            raise ValueError('阶段说明或证据无效')
        seen.add(stage['id']); evidence=[]
        for name in stage['evidence']:
            if not isinstance(name,str) or len(name)>1000 or Path(name).is_absolute() or '..' in Path(name).parts:
                raise ValueError('证据路径无效')
            target=root/name; files.safe(target,root)
            if not files.writable(target,root): raise ValueError('证据路径不能是链接')
            evidence.append(dict(path=name,exists=target.is_file()))
        updated=stage.get('updated_at')
        result.append(dict(id=stage['id'],status=stage['status'],note=stage['note'][:1600],evidence=evidence,
                           updated_at=updated if isinstance(updated,str) else None))
    return dict(task=task,project=value['project'],title=value['title'][:160],status=value['status'],
                updated_at=value['updated_at'][:80],stages=result,source=str(path.relative_to(root)).replace('\\','/'))


def snapshot(root, *, home=None):
    root=Path(root).resolve();home=Path(home or os.environ.get('CODEX_HOME') or Path.home()/'.codex').resolve()
    groups=[dict(id='router',skills=['ask-matt'])]+STAGES+BRANCHES+SUPPORT
    names=list(dict.fromkeys(name for group in groups for name in group['skills']))
    skills=[]
    for name in names:
        found=None
        for base in (home/'skills',home.parent/'.agents/skills'):
            if not files.writable(base/name/'SKILL.md',base.parent): continue
            found=metadata.skill_file(base/name/'SKILL.md','user',base.parent)
            if found: break
        skills.append(dict(id=name,available=bool(found),path=found['path'] if found else None,
                           sha256=found['sha256'] if found else None,description=found['description'] if found else '未发现本机入口'))
    warnings=[];tasks=[];scratch=root/'.scratch'
    if scratch.exists() and not files.writable(scratch,root): raise ValueError('Matt记录目录不能是链接')
    paths=list(itertools.islice(scratch.glob('*/matt-workflow.json'),201))
    if len(paths)>200: warnings.append('阶段记录超过200份，本次仅读取前200份。')
    for path in paths[:200]:
        try: tasks.append(read_record(root,path))
        except (ValueError,OSError,TypeError,KeyError) as error: warnings.append(f'{path.parent.name}：{str(error)[:160]}')
    tasks.sort(key=lambda t:t['updated_at'],reverse=True)
    sources=[]
    for path,boundary in ((root/'docs/agents/workflow.md',root),(home/'skills/ask-matt/SKILL.md',home)):
        if path.is_file() and files.writable(path,boundary) and path.stat().st_size<=100000:
            sources.append(dict(path=str(path),sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    return dict(schema_version=1,actor=dict(id='codex',title='Codex · 我',description='由当前聊天中的我选择路线、调用适用技能、核验结果并记录阶段。'),
        router=dict(id='router',title='ask-matt · 选择路线',skills=['ask-matt'],when='先看任务类型与已有上下文',output='选择适用路线与技能，不要求每个任务跑完整清单'),
        stages=copy.deepcopy(STAGES),branches=copy.deepcopy(BRANCHES),support=copy.deepcopy(SUPPORT),skills=skills,
        tasks=tasks,projects=projects(root),sources=sources,warnings=warnings,read_at=metadata.utc_now(),mode='method-map-and-explicit-records; no executor')


def project_projection(root, project, value):
    """Project local metadata plus explicitly shared user/station resources."""
    project_name(root,project);value=copy.deepcopy(value);boundary=(root/'Projects').resolve();current=boundary/project
    def visible(path):
        p=Path(path).resolve()
        return not p.is_relative_to(boundary) or p.is_relative_to(current)
    value['local']['skills']=[s for s in value['local']['skills'] if visible(s['path'])]
    for key in ('rules','roles'):value['configuration'][key]=[s for s in value['configuration'][key] if visible(s['path'])]
    value['local']['threads']=[t for t in value['local']['threads'] if Path(t.get('cwd','')).resolve().is_relative_to(current)]
    value['cwd']=str(current);value['project']=project
    return value
