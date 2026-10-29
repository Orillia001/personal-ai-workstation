/* Three disposable UI variants on /workbench?variant=A|B|C. No writes or persistence. */
window.EducationNetwork=(()=>{
  const data=JSON.parse(document.querySelector('#mindmap-data').textContent),names={A:'分层导图',B:'大纲目录',C:'分栏浏览'};
  const statusNames={not_started:'未开始',in_progress:'学习中',learned:'已学习',review_due:'待复习'};
  const relationNames={contains:'包含',prerequisite:'先修',applies:'应用',contrast:'对比'};
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const sessions=new Map();let host,course,graph,modules,index,session,variant='A',controller,resize,world,drag;
  let camera={scale:1,x:0,y:0},geometry={w:900,h:600},detailOpen=false,query='';
  function html(){return '<section class="mm edu-network" aria-label="知识导图布局演示"></section>'}
  function setup(id){
    course=data.courses[id]?id:'machine-design';graph=data.courses[course].graph;index=new Map(graph.nodes.map(n=>[n.id,n]));
    modules=graph.nodes.filter(n=>n.kind==='module');
    if(!modules.length)modules=[{id:'all',kind:'module',title:'课程知识',body:'浏览已有知识点。'}];
    if(!sessions.has(course))sessions.set(course,{module:modules.find(n=>n.id==='module-MD02')?.id||modules[0].id,selected:'',
      open:new Set(),status:new Map(data.courses[course].progress.nodes.map(n=>[n.id,n.status])),changed:new Set()});
    session=sessions.get(course);session.open.add(session.module);
  }
  const node=id=>index.get(id)||modules.find(n=>n.id===id);
  const status=id=>session.status.get(id)||'not_started';
  const dot=id=>`<i class="mm-dot" data-state="${status(id)}"></i>`;
  const originalKids=id=>id==='all'?graph.nodes.filter(n=>n.kind!=='module').map(n=>n.id):graph.edges.filter(e=>e.kind==='contains'&&e.from===id).map(e=>e.to);
  function descendants(id){const found=new Set(),queue=[...originalKids(id)];while(queue.length){const id=queue.shift();if(found.has(id))continue;found.add(id);queue.push(...originalKids(id))}return [...found]}
  function branchTree(module){
    const reachable=new Set([module,...descendants(module)]),parents=new Map();
    for(const id of reachable){if(id===module)continue;
      const options=graph.edges.filter(e=>e.kind==='contains'&&e.to===id&&reachable.has(e.from));
      options.sort((a,b)=>(node(a.from)?.kind==='module'?1:0)-(node(b.from)?.kind==='module'?1:0));
      parents.set(id,options[0]?.from||module);
    }
    return id=>[...parents].filter(([,parent])=>parent===id).map(([child])=>child);
  }
  function getModule(id){const current=modules.find(m=>m.id===session.module);if(current&&(current.id===id||descendants(current.id).includes(id)))return current;return modules.find(m=>m.id===id||descendants(m.id).includes(id))||modules[0]}
  function moduleButtons(){return modules.map((m,i)=>`<button class="mm-module ${session.module===m.id?'active':''}" data-mm="module" data-id="${esc(m.id)}"><span class="mm-number">${String(i+1).padStart(2,'0')}</span><span><b>${esc(m.title)}</b></span></button>`).join('')}
  function currentModule(){return node(session.module)}
  function header(){const knowledge=graph.nodes.filter(n=>n.kind!=='module'),learned=knowledge.filter(n=>status(n.id)==='learned').length;
    return `<header class="mm-header"><div><div class="mm-eyebrow">EDUCATION / COURSE MAP</div><h1>把知识，理成一条清晰的脉络。</h1><p>${esc(graph.name)} · ${modules.length} 个模块 · ${knowledge.length} 个知识点</p></div><div class="mm-course-summary"><div class="mm-numbers"><strong>${learned}<span style="font-size:12px;color:#a1ae9e"> / ${knowledge.length}</span></strong><small>已学习知识点</small></div><span class="mm-demo-badge">交互 Demo</span></div></header>
      <div class="mm-toolbar"><div class="mm-search"><input data-mm-input="search" type="search" value="${esc(query)}" placeholder="搜索知识点，定位到所属模块" aria-label="搜索知识点"><div class="mm-search-results" hidden></div></div><select class="mm-mobile-module" data-mm-input="module" aria-label="选择当前模块">${modules.map(m=>`<option value="${esc(m.id)}" ${m.id===session.module?'selected':''}>${esc(m.title)}</option>`).join('')}</select><div class="mm-legend">${Object.entries(statusNames).map(([id,title])=>`<span><i class="mm-dot" data-state="${id}"></i>${title}</span>`).join('')}</div></div>`;
  }
  function detail(){const n=node(session.selected)||currentModule(),info=data.courses[course].progress.nodes.find(v=>v.id===n.id);
    const related=graph.edges.filter(e=>e.from===n.id||e.to===n.id),pages=[...new Set(n.pages||[])];
    return `<aside class="mm-detail" aria-label="知识点详情"><div class="mm-detail-head"><small>${n.kind==='module'?'MODULE / 课程模块':'KNOWLEDGE / 知识点'}</small><button data-mm="close" aria-label="关闭知识点详情">×</button></div><h2>${esc(n.title)}</h2><div class="mm-body">${esc(n.body||'知识内容待补充。')}</div><div class="mm-status-box"><label>学习状态<select data-mm-input="status" data-id="${esc(n.id)}" aria-label="学习状态">${Object.entries(statusNames).map(([k,v])=>`<option value="${k}" ${status(n.id)===k?'selected':''}>${v}</option>`).join('')}</select></label><button data-mm="learned" data-id="${esc(n.id)}">${status(n.id)==='learned'?'✓ 已学习':'✓ 标记为已学习'}</button><p>此处标记仅用于 Demo 体验。<br>掌握证据：${esc(info?.mastery_label||'尚未评估')}</p></div>${pages.length?`<h3>教材 PDF 页码</h3><div class="mm-pages">${pages.map(p=>`<span>P${p}</span>`).join('')}</div>`:''}<h3>其他知识联系 · ${related.length}</h3>${related.map(e=>{const id=e.from===n.id?e.to:e.from;return `<button class="mm-related" data-mm="select" data-id="${esc(id)}"><small>${relationNames[e.kind]} ${e.from===n.id?'→':'←'}</small>${esc(node(id)?.title)}</button>`}).join('')||'<p class="mm-body">可随学习继续补充。</p>'}</aside>`;
  }
  function VariantA(){return `<div class="mm-view"><nav class="mm-modules" aria-label="课程模块"><div class="mm-list-title"><span>课程模块</span><span>${modules.length}</span></div>${moduleButtons()}</nav><section class="mm-stage"><div class="mm-stage-title">${esc(graph.name)} <span style="margin:0 8px">/</span> <strong>${esc(currentModule().title)}</strong></div><div class="mm-canvas" aria-label="章节知识导图"><div class="mm-world"></div></div><div class="mm-map-controls"><button data-mm="zoom-out" aria-label="缩小">−</button><button data-mm="zoom-in" aria-label="放大">＋</button><button data-mm="fit">适应</button><button data-mm="expand-all">展开本模块</button><button data-mm="collapse">收起分支</button></div><div class="mm-map-help">点击知识点查看内容 · 拖动画布浏览</div></section>${detailOpen?detail():''}</div>`}
  function outlineNode(id,level,kids){const n=node(id),children=kids(id);return `<div class="mm-outline-row" style="margin-left:${level*16}px">${children.length?`<button class="mm-outline-expand" data-mm="toggle" data-id="${esc(id)}" aria-label="展开或收起 ${esc(n.title)}">${session.open.has(id)?'−':'＋'}</button>`:'<span style="width:25px;flex:none"></span>'}<button class="${session.selected===id?'selected':''}" data-mm="select" data-id="${esc(id)}">${dot(id)}${esc(n.title)}${status(id)==='learned'?'<small style="margin-left:auto;color:#62a283">✓</small>':''}</button></div>${session.open.has(id)?children.map(child=>outlineNode(child,level+1,kids)).join(''):''}`}
  function VariantB(){return `<div class="mm-view"><aside class="mm-outline-side"><div class="mm-eyebrow">COURSE OUTLINE</div><h2>${esc(graph.name)}</h2><p>从大纲往下读，<br>一次展开一个模块。</p><strong>${modules.length}</strong><small>个课程模块</small><p style="margin-top:25px">关系不用全画出来。<br>需要时点进知识点，<br>再看先修与应用。</p></aside><section class="mm-outline-area"><p class="mm-outline-intro">按课程大纲浏览 · 展开后查看知识点与学习状态</p>${modules.map((m,i)=>`<section class="mm-outline-section"><button class="mm-outline-head" data-mm="outline-module" data-id="${esc(m.id)}"><small>${String(i+1).padStart(2,'0')}</small><b>${esc(m.title)}</b><span class="mm-outline-count">${descendants(m.id).length} 个知识点</span><span>${session.open.has(m.id)?'−':'＋'}</span></button>${session.open.has(m.id)?`<div class="mm-outline-children">${branchTree(m.id)(m.id).map(id=>outlineNode(id,0,branchTree(m.id))).join('')}</div>`:''}</section>`).join('')}</section>${detailOpen?detail():''}</div>`}
  function VariantC(){const descendantsList=descendants(session.module);return `<div class="mm-view"><section class="mm-column modules"><div class="mm-column-title">01 &nbsp; 选择模块</div>${moduleButtons()}</section><section class="mm-column knowledge"><div class="mm-column-title">02 &nbsp; ${esc(currentModule().title)}</div>${descendantsList.map(id=>`<button class="mm-column-card ${session.selected===id?'active':''}" data-mm="select" data-id="${esc(id)}">${dot(id)}${esc(node(id).title)}<span>${status(id)==='learned'?'✓':'›'}</span></button>`).join('')||'<p class="mm-body">本模块知识点待补充。</p>'}</section>${detail()}</div>`}
  function switcher(){return `<div class="mm-switcher" aria-label="切换Demo布局"><button class="mm-switch-arrow" data-mm="previous" aria-label="上一个布局">←</button>${Object.entries(names).map(([id,title])=>`<button data-mm="variant" data-variant="${id}" aria-pressed="${variant===id}">${id} ${title}</button>`).join('')}<span class="mm-variant-counter">3 个方案</span><button class="mm-switch-arrow" data-mm="next" aria-label="下一个布局">→</button></div>`}
  function render(){if(!host?.isConnected)return;
    resize?.disconnect();const navScroll=host.querySelector('.mm-modules,.mm-column.modules')?.scrollTop||0;
    host.dataset.variant=variant;host.innerHTML=header()+({A:VariantA,B:VariantB,C:VariantC}[variant])()+`<footer class="mm-footer"><span><strong>${variant} · ${names[variant]}</strong> &nbsp; / &nbsp; 当前模块：${esc(currentModule().title)} &nbsp; / &nbsp; 演示标记：${session.changed.size} 处</span><span>学习状态为现有快照；演示标记不写入学习记录。</span></footer>`+switcher();
    const nav=host.querySelector('.mm-modules,.mm-column.modules');if(nav)nav.scrollTop=navScroll;
    if(variant==='A'){drawMap();resize=new ResizeObserver(()=>drawMap());resize.observe(host.querySelector('.mm-canvas'))}
  }
  function drawMap(){
    const kids=branchTree(session.module),positions=[],links=[],mobile=innerWidth<=760;
    const measure=id=>{const children=session.open.has(id)?kids(id):[];return children.length?Math.max(60,children.reduce((sum,id)=>sum+measure(id),0)+(children.length-1)*12):52};
    const span=measure(session.module),origin=60;
    function layout(id,depth,top){const children=session.open.has(id)?kids(id):[],height=measure(id),p={id,depth,x:268+depth*290,y:top+height/2-26,w:depth===0?214:232,h:52};positions.push(p);let offset=top;for(const child of children){const c=layout(child,depth+1,offset);links.push([p,c]);offset+=measure(child)+12}return p}
    const module=layout(session.module,0,origin),root={id:'__course',x:28,y:module.y-17,w:178,h:86};positions.push(root);links.unshift([root,module]);
    if(mobile){let offset=225;root.x=29;root.y=65;root.w=270;root.h=72;module.x=29;module.y=160;module.w=270;module.h=52;for(const p of positions){if(p===root||p===module)continue;const indent=Math.max(0,p.depth-1)*16;p.x=52+indent;p.y=offset;p.w=247-indent;offset+=64}}
    geometry={w:Math.max(...positions.map(p=>p.x+p.w))+30,h:Math.max(...positions.map(p=>p.y+p.h))+38};
    const byId=new Map(positions.map(p=>[p.id,p]));
    const linePath=(a,b)=>mobile?(a===root?`M ${a.x+135} ${a.y+a.h} V ${b.y}`:`M ${a.x+9} ${a.y+a.h} V ${b.y+26} H ${b.x}`):`M ${a.x+a.w} ${a.y+a.h/2} C ${a.x+a.w+46} ${a.y+a.h/2}, ${b.x-46} ${b.y+b.h/2}, ${b.x} ${b.y+b.h/2}`;
    world=host.querySelector('.mm-world');world.style.width=`${geometry.w}px`;world.style.height=`${geometry.h}px`;
    world.innerHTML=`<svg class="mm-lines" width="${geometry.w}" height="${geometry.h}" aria-hidden="true">${links.map(([a,b],i)=>`<path class="${i===0?'major':''}" d="${linePath(a,b)}"/>`).join('')}</svg>`+positions.map(p=>{
      const n=p.id==='__course'?null:node(p.id),children=n?kids(n.id):[];
      return `<div class="mm-node ${p.id==='__course'?'course':p.id===session.module?'module':'knowledge'} ${session.selected===p.id?'selected':''}" data-node-id="${esc(p.id)}" data-state="${status(p.id)}" style="left:${p.x}px;top:${p.y}px;width:${p.w}px;height:${p.h}px">${p.id==='__course'?`<b>${esc(graph.name)}</b><small>课程知识导图 · ${modules.length} 个模块</small>`:`<button class="mm-node-main" data-mm="select" data-id="${esc(n.id)}">${p.id===session.module?`<span><b>${esc(n.title)}</b></span>`:`${dot(n.id)}<span class="mm-node-label">${esc(n.title)}</span>${status(n.id)==='learned'?'<span class="mm-learned-mark">✓</span>':''}`}</button>${children.length?`<button class="mm-toggle" data-mm="toggle" data-id="${esc(n.id)}" aria-label="展开或收起 ${esc(n.title)}">${session.open.has(n.id)?'−':children.length+' +'}</button>`:''}`}</div>`;
    }).join('');fit();
  }
  function place(){if(world)world.style.transform=`translate(${camera.x}px,${camera.y}px) scale(${camera.scale})`}
  function fit(){const canvas=host?.querySelector('.mm-canvas');if(!canvas)return;const w=canvas.clientWidth,h=canvas.clientHeight,mobile=innerWidth<=760;
    camera.scale=mobile?Math.max(.65,Math.min(1.08,(w-18)/geometry.w)):Math.max(.25,Math.min(1.15,(w-40)/geometry.w,(h-112)/geometry.h));
    camera.x=(w-geometry.w*camera.scale)/2;camera.y=mobile?6:Math.max(44,(h-geometry.h*camera.scale)/2);place();
  }
  function choose(id){if(!node(id))return;const m=getModule(id);session.module=m.id;session.open.add(m.id);
    // Reveal containing ancestors without drawing additional relation edges.
    const kids=branchTree(m.id),reveal=current=>{if(current===id)return true;for(const child of kids(current))if(reveal(child)){session.open.add(current);return true}return false};reveal(m.id);
    session.selected=id;detailOpen=true;query='';render();
  }
  function changeVariant(id){variant=names[id]?id:'A';const url=new URL(location.href);url.searchParams.set('variant',variant);history.replaceState(null,'',url);detailOpen=variant==='C';render()}
  function mark(id,value){if(!Object.hasOwn(statusNames,value))return;session.status.set(id,value);session.changed.add(id);render()}
  function action(button){const type=button.dataset.mm,id=button.dataset.id;
    if(type==='variant'){changeVariant(button.dataset.variant);return}
    if(type==='previous'||type==='next'){const keys=Object.keys(names),i=keys.indexOf(variant);changeVariant(keys[(i+(type==='next'?1:2))%3]);return}
    if(type==='module'){session.module=id;session.selected='';session.open.add(id);detailOpen=variant==='C';query='';render();return}
    if(type==='outline-module'){session.module=id;session.open.has(id)?session.open.delete(id):session.open.add(id);render();return}
    if(type==='select'){choose(id);return}
    if(type==='close'){detailOpen=false;session.selected='';if(variant==='C')changeVariant('A');else render();return}
    if(type==='learned'){mark(id,'learned');return}
    if(type==='toggle'){session.open.has(id)?session.open.delete(id):session.open.add(id);render();return}
    if(type==='expand-all'){session.open.add(session.module);for(const id of descendants(session.module))session.open.add(id);render();return}
    if(type==='collapse'){session.open=new Set([session.module]);render();return}
    if(type==='fit'){fit();return}
    if(type==='zoom-in'||type==='zoom-out'){const factor=type==='zoom-in'?1.2:1/1.2,canvas=host.querySelector('.mm-canvas'),cx=canvas.clientWidth/2,cy=canvas.clientHeight/2,newScale=Math.max(.25,Math.min(2,camera.scale*factor)),ratio=newScale/camera.scale;camera={scale:newScale,x:cx+(camera.x-cx)*ratio,y:cy+(camera.y-cy)*ratio};place()}
  }
  function mount(element,id){unmount();host=element;setup(id);variant=names[new URLSearchParams(location.search).get('variant')]?new URLSearchParams(location.search).get('variant'):'A';controller=new AbortController();const signal=controller.signal;detailOpen=variant==='C';query='';render();
    host.addEventListener('click',event=>{const button=event.target.closest('[data-mm]');if(button)action(button)},{signal});
    host.addEventListener('change',event=>{const input=event.target;if(input.dataset.mmInput==='status')mark(input.dataset.id,input.value);if(input.dataset.mmInput==='module')action({dataset:{mm:'module',id:input.value}})},{signal});
    host.addEventListener('input',event=>{if(event.target.dataset.mmInput!=='search')return;query=event.target.value.trim();const result=host.querySelector('.mm-search-results');result.hidden=!query;const found=graph.nodes.filter(n=>n.title.includes(query));result.innerHTML=found.length?found.slice(0,25).map(n=>`<button data-mm="select" data-id="${esc(n.id)}">${esc(n.title)}</button>`).join(''):'<p>没有匹配的知识点</p>'},{signal});
    document.addEventListener('keydown',event=>{if(event.target.closest('input,textarea,select,[contenteditable=true]'))return;if(['ArrowLeft','ArrowRight'].includes(event.key)){event.preventDefault();action({dataset:{mm:event.key==='ArrowRight'?'next':'previous'}})}},{signal});
    host.addEventListener('pointerdown',event=>{if(!event.target.closest('.mm-canvas')||event.target.closest('button')||event.button!==0)return;const canvas=event.target.closest('.mm-canvas');canvas.setPointerCapture(event.pointerId);drag={id:event.pointerId,x:event.clientX,y:event.clientY,px:camera.x,py:camera.y};event.preventDefault()},{signal});
    host.addEventListener('pointermove',event=>{if(!drag||drag.id!==event.pointerId)return;camera.x=drag.px+event.clientX-drag.x;camera.y=drag.py+event.clientY-drag.y;place()},{signal});
    for(const type of ['pointerup','pointercancel'])host.addEventListener(type,()=>drag=null,{signal});
    host.addEventListener('wheel',event=>{if(!event.target.closest('.mm-canvas'))return;event.preventDefault();camera.y-=event.deltaY;camera.x-=event.deltaX;place()},{signal,passive:false});
  }
  function unmount(){controller?.abort();resize?.disconnect();host=null;world=null;drag=null}
  return {html,mount,unmount};
})();
