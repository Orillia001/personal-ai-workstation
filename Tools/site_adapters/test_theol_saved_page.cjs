/* Run the reviewed DOM reader against a locally saved THEOL page in isolated Edge. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const {spawn} = require("node:child_process");

const source = process.argv[2];
if (!source || !fs.existsSync(source)) throw Error("Usage: node test_theol_saved_page.cjs <saved-html-path>");
const edge = "C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe";
const reader = fs.readFileSync(path.join(__dirname, "theol_homework_reader.js"), "utf8");
const html = new TextDecoder("gbk").decode(fs.readFileSync(source));
const profile = fs.mkdtempSync(path.join(os.tmpdir(), "workstation-theol-reader-"));
const port = 21000 + Math.floor(Math.random() * 1000);
const browser = spawn(edge, ["--headless=new", "--no-first-run", "--disable-gpu", "--disable-background-networking",
  `--remote-debugging-port=${port}`, `--user-data-dir=${profile}`, "about:blank"],
  {stdio: "ignore", windowsHide: true});

async function main() {
  let page;
  for (let i = 0; i < 100; i++) {
    try {
      const pages = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
      page = pages.find(item => item.type === "page" && item.url === "about:blank");
      if (page) break;
    } catch {}
    await new Promise(resolve => setTimeout(resolve, 100));
  }
  assert.ok(page, "Edge did not open the isolated parser page");
  const socket = new WebSocket(page.webSocketDebuggerUrl);
  await new Promise((resolve, reject) => { socket.onopen = resolve; socket.onerror = reject; });
  let id = 0;
  async function evaluate(expression) {
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
  await evaluate(reader);
  // DOMParser creates an inert document: embedded scripts and source assets never run.
  await evaluate(`globalThis.theolFixture = new DOMParser().parseFromString(${JSON.stringify(html)}, 'text/html')`);
  const result = await evaluate("WorkstationTheolReader.parseDocument(theolFixture)");
  assert.equal(result.status, "checked");
  assert.equal(result.count, result.assignments.length);
  assert.ok(result.assignments.every(item => item.title && item.course && /^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}$/.test(item.due_at)));
  const empty = await evaluate("(() => {theolFixture.querySelector('#taskUl li[data-value=homework] h4').textContent='0'; theolFixture.querySelector('#homeworkTask ul').replaceChildren(); return WorkstationTheolReader.parseDocument(theolFixture)})()");
  assert.equal(empty.status, "checked");
  assert.equal(empty.count, 0);
  const missing = await evaluate("(() => {theolFixture.querySelector('#homeworkTask').remove(); return WorkstationTheolReader.parseDocument(theolFixture)})()");
  assert.equal(missing.status, "site_error");
  socket.close();
  process.stdout.write(`THEOL saved page: ${result.count} pending homework row(s) read from both marked sections\n`);
}

main().catch(error => {process.stderr.write(`${error.stack || error}\n`); process.exitCode = 1;}).finally(() => {
  browser.kill();
  const target = path.resolve(profile), parent = path.resolve(os.tmpdir());
  if (target.startsWith(parent + path.sep) && path.basename(target).startsWith("workstation-theol-reader-")) {
    try {fs.rmSync(target, {recursive: true, force: true});} catch {}
  }
});
