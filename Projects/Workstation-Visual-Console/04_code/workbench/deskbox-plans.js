/* DeskBox data stays in its own store; never enters the layout snapshot. */
(() => {
  let snapshot = null, loading = false, draft = null, message = '', busy = false, lastHost = null, migrating = false;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const icons = {
    refresh:'<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 8a7 7 0 0 1 11.6-2L20 9M4 15l2.4 3A7 7 0 0 0 18 16"/>',
    add:'<path d="M12 5v14M5 12h14"/>',
    edit:'<path d="m15 5 4 4M4 20l4-1L20 7a2.8 2.8 0 0 0-4-4L4 15Z"/>',
    delete:'<path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13M10 11v5M14 11v5"/>',
    cancel:'<path d="m6 6 12 12M6 18 18 6"/>'
  };
  const iconButton = (action,label,attrs='') => `<button type="button" class="db-icon-button" data-db-action="${action}" aria-label="${esc(label)}" title="${esc(label)}" ${attrs}><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${icons[action]}</svg></button>`;
  const localDue = value => {
    if (!value) return '';
    const d = new Date(value);
    if (isNaN(d)) return '';
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}T${String(d.getHours()).padStart(2,'0')}:${String(d.getMinutes()).padStart(2,'0')}`;
  };
  async function api(payload) {
    // Uses the host page's existing protected request interface.
    return embeddedApi('/api/workbench/deskbox', payload);
  }
  function mount() {
    const section = document.querySelector('[data-deskbox]');
    if (!section || section === lastHost) return;
    lastHost = section;
    paint();
    if (!snapshot && !loading) refresh();
  }
  function paint() {
    const host = document.querySelector('[data-deskbox]');
    if (!host) return;
    const active=document.activeElement;
    const focused=host.contains(active)?{name:active.name,action:active.dataset.dbAction,widget:active.dataset.widget,id:active.dataset.id,start:active.selectionStart,end:active.selectionEnd}:null;
    const stores = snapshot?.stores || [];
    let rows = '';
    for (const store of stores) {
      if (stores.length>1) rows += `<div class="db-list-heading"><h3>列表 ${stores.indexOf(store)+1}</h3>${iconButton('add','添加到列表 '+(stores.indexOf(store)+1),`data-widget="${esc(store.widget)}"`)}</div>`;
      for (const item of [...store.items].sort((a,b)=>Number(a.done)-Number(b.done)||(a.due||"9999").localeCompare(b.due||"9999"))) rows += `<div class="plan-item ${item.done?'done':''}"><input type="checkbox" data-db-action="complete" data-widget="${esc(store.widget)}" data-id="${esc(item.id)}" aria-label="完成 ${esc(item.title)}" ${item.done?'checked':''} ${busy?'aria-disabled="true"':''}><div class="plan-item-body"><strong>${esc(item.title)}</strong><small>DeskBox${item.due ? ` · ${esc(localDue(item.due).replace('T',' '))}` : ''}${item.recurring?' · 重复事项':''}</small></div><div class="db-item-actions" role="group" aria-label="事项操作">${iconButton('edit','编辑事项',`data-widget="${esc(store.widget)}" data-id="${esc(item.id)}"`)}${iconButton('delete','删除事项',`data-widget="${esc(store.widget)}" data-id="${esc(item.id)}"`)}</div></div>`;
    }
    const form = draft ? `<form data-db-form class="plan-form"><label class="plan-title-field">事项<input name="title" maxlength="500" required value="${esc(draft.title)}"></label><label class="plan-due-field">计划时间<input type="datetime-local" name="due" value="${esc(draft.due)}" ></label><div class="db-form-actions"><button class="db-save-button" type="submit" ${busy?'aria-disabled="true"':''}>${busy?'保存中…':'保存'}</button>${iconButton('cancel','取消编辑')}</div></form>` : '';
    const pending=stores.reduce((n,s)=>n+s.items.filter(i=>!i.done).length,0);
    const legacy=typeof planItems!=="undefined"?planItems.length:0;
    const connected=stores.some(s=>s.live);
    host.innerHTML = `<div class="plan-heading"><div><h2>计划事项</h2><p>${pending} 项待处理 · 与 DeskBox 共用事项</p></div><div class="db-toolbar" role="group" aria-label="计划事项操作">${iconButton('refresh','刷新计划事项',busy?'aria-disabled="true"':'')}${stores.length===1?iconButton('add','添加事项',`data-widget="${esc(stores[0].widget)}"`):''}</div></div><p role="status">${esc(message || (legacy?`还有 ${legacy} 项原计划待迁入。`:connected?'已连接 DeskBox，可直接编辑。':snapshot?.running?(stores.find(s=>s.live_error)?.live_error || '请启动热更新补丁版本，以启用运行中编辑。'):'DeskBox 未运行；保存后下次打开可见。'))}</p>${rows || '<p>未找到待办列表，请先在 DeskBox 创建待办小组件。</p>'}${form}`;
    if(focused) {
      const controls=[...host.querySelectorAll('input,button')];
      const target=controls.find(c=>focused.name?c.name===focused.name:c.dataset.dbAction===focused.action && c.dataset.widget===focused.widget && c.dataset.id===focused.id) || host.querySelector('[data-db-action="refresh"]');
      target?.focus({preventScroll:true});
      if(focused.name && Number.isInteger(focused.start))try{target.setSelectionRange(focused.start,focused.end)}catch{}
    }
  }
  async function refresh(manual=false) {
    if (loading || busy || (!manual && draft)) return;
    loading = true;
    try {
      const next = await api({action:'list'});
      if (JSON.stringify(next) !== JSON.stringify(snapshot)) {snapshot=next; if (!draft) paint();}
      await migrateLegacy();
      if (manual) {
        if (draft) {
          const store=next.stores.find(s=>s.widget===draft.widget);
          if (store && store.revision!==draft.revision) {draft.revision=store.revision; draft.rebased=true;}
        }
        message=draft?'已读取最新文件，草稿保留；请核对列表后保存。':'已读取最新 DeskBox 文件。'; paint();
      }
    } catch(e) {message=String(e.message || e); if (!draft || manual) paint();}
    finally {loading=false;}
  }
  async function migrateLegacy() {
    if (migrating || draft || typeof persistReady==='undefined' || !persistReady || !planItems.length || !snapshot?.stores.some(s=>s.live)) return;
    migrating=true;
    try {
      while(planItems.length) {
        const item=planItems[0],store=snapshot.stores.find(s=>s.live);
        const result=await api({action:'import',widget:store.widget,revision:store.revision,id:item.id,title:item.title,due:item.due,done:item.done,createdAt:item.createdAt});
        if (!result.saved) throw Error('原计划尚未确认保存，请刷新重试');
        snapshot=result;planItems.shift();scheduleSave();
      }
      message='原计划已迁入，双方共用同一份事项。';paint();
    } catch(e) {message=String(e.message||e);paint();}
    finally {migrating=false;}
  }
  async function save(payload) {
    if (busy || migrating) return;
    busy=true; message='正在保存…'; paint();
    try {snapshot=await api(payload); if(!snapshot.saved)throw Error('尚未确认保存，请刷新核对'); delete snapshot.saved; delete snapshot.backup; draft=null; message=snapshot.live_saved?'已保存，DeskBox 已更新。':'已保存，下次打开 DeskBox 可见。';}
    catch(e) {message=String(e.message || e);}
    finally {busy=false; paint();}
  }
  document.addEventListener('input', e => {
    if (draft && e.target.closest('[data-db-form]')) draft[e.target.name]=e.target.value;
  });
  document.addEventListener('click', e => {
    const button=e.target.closest('button[data-db-action]');
    if (!button || busy || migrating) return;
    const action=button.dataset.dbAction;
    if (action==='refresh') {refresh(true); return;}
    if (action==='cancel') {draft=null; message=''; paint(); return;}
    if (draft) {message='请先保存或取消当前草稿，再操作其他事项。'; paint(); return;}
    const store=snapshot?.stores.find(s=>s.widget===button.dataset.widget);
    if (!store) return;
    const item=store.items.find(i=>i.id===button.dataset.id);
    if (action==='add' || action==='edit') {
      draft={widget:store.widget,revision:store.revision,action:item?'edit':'add',id:item?.id || crypto.randomUUID().replaceAll('-',''),title:item?.title||'',due:localDue(item?.due),recurring:item?.recurring,originalDue:item?.due};
      message=''; paint(); document.querySelector('[data-db-form] input')?.focus();
    } else if (action==='delete' && item && confirm(`删除 DeskBox 事项“${item.title}”？`)) save({action,widget:store.widget,revision:store.revision,id:item.id});
  });
  document.addEventListener('change', e => {
    const input=e.target;
    if (input.dataset.dbAction!=='complete') return;
    if (busy || migrating) {paint();return;}
    if (draft) {message='请先保存或取消当前草稿，再操作其他事项。'; paint(); return;}
    const store=snapshot?.stores.find(s=>s.widget===input.dataset.widget);
    if (store) save({action:'complete',widget:store.widget,revision:store.revision,id:input.dataset.id,done:input.checked});
  });
  document.addEventListener('submit', e => {
    if (!e.target.matches('[data-db-form]')) return;
    e.preventDefault();
    if (draft && !busy) {
      if (draft.rebased && !confirm('文件已变化，列表已刷新。确认用当前草稿保存此事项？')) return;
      save({...draft,due:draft.due===localDue(draft.originalDue)?draft.originalDue:draft.due});
    }
  });
  new MutationObserver(mount).observe(document.getElementById('app'),{childList:true,subtree:true});
  mount();
  setInterval(()=>{if(document.querySelector('[data-deskbox]')) refresh();},5000);
})();
