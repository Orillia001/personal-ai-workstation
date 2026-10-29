const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

const script = fs.readFileSync(path.join(__dirname, "background.js"), "utf8");
const context = {chrome: {runtime: {onMessage: {addListener() {}}}}, URL, setTimeout, clearTimeout};
vm.createContext(context);
vm.runInContext(script, context);
const normalize = vm.runInContext("normalizeForWorkbench", context);
assert.equal(JSON.stringify(normalize({format: "workstation.rain.visible-count.v1", status: "checked", count: 2,
  pageText: "should not leave extension"})), '{"status":"checked","count":2}');
assert.equal(normalize({status: "checked", count: -1}).status, "site_error");
assert.equal(JSON.stringify(normalize({status: "user_action_required", cookie: "should not leave extension"})),
  '{"status":"user_action_required"}');
assert.equal(JSON.stringify(normalize({status: "site_error", reason: "course_page_not_ready", pageText: "private"})),
  '{"status":"site_error","reason":"course_page_not_ready"}');
process.stdout.write("Rain extension result whitelist OK\n");
const normalizeTheol = vm.runInContext("normalizeTheolForWorkbench", context);
const theol = normalizeTheol({format: "workstation.theol.pending-homework.v1", status: "checked", count: 1,
  cookie: "never-send", assignments: [{external_id: "theol-1", title: "练习一", course: "控制基础",
    due_at: "2026/10/01 00:00", url: null, status: "pending_homework", password: "never-send"}]});
assert.equal(theol.count, 1);
assert.equal(theol.assignments.length, 1);
assert.ok(!JSON.stringify(theol).includes("never-send"));
assert.equal(normalizeTheol({format: theol.format, status: "checked", count: 2, assignments: []}).status, "site_error");
process.stdout.write("THEOL extension result whitelist OK\n");
