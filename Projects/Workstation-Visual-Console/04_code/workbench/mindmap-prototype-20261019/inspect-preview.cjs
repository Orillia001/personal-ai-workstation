// One-off preview inspection and captures; no production mutations.
const {chromium}=require('C:/Users/ok/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs');const path=require('node:path');
async function main(){
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const errors=[],actions=[];
  try{
    const page=await browser.newPage({viewport:{width:1600,height:1000}});page.on('pageerror',error=>errors.push(error.message));
    await page.goto('http://127.0.0.1:8774/workbench?variant=A&education=machine-design');
    await page.waitForSelector('.mm-node.knowledge');await page.waitForTimeout(100);
    actions.push({variant:'A',visibleNodes:await page.locator('.mm-node').count(),modules:await page.locator('.mm-module').count()});
    await page.screenshot({path:path.join(__dirname,'variant-A.png'),fullPage:true});
    await page.locator('[data-mm="variant"][data-variant="B"]').click();
    actions.push({variant:'B',sections:await page.locator('.mm-outline-section').count()});
    await page.screenshot({path:path.join(__dirname,'variant-B.png'),fullPage:true});
    await page.locator('[data-mm="variant"][data-variant="C"]').click();
    actions.push({variant:'C',knowledgeRows:await page.locator('.mm-column-card').count()});
    await page.screenshot({path:path.join(__dirname,'variant-C.png'),fullPage:true});
    await page.locator('.mm-column-card').first().click();const title=await page.locator('.mm-detail h2').textContent();
    await page.locator('.mm-status-box select').selectOption('learned');
    actions.push({detail:title,temporaryMark:await page.locator('.mm-footer').innerText()});
    await page.locator('[data-mm="variant"][data-variant="A"]').click();
    await page.locator('[data-mm-input="search"]').fill('强度');await page.locator('.mm-search-results button').filter({hasText:/^强度$/}).click();
    actions.push({searchLocated:await page.locator('.mm-detail h2').textContent()});
    await page.locator('[data-mm="close"]').click();
    await page.locator('[data-mm-input="module"]').evaluate(el=>{el.value='module-MD02';el.dispatchEvent(new Event('change',{bubbles:true}))});
    await page.setViewportSize({width:390,height:844});await page.waitForTimeout(120);
    await page.screenshot({path:path.join(__dirname,'variant-A-mobile.png'),fullPage:true});
    actions.push({mobileOverflow:await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth)});
    await page.reload();await page.waitForSelector('.mm-node.knowledge');
    actions.push({reloadNoDemoMarks:(await page.locator('.mm-footer').innerText()).includes('演示标记：0 处')});
    fs.writeFileSync(path.join(__dirname,'preview-inspection.json'),JSON.stringify({pageErrors:errors,actions,checked:true},null,2));
    console.log(JSON.stringify({pageErrors:errors,actions},null,2));
  }finally{await browser.close()}
}
main().catch(error=>{console.error(error);process.exitCode=1});
