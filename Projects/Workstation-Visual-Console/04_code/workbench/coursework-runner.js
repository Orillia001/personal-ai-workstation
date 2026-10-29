/* Bounded coursework execution. The server owns transitions, evidence and approvals. */
window.CourseworkRunner = (() => {
  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const states = {ready:'待启动', running:'正在执行', awaiting_approval:'等待人工确认', blocked:'受阻', interrupted:'已中断', released:'已批准本地交付', pending:'待执行', passed:'已通过', completed:'已完成', skipped:'不适用', failed:'未通过'};
  const stateName = value => states[value] || value || '未知';
  const excerpt = (value, limit=180) => {const text=String(value || '');return text.length>limit?text.slice(0,limit)+'…（完整内容见产物）':text};
  const instances = new Map();
  function create(project) {
    const s = {form:{workflow:'',title:'',requirements:'',paths:'',mode:'new',sourceTitle:'',sourcePath:'',sourceText:'',sourceUrl:'',sourceLocator:'',query:'',note:''}, workflows:[], runs:[], selected:'', run:null, status:null, supported:false, profileMessage:'请选择已保存的九关金融学工作流。', message:'正在读取运行环境…', busy:false, retrieved:[], preview:null, viewed:'', scroll:0, expansion:{}};
    let host = null, token = '', lifecycle = 0, controller = null, timer = null, detailSignature = '';
    const html = () => '<section class="coursework-runner" aria-label="作业运行与证据"></section>';
    const button = (action, label, more='') => `<button type="button" data-cr="${action}" ${more}>${label}</button>`;
    const field = (label,key,type='input',rows=4) => `<label>${label}${type==='textarea'?`<textarea aria-label="${label}" data-cr-field="${key}" rows="${rows}">${esc(s.form[key])}</textarea>`:`<input aria-label="${label}" data-cr-field="${key}" value="${esc(s.form[key])}">`}</label>`;
    const current = () => !!s.run && s.run.id === s.selected;
    function shell() {
      host.innerHTML = `<div class="cr-top"><p>按保存的九关流程执行。研究计划、分析方案和最终稿分别等待人工确认；最终确认只生成本地交付包。</p>${button('refresh','刷新运行')}</div><div class="cr-message" role="status" aria-live="polite"></div><div class="cr-environment"></div><div class="cr-body"><details class="cr-create" open><summary>新建作业运行</summary><div class="cr-form"><label>已保存的工作流<select aria-label="已保存的工作流" data-cr-field="workflow"></select></label><p class="cr-profile"></p>${field('作业标题','title')}${field('作业要求','requirements','textarea',5)}<label>处理方式<select aria-label="处理方式" data-cr-field="mode"><option value="new">新写作业</option><option value="rewrite">改写现稿</option><option value="review">仅审校</option></select></label>${field('已有资料路径（每行一项，项目内 .md 或 .txt）','paths','textarea',3)}<p class="cr-help">没有本地资料也可先建立研究计划，后续在“资料与证据”中粘贴原文。路径相对于当前项目；现稿需作为资料提供。</p>${button('create','创建运行')}<p class="cr-help">创建只保存任务。点击“启动执行”才调用本机 Codex。</p></div></details><div class="cr-select"><label>已有运行<select aria-label="已有运行" data-cr-run></select></label></div><div class="cr-run"></div><details class="cr-source"><summary>资料与证据</summary><div class="cr-form">${field('资料标题','sourceTitle')}${field('项目内资料路径（可选）','sourcePath')}${field('粘贴原文（与路径二选一）','sourceText','textarea',6)}${field('原始网址（可选，仅登记来源）','sourceUrl')}${field('原文位置（页码／章节，可选）','sourceLocator')}<p class="cr-help">导入后会保留原文与指纹，并使受影响的核验和确认失效。网址不会自动抓取；仅有标题或网址不能充当正文证据。</p>${button('add-source','导入资料')}<label>检索当前运行证据<input aria-label="检索当前运行证据" data-cr-field="query" value="${esc(s.form.query)}"></label>${button('retrieve','检索证据')}<p class="cr-help">使用本地原文及已提取证据，按词项匹配；不代表互联网检索或向量语义检索。</p><div class="cr-retrieved"></div></div></details><section class="cr-preview" hidden><h3>产物预览</h3><p class="cr-preview-path"></p><pre tabindex="0" aria-label="产物正文"></pre></section></div>`;
      host.querySelector('[data-cr-field="mode"]').value = s.form.mode;
      updateLists(); update();
      for(const el of host.querySelectorAll('.cr-body > details')) if(Object.hasOwn(s.expansion,el.className))el.open=s.expansion[el.className];
    }
    function updateLists() {
      if (!host) return;
      const work = host.querySelector('[data-cr-field="workflow"]');
      work.innerHTML = '<option value="">选择流程</option>' + s.workflows.map(w=>`<option value="${esc(w.id)}">${esc(w.name)}</option>`).join(''); work.value = s.form.workflow;
      const runs = host.querySelector('[data-cr-run]');
      runs.innerHTML = '<option value="">选择运行</option>' + s.runs.map(r=>`<option value="${esc(r.id)}">${esc(r.title || r.id)} · ${esc(stateName(r.status))}</option>`).join(''); runs.value = s.selected;
    }
    function approvalArtifacts() {
      if(!current()||!s.run.pending_approval)return {items:[],reason:'当前没有待确认关卡。'};
      const r=s.run,kind=r.pending_approval.kind,stage=id=>(r.stages||[]).find(row=>row.id===id)?.output_path;
      let paths=[];
      if(kind==='release'){
        const candidate=r.task?.mode==='review'?stage('g7'):(stage('g8')||stage('g6'));
        if(!candidate)return {items:[],reason:r.task?.mode==='review'?'缺少审校结果：需要 G7 审稿产物后才能确认本地交付。':'缺少可交付正文：需要 G8 润色稿或 G6 初稿，不能仅凭终核报告确认。'};
        if(!stage('g9'))return {items:[],reason:'缺少 G9 终核报告，请完成终核后再确认。'};
        paths=[candidate,stage('g9')];
        if(paths[0]===paths[1])return {items:[],reason:'正文与终核报告必须是分别登记的产物，请刷新并核查运行记录。'};
      }else{
        const path=stage({plan:'g1',method:'g4'}[kind]);
        if(!path)return {items:[],reason:'缺少本关产物，请刷新运行并核查阶段记录。'};
        paths=[path];
      }
      const items=paths.map(path=>(r.artifacts||[]).find(a=>a.path===path));
      if(items.some(item=>!item?.sha256))return {items:[],reason:'本关产物尚未完整登记，不能确认。请刷新运行并核查产物记录。'};
      return {items,reason:''};
    }
    const approvalKey = () => current() && s.run.pending_approval ? JSON.stringify([s.run.id,s.run.revision,s.run.pending_approval.request_id,s.run.pending_approval.fingerprint,approvalArtifacts().items.map(a=>[a.path,a.sha256])]) : '';
    function detailsMarkup() {
      if (!current()) return '<p class="cr-empty">选择已有运行，或填写要求后创建。运行与资料仅属于当前项目。</p>';
      const r = s.run, pending = r.pending_approval;
      const approval = pending ? `<section class="cr-approval"><h3>${esc({plan:'确认研究问题与计划',method:'确认分析方案',release:'审阅最终稿并确认本地交付'}[pending.kind] || '人工确认')}</h3><p>${esc(excerpt(pending.summary,240))}</p>${button('approval-preview','查看本关产物')}<p class="cr-help">${pending.kind==='release'?'最终确认需要阅读候选正文（仅审校时为审稿结果）与终核报告。':'先阅读本关产物，再明确确认。'}确认仅放行关卡，不会自动执行下一段。</p>${approvalArtifacts().reason?`<p class="cr-error">${esc(approvalArtifacts().reason)}</p>`:''}<label>确认或退回说明<textarea aria-label="确认或退回说明" data-cr-field="note" rows="3">${esc(s.form.note)}</textarea></label><div class="cr-actions">${button('approve', {plan:'确认计划并放行',method:'确认方案并放行',release:'确认本地交付'}[pending.kind] || '确认并放行')}${button('reject','退回并记录原因')}</div></section>` : '';
      return `<header class="cr-run-header"><div><h2>${esc(r.title)}</h2><p><strong>${esc(stateName(r.status))}</strong> · 当前 ${esc(r.current_stage || '尚未开始')} · ${esc(r.updated_at || '')}</p></div><div class="cr-actions">${button('start',r.status==='ready'&&!r.stages?.some(x=>x.output_path)?'启动执行':'恢复／执行下一段')}${button('stop','停止执行')}</div></header>${r.error?`<p class="cr-error">${esc(r.error)}</p>`:''}${approval}<h3>阶段与执行角色</h3><ol class="cr-stages">${(r.stages || []).map(stage=>`<li class="cr-stage"><div><b>${esc(stage.label || stage.id)}</b><span>${esc(stateName(stage.status))}</span></div><p>${esc(stage.role || '角色由执行器分配')}</p>${stage.summary?`<p>${esc(excerpt(stage.summary))}</p>`:''}${stage.error?`<p class="cr-error">${esc(stage.error)}</p>`:''}${stage.output_path?button('artifact','查看阶段产物',`data-path="${esc(stage.output_path)}"`):''}</li>`).join('')}</ol>${r.plan?.length?`<details class="cr-plan"><summary>当前执行计划</summary><ol>${r.plan.map(p=>`<li>${esc(p.label || p.id)} · ${esc(stateName(p.status))}</li>`).join('')}</ol></details>`:''}<details class="cr-artifacts"><summary>产物与来源记录</summary>${(r.artifacts || []).map(a=>`<div class="cr-artifact">${button('artifact',a.label || a.path,`data-path="${esc(a.path)}"`)}<small>${esc(a.sha256 || '')}</small></div>`).join('') || '<p>尚无产物。</p>'}<h4>已登记资料</h4>${(r.sources || []).map(a=>`<p>${esc(a.id || a.source_id)} · ${esc(a.title)}<br><small>${esc(a.url || a.path || a.origin_url || '')}</small></p>`).join('') || '<p>尚无资料。无证据时依赖资料的阶段会受阻。</p>'}</details><details class="cr-history"><summary>运行记录</summary><pre>${esc(JSON.stringify(r.events || [],null,2))}</pre><p class="cr-help">运行 ID：${esc(r.id)} · 版本：${esc(r.revision)}</p></details>`;
    }
    function renderDetails() {
      if (!host) return;
      const box = host.querySelector('.cr-run'), signature = JSON.stringify(s.run);
      if (signature === detailSignature) return;
      const active = document.activeElement, inBox = active && box.contains(active), action = inBox ? active.dataset.cr : '', path = inBox ? active.dataset.path : '', input = inBox ? active.dataset.crField : '', start = active?.selectionStart, end = active?.selectionEnd;
      const open = new Set([...box.querySelectorAll('details[open]')].map(e=>e.className));
      const top = host.scrollTop, body = host.querySelector('.cr-body'), bodyTop = body.scrollTop;
      box.innerHTML = detailsMarkup(); detailSignature = signature;
      for (const el of box.querySelectorAll('details')) if (open.has(el.className)) el.open = true;
      if (inBox) {
        const next = [...box.querySelectorAll('button,textarea,input')].find(e=>input ? e.dataset.crField===input : e.dataset.cr===action && (e.dataset.path || '')===(path || ''));
        if (next && !next.disabled) { next.focus({preventScroll:true}); if (input && typeof start==='number') next.setSelectionRange(start,end); }
      }
      body.scrollTop = bodyTop; host.scrollTop = top;
    }
    function controls() {
      if (!host) return;
      for (const b of host.querySelectorAll('[data-cr]')) {
        const a = b.dataset.cr, r = s.run;
        let disabled = s.busy;
        if (a==='create') disabled ||= !s.supported || !s.form.title.trim() || !s.form.requirements.trim();
        if (a==='start') disabled ||= !current() || !['ready','interrupted','blocked'].includes(r.status) || !!r.pending_approval || !s.status?.available || !s.status?.logged_in;
        if (a==='stop') disabled ||= !current() || r.status!=='running';
        if (a==='add-source') disabled ||= !current() || r.status==='running' || r.status==='released' || !s.form.sourceTitle.trim() || (!s.form.sourcePath.trim() && !s.form.sourceText.trim());
        if (a==='retrieve') disabled ||= !current() || !s.form.query.trim();
        if (a==='approve') disabled ||= !current() || r.status!=='awaiting_approval' || !!approvalArtifacts().reason || s.viewed!==approvalKey();
        if (a==='reject') disabled ||= !current() || r.status!=='awaiting_approval' || !s.form.note.trim();
        if (a==='approval-preview') disabled ||= !!approvalArtifacts().reason;
        b.disabled = disabled;
      }
      host.querySelector('[data-cr-run]').disabled = s.busy;
      host.querySelector('[data-cr-field="workflow"]').disabled = s.busy;
    }
    function update() {
      if (!host) return;
      host.querySelector('.cr-message').textContent = s.message;
      host.querySelector('.cr-profile').textContent = s.profileMessage;
      host.querySelector('.cr-environment').textContent = s.status ? `Codex 执行环境：${s.status.available && s.status.logged_in ? '可执行' : '暂不可执行'}。${s.status.detail || ''}` : '正在读取 Codex 执行环境…';
      renderDetails(); controls();
    }
    async function api(endpoint, action, args={}) {
      const generation=lifecycle,parentSignal=controller.signal,request=new AbortController(),abort=()=>request.abort();
      parentSignal.addEventListener('abort',abort,{once:true});const timeout=setTimeout(()=>request.abort(),30000);
      try {
        const response=await fetch(`/api/workbench/${endpoint}`, {method:'POST',headers:{'Content-Type':'application/json','X-Workstation-Token':token},body:JSON.stringify({action,project,...args}),signal:request.signal});
        const data=await response.json();
        if(generation!==lifecycle||!host)throw new DOMException('视图已离开','AbortError');
        if(!response.ok)throw Error(response.status===403?'页面校验已失效，请刷新工作台。':`${data.error||'操作失败'}${response.status===409?'；请点击“刷新运行”读取最新版本后重试。':''}`);
        return data;
      }catch(e){if(e.name==='AbortError'&&!parentSignal.aborted)throw Error('请求超时，请刷新运行核对结果后重试。');throw e;}
      finally{clearTimeout(timeout);parentSignal.removeEventListener('abort',abort);}
    }
    const call = (action,args={}) => api('coursework',action,args);
    function take(run) {
      if (!run?.id || run.project && run.project!==project) throw Error('返回的运行不属于当前项目。');
      if (s.run?.id!==run.id) {s.preview=null;s.retrieved=[];s.form.note='';s.viewed='';showPreview();showRetrieved();}
      if (s.run?.revision!==run.revision) s.viewed='';
      s.run=run;s.selected=run.id;
      const index=s.runs.findIndex(r=>r.id===run.id); if(index<0)s.runs.unshift(run);else s.runs[index]=run;
      updateLists();update();schedule();
    }
    function schedule() {
      clearTimeout(timer);timer=null;
      if (!host || s.run?.status!=='running') return;
      const id=s.selected, generation=lifecycle;
      timer=setTimeout(async()=>{if(s.busy){schedule();return}try{const run=await call('get',{id});if(generation===lifecycle&&id===s.selected)take(run)}catch(e){if(e.name!=='AbortError'&&generation===lifecycle){s.message=`状态读取失败：${e.message} 请点击“刷新运行”重试。`;update();}}},2000);
    }
    async function work(fn) {
      if(s.busy)return;const generation=lifecycle;s.busy=true;controls();
      try{await fn()}catch(e){if(e.name!=='AbortError'&&generation===lifecycle){s.message=e.message;update();}}finally{if(generation===lifecycle){s.busy=false;update();schedule();}}
    }
    async function checkProfile() {
      s.supported=false;s.profileMessage='正在检查所选流程…';update();
      if(!s.form.workflow){s.profileMessage='请选择已保存的九关金融学工作流。';update();return}
      const chosen=s.form.workflow, data=await api('workflows','load',{id:chosen});
      if(chosen!==s.form.workflow)return;
      const nodes=data.graph?.nodes || [], agents=nodes.filter(n=>n.type==='agent');
      s.supported=agents.length===9 && Array.from({length:9},(_,i)=>'g'+(i+1)).every(id=>agents.some(n=>n.id===id)) && nodes.filter(n=>n.type==='input').length===1 && nodes.filter(n=>n.type==='output').length===1;
      s.profileMessage=s.supported?'九关金融学流程可创建运行；创建时执行器还会核对依赖和规则来源。':'当前执行器仅支持 G1–G9 九关金融学流程，所选流程不兼容。请改选对应流程或在编排画布修正后刷新。';update();
    }
    async function refresh() {
      const [environment,runs,flows]=await Promise.all([call('status'),call('list'),api('workflows','list')]);
      s.status=environment;s.runs=runs.items || [];s.workflows=flows.items || [];
      if(!s.workflows.some(w=>w.id===s.form.workflow)) s.form.workflow=s.workflows.length===1?s.workflows[0].id:'';
      updateLists();await checkProfile();
      if(s.selected&&s.runs.some(r=>r.id===s.selected))take(await call('get',{id:s.selected}));
      else if(s.selected){s.run=null;s.selected='';s.viewed='';s.preview=null;showPreview();}
      s.message=s.run?'已读取最新运行状态。':'填写作业要求并创建运行，随后显式启动。';update();
    }
    function showPreview(){if(!host)return;const el=host.querySelector('.cr-preview');el.hidden=!s.preview;if(s.preview){el.querySelector('pre').textContent=s.preview.content;el.querySelector('.cr-preview-path').textContent=`${s.preview.path} · SHA-256 ${s.preview.sha256}`;}}
    function showRetrieved(){if(!host)return;host.querySelector('.cr-retrieved').innerHTML=s.retrieved.map(e=>`<article><h4>${esc(e.id || e.evidence_id || '原文片段')} · ${esc(e.title || e.source_id || '')}</h4><blockquote>${esc(e.text || e.quote || '')}</blockquote><p>${esc(e.locator || '')}</p><small>来源：${esc(e.source_id || '')} · ${esc(e.source_sha256 || e.sha256 || '')}</small>${e.claim?`<p>支持的主张：${esc(e.claim)}</p>`:''}</article>`).join('') || '<p>没有匹配证据。可导入原文或调整关键词；不会补造结果。</p>';}
    function revealPreview(){showPreview();update();const body=host.querySelector('.cr-preview pre');body.focus({preventScroll:true});body.scrollIntoView({block:'nearest'});}
    async function preview(path){const id=s.selected,result=await call('artifact',{id,path});if(id!==s.selected)return;s.preview=result;s.message='已打开本运行登记产物。人工确认请使用“查看本关产物”阅读所需完整材料。';revealPreview();}
    async function previewApproval(){
      const id=s.selected,key=approvalKey(),needed=approvalArtifacts();
      s.viewed='';if(needed.reason)throw Error(needed.reason);
      const results=await Promise.all(needed.items.map(async item=>{const result=await call('artifact',{id,path:item.path});if(result.path!==item.path||result.sha256!==item.sha256||typeof result.content!=='string')throw Error('产物版本与当前关卡登记不一致，请刷新后重新查看。');return result;}));
      const latest=await call('get',{id});if(id!==s.selected)return;take(latest);
      if(key!==approvalKey()||approvalArtifacts().reason)throw Error('关卡或产物版本已变化，请重新查看当前关卡的全部产物后确认。');
      s.preview=results.length===1?results[0]:{path:results.map(r=>r.path).join(' + '),sha256:'分别见下方各产物',content:results.map(r=>`## ${r.path}\nSHA-256 ${r.sha256}\n\n${r.content}`).join('\n\n---\n\n')};
      s.viewed=key;s.message=results.length>1?'候选产物与终核报告已完整打开，请阅读后决定是否确认。':'已打开本关登记产物，请阅读后决定是否确认。';revealPreview();
    }
    function input(event){const key=event.target.dataset.crField;if(!key)return;s.form[key]=event.target.value;controls();}
    function click(event){const b=event.target.closest('[data-cr]');if(!b||b.disabled)return;const action=b.dataset.cr;work(async()=>{
      if(action==='refresh')await refresh();
      if(action==='create'){take(await call('create',{workflow_id:s.form.workflow,task:{title:s.form.title.trim(),requirements:s.form.requirements,source_paths:s.form.paths.split(/\r?\n/).map(x=>x.trim()).filter(Boolean),mode:s.form.mode}}));s.message='运行已创建，尚未启动。';}
      if(action==='start'){take(await call('start',{id:s.selected,revision:s.run.revision}));s.message=s.run.status==='running'?'执行已启动，状态来自本机执行器。':`当前状态：${stateName(s.run.status)}。`;}
      if(action==='stop'){take(await call('stop',{id:s.selected,revision:s.run.revision}));s.message='已请求停止，以下状态以执行器返回为准。';}
      if(action==='approve'||action==='reject'){if(action==='approve'&&(approvalArtifacts().reason||s.viewed!==approvalKey()))throw Error('请先查看当前关卡所需的全部产物。');const pending=s.run.pending_approval;if(!pending)throw Error('当前没有待确认关卡，请刷新。');take(await call('approve',{id:s.selected,revision:s.run.revision,request_id:pending.request_id,decision:action==='approve'?'approve':'reject',note:s.form.note}));s.form.note='';s.message=action==='reject'?'已记录退回原因，产物仍保留。':s.run.status==='released'?'已确认本地交付，可查看交付产物。':'已记录人工确认。请启动下一段执行。';}
      if(action==='approval-preview')await previewApproval();
      if(action==='artifact')await preview(b.dataset.path);
      if(action==='add-source'){if(s.form.sourcePath.trim()&&s.form.sourceText.trim())throw Error('请选择项目内资料路径或粘贴原文其中一种，避免来源含混。');const source={title:s.form.sourceTitle.trim()};if(s.form.sourcePath.trim())source.path=s.form.sourcePath.trim();if(s.form.sourceText.trim())source.text=s.form.sourceText;if(s.form.sourceUrl.trim())source.url=s.form.sourceUrl.trim();if(s.form.sourceLocator.trim())source.locator=s.form.sourceLocator.trim();take(await call('add-source',{id:s.selected,revision:s.run.revision,source}));s.message='资料已导入；受影响的阶段与人工确认按执行器状态重新核验。';}
      if(action==='retrieve'){s.retrieved=(await call('retrieve',{id:s.selected,query:s.form.query})).items || [];showRetrieved();s.message=`检索得到 ${s.retrieved.length} 项当前运行证据。`;}
    });}
    function unmount(){s.scroll=host?.querySelector('.cr-body')?.scrollTop??s.scroll;if(host)for(const el of host.querySelectorAll('.cr-body > details'))s.expansion[el.className]=el.open;lifecycle++;clearTimeout(timer);timer=null;controller?.abort();controller=null;host=null;s.busy=false;detailSignature='';}
    function mount(element,controlToken){unmount();host=element;token=controlToken;controller=new AbortController();shell();host.querySelector('.cr-body').scrollTop=s.scroll;host.addEventListener('input',input,{signal:controller.signal});host.addEventListener('change',e=>{input(e);if(e.target.dataset.crField==='workflow')work(checkProfile);if(e.target.matches('[data-cr-run]')){s.selected=e.target.value;s.run=null;s.viewed='';s.preview=null;s.retrieved=[];detailSignature='';showPreview();showRetrieved();update();if(s.selected)work(async()=>take(await call('get',{id:s.selected})));}},{signal:controller.signal});host.addEventListener('click',click,{signal:controller.signal});showPreview();if(s.retrieved.length)showRetrieved();work(refresh);}
    return {html,mount,unmount};
  }
  function forProject(project=''){if(!instances.has(project))instances.set(project,create(project));return instances.get(project);}
  return {forProject};
})();
