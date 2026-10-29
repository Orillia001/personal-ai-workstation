const assert = require("node:assert/strict");
const test = require("node:test");
const {readUpcomingExams, readVisibleExamCount, visibleExamCount} = require("./rain_classroom_reader.js");

test("reads only the visible weekly count after the course page is ready", async () => {
  assert.equal(visibleExamCount("登录 雨课堂"), null);
  assert.equal(visibleExamCount("最近一周有2门考试"), 2);
  assert.equal(visibleExamCount("我听的课 搜索课程 最近一周有2门考试"), 2);
  assert.equal(visibleExamCount("我听的课 搜索课程"), 0);
  const location = {protocol: "https:", hostname: "www.yuketang.cn"};
  const page = {body: {innerText: "我听的课 搜索课程 最近一周有2门考试"}};
  assert.deepEqual(await readVisibleExamCount({document: page, location}),
    {format: "workstation.rain.visible-count.v1", status: "checked", count: 2});
  assert.deepEqual(await readVisibleExamCount({document: {body: {innerText: "我听的课 搜索课程"}}, location,
    timeoutMs: 100, intervalMs: 1, zeroStableMs: 2}),
    {format: "workstation.rain.visible-count.v1", status: "checked", count: 0});
  assert.equal((await readVisibleExamCount({document: {body: {innerText: "请扫码登录"}}, location,
    timeoutMs: 10, intervalMs: 1})).status, "user_action_required");
  assert.deepEqual(await readVisibleExamCount({document: {body: {innerText: "雨课堂 加载中"}}, location,
    timeoutMs: 10, intervalMs: 1}), {status: "site_error", reason: "course_page_not_ready"});
});

function reply(payload, status = 200) {
  return {ok: status >= 200 && status < 300, status, json: async () => payload};
}

test("reads the same upcomingExam list that feeds the blue notice", async () => {
  let request;
  const result = await readUpcomingExams({origin: "https://www.yuketang.cn", fetch: async (...args) => {
    request = args;
    return reply({code: 0, data: {upcomingExam: [
      {id: 10, title: "实验报告", classroom_name: "示例班级"},
      {id: 11, title: "视频提交", classroom_name: "示例班级"}
    ]}});
  }});
  assert.equal(request[0], "https://www.yuketang.cn/api/v3/classroom/on-lesson-upcoming-exam");
  assert.equal(request[1].credentials, "same-origin");
  assert.equal(request[1].method, "GET");
  assert.deepEqual(result, {status: "checked", assignments: [
    {external_id: "10", title: "实验报告", course: "示例班级", due_at: null, url: null, status: "upcoming_exam"},
    {external_id: "11", title: "视频提交", course: "示例班级", due_at: null, url: null, status: "upcoming_exam"}
  ]});
});

test("empty authenticated list is distinct from a failed request", async () => {
  const empty = await readUpcomingExams({origin: "https://pro.yuketang.cn", fetch: async () => reply({code: 0, data: {upcomingExam: []}})});
  assert.deepEqual(empty, {status: "checked", assignments: []});
  const unauthenticated = await readUpcomingExams({origin: "https://www.yuketang.cn", fetch: async () => reply({code: 50000, msg: "UNAUTHENTICATED"})});
  assert.equal(unauthenticated.status, "user_action_required");
  const changed = await readUpcomingExams({origin: "https://www.yuketang.cn", fetch: async () => reply({code: 0, data: {}})});
  assert.equal(changed.status, "site_error");
});

test("refuses to send the request to another origin", async () => {
  let called = false;
  const result = await readUpcomingExams({origin: "https://example.com", fetch: async () => {called = true; return reply({});}});
  assert.equal(result.status, "site_error");
  assert.equal(called, false);
});
