const {chromium}=require('C:/Users/ok/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path');
const {installStage}=require('./education-release-test.cjs');
const base=process.env.EDUCATION_BASE||'http://127.0.0.1:8765',output=process.env.EDUCATION_OUTPUT||__dirname;
async function main(){
 const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1280,height:800}});await installStage(context);const page=await context.newPage();
  await context.route('**/api/education/open-note',async route=>{await new Promise(resolve=>setTimeout(resolve,11000));await route.fulfill({status:200,contentType:'application/json',body:'{"requested":true}'}).catch(()=>{})});
  await page.goto(base+'/workbench?smoke=1&education=machine-design');await page.waitForSelector('.mm[data-obsidian=connected]');
  await page.locator('[data-mm-input=search]').fill('静强度');await page.locator('.mm-results [data-id="MD-C-static"]').click();
  const view=await page.locator('.mm-world').evaluate(e=>e.style.transform),started=Date.now();
  await page.locator('.mm-open-obsidian').click();await page.waitForFunction(()=>!document.querySelector('.mm-open-obsidian')?.hasAttribute('aria-busy'),{},{timeout:12000});
  const result=await page.locator('.mm-open-message').evaluate(e=>({message:e.textContent,visible:!e.hidden,error:e.dataset.error}));
  const checks=[{name:'打开请求真实10秒超时后有中文错误提示',pass:result.visible&&result.message.includes('超时')&&result.error==='true'},
   {name:'超时后保留视角并允许重试',pass:await page.locator('.mm-open-obsidian').isEnabled()&&view===await page.locator('.mm-world').evaluate(e=>e.style.transform)}];
  let release;await context.route('**/api/education/open-note',async route=>{await new Promise(resolve=>{release=resolve});await route.fulfill({status:200,contentType:'application/json',body:'{"requested":true}'}).catch(()=>{})});
  await page.locator('.mm-open-obsidian').click();await page.evaluate(()=>openEducation('thermal-engineering'));await page.waitForFunction(()=>document.querySelector('.mm-root')?.textContent==='热工基础');release();await page.waitForTimeout(80);
  checks.push({name:'切换课程取消打开请求不会向新页面显示错误',pass:await page.locator('.mm-open-message:visible').count()===0&&!(await page.locator('.mm').innerText()).includes('超时')});
  const report={checks,passed:checks.every(c=>c.pass),elapsed_ms:Date.now()-started,result};
  fs.writeFileSync(path.join(output,process.argv.includes('--red')?'timeout-before.json':'timeout-validation.json'),JSON.stringify(report,null,2));console.log(JSON.stringify(report,null,2));if(!report.passed)process.exitCode=1;
 }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
