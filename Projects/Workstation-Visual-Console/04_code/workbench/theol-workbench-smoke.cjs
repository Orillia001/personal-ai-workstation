/* Exercise THEOL result rendering without writing a simulated result to the real DB. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawn} = require("node:child_process");

const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "workstation-theol-ui-"));
const port = 22000 + Math.floor(Math.random() * 1000);
const browser = spawn(edge, ["--headless=new", "--no-first-run", "--disable-gpu", "--disable-background-networking",
  "--window-size=1440,900", `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "http://127.0.0.1:8765/workbench?smoke=1"],
  {stdio: "ignore", windowsHide: true});

async function main() {
  let page;
  for (let i = 0; i < 100; i++) {
    try {
      const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      page = pages.find(item => item.type === "page" && item.url.includes("/workbench?smoke=1"));
      if (page) break;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(page, "Edge did not load workbench");
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject;});
  let id = 0;
  function evaluate(expression) {
    return new Promise((resolve, reject) => {
      const next = ++id;
      const listener = event => {
        const data = JSON.parse(event.data);
        if (data.id !== next) return;
        socket.removeEventListener("message", listener);
        if (data.error || data.result?.exceptionDetails) reject(Error(data.error?.message || data.result?.exceptionDetails?.text));
        else resolve(data.result?.result?.value);
      };
      socket.addEventListener("message", listener);
      socket.send(JSON.stringify({id: next, method: "Runtime.evaluate", params: {expression, returnByValue: true}}));
    });
  }
  for (let i = 0; i < 100; i++) {
    if (await evaluate("typeof siteBridgeState !== 'undefined' && siteBridgeState.loaded")) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(await evaluate("siteBridgeState.loaded"), true);
  await evaluate("document.querySelector('.icon-rail [data-action=open-console]').click()");
  const result = {format: "workstation.theol.pending-homework.v1", status: "checked", count: 1,
    assignments: [{external_id: "theol-1", title: "示例练习", course: "示例课程",
      due_at: "2026/10/01 00:00", url: null, status: "pending_homework"}]};
  await evaluate(`window.postMessage({source:'workstation-theol-extension',type:'result',result:${JSON.stringify(result)}},location.origin)`);
  for (let i = 0; i < 50; i++) {
    if (await evaluate("document.querySelector('.plan-panel')?.textContent.includes('示例练习')")) break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.equal(await evaluate("document.querySelector('.plan-panel')?.textContent.includes('示例练习')"), true);
  assert.equal(await evaluate("document.querySelectorAll('.plan-item[data-plan-kind=homework]').length"), 1);
  await evaluate("(() => {const form=document.querySelector('[data-role=plan-add]');form.querySelector('[name=title]').value='个人测试计划';form.querySelector('[name=due]').value='2026-10-02T09:30';form.requestSubmit()})()");
  assert.equal(await evaluate("planItems.length"), 1);
  assert.equal(await evaluate("document.querySelector('.plan-panel').textContent.includes('个人测试计划')"), true);
  await evaluate("(() => {const checkbox=document.querySelector('[data-role=plan-done]');checkbox.checked=true;checkbox.dispatchEvent(new Event('change',{bubbles:true}))})()");
  assert.equal(await evaluate("planItems[0].done"), true);
  await evaluate("(() => {const snapshot=snapshotState();planItems.length=0;restoreState(snapshot);render()})()");
  assert.equal(await evaluate("planItems[0].title"), "个人测试计划");
  assert.equal(await evaluate("planItems[0].due"), "2026-10-02T09:30");
  assert.equal(await evaluate("planItems[0].done"), true);
  if (process.argv.includes("--screenshot")) {
    const shot = await new Promise((resolve, reject) => {
      const next = ++id;
      const listener = event => {
        const data = JSON.parse(event.data);
        if (data.id !== next) return;
        socket.removeEventListener("message", listener);
        if (data.error) reject(Error(data.error.message)); else resolve(data.result.data);
      };
      socket.addEventListener("message", listener);
      socket.send(JSON.stringify({id: next, method: "Page.captureScreenshot", params: {format: "png"}}));
    });
    const target = path.resolve(__dirname, "../../08_evidence/plan-panel-20260930.png");
    assert.equal(fs.existsSync(target), false, "Screenshot target already exists");
    fs.writeFileSync(target, Buffer.from(shot, "base64"));
  }
  await evaluate("document.querySelector('[data-action=remove-plan]').click()");
  assert.equal(await evaluate("planItems.length"), 0);
  assert.equal(await evaluate("document.querySelectorAll('.plan-item[data-plan-kind=homework]').length"), 1);
  assert.equal(await evaluate("document.querySelector('.bridge-panel')?.textContent.includes('立即同步作业')"), true);
  socket.close();
  process.stdout.write("Workbench plan smoke OK: automatic homework, manual add, complete, restore and remove\n");
}

main().catch(error => {process.stderr.write(`${error.stack || error}\n`); process.exitCode = 1;}).finally(() => {
  browser.kill();
  const target = path.resolve(profile), parent = path.resolve(os.tmpdir());
  if (target.startsWith(parent + path.sep) && path.basename(target).startsWith("workstation-theol-ui-")) {
    try {fs.rmSync(target, {recursive: true, force: true});} catch {}
  }
});
