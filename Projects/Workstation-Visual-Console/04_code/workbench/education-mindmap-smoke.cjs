const {chromium}=require('C:/Users/ok/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path');
const base=process.env.EDUCATION_BASE||'http://127.0.0.1:8765';
const output=process.env.EDUCATION_OUTPUT||__dirname;
const {installStage}=require('./education-release-test.cjs');
async function main(){
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const checks=[],errors=[];const check=(name,pass)=>checks.push({name,pass:!!pass});
 try{
  const context=await browser.newContext({viewport:{width:1600,height:1000}});await installStage(context);
  const page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));page.setDefaultTimeout(6000);
  await page.goto(base+'/workbench?smoke=1&education=machine-design');
  await page.waitForSelector('.mm-module').catch(()=>{});
  check('正式教育入口使用深色分层思维导图',await page.locator('.mm-module').count()===17&&await page.locator('.mm-top input[type=search]').count()===1&&await page.locator('.edu-toolbar').count()===0);
  if(!process.argv.includes('--red')){
   const catalog=await (await fetch(base+'/api/education/network')).json(),graphs=new Map(),progress=new Map();
   for(const c of catalog.courses){graphs.set(c.id,await(await fetch(base+'/api/education/network?course='+c.id)).json());progress.set(c.id,await(await fetch(base+'/api/education/progress?course='+c.id)).json())}
   let conflict=false,progressFail=false,openFail=false,posted,openPayload,tokenValid=false;
   await context.route('**/api/education/progress?*',route=>{const id=new URL(route.request().url()).searchParams.get('course');return route.fulfill({status:progressFail?503:200,contentType:'application/json',body:JSON.stringify(progressFail?{error:'测试读取失败'}:progress.get(id))})});
   await context.route('**/api/education/learning-status',async route=>{
    const data=route.request().postDataJSON();posted=data;tokenValid=!!route.request().headers()['x-workstation-token']&&!route.request().headers()['x-mindmap-token'];
    const response=progress.get(data.course),entry=response.nodes.find(n=>n.id===data.node_id);
    if(conflict){entry.status='review_due';entry.revision='fixture-newer';return route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'笔记已在另一处修改，请先同步状态再重试'})})}
    entry.status=data.status;entry.revision='fixture-saved';await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(response)});
   });
   await context.route('**/api/education/open-note',route=>{openPayload=route.request().postDataJSON();return route.fulfill({status:openFail?503:200,contentType:'application/json',body:JSON.stringify(openFail?{error:'测试：无法启动 Obsidian'}:{requested:true,node_id:openPayload.node_id})})});
   await page.reload();await page.waitForSelector('.mm[data-obsidian=connected]');
   const search=async(id,text)=>{await page.locator('[data-mm-input=search]').fill(text);await page.locator(`.mm-results [data-id="${id}"]`).click()};
   const matrix=()=>page.locator('.mm-world').evaluate(e=>e.style.transform);
   await search('MD-C-strength','强度');await page.waitForSelector('.mm-open-obsidian:not([disabled])');
   check('正文和掌握证据来自现有图谱及正式状态接口',await page.locator('.mm-body').innerText()===graphs.get('machine-design').nodes.find(n=>n.id==='MD-C-strength').body&&(await page.locator('.mm-evidence').innerText()).includes(progress.get('machine-design').nodes.find(n=>n.id==='MD-C-strength').mastery_label));
   check('正式版不含Demo临时标记提示',!(await page.locator('.mm').innerText()).includes('Demo'));
   const view=await matrix();await page.locator('[data-mm=close]').click();await page.locator('.mm-knowledge[data-id="MD-C-strength"][data-module="module-MD01"]').click();
   check('开关知识详情不改变视角',view===await matrix());
   const entry=progress.get('machine-design').nodes.find(n=>n.id==='MD-C-strength'),wanted=entry.status==='learned'?'in_progress':'learned',mastery=await page.locator('.mm-evidence').innerText();
   await page.locator('.mm-status-row select').selectOption(wanted);await page.waitForFunction(value=>document.querySelector('.mm-learning-message')?.textContent==='已同步到 Obsidian'&&document.querySelector('.mm-status-row select').value===value,wanted);
   check('学习标记通过正式令牌与修订号接口提交',posted.course==='machine-design'&&posted.node_id==='MD-C-strength'&&posted.status===wanted&&typeof posted.revision==='string'&&tokenValid);
   check('标记成功更新节点但不升级掌握证据或重置视角',await page.locator('.mm-knowledge[data-id="MD-C-strength"]').first().getAttribute('data-state')===wanted&&mastery===await page.locator('.mm-evidence').innerText()&&view===await matrix());
   conflict=true;await page.locator('.mm-status-row select').selectOption('not_started');await page.waitForFunction(()=>document.querySelector('.mm-status-row select')?.value==='review_due'&&!document.querySelector('.mm-status-row select').disabled);
   check('修订冲突显示错误并读取另一处最新状态',(await page.locator('.mm-learning-message').innerText()).includes('另一处修改')&&await page.locator('.mm-learning-message').getAttribute('data-error')==='true'&&await page.locator('.mm-knowledge[data-id="MD-C-strength"]').first().getAttribute('data-state')==='review_due');conflict=false;
   entry.status='learned';entry.revision='fixture-obsidian';await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.waitForFunction(()=>document.querySelector('.mm-status-row select')?.value==='learned');
   check('回到窗口读取Obsidian侧变化并保留视角',await page.locator('.mm-done').count()>0&&view===await matrix());
   progressFail=true;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.waitForSelector('.mm-sync-retry:not([hidden])');
   check('状态读取失败时禁止写入且保留可浏览图谱',await page.locator('.mm-status-row select').isDisabled()&&await page.locator('.mm-module').count()===17);
   progressFail=false;await page.locator('.mm-sync-retry').click();await page.waitForSelector('.mm-status-row select:not([disabled])');
   check('状态读取失败支持重试恢复',await page.locator('.mm-sync-retry').isHidden());
   entry.linked=false;entry.error='测试：笔记未绑定';await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.waitForSelector('.mm-open-obsidian:disabled');
   check('未绑定笔记禁用标记和打开按钮',await page.locator('.mm-status-row select').isDisabled());entry.linked=true;entry.error=null;await page.evaluate(()=>window.dispatchEvent(new Event('focus')));await page.waitForSelector('.mm-open-obsidian:not([disabled])');
   await page.locator('.mm-open-obsidian').click();await page.waitForFunction(()=>document.querySelector('.mm-open-message')?.textContent==='已请求在 Obsidian 打开');
   check('Obsidian按钮提交正确课程与知识点',openPayload.course==='machine-design'&&openPayload.node_id==='MD-C-strength'&&view===await matrix());
   openFail=true;await page.locator('.mm-open-obsidian').click();await page.waitForFunction(()=>document.querySelector('.mm-open-message')?.dataset.error==='true');
   check('打开笔记失败可重试且不关闭详情',await page.locator('.mm-open-obsidian').isEnabled()&&await page.locator('.mm-detail').isVisible());openFail=false;
   await page.locator('[data-mm=zoom-in]').click();const saved=await matrix();await page.reload();await page.waitForSelector('.mm[data-obsidian=connected]');
   check('刷新恢复当前知识点、展开和视角',saved===await matrix()&&await page.locator('.mm-detail').getAttribute('data-node')==='MD-C-strength');
   for(const c of catalog.courses){await page.evaluate(id=>openEducation(id),c.id);await page.waitForFunction(name=>document.querySelector('.mm-root')?.textContent===name,c.name);const expected=Math.max(1,graphs.get(c.id).nodes.filter(n=>n.kind==='module').length);check('实时读取课程：'+c.id,await page.locator('.mm-module').count()===expected)}
   await page.locator('.mm-module').first().click();await page.waitForSelector('.mm-detail');check('只有章节的课程仍可查看内容并打开绑定笔记',await page.locator('.mm-body').innerText()===graphs.get('math-competition').nodes[0].body);
   await page.evaluate(()=>openEducation('machine-design'));await page.waitForSelector('.mm[data-obsidian=connected]');check('课程往返保留独立视角',saved===await matrix());
   await page.locator('[data-mm=workspace]').click();check('既有课程工作区仍可进入',await page.locator('.split-canvas').count()===1&&await page.locator('.mm').count()===0);
   await page.locator('[data-action=open-education]').click();await page.waitForSelector('.mm-module');
   await page.screenshot({path:path.join(output,'mindmap-desktop.png'),fullPage:true});
   await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'mindmap-mobile.png'),fullPage:true});
   check('窄屏无页面横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
   await page.setViewportSize({width:1600,height:1000});await page.locator('.rail-button[data-action=open-console]').click();check('教育样式不影响中控台和状态栏',await page.locator('.control-center').count()===1&&await page.locator('.demo-statusbar').isVisible()&&await page.locator('body').getAttribute('data-education-map')==='false');
   const recovery=await browser.newContext({viewport:{width:1280,height:800}});await installStage(recovery);const failed=await recovery.newPage();failed.setDefaultTimeout(6000);
   await recovery.route('**/api/education/network?course=control-engineering',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'测试图谱不可读'})}));await failed.goto(base+'/workbench?smoke=1&education=control-engineering');await failed.waitForSelector('[data-mm=retry]');
   await recovery.unroute('**/api/education/network?course=control-engineering');await failed.locator('[data-mm=retry]').click();await failed.waitForSelector('.mm-root');check('图谱加载失败可以重试',await failed.locator('.mm-root').innerText()===graphs.get('control-engineering').name);await recovery.close();
   const race=await browser.newContext({viewport:{width:1280,height:800}});await installStage(race);const raced=await race.newPage();let releaseGraph;const ready=new Promise(resolve=>releaseGraph=resolve);let intercepted;const interceptedPromise=new Promise(resolve=>intercepted=resolve);
   await race.route('**/api/education/network?course=control-engineering',async route=>{intercepted();await ready;await route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(graphs.get('control-engineering'))}).catch(()=>{})});
   await raced.goto(base+'/workbench?smoke=1&education=control-engineering');await interceptedPromise;await raced.evaluate(()=>openEducation('fluid-power'));await raced.waitForSelector('.mm-root');releaseGraph();await raced.waitForTimeout(80);
   check('过期课程请求不会覆盖新课程',await raced.locator('.mm-root').innerText()===graphs.get('fluid-power').name);await race.close();
  }
  check('无页面脚本错误',errors.length===0);
  const report={checks,passed:checks.every(c=>c.pass),pageErrors:errors,staged:!!process.env.EDUCATION_STAGED};fs.writeFileSync(path.join(output,process.argv.includes('--red')?'mindmap-before.json':'mindmap-validation.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
 }catch(error){console.log(JSON.stringify({checks,pageErrors:errors},null,2));throw error}finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
