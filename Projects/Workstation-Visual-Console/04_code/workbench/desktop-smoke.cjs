// Local browser smoke check for the standalone layout prototype.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const http = require("node:http");
const {spawn} = require("node:child_process");

const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const port = 19000 + Math.floor(Math.random() * 1000);
const profile = path.join(os.tmpdir(), `workstation-desktop-smoke-${process.pid}`);
const browser = spawn(edge, ["--headless=new", "--disable-gpu", "--no-first-run", "--window-size=1600,900",
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  "http://127.0.0.1:8765/workbench?smoke=1"], {stdio: "ignore", windowsHide: true});

async function main() {
  let target;
  for (let attempt = 0; attempt < 80; attempt++) {
    try {
      const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      target = pages.find(page => page.type === "page" && page.url.includes("/workbench?smoke=1"));
      if (target) break;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 125));
  }
  assert.ok(target, "Edge did not open the prototype");
  const socket = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject});
  let serial = 0;
  const pending = new Map();
  socket.onmessage = event => {
    const message = JSON.parse(event.data);
    if (!message.id) return;
    const entry = pending.get(message.id);
    if (!entry) return;
    pending.delete(message.id);
    if (message.error) entry.reject(new Error(message.error.message));
    else entry.resolve(message.result);
  };
  function send(method, params = {}, sessionId) {
    const id = ++serial;
    return new Promise((resolve, reject) => {
      pending.set(id, {resolve, reject});
      socket.send(JSON.stringify({id, method, params,...(sessionId?{sessionId}:{})}));
    });
  }
  async function evaluate(expression) {
    const response = await send("Runtime.evaluate", {expression, returnByValue: true, awaitPromise: true});
    if (response.exceptionDetails) throw new Error(response.exceptionDetails.text);
    return response.result.value;
  }
  for (let attempt = 0; attempt < 80; attempt++) {
    if (await evaluate(`!!document.querySelector('.split-canvas')`)) break;
    await new Promise(resolve => setTimeout(resolve, 125));
  }
  const initial = await evaluate(`({
    theme:document.body.dataset.theme,
    panes:document.querySelectorAll('.split-pane').length,
    dividers:document.querySelectorAll('.split-divider').length,
    windows:document.querySelectorAll('.tool-window').length,
    orientation:document.querySelector('.split-divider')?.getAttribute('aria-orientation'),
    workflow:!!document.querySelector('.workflow-pane')
  })`);
  assert.deepEqual(initial, {theme:"vscode",panes:2,dividers:1,windows:0,orientation:"vertical",workflow:true});
  await evaluate(`document.querySelector('.icon-rail [data-action="open-console"]').click()`);
  const consoleReady=await evaluate(`({title:document.querySelector('.control-title h1')?.textContent,metrics:[...document.querySelectorAll('.control-metric strong')].map(el=>el.textContent),projects:document.querySelectorAll('.control-project-name').length,filters:document.querySelectorAll('.control-filters').length,chat:!!document.querySelector('.icon-rail [data-action="open-chat"]')})`);
  assert.equal(consoleReady.title,"中控台");
  assert.deepEqual(consoleReady.metrics.slice(0,3),["4","5","13"]);
  assert.equal(consoleReady.projects,5);
  assert.equal(consoleReady.filters,0);
  assert.equal(consoleReady.chat,false);
  for(let attempt=0;attempt<30&&!await evaluate(`!!document.querySelector('.bridge-card')`);attempt++)await new Promise(resolve=>setTimeout(resolve,100));
  const bridgeInitial=await evaluate(`({name:document.querySelector('.bridge-card strong')?.textContent,status:document.querySelector('.bridge-card .bridge-badge')?.textContent,homework:document.querySelector('.bridge-card p')?.textContent})`);
  assert.equal(bridgeInitial.name,"雨课堂");
  assert.equal(bridgeInitial.status,"只读考试提醒");
  assert.match(bridgeInitial.homework,/最近检查/);
  assert.match(bridgeInitial.homework,/Edge 收藏夹/);
  const missingExtensionHelp=await evaluate(`(()=>{siteBridgeState.autoStatus='extension_unavailable';render();return document.querySelector('.bridge-error[role="status"]')?.textContent||''})()`);
  assert.match(missingExtensionHelp,/Codex 内置浏览器/);
  await evaluate(`(()=>{siteBridgeState.autoStatus='waiting';render()})()`);
  const countPreview=await evaluate(`(async()=>{
    const real=embeddedApi;
    embeddedApi=async(path,payload)=>{
      if(path==='/api/workbench/site-bridges/rain-check')throw Error('smoke must not save a Rain check');
      return real(path,payload);
    };
    await saveRainCheck({status:'checked',count:2});
    embeddedApi=real;
    return {summary:document.querySelector('.attention-item strong')?.textContent,
      notice:siteBridgeState.scriptNotice,detail:!!document.querySelector('.bridge-results')};
  })()`);
  assert.equal(countPreview.summary,"最近一周 2 门考试");
  assert.match(countPreview.notice,/不保存/);
  assert.equal(countPreview.detail,false);
  const consoleShot=await send("Page.captureScreenshot",{format:"png"});
  fs.writeFileSync(path.join(__dirname,"../../08_evidence/control-center-demo.png"),Buffer.from(consoleShot.data,"base64"));
  const bridgeAdded=await evaluate(`(async()=>{
    const real=embeddedApi,realOpen=window.open;
    const before=siteBridgeState.sites.length;
    const full='https://student:demo@school.example.edu/course?ticket=demo';
    window.__fakeTab={opener:null,location:{replace(url){window.__resolvedLogin=url}},close(){}};
    window.open=url=>{if(url==='about:blank')return window.__fakeTab;window.__directLogin=url;return window.__fakeTab};
    embeddedApi=async(path,payload)=>path==='/api/workbench/site-bridges/save'
      ?(window.__bridgePayload=payload,{sites:[...siteBridgeState.sites,{id:'mock_school',name:payload.name,url:'https://school.example.edu/course',login_strategy:'encrypted_link',has_login_url:true,adapter_ready:false,assignment_status:'not_checked',assignment_count:null}]})
      :path==='/api/workbench/site-bridges/login-url'?{url:full,strategy:'encrypted_link'}:real(path,payload);
    document.querySelector('[data-action="add-site-bridge"]').click();
    await new Promise(resolve=>setTimeout(resolve,0));
    const form=document.querySelector('[data-role="site-bridge-form"]');
    form.querySelector('[name="name"]').value='测试课程站';
    form.querySelector('[name="url"]').value=full;
    form.querySelector('[name="login_strategy"]').value='encrypted_link';
    form.querySelector('[data-action="open-site-login"]').click();
    form.requestSubmit();
    await new Promise(resolve=>setTimeout(resolve,50));
    document.querySelector('.bridge-card:last-child [data-action="open-saved-site"]').click();
    await new Promise(resolve=>setTimeout(resolve,50));
    embeddedApi=real;window.open=realOpen;
    return {payload:window.__bridgePayload,before,cards:document.querySelectorAll('.bridge-card').length,open:!!document.querySelector('.bridge-form'),direct:window.__directLogin,resolved:window.__resolvedLogin,leaked:document.querySelector('.bridge-card:last-child')?.textContent.includes('demo')};
  })()`);
  assert.deepEqual(bridgeAdded.payload,{id:"",name:"测试课程站",url:"https://student:demo@school.example.edu/course?ticket=demo",login_strategy:"encrypted_link",bookmark_query:""});
  assert.equal(bridgeAdded.cards,bridgeAdded.before+1);
  assert.equal(bridgeAdded.open,false);
  assert.equal(bridgeAdded.direct,"https://student:demo@school.example.edu/course?ticket=demo");
  assert.equal(bridgeAdded.resolved,bridgeAdded.direct);
  assert.equal(bridgeAdded.leaked,false);
  await evaluate(`(async()=>{document.querySelector('.control-topbar [data-action="resume-workbench"]').click();await new Promise(resolve=>setTimeout(resolve,0))})()`);
  assert.deepEqual(await evaluate(`({key:boardKey(),panes:document.querySelectorAll('.split-pane').length})`),{key:"console/workbench",panes:2});
  const usageRecorded=await evaluate(`(()=>{usageWasActive=true;usageProject='console';usageLastTick=Date.now()-2400;tickUsage();render();return snapshotState().usage.find(row=>row[0]==='console')?.[1]})()`);
  assert.ok(usageRecorded>=2,"foreground project time must enter the saved snapshot");
  const projectBefore=await evaluate(`(()=>{const pane=document.querySelector('.project-pane').getBoundingClientRect(),handle=document.querySelector('.project-resizer').getBoundingClientRect();return {width:pane.width,x:handle.x+handle.width/2,y:handle.y+120,main:document.querySelector('main').getBoundingClientRect().width}})()`);
  await send("Input.dispatchMouseEvent",{type:"mousePressed",x:projectBefore.x,y:projectBefore.y,button:"left",clickCount:1});
  await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:projectBefore.x+80,y:projectBefore.y,button:"left",buttons:1});
  await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:projectBefore.x+80,y:projectBefore.y,button:"left",buttons:0});
  const projectAfter=await evaluate(`({width:document.querySelector('.project-pane').getBoundingClientRect().width,main:document.querySelector('main').getBoundingClientRect().width,panes:document.querySelectorAll('.split-pane').length})`);
  assert.ok(projectAfter.width>projectBefore.width+60,"project sidebar divider must widen the sidebar");
  assert.ok(projectAfter.main<projectBefore.main-60,"main area must adjust with the sidebar");
  assert.equal(projectAfter.panes,2);
  const hidden=await evaluate(`(async()=>{document.querySelector('.project-pane .project-hide').click();await new Promise(resolve=>setTimeout(resolve,0));return {hidden:document.querySelector('.layout-b').classList.contains('project-hidden'),pane:document.querySelector('.project-pane').getBoundingClientRect().width,main:document.querySelector('main').getBoundingClientRect().width,workflow:!!document.querySelector('.workflow-pane')}})()`);
  assert.equal(hidden.hidden,true);
  assert.equal(hidden.pane,0);
  assert.ok(hidden.main>projectBefore.main+200,"hiding sidebar must give space to main");
  assert.equal(hidden.workflow,true);
  const restored=await evaluate(`(async()=>{document.querySelector('.icon-rail [data-action="toggle-project-pane"]').click();await new Promise(resolve=>setTimeout(resolve,0));return {width:document.querySelector('.project-pane').getBoundingClientRect().width,panes:document.querySelectorAll('.split-pane').length}})()`);
  assert.ok(Math.abs(restored.width-projectAfter.width)<2,"restoring sidebar must retain its width");
  assert.equal(restored.panes,2);
  const sidebarShot=await send("Page.captureScreenshot",{format:"png"});
  fs.writeFileSync(path.join(__dirname,"../../08_evidence/project-sidebar-resized.png"),Buffer.from(sidebarShot.data,"base64"));
  const before = await evaluate(`(()=>{const d=document.querySelector('.split-divider').getBoundingClientRect(),a=document.querySelector('.split-part.first').getBoundingClientRect(),b=document.querySelector('.split-part.second').getBoundingClientRect();return {x:d.x+d.width/2,y:d.y+Math.min(100,d.height/2),width:a.width,seam:Math.round(a.right-d.left)+Math.round(d.right-b.left)}})()`);
  assert.equal(before.seam,0,"panes must meet the divider");
  await send("Input.dispatchMouseEvent",{type:"mousePressed",x:before.x,y:before.y,button:"left",clickCount:1});
  await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:before.x+80,y:before.y,button:"left",buttons:1});
  await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:before.x+80,y:before.y,button:"left",buttons:0});
  const dragged = await evaluate(`({width:document.querySelector('.split-part.first').getBoundingClientRect().width,ratio:splitTrees.get(boardKey()).ratio,dividers:document.querySelectorAll('.split-divider').length})`);
  assert.ok(dragged.width>before.width+60,"vertical divider must resize panes");
  assert.equal(dragged.dividers,1);
  assert.ok(dragged.ratio>.5);
  const draggedShot=await send("Page.captureScreenshot",{format:"png"});
  fs.writeFileSync(path.join(__dirname,"../../08_evidence/split-pane-dragged.png"),Buffer.from(draggedShot.data,"base64"));
  const documentAndAnnotations = await evaluate(`(async()=>{
    document.querySelector('.split-pane[data-window-id="1"] .blank-prompt button').click();
    await new Promise(resolve=>setTimeout(resolve,0));
    document.querySelector('.split-pane[data-window-id="1"] [data-preset="document"]').click();
    await new Promise(resolve=>setTimeout(resolve,0));
    const editor=document.querySelector('.split-pane[data-window-id="1"] [data-role="document"]');
    editor.value='保留的文档内容';editor.dispatchEvent(new Event('input',{bubbles:true}));
    editor.focus();editor.setSelectionRange(0,4);editor.dispatchEvent(new Event('select',{bubbles:true}));
    document.querySelector('.split-pane[data-window-id="1"] [data-action="new-annotation"]').click();
    await new Promise(resolve=>setTimeout(resolve,0));
    const note=document.querySelector('.split-pane[data-window-id="1"] [data-role="annotation-text"]');
    note.value='这是一条标注';note.dispatchEvent(new Event('input',{bubbles:true}));
    document.querySelector('.split-pane[data-window-id="1"] [data-action="save-annotation"]').click();
    await new Promise(resolve=>setTimeout(resolve,0));
    document.querySelector('.split-pane[data-window-id="1"] [data-action="new-annotation"]').click();
    await new Promise(resolve=>setTimeout(resolve,0));
    const kind=document.querySelector('.split-pane[data-window-id="1"] [data-role="annotation-kind"]');
    kind.value='link';kind.dispatchEvent(new Event('change',{bubbles:true}));
    await new Promise(resolve=>setTimeout(resolve,0));
    const url=document.querySelector('.split-pane[data-window-id="1"] [data-role="annotation-url"]');
    url.value='https://example.com';url.dispatchEvent(new Event('input',{bubbles:true}));
    document.querySelector('.split-pane[data-window-id="1"] [data-action="save-annotation"]').click();
    await new Promise(resolve=>setTimeout(resolve,0));
    document.querySelector('[data-action="show-layouts"]').click();
    await new Promise(resolve=>setTimeout(resolve,0));
    return {text:currentWindows()[0].documentText,annotations:currentWindows()[0].annotations.length,
      kinds:currentWindows()[0].annotations.map(a=>a.kind),quote:currentWindows()[0].annotations[0].quote,
      types:document.querySelectorAll('.template-card').length,primary:document.querySelectorAll('.split-pane[data-window-id="1"] .primary-layout').length}
  })()`);
  assert.deepEqual(documentAndAnnotations,{text:"保留的文档内容",annotations:2,kinds:["note","link"],quote:"保留的文",types:6,primary:1});
  const anchor=await evaluate(`(()=>{document.querySelector('.split-pane[data-window-id="1"] .annotation-quote').click();const editor=document.querySelector('.split-pane[data-window-id="1"] [data-role="document"]');return {start:editor.selectionStart,end:editor.selectionEnd}})()`);
  assert.deepEqual(anchor,{start:0,end:4},"clicking a comment quote must select its document text");
  const galleryShot=await send("Page.captureScreenshot",{format:"png"});
  fs.writeFileSync(path.join(__dirname,"../../08_evidence/split-pane-layouts.png"),Buffer.from(galleryShot.data,"base64"));
  const horizontal=await evaluate(`(async()=>{document.querySelector('[data-layout="top-bottom"]').click();await new Promise(resolve=>setTimeout(resolve,0));return {panes:document.querySelectorAll('.split-pane').length,orientation:document.querySelector('.split-divider')?.getAttribute('aria-orientation'),text:currentWindows()[0].documentText}})()`);
  assert.deepEqual(horizontal,{panes:2,orientation:"horizontal",text:"保留的文档内容"});
  const hBefore=await evaluate(`(()=>{const r=document.querySelector('.split-divider').getBoundingClientRect();return {x:r.x+Math.min(80,r.width/2),y:r.y+r.height/2,height:document.querySelector('.split-part.first').getBoundingClientRect().height}})()`);
  await send("Input.dispatchMouseEvent",{type:"mousePressed",x:hBefore.x,y:hBefore.y,button:"left",clickCount:1});
  await send("Input.dispatchMouseEvent",{type:"mouseMoved",x:hBefore.x,y:hBefore.y+55,button:"left",buttons:1});
  await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:hBefore.x,y:hBefore.y+55,button:"left",buttons:0});
  const hAfter=await evaluate(`document.querySelector('.split-part.first').getBoundingClientRect().height`);
  assert.ok(hAfter>hBefore.height+40,"horizontal divider must resize panes");
  const quad=await evaluate(`(async()=>{document.querySelector('[data-action="show-layouts"]').click();await new Promise(resolve=>setTimeout(resolve,0));document.querySelector('[data-layout="quad"]').click();await new Promise(resolve=>setTimeout(resolve,0));return {panes:document.querySelectorAll('.split-pane').length,dividers:document.querySelectorAll('.split-divider').length,text:currentWindows()[0].documentText}})()`);
  assert.deepEqual(quad,{panes:4,dividers:3,text:"保留的文档内容"});
  const builder=await evaluate(`(async()=>{document.querySelector('.split-pane[data-window-id="2"] .blank-prompt button').click();await new Promise(resolve=>setTimeout(resolve,0));return !!document.querySelector('.split-pane[data-window-id="2"] [data-role="ux-mode"]')})()`);
  assert.equal(builder,true);
  const chosen=await evaluate(`(async()=>{const ui=document.querySelector('.split-pane[data-window-id="2"] [data-role="ui-style"]');ui.value='cards';ui.dispatchEvent(new Event('change',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,0));const ux=document.querySelector('.split-pane[data-window-id="2"] [data-role="ux-mode"]');ux.value='guided';ux.dispatchEvent(new Event('change',{bubbles:true}));await new Promise(resolve=>setTimeout(resolve,0));return {ui:currentWindows()[1].uiStyle,ux:currentWindows()[1].uxMode}})()`);
  assert.deepEqual(chosen,{ui:"cards",ux:"guided"});
  const customSentence=await evaluate(`(async()=>{document.querySelector('.split-pane[data-window-id="2"] [data-preset="custom"]').click();await new Promise(resolve=>setTimeout(resolve,0));const input=document.querySelector('.split-pane[data-window-id="2"] [data-role="codex-description"]');input.value='设计一个项目预算与支出对照表';input.dispatchEvent(new Event('input',{bubbles:true}));return {kind:currentWindows()[1].kind,tag:input.tagName,text:currentWindows()[1].codexText,primary:document.querySelectorAll('.split-pane[data-window-id="2"] .primary-layout').length}})()`);
  assert.deepEqual(customSentence,{kind:"custom",tag:"INPUT",text:"设计一个项目预算与支出对照表",primary:1});
  const browser=await evaluate(`(async()=>{document.querySelector('.split-pane[data-window-id="2"] [data-preset="browser"]').click();await new Promise(resolve=>setTimeout(resolve,0));const input=document.querySelector('.split-pane[data-window-id="2"] [data-role="browser-address"]');input.value='https://example.com/';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.split-pane[data-window-id="2"] [data-action="browser-go"]').click();await new Promise(resolve=>setTimeout(resolve,0));const frame=document.querySelector('#browser-portals .browser-frame'),host=document.querySelector('.split-pane[data-window-id="2"] .browser-viewport');const a=frame?.getBoundingClientRect(),b=host?.getBoundingClientRect();return {kind:currentWindows()[1].kind,url:currentWindows()[1].browserUrl,frame:frame?.getAttribute('src'),primary:document.querySelectorAll('.split-pane[data-window-id="2"] .primary-layout').length,fill:!!a&&!!b&&Math.abs(a.width-b.width)<1&&Math.abs(a.height-b.height)<1}})()`);
  assert.deepEqual(browser,{kind:"browser",url:"https://example.com/",frame:"https://example.com/",primary:1,fill:true});
  const browserPreserved=await evaluate(`(()=>{const frame=document.querySelector('#browser-portals .browser-frame');render();return frame===document.querySelector('#browser-portals .browser-frame')&&frame.style.display==='block'})()`);
  assert.equal(browserPreserved,true,"workbench redraw must preserve the live browser frame");
  const hits={home:0,submitted:[]};
  const fixture=http.createServer((request,response)=>{
    const url=new URL(request.url,"http://127.0.0.1");
    response.setHeader("Content-Type","text/html; charset=utf-8");
    if(url.pathname==="/clicked"){
      hits.submitted.push(url.searchParams.get("q"));
      response.end(`<html><body style="font:18px Segoe UI;padding:25px">已在页面内提交：${url.searchParams.get("q")||""}</body></html>`);
    }else{
      hits.home++;
      response.end('<html><body style="margin:8px"><form action="/clicked" style="display:flex;gap:6px"><input name="q" style="width:110px;height:36px"><button style="width:86px;height:36px">提交</button></form></body></html>');
    }
  });
  await new Promise(resolve=>fixture.listen(0,"127.0.0.1",resolve));
  fixture.unref();
  const fixtureUrl=`http://127.0.0.1:${fixture.address().port}/`;
  const liveRect=await evaluate(`(async()=>{const input=document.querySelector('.split-pane[data-window-id="2"] [data-role="browser-address"]');input.value=${JSON.stringify(fixtureUrl)};input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.split-pane[data-window-id="2"] [data-action="browser-go"]').click();await new Promise(resolve=>setTimeout(resolve,0));const r=document.querySelector('#browser-portals .browser-frame').getBoundingClientRect();return {x:r.x,y:r.y}})()`);
  for(let i=0;i<40&&hits.home===0;i++)await new Promise(resolve=>setTimeout(resolve,100));
  assert.equal(hits.home,1,"local interactive page must load inside the browser space");
  let frameTarget;
  for(let i=0;i<40&&!frameTarget;i++){
    frameTarget=(await send("Target.getTargets")).targetInfos.find(target=>target.type==="iframe"&&target.url.startsWith(fixtureUrl));
    if(!frameTarget)await new Promise(resolve=>setTimeout(resolve,100));
  }
  assert.ok(frameTarget,"interactive page must have a browser frame target");
  const {sessionId:frameSession}=await send("Target.attachToTarget",{targetId:frameTarget.targetId,flatten:true});
  for(const [index,point] of [{x:36,y:25},{x:155,y:25}].entries()){
    await send("Input.dispatchMouseEvent",{type:"mousePressed",x:point.x,y:point.y,button:"left",clickCount:1},frameSession);
    await send("Input.dispatchMouseEvent",{type:"mouseReleased",x:point.x,y:point.y,button:"left",clickCount:1},frameSession);
    if(index===0)await send("Input.insertText",{text:"browser-check"},frameSession);
  }
  for(let i=0;i<40&&hits.submitted.length===0;i++)await new Promise(resolve=>setTimeout(resolve,100));
  if(hits.submitted.length===0){
    console.error("Browser click diagnostic",await evaluate(`(()=>{const r=document.querySelector('#browser-portals .browser-frame').getBoundingClientRect();return {topElement:document.elementFromPoint(r.x+155,r.y+25)?.outerHTML.slice(0,180),focused:document.activeElement?.outerHTML.slice(0,180),rect:{x:r.x,y:r.y,width:r.width,height:r.height},frameDisplay:document.querySelector('#browser-portals .browser-frame').style.display}})()`));
    console.error("Frame state",(await send("Runtime.evaluate",{expression:"({value:document.querySelector('input')?.value,active:document.activeElement?.tagName,html:document.body.innerHTML.slice(0,100)})",returnByValue:true},frameSession)).result.value);
    const shot=await send("Page.captureScreenshot",{format:"png"});fs.writeFileSync(path.join(__dirname,"../../08_evidence/browser-workspace-diagnostic.png"),Buffer.from(shot.data,"base64"));
  }
  assert.deepEqual(hits.submitted,["browser-check"],"the embedded page must accept typing and form submission");
  const frameAfterWork=await evaluate(`(()=>{const frame=document.querySelector('#browser-portals .browser-frame');render();const same=frame===document.querySelector('#browser-portals .browser-frame');document.querySelector('.split-pane[data-window-id="2"] [data-action="browser-home"]').click();const home=!!document.querySelector('.split-pane[data-window-id="2"] .browser-start');document.querySelector('.split-pane[data-window-id="2"] [data-action="browser-back"]').click();return {same,home,restored:frame.style.display==='block',url:currentWindows()[1].browserUrl}})()`);
  assert.deepEqual(frameAfterWork,{same:true,home:true,restored:true,url:fixtureUrl});
  assert.equal(hits.home,1,"workbench redraw must not reload the live page");
  const browserAnnotation=await evaluate(`(()=>{const before=document.querySelector('.split-pane[data-window-id="2"] .browser-viewport').getBoundingClientRect().width;document.querySelector('.split-pane[data-window-id="2"] [data-action="browser-annotations"]').click();const pane=document.querySelector('.split-pane[data-window-id="2"] .annotation-pane'),host=document.querySelector('.split-pane[data-window-id="2"] .browser-viewport').getBoundingClientRect(),r=pane.getBoundingClientRect();return {open:!!pane,reachable:!!document.elementFromPoint(r.x+r.width/2,r.y+20)?.closest('.annotation-pane'),shrunk:host.width<before}})()`);
  assert.deepEqual(browserAnnotation,{open:true,reachable:true,shrunk:true},"annotations must remain operable beside the browser page");
  await evaluate(`document.querySelector('.split-pane[data-window-id="2"] [data-action="browser-annotations"]').click()`);
  const browserShot=await send("Page.captureScreenshot",{format:"png"});
  fs.writeFileSync(path.join(__dirname,"../../08_evidence/browser-workspace-interactive.png"),Buffer.from(browserShot.data,"base64"));
  fixture.close();
  await evaluate(`document.querySelector('.split-pane[data-window-id="2"] [data-action="configure-window"]').click()`);
  const files=await evaluate(`(async()=>{await new Promise(resolve=>setTimeout(resolve,0));document.querySelector('.split-pane[data-window-id="2"] [data-preset="files"]').click();for(let i=0;i<40&&currentWindows()[1].fileLoading;i++)await new Promise(resolve=>setTimeout(resolve,100));return {kind:currentWindows()[1].kind,error:currentWindows()[1].fileError||'',entries:currentWindows()[1].fileEntries?.length||0,readme:!!document.querySelector('.split-pane[data-window-id="2"] [data-path="10-README.MD"]')}})()`);
  assert.equal(files.kind,"files");assert.equal(files.error,"");assert.ok(files.entries>0);assert.equal(files.readme,true);
  const preview=await evaluate(`(async()=>{document.querySelector('.split-pane[data-window-id="2"] [data-path="10-README.MD"]').click();for(let i=0;i<40&&!currentWindows()[1].filePreview;i++)await new Promise(resolve=>setTimeout(resolve,100));return {relative:currentWindows()[1].filePreview?.relative,content:document.querySelector('.split-pane[data-window-id="2"] .file-preview')?.textContent||''}})()`);
  assert.equal(preview.relative,"10-README.MD");assert.ok(preview.content.includes("Workstation-Visual-Console"));
  const terminalReady=await evaluate(`(async()=>{document.querySelector('.split-pane[data-window-id="4"] [data-preset="terminal"]').click();await new Promise(resolve=>setTimeout(resolve,0));document.querySelector('.split-pane[data-window-id="4"] [data-action="terminal-start"]').click();for(let i=0;i<40&&!currentWindows()[3].terminalSession;i++)await new Promise(resolve=>setTimeout(resolve,100));return {kind:currentWindows()[3].kind,session:!!currentWindows()[3].terminalSession}})()`);
  assert.deepEqual(terminalReady,{kind:"terminal",session:true});
  const terminalOutput=await evaluate(`(async()=>{const input=document.querySelector('.split-pane[data-window-id="4"] [data-role="terminal-command"]');input.value='Write-Output "UI-TERMINAL-OK"';input.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('.split-pane[data-window-id="4"] [data-action="terminal-send"]').click();for(let i=0;i<100&&!currentWindows()[3].terminalOutput?.includes('UI-TERMINAL-OK');i++)await new Promise(resolve=>setTimeout(resolve,150));return currentWindows()[3].terminalOutput||''})()`);
  assert.ok(terminalOutput.includes("UI-TERMINAL-OK"),"interactive pwsh command must return output");
  const terminalState=await evaluate(`(async()=>{const item=currentWindows()[3];await embeddedApi('/api/workbench/terminal/input',{session_id:item.terminalSession,command:'$x=41'});await embeddedApi('/api/workbench/terminal/input',{session_id:item.terminalSession,command:'Write-Output ($x+1); Write-Output (Get-Location).Path'});for(let i=0;i<70&&!item.terminalOutput?.includes('Workstation-Visual-Console');i++)await new Promise(resolve=>setTimeout(resolve,150));return item.terminalOutput||''})()`);
  assert.ok(terminalState.includes("42"),"pwsh variables must persist across commands");
  assert.ok(terminalState.includes("Workstation-Visual-Console"),"pwsh must start in the selected project");
  await evaluate(`document.querySelector('.split-pane[data-window-id="4"] [data-action="terminal-stop"]').click()`);
  const embedShot=await send("Page.captureScreenshot",{format:"png"});
  fs.writeFileSync(path.join(__dirname,"../../08_evidence/embedded-tools-preview.png"),Buffer.from(embedShot.data,"base64"));
  await send("Emulation.setDeviceMetricsOverride",{width:800,height:700,deviceScaleFactor:1,mobile:false});
  const narrow=await evaluate(`(async()=>{await new Promise(resolve=>setTimeout(resolve,120));return {panes:document.querySelectorAll('.split-pane').length,dividers:document.querySelectorAll('.split-divider').length,canvas:document.querySelector('.split-canvas').getBoundingClientRect().width}})()`);
  assert.equal(narrow.panes,4);
  assert.equal(narrow.dividers,3);
  assert.ok(narrow.canvas>0);
  await send("Emulation.setDeviceMetricsOverride",{width:600,height:700,deviceScaleFactor:1,mobile:false});
  const mobile=await evaluate(`(async()=>{await new Promise(resolve=>setTimeout(resolve,120));const toggle=document.querySelector('.mobile-project-toggle');const visible=getComputedStyle(toggle).display!=='none';toggle.click();await new Promise(resolve=>setTimeout(resolve,0));const hidden=document.querySelector('.project-pane').getBoundingClientRect().height===0;document.querySelector('.mobile-project-toggle').click();await new Promise(resolve=>setTimeout(resolve,0));return {visible,hidden,restored:document.querySelector('.project-pane').getBoundingClientRect().height>0}})()`);
  assert.deepEqual(mobile,{visible:true,hidden:true,restored:true});
  const persisted=await evaluate(`(()=>{const pane=currentWindows()[0],terminal=currentWindows()[3];pane.kind='document';pane.documentText='刷新后保留正文';pane.annotations=[{id:'a91',kind:'note',text:'保留标注',label:'',url:'',quote:'正文',start:5,end:7,fieldId:''}];terminal.kind='terminal';terminal.terminalCommand='SECRET-COMMAND';terminal.terminalOutput='SECRET-OUTPUT';const saved=snapshotState(),serialized=JSON.stringify(saved);pane.documentText='已更改';state.project='university';restoreState(saved);render();return {project:state.project,text:currentWindows()[0].documentText,annotation:currentWindows()[0].annotations[0]?.text,terminalCommand:serialized.includes('SECRET-COMMAND'),terminalOutput:serialized.includes('SECRET-OUTPUT'),panes:document.querySelectorAll('.split-pane').length}})()`);
  assert.deepEqual(persisted,{project:'console',text:'刷新后保留正文',annotation:'保留标注',terminalCommand:false,terminalOutput:false,panes:4});
  const treeGrowth=await evaluate(`(async()=>{const tick=()=>new Promise(resolve=>setTimeout(resolve,0));
    document.querySelector('[data-action="open-create"][data-kind="category"]').click();await tick();
    document.querySelector('.tree-create [name="name"]').value='科研写作';document.querySelector('.tree-create').requestSubmit();
    const category=categories.find(item=>item.name==='科研写作');
    document.querySelector('[data-action="open-create"][data-kind="assign"][data-category="'+category.id+'"]').click();await tick();
    document.querySelector('.tree-create [name="project"]').value='challenge';document.querySelector('.tree-create').requestSubmit();
    document.querySelector('[data-action="open-create"][data-kind="child"][data-project="challenge"]').click();await tick();
    const recommended=document.querySelector('.tree-create [name="layout"]').value;
    document.querySelector('.tree-create [name="name"]').value='独立进度 A';document.querySelector('.tree-create').requestSubmit();
    const first=selectedChild(),firstId=first.id,firstBoard=boardKey();currentWindows()[0].kind='document';currentWindows()[0].documentText='A 的内容';
    document.querySelector('[data-action="show-progress"]').click();await tick();const slider=document.querySelector('[data-role="child-progress"]');slider.value='35';slider.dispatchEvent(new Event('input',{bubbles:true}));const progressed=first.progress===35&&document.querySelector('[data-progress-label]').textContent==='35%';applyLayout('quad');render();
    document.querySelector('[data-action="open-create"][data-kind="child"][data-project="challenge"]').click();await tick();
    document.querySelector('.tree-create [name="name"]').value='独立进度 B';document.querySelector('.tree-create [name="layout"]').value='single';document.querySelector('.tree-create').requestSubmit();
    const second=selectedChild(),secondId=second.id,secondBoard=boardKey(),separate=secondBoard!==firstBoard&&currentWindows()[0].documentText!=='A 的内容'&&second.progress===0;
    document.querySelector('[data-action="select-child"][data-child="'+firstId+'"]').click();await tick();
    const preserved=selectedChild().progress===35&&currentWindows()[0].documentText==='A 的内容'&&boardLayouts.get(boardKey())==='quad';
    const saved=snapshotState();categories.splice(categories.findIndex(item=>item.id===category.id),1);projects.find(item=>item.id==='challenge').children.pop();restoreState(saved);render();
    return {category:categories.some(item=>item.id===category.id),assigned:categories.find(item=>item.id===category.id)?.projects.includes('challenge'),recommended,progressed,separate,preserved,restoredChildren:projects.find(item=>item.id==='challenge').children.some(item=>item.id===secondId),restoredProgress:selectedChild().progress,restoredLayout:boardLayouts.get(boardKey())};})()`);
  assert.deepEqual(treeGrowth,{category:true,assigned:true,recommended:'side-stack',progressed:true,separate:true,preserved:true,restoredChildren:true,restoredProgress:35,restoredLayout:'quad'});
  await send("Emulation.setDeviceMetricsOverride",{width:1400,height:900,deviceScaleFactor:1,mobile:false});
  await evaluate(`document.querySelector('.pane-body').scrollTop=document.querySelector('.pane-body').scrollHeight`);
  await new Promise(resolve=>setTimeout(resolve,120));
  const treeShot=await send("Page.captureScreenshot",{format:"png"});
  fs.writeFileSync(path.join(__dirname,"../../08_evidence/project-tree-growth.png"),Buffer.from(treeShot.data,"base64"));
  const projectCreated=await evaluate(`(async()=>{const tick=()=>new Promise(resolve=>setTimeout(resolve,0));const original=embeddedApi;let request=null;
    embeddedApi=async(path,payload)=>{if(path==='/api/v4/project-create'){request={path,...payload};return {name:payload.name,status:'created'}}return original(path,payload)};
    try{const category=categories.find(item=>item.name==='科研写作');document.querySelector('[data-action="open-create"][data-kind="project"][data-category="'+category.id+'"]').click();await tick();
      document.querySelector('.tree-create [name="name"]').value='新建科研项目';document.querySelector('.tree-create [name="folder"]').value='Research2026';document.querySelector('.tree-create [name="description"]').value='验证真实新建入口';document.querySelector('.tree-create').requestSubmit();
      for(let i=0;i<30&&state.create;i++)await new Promise(resolve=>setTimeout(resolve,10));
      const created=selectedProject(),layout=boardLayouts.get(boardKey()),inCategory=category.projects.includes(created.id),snapshot=snapshotState();
      projects.splice(projects.findIndex(item=>item.id===created.id),1);category.projects=category.projects.filter(id=>id!==created.id);restoreState(snapshot);render();
      return {request,folder:created.folder,name:created.name,layout,inCategory,restored:projects.some(item=>item.id===created.id&&item.folder==='Research2026')};
    }finally{embeddedApi=original}})()`);
  assert.deepEqual(projectCreated,{request:{path:'/api/v4/project-create',name:'Research2026',description:'验证真实新建入口'},folder:'Research2026',name:'新建科研项目',layout:'halves',inCategory:true,restored:true});
  const createdShot=await send("Page.captureScreenshot",{format:"png"});
  fs.writeFileSync(path.join(__dirname,"../../08_evidence/project-created-preview.png"),Buffer.from(createdShot.data,"base64"));
  const consoleProjectOpen=await evaluate(`(async()=>{document.querySelector('.icon-rail [data-action="open-console"]').click();await new Promise(resolve=>setTimeout(resolve,0));const shown=document.querySelector('.control-project [data-project="console"]').closest('.control-project').querySelector('small').textContent;document.querySelector('.control-project-name[data-project="university"]').click();await new Promise(resolve=>setTimeout(resolve,0));return {view:state.view,project:state.project,canvas:!!document.querySelector('.split-canvas'),shown}})()`);
  assert.match(consoleProjectOpen.shown,/[1-9]/);
  assert.deepEqual({view:consoleProjectOpen.view,project:consoleProjectOpen.project,canvas:consoleProjectOpen.canvas},{view:"project",project:"university",canvas:true});
  const usageRoundTrip=await evaluate(`(()=>{const saved=snapshotState(),before=saved.usage.find(row=>row[0]==='console')?.[1];projectUsage.clear();restoreState(saved);return {before,after:Math.floor(projectUsage.get('console')||0)}})()`);
  assert.ok(usageRoundTrip.before>=2);
  assert.equal(usageRoundTrip.after,usageRoundTrip.before);
  console.log("Workbench browser smoke OK: global control center, one primary content, annotations, embedded tools, dividers and sidebar");
  socket.close();
}

main().catch(error => {console.error(error); process.exitCode = 1}).finally(async () => {
  try {await fetch(`http://127.0.0.1:${port}/json/close`, {method: "POST"})} catch {}
  browser.kill();
  if (path.resolve(profile).startsWith(path.resolve(os.tmpdir()) + path.sep) &&
      path.basename(profile).startsWith("workstation-desktop-smoke-")) {
    try {fs.rmSync(profile, {recursive: true, force: true})} catch {}
  }
});
