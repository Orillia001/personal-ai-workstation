/* Runs only for Rain Classroom and the local workbench. */
"use strict";

const RAIN_HOME = "https://www.yuketang.cn/v2/web/index";
const THEOL_HOME = "http://eol.imut.edu.cn/meol/personal/stuPersonal.do";
let checkPromise = null;
let activeTabCheck = null;
let lastCheckAt = 0;
let theolCheckPromise = null;
let activeTheolTabCheck = null;
let lastTheolCheckAt = 0;

function isRain(url) {
  try { const parsed = new URL(url); return parsed.protocol === "https:" && /(^|\.)yuketang\.cn$/.test(parsed.hostname); }
  catch { return false; }
}
function isTheol(url) {
  try {
    const parsed = new URL(url);
    return parsed.protocol === "http:" && parsed.hostname === "eol.imut.edu.cn" &&
      parsed.pathname.startsWith("/meol/personal/");
  } catch { return false; }
}
function isWorkbench(url) {
  try {
    const parsed = new URL(url);
    return parsed.origin === "http://127.0.0.1:8765" && /(^\/$|^\/workbench(?:\/|$))/.test(parsed.pathname);
  } catch { return false; }
}
function queryTabs(query) {
  return new Promise(resolve => chrome.tabs.query(query, tabs => resolve(chrome.runtime.lastError ? [] : tabs)));
}
function createRainTab() {
  return new Promise(resolve => chrome.tabs.create({url: RAIN_HOME, active: false}, tab => resolve(chrome.runtime.lastError ? null : tab)));
}
function createTheolTab() {
  return new Promise(resolve => chrome.tabs.create({url: THEOL_HOME, active: false}, tab => resolve(chrome.runtime.lastError ? null : tab)));
}
function getTab(tabId) {
  return new Promise(resolve => chrome.tabs.get(tabId, tab => resolve(chrome.runtime.lastError ? null : tab)));
}
function waitForTabComplete(tabId) {
  return new Promise(resolve => {
    let finished = false;
    const timer = setTimeout(() => finish(false), 15000);
    const listener = (changedId, info) => { if (changedId === tabId && info.status === "complete") finish(true); };
    function finish(loaded) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      chrome.tabs.onUpdated.removeListener(listener);
      resolve(loaded);
    }
    chrome.tabs.onUpdated.addListener(listener);
    void getTab(tabId).then(tab => {
      if (!tab) finish(false);
      else if (tab.status === "complete") finish(true);
    });
  });
}
function sendToTab(tabId, message) {
  return new Promise(resolve => {
    let finished = false;
    const timeout = setTimeout(() => { if (!finished) { finished = true; resolve(null); } }, 20000);
    chrome.tabs.sendMessage(tabId, message, reply => {
      if (finished) return;
      finished = true;
      clearTimeout(timeout);
      resolve(chrome.runtime.lastError ? null : reply);
    });
  });
}
async function workbenchTabs() {
  return (await queryTabs({url: "http://127.0.0.1:8765/*"})).filter(tab => isWorkbench(tab.url));
}
function normalizeForWorkbench(result) {
  if (!result || !["checked", "user_action_required", "site_error"].includes(result.status)) {
    return {status: "site_error", reason: "reader_failed"};
  }
  if (result.status !== "checked") {
    const allowed = new Set(["wrong_site", "login_page", "course_page_not_ready", "reader_not_available",
      "reader_failed", "page_load_timeout", "open_failed", "login_redirect"]);
    return {status: result.status, ...(allowed.has(result.reason) ? {reason: result.reason} : {})};
  }
  if (result.format !== "workstation.rain.visible-count.v1" ||
      !Number.isInteger(result.count) || result.count < 0 || result.count > 1000) return {status: "site_error", reason: "reader_failed"};
  return {status: "checked", count: result.count};
}
async function publish(result) {
  const safeResult = normalizeForWorkbench(result);
  for (const tab of await workbenchTabs()) {
    await sendToTab(tab.id, {type: "WORKSTATION_RAIN_RESULT", result: safeResult});
  }
}
async function checkRainTab(tabId) {
  if (activeTabCheck) return activeTabCheck;
  activeTabCheck = (async () => {
    let result = await sendToTab(tabId, {type: "WORKSTATION_RAIN_CHECK"});
    if (!result) {
      const tab = await getTab(tabId);
      if (tab && (tab.status === "loading" ? await waitForTabComplete(tabId) : true)) {
        await new Promise(resolve => setTimeout(resolve, 500));
        result = await sendToTab(tabId, {type: "WORKSTATION_RAIN_CHECK"});
      }
    }
    if (!result || !["checked", "user_action_required", "site_error"].includes(result.status)) return false;
    await publish(result);
    return true;
  })();
  try { return await activeTabCheck; }
  finally { activeTabCheck = null; }
}
async function checkOrOpen(force = false) {
  if (checkPromise) return checkPromise;
  if (!force && Date.now() - lastCheckAt < 60000) return;
  checkPromise = (async () => {
    lastCheckAt = Date.now();
    const tabs = (await queryTabs({url: "https://*.yuketang.cn/*"})).filter(tab => isRain(tab.url));
    const preferred = tabs.find(tab => tab.url.startsWith("https://www.yuketang.cn/v2/web/index")) || tabs[0];
    if (preferred && await checkRainTab(preferred.id)) return;
    const opened = await createRainTab();
    if (!opened?.id) { await publish({status: "site_error", reason: "open_failed"}); return; }
    const loaded = await waitForTabComplete(opened.id);
    if (!loaded) { await publish({status: "site_error", reason: "page_load_timeout"}); return; }
    const current = await getTab(opened.id);
    if (!current || !isRain(current.url)) { await publish({status: "user_action_required", reason: "login_redirect"}); return; }
    if (!await checkRainTab(opened.id)) await publish({status: "site_error", reason: "reader_not_available"});
  })();
  try { await checkPromise; }
  finally { checkPromise = null; }
}

