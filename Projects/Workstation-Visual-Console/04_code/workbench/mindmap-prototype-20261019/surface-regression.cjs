// Runs against the real read-only demo; never writes learning records.
const {chromium}=require('C:/Users/ok/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path');
const url='http://127.0.0.1:8774/workbench?variant=A&education=machine-design&revision=dark';
const near=(a,b)=>Math.abs(a-b)<1;
async function view(page){return page.locator('.mm-world').evaluate(e=>{const m=new DOMMatrix(getComputedStyle(e).transform);return {scale:m.a,x:m.e,y:m.f}})}
async function main(){
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const checks=[],errors=[];
 const check=(name,pass,evidence)=>checks.push({name,pass,evidence});
 try{
  const page=await browser.newPage({viewport:{width:1600,height:1000}});page.on('pageerror',e=>errors.push(e.message));
  await page.goto(url);await page.waitForSelector('.mm-module');
  await page.locator('[data-mm="zoom-in"]').click();
  const module=page.locator('.mm-module[data-id="module-MD02"]');
  const before=await view(page),anchor=await module.boundingBox();await module.click();
  const after=await view(page),next=await module.boundingBox();
  check('展开/收起保留缩放与被点击章节的位置',near(before.scale,after.scale)&&near(anchor.x,next.x)&&near(anchor.y,next.y),{before,after,anchor,next});
  await module.click();
  const leaf=page.locator('.mm-knowledge[data-id="MD-C-static"][data-module="module-MD02"]');
  const beforeOpen=await view(page);await leaf.click();const afterOpen=await view(page);
  check('打开知识内容保留视角',near(beforeOpen.scale,afterOpen.scale)&&near(beforeOpen.x,afterOpen.x)&&near(beforeOpen.y,afterOpen.y),{before:beforeOpen,after:afterOpen});
  check('内容正常显示',await page.locator('.mm-detail h2').isVisible());
  const opened=await view(page);await page.locator('[data-mm="close"]').click();
  check('关闭内容保留视角',JSON.stringify(opened)===JSON.stringify(await view(page)));
  const input=page.locator('[data-mm-input="search"]');await input.fill('强度');await page.locator('.mm-results [data-id="MD-C-strength"]').click();
  check('搜索仍可主动定位并打开结果',await page.locator('.mm-detail h2').isVisible()&&await page.locator('.mm-location').innerText().then(t=>t.includes('强度')));
  const status=page.locator('.mm-status-row select'),statusView=await view(page);
  await page.locator('.mm-detail').evaluate(e=>{e.scrollTop=e.scrollHeight});const scroll=await page.locator('.mm-detail').evaluate(e=>e.scrollTop);
  await status.selectOption('learned');
  check('更改Demo标记保留视角和内容滚动',JSON.stringify(statusView)===JSON.stringify(await view(page))&&scroll===await page.locator('.mm-detail').evaluate(e=>e.scrollTop));
  await page.locator('[data-mm="close"]').click();
  await page.evaluate(()=>{const host=document.querySelector('.mm');window.EducationNetwork.mount(host,'thermal');window.EducationNetwork.mount(host,'machine-design')});
  check('切换课程返回保留原视角与展开',JSON.stringify(statusView)===JSON.stringify(await view(page))&&await page.locator('.mm-module[aria-expanded=true]').count()>0);
  const beforeResize=await view(page),oldCanvas=await page.locator('.mm-canvas').boundingBox();
  await page.setViewportSize({width:1420,height:900});await page.waitForTimeout(80);
  const afterResize=await view(page),newCanvas=await page.locator('.mm-canvas').boundingBox();
  check('尺寸变化保留缩放与画布中心',near(beforeResize.scale,afterResize.scale)&&near(afterResize.x-beforeResize.x,(newCanvas.width-oldCanvas.width)/2)&&near(afterResize.y-beforeResize.y,(newCanvas.height-oldCanvas.height)/2),{beforeResize,afterResize});
  await page.screenshot({path:path.join(__dirname,'surface-desktop.png'),fullPage:true});
  // Real Chromium touch input, using a desktop (Surface-style) viewport.
  const touchContext=await browser.newContext({hasTouch:true,isMobile:false,viewport:{width:1280,height:800},deviceScaleFactor:1.5});
  const touch=await touchContext.newPage();touch.on('pageerror',e=>errors.push(e.message));
  await touch.goto(url);await touch.waitForSelector('.mm-module');
  const cdp=await touchContext.newCDPSession(touch);
  const send=async(type,points)=>{await cdp.send('Input.dispatchTouchEvent',{type,touchPoints:points.map(p=>({...p,radiusX:3,radiusY:3,force:1}))});await touch.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))))};
  const mid=async locator=>{const b=await locator.boundingBox();return {x:b.x+b.width/2,y:b.y+b.height/2}};
  const chapter=touch.locator('.mm-module[data-id="module-MD02"]');
  await touch.screenshot({path:path.join(__dirname,'surface-touch-initial.png'),fullPage:true});
  let p=await mid(chapter),v0=await view(touch),expanded=await chapter.getAttribute('aria-expanded');
  await send('touchStart',[{id:1,...p}]);await send('touchMove',[{id:1,x:p.x+65,y:p.y+45}]);await send('touchEnd',[]);
  let v1=await view(touch);
  check('单指从章节节点拖动且松手不误展开',near(v1.x-v0.x,65)&&near(v1.y-v0.y,45)&&expanded===await chapter.getAttribute('aria-expanded'),{before:v0,after:v1});
  p=await mid(touch.locator('.mm-root'));
  const a={id:1,x:p.x-45,y:p.y},b={id:2,x:p.x+45,y:p.y};v0=await view(touch);
  await send('touchStart',[a]);await send('touchStart',[a,b]);
  const aa={id:1,x:a.x-15+20,y:a.y+15},bb={id:2,x:b.x+15+20,y:b.y+15};
  await send('touchMove',[aa,bb]);v1=await view(touch);
  const box=await touch.locator('.mm-canvas').boundingBox(),ratio=120/90;
  check('双指同时平移和缩放并跟随手指中心',near(v1.scale,v0.scale*ratio)&&near(v1.x,p.x+20-box.x-(p.x-box.x-v0.x)*ratio)&&near(v1.y,p.y+15-box.y-(p.y-box.y-v0.y)*ratio),{before:v0,after:v1});
  // CDP touchEnd with a point ends that contact; the other contact remains active.
  await send('touchEnd',[bb]);await send('touchMove',[{id:1,x:aa.x+35,y:aa.y+25}]);const single=await view(touch);await send('touchEnd',[]);
  check('双指松开一指后可继续拖动',near(single.x-v1.x,35)&&near(single.y-v1.y,25)&&expanded===await chapter.getAttribute('aria-expanded'),{before:v1,after:single});
  // Fit is now an explicit operation; a node tap itself never fits the map.
  await touch.locator('[data-mm="fit"]').tap();p=await mid(chapter);
  const chapterBefore=await chapter.boundingBox(),tapScale=(await view(touch)).scale;
  await touch.touchscreen.tap(p.x,p.y);const chapterAfter=await chapter.boundingBox();
  check('触控点按只切换一次且章节原位保留',expanded!==await chapter.getAttribute('aria-expanded')&&near(chapterBefore.x,chapterAfter.x)&&near(chapterBefore.y,chapterAfter.y)&&near(tapScale,(await view(touch)).scale));
  // Cancelled input must not leave a stuck drag or become a tap.
  p=await mid(chapter);const cancelExpanded=await chapter.getAttribute('aria-expanded');
  await send('touchStart',[{id:1,...p}]);await send('touchCancel',[]);
  await touch.touchscreen.tap(p.x,p.y);
  check('系统取消触控后下一次点按正常',cancelExpanded!==await chapter.getAttribute('aria-expanded'));
  // Pen input uses the same pointer path. Mouse/pen compatibility events are real CDP input.
  p=await mid(touch.locator('.mm-root'));v0=await view(touch);
  await cdp.send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,pointerType:'pen',x:p.x,y:p.y});
  await cdp.send('Input.dispatchMouseEvent',{type:'mouseMoved',buttons:1,pointerType:'pen',x:p.x+40,y:p.y+30});
  await cdp.send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,pointerType:'pen',x:p.x+40,y:p.y+30});v1=await view(touch);
  check('触控笔拖动画布',near(v1.x-v0.x,40)&&near(v1.y-v0.y,30),{before:v0,after:v1});
  const blank=await touch.locator('.mm-canvas').boundingBox();p={x:blank.x+12,y:blank.y+12};v0=await view(touch);expanded=await chapter.getAttribute('aria-expanded');
  await cdp.send('Input.dispatchMouseEvent',{type:'mousePressed',button:'left',buttons:1,pointerType:'pen',x:p.x,y:p.y});
  const palm=await mid(chapter);await send('touchStart',[{id:1,...palm}]);await send('touchMove',[{id:1,x:palm.x+50,y:palm.y+30}]);await send('touchEnd',[]);
  await cdp.send('Input.dispatchMouseEvent',{type:'mouseReleased',button:'left',buttons:0,pointerType:'pen',x:p.x,y:p.y});
  check('笔按下时忽略同时触碰的手掌',JSON.stringify(v0)===JSON.stringify(await view(touch))&&expanded===await chapter.getAttribute('aria-expanded'));
  const canvasBox=await touch.locator('.mm-canvas').boundingBox(),wx=canvasBox.x+20,wy=canvasBox.y+30;
  await touch.evaluate(()=>document.addEventListener('wheel',e=>{window.lastWheel={x:e.deltaX,y:e.deltaY,mode:e.deltaMode}},{once:true,capture:true}));
  v0=await view(touch);await touch.mouse.move(wx,wy);await touch.mouse.wheel(12,24);await touch.waitForTimeout(60);v1=await view(touch);
  const wheel=await touch.evaluate(()=>window.lastWheel);
  check('触控板双向滚动平移',near(v1.x-v0.x,-wheel.x)&&near(v1.y-v0.y,-wheel.y)&&wheel.mode===0,{before:v0,after:v1,input:wheel});
  v0=await view(touch);await touch.keyboard.down('Control');await touch.mouse.wheel(0,-35);await touch.keyboard.up('Control');await touch.waitForTimeout(60);v1=await view(touch);
  const wheelRatio=v1.scale/v0.scale;
  check('触控板缩放跟随指针且不缩放整页',v1.scale>v0.scale&&near(v1.x,wx-canvasBox.x+(v0.x-(wx-canvasBox.x))*wheelRatio)&&await touch.evaluate(()=>visualViewport.scale===1),{before:v0,after:v1});
  v0=await view(touch);await touch.mouse.dblclick(wx,wy);check('背景双击不会重置全图',JSON.stringify(v0)===JSON.stringify(await view(touch)));
  await touch.locator('[data-mm="fit"]').tap();
  await touch.locator('[data-mm-input="search"]').fill('强度');await touch.locator('.mm-results [data-id="MD-C-strength"]').tap();
  // Short landscape/onscreen-keyboard height gives real content a native scroll range.
  await touch.setViewportSize({width:1280,height:600});await touch.waitForTimeout(80);
  const detailView=await view(touch),panel=touch.locator('.mm-detail');
  await panel.evaluate(e=>{e.scrollTop=0});const panelBox=await panel.boundingBox();
  const sx=panelBox.x+panelBox.width/2,sy=panelBox.y+panelBox.height-65;
  await send('touchStart',[{id:1,x:sx,y:sy}]);
  for(let dy=20;dy<=160;dy+=20)await send('touchMove',[{id:1,x:sx,y:sy-dy}]);
  await send('touchEnd',[]);await touch.waitForTimeout(120);
  const panelScroll=await panel.evaluate(e=>({scroll:e.scrollTop,client:e.clientHeight,full:e.scrollHeight}));
  check('详情可原生触控滚动且不拖动底图',panelScroll.scroll>0&&JSON.stringify(detailView)===JSON.stringify(await view(touch)),{panelScroll,before:detailView,after:await view(touch)});
  await touch.locator('.mm-detail select').selectOption('in_progress');
  check('触控详情更改标记不重置滚动',panelScroll.scroll===await panel.evaluate(e=>e.scrollTop)&&JSON.stringify(detailView)===JSON.stringify(await view(touch)));
  const sizes=await touch.locator('.mm-controls button,.mm-close,[data-mm-input="search"],.mm-detail select').evaluateAll(els=>els.map(e=>({element:e.className||e.tagName,width:e.getBoundingClientRect().width,height:e.getBoundingClientRect().height})));
  check('Surface主要操作目标至少44像素',sizes.every(b=>b.height>=44&&b.width>=44),sizes);
  await touch.screenshot({path:path.join(__dirname,'surface-touch-detail.png'),fullPage:true});
  await touch.setViewportSize({width:1280,height:800});await touch.waitForTimeout(80);
  await touch.locator('[data-mm="close"]').tap();await touch.locator('[data-mm="fit"]').tap();
  await touch.screenshot({path:path.join(__dirname,'surface-touch-overview.png'),fullPage:true});
  const keyboardView=await view(touch);await touch.locator('.mm-canvas').focus();await touch.keyboard.press('ArrowRight');
  check('键盘仍可平移画布',near((await view(touch)).x-keyboardView.x,-45));
  expanded=await chapter.getAttribute('aria-expanded');p=await chapter.boundingBox();v0=await view(touch);
  await chapter.evaluate(e=>e.focus({preventScroll:true}));await touch.keyboard.press('Space');const keyBox=await chapter.boundingBox();
  check('键盘点开章节保留缩放和位置',expanded!==await chapter.getAttribute('aria-expanded')&&near(p.x,keyBox.x)&&near(p.y,keyBox.y)&&near(v0.scale,(await view(touch)).scale));
  await touch.setViewportSize({width:390,height:844});await touch.waitForTimeout(80);
  await touch.screenshot({path:path.join(__dirname,'surface-touch-narrow.png'),fullPage:true});
  check('窄屏无水平页面溢出',await touch.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  check('无页面脚本错误',errors.length===0,errors);
  const report={phase:process.argv.includes('--repro')?'before-fix':'regression',checks,passed:checks.every(c=>c.pass)};
  fs.writeFileSync(path.join(__dirname,process.argv.includes('--repro')?'surface-before.json':'surface-regression.json'),JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
 }catch(error){console.log(JSON.stringify({checks,errors},null,2));throw error}finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
