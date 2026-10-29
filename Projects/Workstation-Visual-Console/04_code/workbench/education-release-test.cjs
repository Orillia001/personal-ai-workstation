// Serve staged files through the actual workstation origin without changing production.
const fs=require('node:fs'),path=require('node:path');
async function installStage(context,stage=process.env.EDUCATION_STAGED){
 if(!stage)return;
 await context.route('**/workbench/education-network.*',async route=>{
  const name=path.basename(new URL(route.request().url()).pathname);
  await route.fulfill({status:200,contentType:name.endsWith('.js')?'application/javascript':'text/css',body:fs.readFileSync(path.join(stage,name))});
 });
 await context.route(url=>url.pathname==='/workbench',async route=>{
  const response=await route.fetch(),served=await response.text();
  const declaration=served.match(/const WORKBENCH_TOKEN="[^"\r\n]+";/)?.[0];if(!declaration)throw Error('Missing workstation token declaration');
  const body=fs.readFileSync(path.join(stage,'layout-prototype.html'),'utf8').replace('const WORKBENCH_TOKEN="__TOKEN__";',declaration);
  await route.fulfill({response,body});
 });
}
module.exports={installStage};
