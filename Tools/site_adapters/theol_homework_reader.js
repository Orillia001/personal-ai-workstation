/* Read the two homework reminder areas on the signed-in THEOL personal page.
   No page scripts, site APIs, cookies, or login links are read or executed. */
(function (root) {
  "use strict";
  const FORMAT = "workstation.theol.pending-homework.v1";
  const text = node => (node?.textContent || "").trim().replace(/\s+/g, " ");

  function parseDocument(doc) {
    const reminder = doc.querySelector("#taskRemind");
    const number = reminder?.querySelector('#taskUl li[data-value="homework"] h4');
    const section = reminder?.querySelector("#homeworkTask");
    if (!number || !section || !/待提交作业/.test(text(section.querySelector(".title h5")))) {
      return {format: FORMAT, status: "site_error", reason: "reminder_not_ready"};
    }
    const rawCount = text(number);
    if (!/^\d{1,3}$/.test(rawCount)) return {format: FORMAT, status: "site_error", reason: "invalid_count"};
    const count = Number(rawCount);
    const rows = [...section.querySelectorAll("ul > li")];
    if (rows.length > 100 || rows.length !== count) {
      return {format: FORMAT, status: "site_error", reason: "incomplete_list"};
    }
    const assignments = [];
    for (const [index, row] of rows.entries()) {
      const heading = row.querySelector("h6");
      const title = (heading?.getAttribute("title") || text(heading)).trim();
      const paragraphs = [...row.querySelectorAll("p")];
      const due = text(paragraphs.find(node => text(node).startsWith("截止"))?.querySelector("span"));
      const courseNode = paragraphs.find(node => text(node).startsWith("课程"))?.querySelector("span");
      const course = (courseNode?.getAttribute("title") || text(courseNode)).trim();
      if (!title || !course || !/^\d{4}\/\d{2}\/\d{2} \d{2}:\d{2}$/.test(due)) {
        return {format: FORMAT, status: "site_error", reason: "invalid_assignment"};
      }
      assignments.push({external_id: `theol-${index + 1}`, title, course, due_at: due,
        url: null, status: "pending_homework"});
    }
    return {format: FORMAT, status: "checked", count, assignments};
  }

  async function readPendingHomework(doc = root.document, settings = {}) {
    if (!doc) return {format: FORMAT, status: "site_error", reason: "reminder_not_ready"};
    const deadline = Date.now() + (settings.timeoutMs ?? 12000);
    let result;
    let zeroSince = 0;
    do {
      result = parseDocument(doc);
      if (result.status === "checked" && result.count > 0) return result;
      if (result.status === "checked" && result.count === 0) {
        zeroSince ||= Date.now();
        if (Date.now() - zeroSince >= (settings.zeroStableMs ?? 1500)) return result;
      } else zeroSince = 0;
      if (result.status !== "checked" && !["reminder_not_ready", "incomplete_list"].includes(result.reason)) return result;
      await new Promise(resolve => setTimeout(resolve, 250));
    } while (Date.now() < deadline);
    return result;
  }

  const api = {FORMAT, parseDocument, readPendingHomework};
  root.WorkstationTheolReader = api;
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  // When pasted into DevTools as a snippet, offer a manual fallback.
  if (typeof chrome === "undefined" || !chrome.runtime?.id) {
    void readPendingHomework().then(async result => {
      const value = JSON.stringify(result);
      try { await root.navigator.clipboard.writeText(value); }
      catch { /* DevTools still shows the result if clipboard permission is absent. */ }
      root.console.info("课程伴侣待提交作业读取结果（已尝试复制）：", value);
    });
  }
})(globalThis);
