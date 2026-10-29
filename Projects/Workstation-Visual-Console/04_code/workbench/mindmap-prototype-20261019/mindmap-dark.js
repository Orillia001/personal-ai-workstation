/* Selected A refinement: every module and its knowledge belong to one map. Demo-only state. */
window.EducationNetwork=(()=>{
  const source=JSON.parse(document.querySelector('#mindmap-data').textContent);
  const labels={not_started:'未开始',in_progress:'学习中',learned:'已学习',review_due:'待复习'};
  const relations={contains:'包含',prerequisite:'先修',applies:'应用',contrast:'对比'};
  const palette=['#82adbd','#9d99bf','#83ada1','#b2a184'];
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const sessions=new Map();let host,graph,course,index,modules,session,controller,observer,world,pointers=new Map(),gesture;
  let camera={scale:1,x:0,y:0},bounds={left:0,right:0,top:0,bottom:0},locations=new Map(),query='',detail=false;
  const html=()=>'<section class="mm edu-network" aria-label="课程思维导图 Demo"></section>';
  const item=id=>index.get(id)||modules.find(n=>n.id===id);
  const state=id=>session.status.get(id)||'not_started';
  function knowledge(module){
    if(module==='all')return graph.nodes.filter(n=>n.kind!=='module').map(n=>n.id);
    const found=new Set(),queue=graph.edges.filter(e=>e.kind==='contains'&&e.from===module).map(e=>e.to);
    while(queue.length){const id=queue.shift();if(found.has(id))continue;found.add(id);queue.push(...graph.edges.filter(e=>e.kind==='contains'&&e.from===id).map(e=>e.to))}
    return [...found].filter(id=>item(id)?.kind!=='module');
  }
  function setup(id){
    course=source.courses[id]?id:'machine-design';graph=source.courses[course].graph;index=new Map(graph.nodes.map(n=>[n.id,n]));
    modules=graph.nodes.filter(n=>n.kind==='module');if(!modules.length)modules=[{id:'all',title:'课程知识',kind:'module'}];
    if(!sessions.has(course))sessions.set(course,{open:new Set(modules.some(n=>n.id==='module-MD02')?['module-MD02']:[]),
      selected:'',module:'',status:new Map(source.courses[course].progress.nodes.map(n=>[n.id,n.status]))});
    session=sessions.get(course);
  }
  function pathText(){return [graph.name,session.module&&item(session.module)?.title,session.selected&&item(session.selected)?.title].filter(Boolean)}
  function updatePath(){const parts=pathText(),el=host.querySelector('.mm-location');el.innerHTML=parts.map((p,i)=>`${i?'<span>/</span>':''}${i===parts.length-1?`<strong>${esc(p)}</strong>`:esc(p)}`).join('');el.title=parts.join(' / ')}
  const searchIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/></svg>';
  const fitIcon='<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8 3H3v5m13-5h5v5M3 16v5h5m13-5v5h-5"/><circle cx="12" cy="12" r="3"/></svg>';
  function saveView(){
    if(!host||!world||!session)return;
    const canvas=host.querySelector('.mm-canvas');session.camera={...camera};session.viewport={w:canvas.clientWidth,h:canvas.clientHeight};
    session.detail=detail;session.query=query;session.detailScroll=host.querySelector('.mm-detail')?.scrollTop??session.detailScroll??0;
  }
  // Update the map in place: the canvas, search and gesture surface stay mounted.
  function render(anchorKey){
    const previous=locations.get(anchorKey),focusKey=host.contains(document.activeElement)?document.activeElement?.dataset.key:null;
    const oldPanel=host.querySelector('.mm-detail'),scroll=oldPanel?.dataset.node===session.selected?oldPanel.scrollTop:session.detailScroll||0;
    if(!host.querySelector('.mm-canvas'))host.innerHTML=`<header class="mm-top"><div class="mm-search">${searchIcon}<input type="search" data-mm-input="search" value="${esc(query)}" placeholder="搜索章节或知识点" aria-label="搜索章节或知识点" autocomplete="off"><div class="mm-results" hidden></div></div><div class="mm-location" aria-label="当前位置" aria-live="polite"></div></header><div class="mm-map"><div class="mm-canvas" role="region" tabindex="0" aria-label="课程思维导图；单指或笔拖动，双指平移和缩放"><div class="mm-world"></div></div><div class="mm-controls"><button data-mm="zoom-out" aria-label="缩小" title="缩小">−</button><button data-mm="fit" aria-label="显示全图" title="显示全图">${fitIcon}</button><button data-mm="zoom-in" aria-label="放大" title="放大">＋</button></div></div>`;
    updatePath();world=host.querySelector('.mm-world');layout();
    const next=locations.get(anchorKey);
    if(previous&&next){camera.x+=(previous.x+previous.w/2-next.x-next.w/2)*camera.scale;camera.y+=(previous.y+previous.h/2-next.y-next.h/2)*camera.scale}
    place();
    const input=host.querySelector('[data-mm-input="search"]');if(input.value!==query)input.value=query;results();
    if(detail){
      if(oldPanel?.dataset.node!==session.selected){oldPanel?.remove();host.querySelector('.mm-map').insertAdjacentHTML('beforeend',detailPanel());host.querySelector('.mm-detail').scrollTop=scroll}
      else oldPanel.querySelector('select').value=state(session.selected);
    }else {if(oldPanel)session.detailScroll=scroll;oldPanel?.remove()}
    if(focusKey)world.querySelector(`[data-key="${CSS.escape(focusKey)}"]`)?.focus({preventScroll:true});
    saveView();
  }
  function layout(){
    locations=new Map();const cards=[],lines=[];const root={key:'course',id:'course',x:-88,y:-32,w:176,h:64,kind:'root'};cards.push(root);
    const touch=host.dataset.touch==='true',moduleH=touch?60:52,leafH=touch?48:36,step=touch?60:44,gap=touch?28:25;
    const divide=Math.ceil(modules.length/2),sides=[modules.slice(0,divide),modules.slice(divide)];
    sides.forEach((list,side)=>{
      const direction=side===0?1:-1;
      const heights=list.map(m=>Math.max(moduleH,session.open.has(m.id)?knowledge(m.id).length*step-(step-leafH):moduleH));
      let offset=-(heights.reduce((a,b)=>a+b,0)+Math.max(0,list.length-1)*gap)/2;
      list.forEach((module,i)=>{
        const ordinal=modules.indexOf(module),color=palette[Math.floor(ordinal/3)%palette.length],height=heights[i];
        const p={key:module.id,id:module.id,module:module.id,x:direction===1?210:-466,y:offset+height/2-moduleH/2,w:256,h:moduleH,kind:'module',color,ordinal};
        cards.push(p);lines.push({a:root,b:p,direction,color,major:true});
        if(session.open.has(module.id))knowledge(module.id).forEach((id,j)=>{
          const n={key:module.id+'::'+id,id,module:module.id,x:direction===1?548:-812,y:offset+j*step,w:264,h:leafH,kind:'knowledge',color};
          cards.push(n);lines.push({a:p,b:n,direction,color,major:false});
        });offset+=height+gap;
      });
    });
    bounds={left:Math.min(...cards.map(p=>p.x)),right:Math.max(...cards.map(p=>p.x+p.w)),top:Math.min(...cards.map(p=>p.y)),bottom:Math.max(...cards.map(p=>p.y+p.h))};
    const curve=line=>{const {a,b,direction:d}=line,x1=d===1?a.x+a.w:a.x,x2=d===1?b.x:b.x+b.w,y1=a.y+a.h/2,y2=b.y+b.h/2,reach=Math.abs(x2-x1)*.52;return `M ${x1} ${y1} C ${x1+d*reach} ${y1}, ${x2-d*reach} ${y2}, ${x2} ${y2}`};
    world.innerHTML=`<svg class="mm-lines" width="1" height="1" aria-hidden="true">${lines.map(l=>`<path class="${l.major?'mm-major':'mm-minor'}" d="${curve(l)}" stroke="${l.color}"/>`).join('')}</svg>`+cards.map(p=>{
      locations.set(p.key,p);
      const label=p.kind==='root'?graph.name:item(p.id).title;
      const title=p.kind==='module'?`${label} · ${knowledge(p.id).length} 个知识点 · 点击${session.open.has(p.id)?'收起':'展开'}`:p.kind==='knowledge'?`${label} · ${labels[state(p.id)]}`:graph.name;
      return `<button class="mm-node mm-${p.kind} ${p.id===session.selected&&p.module===session.module?'selected':''}" data-mm="${p.kind==='root'?'root':p.kind==='module'?'module':'knowledge'}" data-id="${esc(p.id)}" data-module="${esc(p.module||'')}" data-key="${esc(p.key)}" data-state="${state(p.id)}" ${p.kind==='module'?`aria-expanded="${session.open.has(p.id)}"`:''} title="${esc(title)}" style="left:${p.x}px;top:${p.y}px;width:${p.w}px;height:${p.h}px;--branch:${p.color||'#92adbd'}">${p.kind==='root'?esc(label):p.kind==='module'?`<span class="mm-number">${String(p.ordinal+1).padStart(2,'0')}</span><span class="mm-module-label">${esc(label)}</span><span class="mm-fold">${knowledge(p.id).length}<svg viewBox="0 0 12 12" aria-hidden="true"><path d="m4 2 4 4-4 4"/></svg></span>`:`<i class="mm-state" data-state="${state(p.id)}"></i><span class="mm-label">${esc(label)}</span>${state(p.id)==='learned'?'<span class="mm-done">✓</span>':''}`}</button>`;
    }).join('');
  }
  function place(){world.style.transform=`translate(${camera.x}px,${camera.y}px) scale(${camera.scale})`;session.camera={...camera}}
  function fit(){const box=host.querySelector('.mm-canvas'),padding=innerWidth<=760?22:80;
    camera.scale=Math.max(.18,Math.min(1.12,(box.clientWidth-padding)/(bounds.right-bounds.left),(box.clientHeight-padding)/(bounds.bottom-bounds.top)));
    camera.x=box.clientWidth/2-(bounds.left+bounds.right)/2*camera.scale;camera.y=box.clientHeight/2-(bounds.top+bounds.bottom)/2*camera.scale;place();
  }
  function zoom(factor,x,y){const box=host.querySelector('.mm-canvas');x??=box.clientWidth/2;y??=box.clientHeight/2;const next=Math.max(.18,Math.min(2.4,camera.scale*factor)),ratio=next/camera.scale;camera.x=x+(camera.x-x)*ratio;camera.y=y+(camera.y-y)*ratio;camera.scale=next;place()}
  function focus(key){const p=locations.get(key);if(!p)return;const box=host.querySelector('.mm-canvas'),available=box.clientWidth-(detail&&innerWidth>760?340:0);
    camera.scale=Math.max(camera.scale,innerWidth<=760 ? .9 : 1);camera.x=available/2-(p.x+p.w/2)*camera.scale;camera.y=box.clientHeight/2-(p.y+p.h/2)*camera.scale;place();
  }
  function detailPanel(){const n=item(session.selected),evidence=source.courses[course].progress.nodes.find(n=>n.id===session.selected);if(!n)return '';
    const related=graph.edges.filter(e=>e.from===n.id||e.to===n.id),pages=[...new Set(n.pages||[])];
    const openNote=`<button class="mm-open-obsidian" data-mm="open-note" data-id="${esc(n.id)}" ${evidence?.linked?'':'disabled'} title="${esc(evidence?.linked?'打开此知识点对应的 Obsidian 笔记':evidence?.error||'此知识点尚未绑定笔记')}">在 Obsidian 中打开 <svg viewBox="0 0 20 20" aria-hidden="true"><path d="M11 3h6v6m0-6-8 8M8 4H4a1 1 0 0 0-1 1v11a1 1 0 0 0 1 1h11a1 1 0 0 0 1-1v-4"/></svg></button><p class="mm-open-message" role="status" hidden></p>`;
    return `<aside class="mm-detail" data-node="${esc(n.id)}" aria-label="知识点内容"><div class="mm-detail-head"><h2>${esc(n.title)}</h2><button class="mm-close" data-mm="close" aria-label="关闭内容">×</button></div>${openNote}<div class="mm-body">${esc(n.body||'内容待补充。')}</div><div class="mm-status-row"><span>学习状态</span><select data-mm-input="status" data-id="${esc(n.id)}" aria-label="学习状态">${Object.entries(labels).map(([id,title])=>`<option value="${id}" ${state(n.id)===id?'selected':''}>${title}</option>`).join('')}</select></div><p class="mm-note">${esc(evidence?.mastery_label||'尚未评估')}<br>Demo 标记仅在本页有效</p>${pages.length?`<h3>教材页码</h3><div class="mm-pages">${pages.map(p=>'P'+p).join(' · ')}</div>`:''}${related.length?`<h3>知识联系</h3>${related.map(e=>{const id=e.from===n.id?e.to:e.from;return `<button class="mm-related" data-mm="related" data-id="${esc(id)}"><small>${relations[e.kind]} ${e.from===n.id?'→':'←'}</small>${esc(item(id)?.title)}</button>`}).join('')}`:''}</aside>`;
  }
  async function openNote(button){
    if(button.disabled)return;const panel=button.closest('.mm-detail'),message=panel.querySelector('.mm-open-message');
    button.disabled=true;button.setAttribute('aria-busy','true');message.hidden=true;
    try{
      const token=document.querySelector('meta[name="mindmap-open-token"]')?.content;
      if(!token||token==='__MINDMAP_OPEN_TOKEN__')throw new Error('请在工作台预览中打开此笔记');
      const response=await fetch('/api/education/open-note',{method:'POST',headers:{'Content-Type':'application/json','X-Mindmap-Token':token},body:JSON.stringify({course,node_id:button.dataset.id}),signal:controller.signal});
      const result=await response.json();if(!response.ok||!result.requested)throw new Error(result.message||'暂时无法打开笔记，请重试');
      message.textContent='已请求在 Obsidian 打开';message.dataset.error='false';message.hidden=false;
    }catch(error){if(error.name!=='AbortError'){message.textContent=error.message;message.dataset.error='true';message.hidden=false}}
    finally{button.disabled=false;button.removeAttribute('aria-busy')}
  }
  function openKnowledge(id,module,locate=false){const owner=modules.find(m=>m.id===module&&knowledge(m.id).includes(id))||modules.find(m=>knowledge(m.id).includes(id));if(!owner)return;
    if(session.selected!==id)session.detailScroll=0;
    session.module=owner.id;session.selected=id;session.open.add(owner.id);detail=true;query='';render(owner.id);if(locate)focus(owner.id+'::'+id);
  }
  function click(button){const {mm:action,id,module}=button.dataset;
    if(action==='open-note'){openNote(button);return}
    if(action==='module'){session.open.has(id)?session.open.delete(id):session.open.add(id);session.module=id;session.selected='';detail=false;query='';render(id);return}
    if(action==='knowledge'){openKnowledge(id,module);return}
    if(action==='related'){if(item(id)?.kind==='module'){session.module=id;session.selected='';session.open.add(id);detail=false;render(id)}else openKnowledge(id,session.module);return}
    if(action==='root'){session.open.clear();session.module='';session.selected='';detail=false;query='';render();return}
    if(action==='close'){detail=false;render();return}
    if(action==='fit'){fit();return}
    if(action==='zoom-in'||action==='zoom-out'){zoom(action==='zoom-in'?1.2:1/1.2);return}
    if(action==='result'){if(id==='course'){click({dataset:{mm:'root'}});return}if(item(id)?.kind==='module'){session.open.add(id);session.module=id;session.selected='';detail=false;query='';render(id);focus(id)}else openKnowledge(id,session.module,true)}
  }
  function results(){const box=host.querySelector('.mm-results');box.hidden=!query;if(!query)return;
    const found=graph.nodes.filter(n=>n.title.toLowerCase().includes(query.toLowerCase()));
    box.innerHTML=found.slice(0,25).map(n=>{const owner=modules.find(m=>m.id===n.id||knowledge(m.id).includes(n.id));return `<button data-mm="result" data-id="${esc(n.id)}">${esc(n.title)}<small>${esc(graph.name)}${owner?' / '+esc(owner.title):''}</small></button>`}).join('')||'<p>没有匹配的知识点</p>';
  }
  function rebaseGesture(){
    const [a,b]=[...pointers.values()];if(!a||!gesture)return;
    gesture.origin={...camera};gesture.start={x:b?(a.x+b.x)/2:a.x,y:b?(a.y+b.y)/2:a.y,d:b?Math.max(1,Math.hypot(a.x-b.x,a.y-b.y)):0};
    if(b){gesture.multi=true;gesture.moved=true}
  }
  function cancelGesture(){
    const canvas=gesture?.canvas,ids=[...pointers.keys()];pointers.clear();gesture=null;
    canvas?.classList.remove('is-dragging');for(const id of ids)if(canvas?.hasPointerCapture(id))canvas.releasePointerCapture(id);
  }
  function mount(element,id){
    unmount();host=element;setup(id);detail=!!session.detail;query=session.query||'';
    const initial=!session.camera,previousSize=session.viewport;
    camera=session.camera?{...session.camera}:{scale:1,x:0,y:0};
    host.dataset.touch=String(navigator.maxTouchPoints>0||matchMedia('(any-pointer:coarse)').matches);
    controller=new AbortController();const signal=controller.signal;render();
    const canvas=host.querySelector('.mm-canvas');
    if(initial){fit();if(host.dataset.touch==='true'&&camera.scale<1)zoom(1/camera.scale)}
    else if(previousSize){camera.x+=(canvas.clientWidth-previousSize.w)/2;camera.y+=(canvas.clientHeight-previousSize.h)/2;place()}
    saveView();let w=canvas.clientWidth,h=canvas.clientHeight;
    observer=new ResizeObserver(()=>{if(!world||!canvas.isConnected)return;const nw=canvas.clientWidth,nh=canvas.clientHeight;
      if(nw!==w||nh!==h){cancelGesture();camera.x+=(nw-w)/2;camera.y+=(nh-h)/2;w=nw;h=nh;place();saveView()}});observer.observe(canvas);
    host.addEventListener('click',event=>{
      // Pointer taps are handled on pointerup. Ignore compatibility clicks after drags/pinches.
      // Keyboard and assistive clicks have detail=0 and still use the normal button path.
      if(event.isTrusted&&event.detail>0&&event.target.closest('.mm-canvas')){event.preventDefault();event.stopPropagation();return}
      const button=event.target.closest('[data-mm]');if(button)click(button);
    },{signal});
    host.addEventListener('input',event=>{if(event.target.dataset.mmInput==='search'){query=event.target.value.trim();results()}},{signal});
    host.addEventListener('change',event=>{if(event.target.dataset.mmInput==='status'&&Object.hasOwn(labels,event.target.value)){session.status.set(event.target.dataset.id,event.target.value);render()}},{signal});
    host.addEventListener('keydown',event=>{
      if(event.target.matches('input')){if(event.key==='Escape'){host.querySelector('.mm-results').hidden=true;event.target.blur()}if(event.key==='Enter'){host.querySelector('.mm-results button')?.click();event.preventDefault()}return}
      if(event.target.closest('select'))return;if(event.key==='Escape'&&detail){detail=false;render();return}
      if(event.target.closest('.mm-canvas')){if(['+','=','-','0'].includes(event.key)){event.preventDefault();event.key==='0'?fit():zoom(event.key==='-'?1/1.2:1.2)}else if(event.key.startsWith('Arrow')){event.preventDefault();camera.x+=event.key==='ArrowLeft'?45:event.key==='ArrowRight'?-45:0;camera.y+=event.key==='ArrowUp'?45:event.key==='ArrowDown'?-45:0;place()}}
    },{signal});
    host.addEventListener('pointerdown',event=>{
      if(!event.target.closest('.mm-canvas')||event.button!==0)return;
      event.preventDefault();
      if(event.pointerType==='touch'&&[...pointers.values()].some(p=>p.type==='pen'))return;
      if(event.pointerType==='pen'&&pointers.size)cancelGesture();
      if(!gesture)gesture={canvas,target:event.target.closest('.mm-node'),multi:false,moved:false};
      pointers.set(event.pointerId,{x:event.clientX,y:event.clientY,type:event.pointerType});canvas.setPointerCapture(event.pointerId);
      rebaseGesture();
    },{signal});
    host.addEventListener('pointermove',event=>{
      const pointer=pointers.get(event.pointerId);if(!pointer||!gesture)return;
      pointer.x=event.clientX;pointer.y=event.clientY;
      const [a,b]=[...pointers.values()],start=gesture.start,origin=gesture.origin;
      const x=b?(a.x+b.x)/2:a.x,y=b?(a.y+b.y)/2:a.y;
      if(!gesture.moved&&Math.hypot(x-start.x,y-start.y)<(pointer.type==='mouse'?4:8))return;
      gesture.moved=true;canvas.classList.add('is-dragging');
      if(b){
        const rect=canvas.getBoundingClientRect(),scale=Math.max(.18,Math.min(2.4,origin.scale*Math.hypot(a.x-b.x,a.y-b.y)/start.d)),ratio=scale/origin.scale;
        camera.x=x-rect.left-(start.x-rect.left-origin.x)*ratio;camera.y=y-rect.top-(start.y-rect.top-origin.y)*ratio;camera.scale=scale;
      }else {camera.x=origin.x+x-start.x;camera.y=origin.y+y-start.y}
      place();
    },{signal});
    host.addEventListener('pointerup',event=>{
      if(!pointers.has(event.pointerId)||!gesture)return;
      const target=!gesture.moved&&!gesture.multi?gesture.target:null;
      pointers.delete(event.pointerId);if(canvas.hasPointerCapture(event.pointerId))canvas.releasePointerCapture(event.pointerId);
      if(pointers.size)rebaseGesture();else {gesture=null;canvas.classList.remove('is-dragging')}
      if(target?.isConnected){target.focus({preventScroll:true});target.click()}
      else if(!pointers.size)canvas.focus({preventScroll:true});
    },{signal});
    for(const type of ['pointercancel','lostpointercapture'])host.addEventListener(type,event=>{
      if(pointers.has(event.pointerId))cancelGesture();
    },{signal});
    window.addEventListener('blur',cancelGesture,{signal});
    document.addEventListener('visibilitychange',()=>{if(document.hidden)cancelGesture()},{signal});
    host.addEventListener('wheel',event=>{
      if(!event.target.closest('.mm-canvas'))return;event.preventDefault();if(pointers.size)return;
      const unit=event.deltaMode===1?16:event.deltaMode===2?canvas.clientHeight:1;
      if(event.ctrlKey||event.metaKey){const rect=canvas.getBoundingClientRect();zoom(Math.exp(-event.deltaY*unit*.008),event.clientX-rect.left,event.clientY-rect.top)}
      else {camera.x-=event.deltaX*unit;camera.y-=event.deltaY*unit;place()}
    },{signal,passive:false});
  }
  function unmount(){saveView();controller?.abort();observer?.disconnect();cancelGesture();host=null;world=null;locations.clear()}
  return {html,mount,unmount};
})();
