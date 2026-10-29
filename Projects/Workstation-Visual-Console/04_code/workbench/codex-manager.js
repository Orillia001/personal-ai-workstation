/* Registered local rule files only. Drafts live in this page until discarded or reloaded. */
window.CodexRuleManager=(()=>{
  function create(scope=''){
  const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const kinds={skill:'Skill',role:'Agent 角色',rule:'AGENTS 规则'};
  const operations={save:'保存前版本',create:'新建记录',install:'安装记录',toggle:'切换入口前版本',archive:'移入备份'};
  const state={items:[],scopes:[],loaded:false,query:'',draft:null,view:'list',confirmation:null,install:{repo:'',ref:'main',subpath:'',name:'',scope:scope?'project:'+scope:'user'},installation:null,history:[],message:'',busy:false};
  let host=null,token='';
  const html=()=>'<section class="cm-manager" aria-label="规则管理"></section>';
  async function api(action,args={}){
    const abort=new AbortController(),timer=setTimeout(()=>abort.abort(),110000);
    try{
      const response=await fetch('/api/workbench/codex-manage',{method:'POST',headers:{'Content-Type':'application/json','X-Workstation-Token':token},body:JSON.stringify({action,...args}),signal:abort.signal});
      const value=await response.json();
      if(response.status===403)throw Error('页面校验已失效。请先导出未保存草稿，再刷新工作台。');
      if(!response.ok)throw Error(value.error||'文件操作失败');
      if(scope){const visible=i=>!i.scope?.startsWith('project:')||i.scope==='project:'+scope;if(action==='inventory'){value.items=value.items.filter(visible);value.scopes=value.scopes.filter(i=>!i.id.startsWith('project:')||i.id==='project:'+scope)}if(action==='history'&&Array.isArray(value.items))value.items=value.items.filter(visible)}
      return value;
    }catch(e){if(e.name==='AbortError')throw Error('请求超时。请刷新清单核对结果后再操作；草稿仍在本页。');throw e}
    finally{clearTimeout(timer)}
  }
  function feedback(){if(!host)return;host.querySelector('.crm-message').textContent=state.message;host.setAttribute('aria-busy',String(state.busy));host.querySelectorAll('button[data-rm]').forEach(b=>{b.disabled=state.busy||b.dataset.unavailable==='true'})}
  async function run(work){if(state.busy)return;state.busy=true;state.completedMessage='';state.message='正在处理…';feedback();try{await work()}catch(e){state.message=(state.completedMessage?state.completedMessage+' 后续读取失败，请刷新清单核对结果；如有草稿请先导出。 ':'')+String(e.message||'操作失败')}finally{state.busy=false;feedback()}}
  async function fetchInventory(){const value=await api('inventory');state.items=value.items;state.scopes=value.scopes;state.loaded=true;host?.dispatchEvent(new CustomEvent('codex-inventory-loaded',{bubbles:true}))}
  function changed(){host?.dispatchEvent(new CustomEvent('codex-rules-changed',{bubbles:true}))}
  async function reload(){await run(async()=>{await fetchInventory();state.message='管理清单已刷新，未保存草稿保持原样。';render()})}
  function scopeOptions(kind,value){return state.scopes.filter(s=>s.kinds.includes(kind)).map(s=>`<option value="${esc(s.id)}" ${value===s.id?'selected':''}>${esc(s.label)}</option>`).join('')}
  function button(action,label,id='',unavailable=false){return `<button data-rm="${action}" data-id="${esc(id)}" data-unavailable="${unavailable}" ${unavailable?'disabled':''}>${label}</button>`}
  function toolbar(){return `<div class="crm-actions">${button('new-skill','新建 Skill')}${button('new-role','新建 Agent')}${button('install','安装 Skill')}${button('history','备份历史')}${state.draft?button('draft','继续草稿'):''}</div>`}
  function list(){const rows=state.items.filter(r=>!state.query||`${r.name} ${r.scope_label} ${r.path} ${kinds[r.kind]}`.toLowerCase().includes(state.query.toLowerCase()));return rows.map(r=>`<article class="cm-row"><div class="cm-row-head"><strong>${esc(r.name)}</strong><span class="cm-badge muted">${kinds[r.kind]}</span><span class="cm-badge muted">${esc(r.scope_label)}</span><span class="cm-badge">${r.scope==='readonly'?'发现文件 · 状态未核验':r.active?'入口存在':'入口已停用'}</span></div><p class="crm-path">${esc(r.path)}</p><div class="crm-actions">${button('read',r.writable?'查看 / 编辑':'只读查看',r.id)}${r.writable?button('toggle',r.active?'停用入口':'启用入口',r.id)+(r.kind==='rule'?'':button('archive','移入备份',r.id)):''}</div></article>`).join('')||`<p class="cm-empty">${state.loaded?'没有匹配的文件。':'正在读取管理清单…'}</p>`}
  function editor(){const d=state.draft;if(!d)return '';return `<section class="crm-editor"><div class="cm-row-head"><h2>${d.id?'编辑文件':`新建 ${kinds[d.kind]}`}</h2>${button('close','收起编辑')}</div>${d.id?`<p class="crm-path">${esc(d.path)}</p>`:`<div class="crm-fields"><label>目录名称<input data-field="name" aria-label="目录名称" maxlength="64" value="${esc(d.name)}" placeholder="my-skill"></label><label>保存范围<select data-field="scope" aria-label="保存范围">${scopeOptions(d.kind,d.scope)}</select></label></div>`}<label class="crm-content-label">${d.writable?'文件内容':'文件内容（只读）'}<textarea aria-label="规则文件内容" data-field="content" spellcheck="false" ${d.writable?'':'readonly'}>${esc(d.content)}</textarea></label><p class="crm-hint">草稿仅保留在本页，切换栏目可继续编辑；刷新页面前请导出。已打开的聊天不保证立即更新规则。</p><div class="crm-actions">${d.writable?button('preview','预览差异')+button('save','保存这版修改','',!d.preview?.changed):''}${button('export','导出草稿')}${button('discard','放弃草稿')}</div><div class="crm-diff" ${d.preview?'':'hidden'}><p class="crm-preview-path">${esc(d.preview?.path)}</p><pre tabindex="0">${esc(d.preview?.diff)}</pre></div></section>`}
  function installer(){const i=state.install;return `<section class="crm-editor"><div class="cm-row-head"><h2>从 GitHub 安装 Skill</h2>${button('close','返回列表')}</div><div class="crm-fields">${[['repo','GitHub 仓库','owner/repo'],['ref','分支或标签','main'],['subpath','仓库中的技能目录','skills/my-skill'],['name','安装目录名称','my-skill']].map(([key,label,placeholder])=>`<label>${label}<input data-install="${key}" aria-label="${label}" value="${esc(i[key])}" placeholder="${placeholder}" maxlength="160"></label>`).join('')}<label>安装范围<select data-install="scope" aria-label="安装范围">${scopeOptions('skill',i.scope)}</select></label></div><p class="crm-hint">下载指定目录及其资源，不执行技能脚本。请确认仓库与版本可信；安装超时后先刷新清单核对结果。</p><div class="crm-actions">${button('install-preview','查看安装位置')}${button('install-commit','安装到此目录','',!state.installation)}</div><div class="crm-install-preview" ${state.installation?'':'hidden'}><p class="crm-path">${esc(state.installation?.path)}</p><p>${esc(state.installation?.message)}</p></div></section>`}
  function history(){return `<section><div class="cm-row-head"><h2>备份历史</h2>${button('close','返回列表')}</div>${state.history.map(r=>`<article class="cm-row"><strong>${esc(r.name)} · ${esc(operations[r.operation]||r.operation)}</strong><p>${esc(r.created_at)} · ${esc(r.scope)}</p>${r.available?button('restore','恢复此版本',r.backup_id):'<span class="crm-hint">'+(r.restored_at?'已经恢复':'新建记录，无先前版本')+'</span>'}</article>`).join('')||'<p class="cm-empty">还没有文件管理备份。</p>'}</section>`}
  function confirmation(){const c=state.confirmation;return `<section class="crm-editor" aria-label="确认文件操作"><h2>${c.action==='toggle'?(c.item.active?'停用入口':'启用入口'):c.action==='archive'?'移入备份':'恢复备份'}</h2><p class="crm-path">${esc(c.path)}</p><p class="crm-hint">${c.action==='toggle'?'通过入口文件的 .disabled 后缀切换。不会中断已经执行的任务，也不代表当前聊天立即卸载规则。':c.action==='archive'?'将整个技能目录或角色文件移入本机备份，之后可从备份历史恢复。':'恢复到所选备份版本。当前文件发生变化时会拒绝覆盖；已有文件也会先备份。'}</p><div class="crm-actions">${button('confirm','确认此文件操作')}${button('cancel-confirm','取消')}</div></section>`}
  function render(){if(!host)return;const scroll=host.scrollTop;host.innerHTML=`<div class="crm-message" role="status" aria-live="polite"></div>${state.view==='confirm'?confirmation():state.view==='editor'?editor():state.view==='install'?installer():state.view==='history'?history():toolbar()+list()}`;host.scrollTop=scroll;feedback()}
  function editingGuard(){if(state.draft?.dirty){state.view='editor';state.message='有未保存草稿，请先保存、导出或放弃，再打开其他文件。';render();return true}return false}
  function newDraft(kind){if(editingGuard())return;state.draft={kind,scope:scope?'project:'+scope:'user',name:'',content:kind==='skill'?'---\nname: my-skill\ndescription: 请填写用途及适用场景。\n---\n\n请填写技能操作说明。\n':'name = "my-agent"\ndescription = "请填写角色用途及适用场景。"\ndeveloper_instructions = """\n请填写角色的职责、规则和边界。\n"""\n',writable:true,dirty:true,preview:null};state.view='editor';state.message='填写名称和内容后预览差异，再保存。';render()}
  function invalidatePreview(){const d=state.draft;if(d){d.dirty=true;d.preview=null}if(!host)return;host.querySelector('.crm-diff')?.setAttribute('hidden','');const save=host.querySelector('[data-rm="save"]');if(save){save.dataset.unavailable='true';save.disabled=true}}
  function exportDraft(){if(!state.draft)return;const blob=new Blob([state.draft.content],{type:'text/plain;charset=utf-8'}),url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download=(state.draft.name||'rules-draft')+(state.draft.kind==='role'?'.toml':'.md');link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);state.message='草稿已导出，尚未写入原文件。';feedback()}
  async function onClick(event){const b=event.target.closest('[data-rm]');if(!b||state.busy)return;event.stopPropagation();const action=b.dataset.rm,id=b.dataset.id;
    if(action==='new-skill'||action==='new-role'){newDraft(action==='new-skill'?'skill':'role');return}
    if(action==='export'){exportDraft();return}
    if(action==='draft'){state.view='editor';render();return}
    if(action==='close'||action==='cancel-confirm'){state.view='list';state.confirmation=null;render();return}
    if(action==='discard'){state.draft=null;state.view='list';state.message='已放弃草稿。';render();return}
    if(action==='install'){state.view='install';render();return}
    if(action==='toggle'||action==='archive'){const item=state.items.find(r=>r.id===id);if(!item)return;state.confirmation={action,item,path:item.path};state.view='confirm';render();return}
    if(action==='restore'){const item=state.history.find(r=>r.backup_id===id),current=state.items.find(r=>r.id===item?.id);if(!item)return;state.confirmation={action,item,path:`${item.scope} / ${item.name} · ${item.created_at}`,revision:current?.revision||'missing',active:current?.active};state.view='confirm';render();return}
    await run(async()=>{
      if(action==='read'){if(editingGuard())return;state.draft={...await api('read',{id}),dirty:false,preview:null};state.view='editor';state.message=state.draft.writable?'读取成功。修改后请先预览差异。':'系统及插件缓存仅供查看。';render()}
      if(action==='history'){await fetchInventory();state.history=(await api('history')).items;state.view='history';state.message='备份保存在工作站本机。';render()}
      if(action==='preview'){const d=state.draft,args=d.id?{id:d.id,revision:d.revision}:{kind:d.kind,scope:d.scope,name:d.name},content=d.content;const value=await api('preview',{...args,content});if(state.draft!==d||d.content!==content||(!d.id&&(d.name!==args.name||d.scope!==args.scope)))throw Error('预览期间草稿有变化，请重新预览。');d.preview=value;state.message=d.preview.changed?'差异已生成，请核对后保存。':'内容没有变化。';render()}
      if(action==='save'){const d=state.draft;if(!d.preview?.changed)throw Error('请先预览这版内容');const submitted=d.content,result=await api('save',{preview_id:d.preview.preview_id,content:submitted,confirmed:true});state.completedMessage=`已保存提交的版本，备份编号 ${result.backup_id}。`;const saved=await api('read',{id:result.id}),newer=state.draft===d&&d.content!==submitted;if(state.draft===d)state.draft={...saved,content:newer?d.content:saved.content,dirty:newer,preview:null};state.message=state.completedMessage+(newer?'等待期间的新输入仍为未保存草稿，请再次预览后保存。':'');await fetchInventory();changed();render()}
      if(action==='install-preview'){const args={...state.install},value=await api('install-preview',args);if(JSON.stringify(args)!==JSON.stringify(state.install))throw Error('安装信息有变化，请重新查看安装位置。');state.installation=value;state.message='请核对安装目标和仓库版本。';render()}
      if(action==='install-commit'){if(!state.installation)throw Error('请先查看安装位置');const result=await api('install',{...state.install,confirmed:true});state.installation=null;state.completedMessage=state.message=result.message;await fetchInventory();changed();state.view='list';render()}
      if(action==='confirm'){const c=state.confirmation;if(!c)return;const args=c.action==='restore'?{backup_id:c.item.backup_id,revision:c.revision,...(c.active===undefined?{}:{active:c.active})}:{id:c.item.id,revision:c.item.revision,active:c.item.active};const result=await api(c.action,{...args,confirmed:true});state.completedMessage=state.message=result.message;await fetchInventory();changed();state.view='list';state.confirmation=null;render()}
    });
  }
  function onInput(e){if(e.target.dataset.field&&state.draft){state.draft[e.target.dataset.field]=e.target.value;invalidatePreview()}if(e.target.dataset.install){state.install[e.target.dataset.install]=e.target.value;state.installation=null;host.querySelector('.crm-install-preview')?.setAttribute('hidden','');const b=host.querySelector('[data-rm="install-commit"]');if(b){b.disabled=true;b.dataset.unavailable='true'}}}
  function filter(query){state.query=query;if(state.view==='list')render()}
  function unmount(){if(host){host.removeEventListener('click',onClick);host.removeEventListener('input',onInput);host.removeEventListener('change',onInput)}host=null}
  function mount(element,controlToken,query=''){unmount();host=element;token=controlToken;state.query=query;host.addEventListener('click',onClick);host.addEventListener('input',onInput);host.addEventListener('change',onInput);render();if(!state.loaded)reload()}
  return {html,mount,unmount,reload,filter,count:()=>state.loaded?state.items.length:'—'};

  }
  const instances=new Map();
  function forProject(project=''){if(!instances.has(project))instances.set(project,create(project));return instances.get(project)}
  return {...forProject(),forProject};
})();
