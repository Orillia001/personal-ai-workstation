// Test button behavior, then open one real bound note through the same UI path.
const {chromium}=require('C:/Users/ok/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const url='http://127.0.0.1:8774/workbench?variant=A&education=machine-design&revision=dark';
async function main(){
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 const checks=[],errors=[],requests=[];let mode='pending',release;
 const check=(name,pass)=>checks.push({name,pass:!!pass});
 try{
  const context=await browser.newContext({hasTouch:true,viewport:{width:1280,height:800}}),page=await context.newPage();page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/api/education/open-note',async route=>{
   requests.push(route.request().postDataJSON());
   if(mode==='real')return route.continue();
   if(mode==='pending')await new Promise(resolve=>{release=resolve});
   const fail=mode==='failure';await route.fulfill({status:fail?503:200,contentType:'application/json',body:JSON.stringify(fail?{message:'本机未能启动 Obsidian，请确认应用已安装后重试'}:{requested:true})});
  });
  await page.goto(url);await page.waitForSelector('.mm-module');
  const search=async id=>{await page.locator('[data-mm-input="search"]').fill(id==='MD-C-static'?'静强度':'强度');await page.locator(`.mm-results [data-id="${id}"]`).tap()};
  await search('MD-C-static');const button=page.locator('.mm-open-obsidian'),message=page.locator('.mm-open-message');
  const view=()=>page.locator('.mm-world').evaluate(e=>e.style.transform),before=await view();
  const box=await button.boundingBox();check('详情标题下提供44px的Obsidian按钮',await button.isVisible()&&box.height>=44&&await button.textContent().then(t=>t.includes('在 Obsidian 中打开')));
  await button.tap();await page.waitForFunction(()=>document.querySelector('.mm-open-obsidian').getAttribute('aria-busy')==='true');
  check('打开期间按钮禁用并防重复请求',await button.isDisabled());await button.evaluate(e=>e.click());
  mode='success';release();await message.waitFor({state:'visible'});
  check('触控点击发送当前知识点并显示打开反馈',requests.length===1&&requests[0].course==='machine-design'&&requests[0].node_id==='MD-C-static'&&await message.textContent().then(t=>t==='已请求在 Obsidian 打开'));
  check('点击Obsidian按钮不重置视角或关闭内容',before===await view()&&await page.locator('.mm-detail h2').isVisible());
  mode='failure';await button.click();await page.waitForFunction(()=>document.querySelector('.mm-open-message').dataset.error==='true');
  check('打开失败提供中文反馈并允许重试',await message.textContent().then(t=>t.includes('本机未能启动'))&&await button.isEnabled());
  mode='success';await button.focus();await page.keyboard.press('Enter');await page.waitForFunction(()=>document.querySelector('.mm-open-message').dataset.error==='false');
  check('键盘Enter可重试打开',requests.length===3&&await button.isEnabled());
  await search('MD-C-strength');await button.tap();await message.waitFor({state:'visible'});
  check('切换知识点后按钮对应新笔记',requests.at(-1).node_id==='MD-C-strength'&&requests.at(-1).course==='machine-design');
  await page.screenshot({path:path.join(__dirname,'obsidian-open-detail.png'),fullPage:true});
  await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(__dirname,'obsidian-open-narrow.png'),fullPage:true});
  check('窄屏按钮完整显示且没有页面横向溢出',await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)&&await button.boundingBox().then(b=>b.x>=0&&b.x+b.width<=390));
  await page.setViewportSize({width:1280,height:800});await search('MD-C-static');
  const snapshot=JSON.parse(fs.readFileSync(path.join(__dirname,'snapshot.json'),'utf8'));
  const uri=snapshot.courses['machine-design'].progress.nodes.find(n=>n.id==='MD-C-static').obsidian_uri;
  const notePath=new URL(uri).searchParams.get('path');const hash=()=>crypto.createHash('sha256').update(fs.readFileSync(notePath)).digest('hex'),noteBefore=hash();
  mode='real';const responsePromise=page.waitForResponse(r=>r.url().endsWith('/api/education/open-note')&&r.request().method()==='POST');await button.tap();const response=await responsePromise,result=await response.json();
  await message.waitFor({state:'visible'});
  check('通过页面按钮实际请求本机Obsidian打开静强度笔记',response.ok()&&result.requested&&result.node_id==='MD-C-static');
  check('打开前后笔记内容哈希不变',hash()===noteBefore);
  check('无页面脚本错误',errors.length===0);
  const report={run_id:'EDU-MINDMAP-OBSIDIAN-OPEN-20261019-01',checks,passed:checks.every(c=>c.pass),page_errors:errors,real_note_open_requested:true,note_sha256_before:noteBefore,note_sha256_after:hash()};
  fs.writeFileSync(path.join(__dirname,'obsidian-open-browser.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
 }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