function normalizeTheolForWorkbench(result) {
  const format = "workstation.theol.pending-homework.v1";
  if (!result || !["checked", "user_action_required", "site_error"].includes(result.status))
    return {format, status: "site_error", reason: "reader_failed"};
  if (result.status !== "checked") {
    const allowed = new Set(["tab_not_open", "login_redirect", "reminder_not_ready", "incomplete_list",
      "invalid_count", "invalid_assignment", "reader_not_available", "reader_failed", "page_load_timeout", "open_failed"]);
    return {format, status: result.status, ...(allowed.has(result.reason) ? {reason: result.reason} : {})};
  }
  const count = result.count, source = result.assignments;
  if (result.format !== format || !Number.isInteger(count) || count < 0 || count > 999 ||
      !Array.isArray(source) || source.length > 100 || source.length !== count)
    return {format, status: "site_error", reason: "reader_failed"};
  const assignments = [];
  for (const item of source) {
    if (!item || !/^theol-[1-9]\d{0,2}$/.test(item.external_id) ||
        typeof item.title !== "string" || !item.title.trim() || item.title.length > 300 ||
        typeof item.course !== "string" || !item.course.trim() || item.course.length > 200 ||
        typeof item.due_at !== "string" || !/^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}$/.test(item.due_at) ||
        item.status !== "pending_homework" || item.url != null)
      return {format, status: "site_error", reason: "reader_failed"};
    assignments.push({external_id: item.external_id, title: item.title.trim(), course: item.course.trim(),
      due_at: item.due_at, url: null, status: "pending_homework"});
  }
  return {format, status: "checked", count, assignments};
}
async function publishTheol(result) {
  const safeResult = normalizeTheolForWorkbench(result);
  for (const tab of await workbenchTabs()) {
    await sendToTab(tab.id, {type: "WORKSTATION_THEOL_RESULT", result: safeResult});
  }
}
async function checkTheolTab(tabId) {
  if (activeTheolTabCheck) return activeTheolTabCheck;
  activeTheolTabCheck = (async () => {
    let result = await sendToTab(tabId, {type: "WORKSTATION_THEOL_CHECK"});
    if (!result) {
      const tab = await getTab(tabId);
      if (tab && (tab.status === "loading" ? await waitForTabComplete(tabId) : true)) {
        await new Promise(resolve => setTimeout(resolve, 500));
        result = await sendToTab(tabId, {type: "WORKSTATION_THEOL_CHECK"});
      }
    }
    if (!result || !["checked", "user_action_required", "site_error"].includes(result.status)) return false;
    await publishTheol(result);
    return true;
  })();
  try { return await activeTheolTabCheck; }
  finally { activeTheolTabCheck = null; }
}
async function checkTheolOrOpen(force = false) {
  if (theolCheckPromise) return theolCheckPromise;
  if (!force && Date.now() - lastTheolCheckAt < 60000) return;
  theolCheckPromise = (async () => {
    lastTheolCheckAt = Date.now();
    const tabs = (await queryTabs({url: "http://eol.imut.edu.cn/*"})).filter(tab => isTheol(tab.url));
    const preferred = tabs.find(tab => tab.url.startsWith(THEOL_HOME)) || tabs[0];
    if (preferred && await checkTheolTab(preferred.id)) return;
    const opened = await createTheolTab();
    if (!opened?.id) { await publishTheol({status: "site_error", reason: "open_failed"}); return; }
    if (!await waitForTabComplete(opened.id)) { await publishTheol({status: "site_error", reason: "page_load_timeout"}); return; }
    const current = await getTab(opened.id);
    if (!current || !isTheol(current.url)) { await publishTheol({status: "user_action_required", reason: "login_redirect"}); return; }
    if (!await checkTheolTab(opened.id)) await publishTheol({status: "site_error", reason: "reader_not_available"});
  })();
  try { await theolCheckPromise; }
  finally { theolCheckPromise = null; }
}

chrome.runtime.onMessage.addListener((message, sender, respond) => {
  const senderUrl = sender.url || sender.tab?.url;
  if (message?.type === "WORKSTATION_WORKBENCH_READY" && isWorkbench(senderUrl)) {
    void checkOrOpen();
    void checkTheolOrOpen();
    respond({queued: true});
  } else if (message?.type === "WORKSTATION_RAIN_CHECK_NOW" && isWorkbench(senderUrl)) {
    void checkOrOpen(true);
    respond({queued: true});
  } else if (message?.type === "WORKSTATION_RAIN_READY" && isRain(senderUrl) && sender.tab?.id != null) {
    void workbenchTabs().then(tabs => { if (tabs.length) return checkRainTab(sender.tab.id); });
    respond({queued: true});
  } else if (message?.type === "WORKSTATION_THEOL_CHECK_NOW" && isWorkbench(senderUrl)) {
    void checkTheolOrOpen(true);
    respond({queued: true});
  } else if (message?.type === "WORKSTATION_THEOL_READY" && isTheol(senderUrl) && sender.tab?.id != null) {
    void workbenchTabs().then(tabs => { if (tabs.length) return checkTheolTab(sender.tab.id); });
    respond({queued: true});
  }
});
