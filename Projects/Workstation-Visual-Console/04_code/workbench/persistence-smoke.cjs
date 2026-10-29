// Checks a real save and reload without changing user content.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawn} = require("node:child_process");

const port = 20000 + Math.floor(Math.random() * 1000);
const profile = path.join(os.tmpdir(), `workstation-persistence-smoke-${process.pid}`);
const browser = spawn("C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe",
  ["--headless=new", "--disable-gpu", "--no-first-run", `--remote-debugging-port=${port}`,
    `--user-data-dir=${profile}`, "http://127.0.0.1:8765/workbench"],
  {stdio:"ignore",windowsHide:true});

const pause = ms => new Promise(resolve=>setTimeout(resolve,ms));

async function main(){
  let target;
  for(let i=0;i<80;i++){
    try{target=(await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find(page=>page.type==="page"&&new URL(page.url).pathname==="/workbench");if(target)break}catch{}
    await pause(125);
  }
  assert.ok(target,"Edge did not open the workbench");
  const socket=new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((resolve,reject)=>{socket.onopen=resolve;socket.onerror=reject});
  let serial=0;const pending=new Map();
  socket.onmessage=event=>{const message=JSON.parse(event.data);if(!message.id)return;const entry=pending.get(message.id);if(!entry)return;pending.delete(message.id);if(message.error)entry.reject(new Error(message.error.message));else entry.resolve(message.result)};
  function send(method,params={}){const id=++serial;return new Promise((resolve,reject)=>{pending.set(id,{resolve,reject});socket.send(JSON.stringify({id,method,params}))})}
  async function evaluate(expression){const result=await send("Runtime.evaluate",{expression,returnByValue:true});if(result.exceptionDetails)throw Error(result.exceptionDetails.text);return result.result.value}
  async function savedSnapshot(expected){
    for(let i=0;i<100;i++){
      try{const result=await evaluate(`({status:document.querySelector('#layout-save-status')?.textContent,snapshot:typeof snapshotState==='function'?JSON.stringify(snapshotState()):null})`);
        if(result?.status==="已保存"||result?.status==="已恢复 · 已保存"){
          if(!expected||result.snapshot===expected)return result.snapshot;
        }
      }catch{}
      await pause(100);
    }
    throw Error("Saved workbench state did not survive reload");
  }
  const before=await savedSnapshot();
  await send("Page.reload",{ignoreCache:true});
  await savedSnapshot(before);
  console.log("Workbench persistence smoke OK: server save and page reload restored the same state");
  socket.close();
}

main().catch(error=>{console.error(error);process.exitCode=1}).finally(async()=>{
  browser.kill();
  if(path.resolve(profile).startsWith(path.resolve(os.tmpdir())+path.sep)&&path.basename(profile).startsWith("workstation-persistence-smoke-")){
    try{fs.rmSync(profile,{recursive:true,force:true})}catch{}
  }
});
