/* Codex file mapping and separately mounted explicit coursework runtime. */
window.CodexMap=(()=>{
  function create(scope=''){
  const manager=CodexRuleManager.forProject(scope),canvas=WorkflowCanvas.forProject(scope),runner=CourseworkRunner.forProject(scope);
  const labels={canvas:'编排画布',runs:'运行与证据',skills:'技能',configuration:'Agent 配置',threads:'聊天任务',agents:'当前子 Agent',management:'规则管理'};
  const statusLabels={active:'记录执行中',running:'日志记录执行中',idle:'记录空闲',completed:'日志记录已完成',interrupted:'日志记录已中断',errored:'记录出错',systemError:'记录系统错误',waiting:'记录等待',notLoaded:'未加载',unknown:'状态未知'};
  const scopeLabels={repo:'项目技能',user:'用户技能',system:'系统技能',admin:'管理技能','plugin-cache':'插件缓存'};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const state={tab:'canvas',query:'',scope:'all',scroll:0,open:new Set()};
  let host=null,data=null,busy=false,error='',controller=null,generation=0,token='';
  const html=()=>'<section class="codex-map" aria-label="Codex 数据映射"></section>';
  const date=value=>{if(!value)return '未读取';const d=new Date(typeof value==='number'?value*1000:value);return Number.isNaN(d.getTime())?'时间未知':d.toLocaleString('zh-CN',{hour12:false})};
  const agentTree=()=>data?.agent_tree||{};
  const matches=row=>!state.query||JSON.stringify(row).toLocaleLowerCase().includes(state.query.toLocaleLowerCase());
  const badge=(value,kind='')=>`<span class="cm-badge ${kind}">${esc(value)}</span>`;
  function details(id,fields){return `<details data-detail-id="${esc(id)}" ${state.open.has(id)?'open':''}><summary>来源与详情</summary><dl>${fields.filter(([,v])=>v!==undefined&&v!==null&&v!=='').map(([k,v])=>`<dt>${esc(k)}</dt><dd>${esc(Array.isArray(v)?v.join('\n'):v)}</dd>`).join('')}</dl></details>`}
  function row(id,title,badges,description,fields){return `<article class="cm-row"><div class="cm-row-head"><strong>${esc(title)}</strong>${badges}</div>${description?`<p>${esc(description)}</p>`:''}${details(id,fields)}</article>`}
  function count(tab){if(tab==='canvas'||tab==='runs')return '';if(tab==='management')return manager.count();if(!data)return '—';return {skills:data.local.skills.length,configuration:data.configuration.rules.length+data.configuration.roles.length,threads:data.local.threads.length,agents:agentTree().agents?.filter(a=>a.parent!==null).length||0}[tab]}
  function content(){
    if(state.tab==='canvas')return canvas.html();
    if(state.tab==='runs')return runner.html();
    if(state.tab==='management')return manager.html();
    if(!data)return `<div class="cm-empty">${busy?'正在读取 Codex 本机数据…':'尚未读取数据，点击刷新重试。'}</div>`;
    let rows=[];
    if(state.tab==='skills'){
      const files=data.local.skills.filter(matches),cached=data.plugin_cache.filter(matches);
      rows=(state.scope==='cache'?[]:files).map(s=>row(s.path,s.name,badge('文件发现','muted')+badge(scopeLabels[s.scope]||s.scope,'muted'),s.description,[['来源','本机 SKILL.md 文件'],['范围',data.cwd],['文件',s.path],['修改时间',date(s.modified_at)],['SHA-256',s.sha256],['读取时间',date(data.local.collected_at)]]));
      if(state.scope!=='codex'&&cached.length)rows.push(`<h2 class="cm-section-title">插件缓存 · ${cached.length} 项（启用状态未核验）</h2>`,...cached.map(s=>row(s.path,s.name,badge('缓存发现','muted'),s.description,[['说明','缓存存在不表示当前会话已加载或启用'],['版本',s.version],['文件',s.path]])));
    }else if(state.tab==='configuration'){
      rows=data.configuration.rules.filter(matches).map(r=>row(r.path,r.name,badge('规则文件','muted'),'',[['文件',r.path],['章节',r.headings],['修改时间',date(r.modified_at)],['SHA-256',r.sha256]]));
      const roles=data.configuration.roles.filter(matches);
      rows.push(`<h2 class="cm-section-title">自定义 Agent 角色</h2>`,...(roles.length?roles.map(r=>row(r.path,r.name,badge('角色配置','muted'),r.description,[['模型',r.model],['推理强度',r.model_reasoning_effort],['文件',r.path]])):['<p class="cm-empty">未发现匹配的自定义角色配置。角色配置和 AGENTS.md 均不表示已有运行中的 Agent。</p>']));
    }else if(state.tab==='threads'){
      rows=data.local.threads.filter(matches).map(t=>row(t.id,t.title||`任务 ID · ${t.id}`,badge(statusLabels[t.status]||'状态未知',t.status==='unknown'?'warning':''),t.id,[['工作目录',t.cwd],['任务来源',t.source],['任务更新时间',date(t.updated_at)],['执行事件',t.event||'无可用事件'],['事件时间',date(t.event_at)],['任务读取',date(data.local.task_collected_at)],['状态说明','仅表示文件中的最后执行记录，不证明当前进程存活。']]));
      if(data.local.has_more_threads)rows.push(scope?'<p class="cm-notice">从最近100条本机任务中按此项目筛选，可能仍有更早记录未列出。</p>':'<p class="cm-notice">当前展示最近100条本机任务，仍有更早记录未列出。</p>');
    }else{
      rows=(agentTree().agents||[]).filter(matches).map(a=>row(a.id,a.display_name,badge(statusLabels[a.status]||'状态未知',a.status==='unknown'?'warning':''),a.title,[['线程ID',a.id],['所属映射聊天',agentTree().root_thread_id],['父线程',a.parent||'根 Agent'],['角色',a.agent_role],['执行事件',a.event||'无可用事件'],['事件时间',date(a.event_at)],['读取时间',date(agentTree().read_at)],['数据情况',agentTree().stale?'上次结果（本次读取失败）':'本次读取'],['来源',agentTree().source],['状态说明','父子关系来自状态库；执行状态来自各自日志，不是进程监控。']]));
      if(!agentTree().available)rows.push('<div class="cm-empty">未读取到映射聊天的 Agent 记录，请核对聊天绑定和本机状态库。</div>');
    }
    return rows.join('')||'<div class="cm-empty">没有匹配的数据。</div>';
  }
  function note(){return {runs:'按已保存路线创建任务，显式启动。研究计划、分析方案与最终交付需要人工确认；运行记录保存在本项目。',skills:'直接读取本机 SKILL.md；文件发现不代表当前聊天已加载或启用。插件缓存另列。',configuration:'显示规则文件与自定义角色配置，不代表这些角色正在运行。',threads:'直接只读本机状态库与执行事件。记录不等于实时运行状态；点击刷新读取最新文件。',agents:'显示绑定聊天的真实父子关系与各自日志记录；不创建 Agent，不将历史记录视为进程存活证明。',management:'管理本机 Skill、AGENTS 规则和 Agent 角色文件；系统及插件缓存只读。文件入口状态不代表当前聊天的加载状态。'}[state.tab]}
  function statusText(){if(busy)return '正在读取…';if(!data)return '未读取';return `本机读取 ${date(data.local.collected_at)}${data.local.tasks_stale?' · 任务使用上次结果':''}`}
  function renderResults(){if(!host)return;const box=host.querySelector('.cm-results');state.scroll=box?.scrollTop||0;box.innerHTML=content();box.scrollTop=state.scroll;host.querySelector('.cm-notice').textContent=note()}
  function render(){
    if(!host)return;
    host.classList.toggle('is-canvas',state.tab==='canvas');
    host.innerHTML=`<div class="cm-toolbar"><label class="cm-search"><span>搜索</span><input type="search" aria-label="搜索 Codex 数据" placeholder="名称、说明或来源" maxlength="160" value="${esc(state.query)}"></label><button data-cm-action="refresh">刷新</button><span class="cm-status" role="status">${esc(statusText())}</span></div><nav class="cm-tabs" aria-label="Codex 数据分类">${Object.entries(labels).map(([id,label])=>`<button data-cm-tab="${id}" aria-pressed="${state.tab===id}">${label} <span data-cm-count="${id}">${count(id)}</span></button>`).join('')}</nav><p class="cm-notice">${esc(note())}</p><div class="cm-filter" ${state.tab==='skills'?'':'hidden'} style="padding:0 16px 10px"><label>技能来源 <select aria-label="技能来源"><option value="all">全部来源</option><option value="codex">本机技能文件</option><option value="cache">仅插件缓存</option></select></label></div><div class="cm-messages" role="status"></div><div class="cm-results">${content()}</div>`;
    host.querySelector('select').value=state.scope;
    host.querySelector('.cm-results').scrollTop=state.scroll;
    if(state.tab==='management')manager.mount(host.querySelector('.cm-manager'),token,state.query);
    if(state.tab==='canvas')canvas.mount(host.querySelector('.workflow-canvas'),token);
    if(state.tab==='runs')runner.mount(host.querySelector('.coursework-runner'),token);
    updateMessages();
  }
  function updateMessages(){
    if(!host)return;
    const messages=[error,...(data?.local.warnings||[]),data?.local.tasks_stale?`任务读取失败，保留 ${date(data.local.task_collected_at)} 的任务及子 Agent 记录；点击刷新可重试。`:'',agentTree().error].filter(Boolean);
    host.querySelector('.cm-messages').innerHTML=messages.map(m=>`<p class="cm-notice cm-error">${esc(m)}</p>`).join('');
    host.querySelector('.cm-status').textContent=statusText();
    for(const id of Object.keys(labels))host.querySelector(`[data-cm-count="${id}"]`).textContent=count(id);
    host.querySelector('[data-cm-action="refresh"]').setAttribute('aria-busy',String(busy));
  }
  async function load(refresh=false){
    if(busy||!host)return;
    busy=true;error='';updateMessages();if(!data&&!['canvas','management','runs'].includes(state.tab))renderResults();const seq=++generation,abort=new AbortController();controller=abort;
    const timer=setTimeout(()=>abort.abort(),35000);
    try{
      const response=await fetch('/api/workbench/codex-map',{method:'POST',headers:{'Content-Type':'application/json','X-Workstation-Token':token},body:JSON.stringify({refresh,...(scope?{project:scope}:{})}),signal:abort.signal});
      const value=await response.json();if(!response.ok)throw Error(value.error||'Codex 数据读取失败');
      if(seq!==generation||!host)return;
      data=value;if(!['canvas','management','runs'].includes(state.tab))renderResults();
    }catch(e){if(seq===generation&&host)error=e.name==='AbortError'?'读取超时，可点击刷新重试。':String(e.message||'读取失败，请重试。')}
    finally{clearTimeout(timer);if(seq===generation){busy=false;updateMessages()}}
  }
  function onClick(e){const button=e.target.closest('button');if(!button)return;
    if(button.dataset.cmAction==='refresh'){if(state.tab==='management')manager.reload();else if(state.tab==='runs')runner.mount(host.querySelector('.coursework-runner'),token);else load(true);return}
    const tab=button.dataset.cmTab;if(!Object.hasOwn(labels,tab))return;
    manager.unmount();canvas.unmount();runner.unmount();state.tab=tab;state.scroll=0;render();host.querySelector(`[data-cm-tab="${tab}"]`).focus();
  }
  function onInput(e){if(e.target.closest('.cm-toolbar')&&e.target.matches('input[type="search"]')){state.query=e.target.value;state.scroll=0;if(state.tab==='management')manager.filter(state.query);else if(state.tab!=='runs')renderResults()}}
  function onChange(e){if(e.target.closest('.cm-filter')&&e.target.matches('select')){state.scope=e.target.value;state.scroll=0;renderResults()}}
  function onToggle(e){const id=e.target.dataset?.detailId;if(id){if(e.target.open)state.open.add(id);else state.open.delete(id)}}
  function rulesChanged(){load(true)}
  function unmount(){
    manager.unmount();
    canvas.unmount();
    runner.unmount();
    if(host){state.scroll=host.querySelector('.cm-results')?.scrollTop||0;host.removeEventListener('click',onClick);host.removeEventListener('input',onInput);host.removeEventListener('change',onChange);host.removeEventListener('toggle',onToggle,true);host.removeEventListener('codex-inventory-loaded',updateMessages);host.removeEventListener('codex-rules-changed',rulesChanged)}
    host=null;++generation;controller?.abort();controller=null;busy=false;
  }
  function mount(element,controlToken){
    unmount();host=element;token=controlToken;render();
    host.addEventListener('click',onClick);host.addEventListener('input',onInput);host.addEventListener('change',onChange);host.addEventListener('toggle',onToggle,true);
    host.addEventListener('codex-inventory-loaded',updateMessages);host.addEventListener('codex-rules-changed',rulesChanged);
    load(false);
  }
  return {html,mount,unmount};

  }
  const instances=new Map();
  function forProject(project=''){if(!instances.has(project))instances.set(project,create(project));return instances.get(project)}
  return {...forProject(),forProject};
})();
