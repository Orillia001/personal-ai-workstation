// Checks that Edge injects the installed workbench content script.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawn} = require("node:child_process");

const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const extension = __dirname;
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "workstation-rain-extension-smoke-"));
const port = 20000 + Math.floor(Math.random() * 1000);
const browser = spawn(edge, ["--headless=new", "--no-first-run", "--disable-gpu",
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`,
  `--disable-extensions-except=${extension}`, `--load-extension=${extension}`,
  "http://127.0.0.1:8765/workbench?smoke=1"], {stdio: "ignore", windowsHide: true});

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
  assert.ok(page, "Edge did not open the workbench");
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => {socket.onopen = resolve; socket.onerror = reject});
  let id = 0;
  function evaluate(expression) {
    return new Promise((resolve, reject) => {
      const next = ++id;
      const listener = event => {
        const data = JSON.parse(event.data);
        if (data.id !== next) return;
        socket.removeEventListener("message", listener);
        if (data.error || data.result?.exceptionDetails) reject(new Error(data.error?.message || data.result?.exceptionDetails?.text));
        else resolve(data.result?.result?.value);
      };
      socket.addEventListener("message", listener);
      socket.send(JSON.stringify({id: next, method: "Runtime.evaluate", params: {expression, returnByValue: true}}));
    });
  }
  let status;
  for (let i = 0; i < 60; i++) {
    status = await evaluate("typeof siteBridgeState === 'undefined' ? 'loading' : siteBridgeState.autoStatus");
    if (status === "checking" || status === "saving" || status === "checked" || status === "user_action_required" || status === "site_error") break;
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.notEqual(status, "waiting", "Edge did not inject the workbench content script");
  assert.notEqual(status, "loading", "Workbench page did not initialize");
  if (process.argv.includes("--full")) {
    for (let i = 0; i < 350; i++) {
      status = await evaluate("siteBridgeState.autoStatus");
      if (["checked", "user_action_required", "site_error"].includes(status)) break;
      await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert.ok(["checked", "user_action_required", "site_error"].includes(status),
      `Rain check did not return a terminal result: ${status}`);
  }
  socket.close();
  process.stdout.write(`Rain extension injected into Edge workbench: ${status}\n`);
}

main().catch(error => {process.stderr.write(`${error.stack || error}\n`); process.exitCode = 1}).finally(() => {
  browser.kill();
  const target = path.resolve(profile), parent = path.resolve(os.tmpdir());
  if (target.startsWith(parent + path.sep) && path.basename(target).startsWith("workstation-rain-extension-smoke-")) {
    try {fs.rmSync(target, {recursive: true, force: true})} catch {}
  }
});
