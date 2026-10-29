const fs=require('node:fs'),os=require('node:os'),path=require('node:path'),cp=require('node:child_process'),assert=require('node:assert/strict');
const {chromium}=require(process.env.MATT_PLAYWRIGHT||'C:/Users/ok/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const python=process.env.MATT_PYTHON||'C:/Users/ok/Desktop/workstation/Runtime/Python/python.exe';
const script=path.resolve(__dirname,'../scripts/matt.py'),root=fs.mkdtempSync(path.join(os.tmpdir(),'matt-browser-'));
const output=process.env.MATT_TEST_OUTPUT||root,checks=[];let server,browser;
fs.mkdirSync(output,{recursive:true});fs.writeFileSync(path.join(root,'AGENTS.md'),'Test station');fs.mkdirSync(path.join(root,'Projects/Sandbox'),{recursive:true});fs.writeFileSync(path.join(root,'proof.md'),'# 实际验收证据');
function cli(...args){const r=cp.spawnSync(python,['-X','utf8','-B',script,'--root',root,...args],{encoding:'utf8'});assert.equal(r.status,0,r.stderr);return JSON.parse(r.stdout);}
function check(name,condition){assert.ok(condition,name);checks.push({name,pass:true});}
(async()=>{
  server=cp.spawn(python,['-X','utf8','-B','-u',script,'--root',root,'serve','--port','0'],{windowsHide:true});
  const url=await new Promise((resolve,reject)=>{let buffer='';server.stdout.on('data',data=>{buffer+=data;const line=buffer.split('\n')[0];try{resolve(JSON.parse(line).url);}catch{}});server.once('error',reject);server.once('exit',code=>reject(new Error('server exit '+code)));setTimeout(()=>reject(new Error('startup timed out')),8000).unref();});
  browser=await chromium.launch({executablePath:process.env.MATT_BROWSER||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const page=await browser.newPage({viewport:{width:1440,height:960}}),errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto(url);await page.getByText('让过程有迹可循').waitFor();check('空记录有明确入口说明',true);
  cli('begin','--task','first','--project','Sandbox','--title','教育模块 · 插件流程','--stages','spec,implement,verify,review');
  cli('begin','--task','second','--project','Sandbox','--title','另一个项目任务','--stages','implement,review');
  await page.getByRole('button',{name:/教育模块 · 插件流程/}).waitFor({timeout:6000});await page.getByRole('button',{name:/教育模块 · 插件流程/}).click();
  check('新任务通过轮询出现',await page.locator('.task').count()===2);
  cli('update','--task','first','--stage','spec','--status','completed','--revision','1','--note','规格已确认 <img src=x onerror=alert(1)>','--evidence','proof.md');
  await page.getByRole('button',{name:/规格 已完成/}).waitFor({timeout:6000});await page.getByRole('button',{name:/规格 已完成/}).click();
  check('实际阶段和证据同步显示',await page.locator('.evidence').count()===1);
  check('说明作为文本渲染',await page.locator('.detail img').count()===0&&await page.locator('.detail-note').textContent()==='规格已确认 <img src=x onerror=alert(1)>');
  const evidence=await page.request.get(new URL(await page.locator('.evidence').getAttribute('href'),url).href);check('证据可打开且为纯文本',evidence.headers()['content-type'].includes('text/plain')&&(await evidence.text()).includes('实际验收'));
  await page.getByRole('button',{name:/规格 已完成/}).focus();
  cli('update','--task','first','--stage','implement','--status','running','--revision','2','--note','正在接入');
  await page.waitForTimeout(3400);check('轮询保留所选任务与阶段',await page.locator('.task.active').textContent().then(t=>t.includes('教育模块'))&&await page.locator('.detail h3').textContent()==='规格');
  check('实时重绘保留键盘焦点',await page.evaluate(()=>document.activeElement.dataset.stage==='spec'));
  await page.locator('#search').fill('另一个');check('搜索筛选任务',await page.locator('.task').count()===1);await page.locator('#search').fill('');
  await page.locator('#filter').selectOption('completed');check('状态过滤与无匹配反馈',await page.locator('.task').count()===0&&await page.getByText('没有符合条件的任务').isVisible());await page.locator('#filter').selectOption('all');
  await page.getByRole('button',{name:/教育模块 · 插件流程/}).click();await page.getByRole('button',{name:/规格 已完成/}).click();await page.reload();await page.locator('.detail').waitFor();check('刷新恢复选择',await page.locator('.detail h3').textContent()==='规格');
  await page.route('**/api/workflows',route=>route.abort());await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByText(/连接中断/).waitFor();check('断线保留最近任务',await page.locator('.task').count()===2);await page.unroute('**/api/workflows');await page.getByRole('button',{name:'刷新',exact:true}).click();await page.getByText(/已连接本地记录/).waitFor();check('可恢复连接',true);
  await page.screenshot({path:path.join(output,'dashboard-desktop.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});check('390px没有整页横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
  await page.getByRole('button',{name:/规格 已完成/}).focus();await page.keyboard.press('ArrowRight');await page.keyboard.press('Tab');check('键盘可聚焦阶段',await page.evaluate(()=>document.activeElement.matches('button.stage')));
  await page.screenshot({path:path.join(output,'dashboard-mobile.png'),fullPage:true});check('页面脚本错误为0',errors.length===0);
  fs.writeFileSync(path.join(output,'browser-validation.json'),JSON.stringify({passed:true,checks,errors,isolated:true},null,2));
  console.log(JSON.stringify({passed:true,checks:checks.length,output}));
})().catch(error=>{console.error(error);process.exitCode=1;}).finally(async()=>{await browser?.close();server?.kill();setTimeout(()=>fs.rmSync(root,{recursive:true,force:true}),700).unref();});
