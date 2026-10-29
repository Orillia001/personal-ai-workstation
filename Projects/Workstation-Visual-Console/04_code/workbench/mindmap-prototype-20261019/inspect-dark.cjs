// One-off UI inspection for the selected A refinement. No production writes.
const {chromium}=require('C:/Users/ok/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const fs=require('node:fs'),path=require('node:path');
async function main(){
  const browser=await chromium.launch({executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',headless:true});
  const errors=[],observations=[];
  try{
    const page=await browser.newPage({viewport:{width:1600,height:1000}});page.on('pageerror',e=>errors.push(e.message));
    await page.goto('http://127.0.0.1:8774/workbench?variant=A&education=machine-design');await page.waitForSelector('.mm-module');
    observations.push({firstLevel:await page.locator('.mm-module').count(),secondLevel:await page.locator('.mm-knowledge').count(),searches:await page.locator('.mm-top input').count(),location:await page.locator('.mm-location').innerText(),background:await page.locator('.mm').evaluate(e=>getComputedStyle(e).backgroundColor)});
    await page.screenshot({path:path.join(__dirname,'dark-overview.png'),fullPage:true});
    await page.locator('.mm-root').click();
    observations.push({collapsedModules:await page.locator('.mm-module').count(),collapsedKnowledge:await page.locator('.mm-knowledge').count()});
    await page.screenshot({path:path.join(__dirname,'dark-all-modules.png'),fullPage:true});
    await page.locator('.mm-module[data-id="module-MD02"]').click();
    observations.push({expanded:await page.locator('.mm-knowledge').count(),path:await page.locator('.mm-location').innerText()});
    await page.locator('.mm-knowledge[data-id="MD-C-static"][data-module="module-MD02"]').click();
    observations.push({knowledgePath:await page.locator('.mm-location').innerText(),detail:await page.locator('.mm-detail h2').textContent()});
    await page.screenshot({path:path.join(__dirname,'dark-detail.png'),fullPage:true});
    await page.locator('.mm-status-row select').selectOption('learned');
    observations.push({temporaryStatus:await page.locator('.mm-knowledge[data-id="MD-C-static"]').getAttribute('data-state')});
    await page.locator('[data-mm="close"]').click();
    await page.locator('[data-mm-input="search"]').fill('强度');await page.locator('.mm-results [data-id="MD-C-strength"]').click();
    observations.push({searched:await page.locator('.mm-detail h2').textContent(),path:await page.locator('.mm-location').innerText()});
    await page.locator('[data-mm="close"]').click();await page.locator('[data-mm="fit"]').click();await page.locator('.mm-root').click();
    await page.setViewportSize({width:1100,height:820});await page.waitForTimeout(100);await page.screenshot({path:path.join(__dirname,'dark-compact.png'),fullPage:true});
    await page.setViewportSize({width:390,height:844});await page.waitForTimeout(100);await page.screenshot({path:path.join(__dirname,'dark-mobile.png'),fullPage:true});
    observations.push({mobileOverflow:await page.evaluate(()=>document.documentElement.scrollWidth-innerWidth),mobileModules:await page.locator('.mm-module').count()});
    await page.reload();await page.waitForSelector('.mm-module');observations.push({afterReloadPath:await page.locator('.mm-location').innerText()});
    const receipt={pageErrors:errors,observations,inspected:true};fs.writeFileSync(path.join(__dirname,'dark-inspection.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt,null,2));
  }finally{await browser.close()}
}
main().catch(e=>{console.error(e);process.exitCode=1});
