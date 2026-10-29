/* Run as an Edge DevTools Snippet on a signed-in Rain Classroom course page.
 * The current reader checks only the visible "最近一周有 X 门考试" label.
 * The older API helper remains available for compatibility but is not auto-run.
 */
(function (root) {
  "use strict";

  const ENDPOINT = "/api/v3/classroom/on-lesson-upcoming-exam";

  function visibleExamCount(text) {
    const value = String(text || "");
    const match = value.match(/最近一周有\s*(\d+)\s*门考试/);
    if (match) {
      const count = Number(match[1]);
      return Number.isSafeInteger(count) && count <= 1000 ? count : null;
    }
    return value.includes("我听的课") && value.includes("搜索课程") ? 0 : null;
  }

  async function readVisibleExamCount(options) {
    const settings = options || {};
    const page = settings.document || root.document;
    const address = settings.location || root.location;
    if (!page || !address || address.protocol !== "https:" || !/(^|\.)yuketang\.cn$/.test(address.hostname)) {
      return {status: "site_error", reason: "wrong_site"};
    }
    const deadline = Date.now() + (settings.timeoutMs || 17000);
    let readySince = 0;
    while (Date.now() < deadline) {
      const text = page.body?.innerText || "";
      const count = visibleExamCount(text);
      if (count !== null) {
        if (count > 0) return {format: "workstation.rain.visible-count.v1", status: "checked", count};
        if (!readySince) readySince = Date.now();
        if (Date.now() - readySince >= (settings.zeroStableMs ?? 1500)) return {format: "workstation.rain.visible-count.v1", status: "checked", count: 0};
      } else readySince = 0;
      await new Promise(resolve => setTimeout(resolve, settings.intervalMs || 250));
    }
    return /登录|扫码/.test(page.body?.innerText || "")
      ? {status: "user_action_required", reason: "login_page"}
      : {status: "site_error", reason: "course_page_not_ready"};
  }

  function normalize(payload) {
    if (payload && payload.code === 50000 && payload.msg === "UNAUTHENTICATED") {
      return { status: "user_action_required", assignments: [] };
    }
    const exams = payload && payload.code === 0 && payload.data && payload.data.upcomingExam;
    if (!Array.isArray(exams)) {
      return { status: "site_error", assignments: [] };
    }
    const assignments = [];
    for (const exam of exams) {
      if (!exam || exam.id == null || typeof exam.title !== "string") {
        return { status: "site_error", assignments: [] };
      }
      assignments.push({
        external_id: String(exam.id),
        title: exam.title.trim(),
        course: typeof exam.classroom_name === "string" ? exam.classroom_name.trim() : "",
        due_at: null,
        url: null,
        status: "upcoming_exam"
      });
    }
    return { status: "checked", assignments };
  }

  async function readUpcomingExams(options) {
    const settings = options || {};
    const origin = settings.origin || (root.location && root.location.origin);
    const fetcher = settings.fetch || root.fetch;
    if (typeof origin !== "string" || typeof fetcher !== "function") {
      return { status: "site_error", assignments: [] };
    }
    let parsed;
    try { parsed = new URL(origin); } catch { return { status: "site_error", assignments: [] }; }
    if (parsed.protocol !== "https:" || !/(^|\.)yuketang\.cn$/.test(parsed.hostname)) {
      return { status: "site_error", assignments: [] };
    }
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetcher(new URL(ENDPOINT, parsed.origin).href, {
        method: "GET",
        credentials: "same-origin",
        headers: { Accept: "application/json" },
        cache: "no-store",
        signal: controller.signal
      });
      if (response.status === 401 || response.status === 403) {
        return { status: "user_action_required", assignments: [] };
      }
      if (!response.ok) return { status: "site_error", assignments: [] };
      return normalize(await response.json());
    } catch {
      return { status: "site_error", assignments: [] };
    } finally {
      clearTimeout(timeout);
    }
  }

  function showResult(result) {
    if (!root.document || !root.document.documentElement) return;
    const old = root.document.getElementById("workstation-rain-reader-result");
    if (old) old.remove();
    const panel = root.document.createElement("section");
    panel.id = "workstation-rain-reader-result";
    panel.setAttribute("role", "dialog");
    panel.setAttribute("aria-label", "雨课堂最近一周考试提醒");
    Object.assign(panel.style, {
      position: "fixed", top: "16px", right: "16px", zIndex: "2147483647",
      width: "min(420px, calc(100vw - 32px))", maxHeight: "min(70vh, 600px)",
      overflow: "auto", padding: "16px", background: "#fff", color: "#17213b",
      border: "1px solid #b6c5dd", borderRadius: "8px",
      boxShadow: "0 12px 32px #17213b55", font: "14px/1.5 sans-serif"
    });
    const heading = root.document.createElement("strong");
    heading.textContent = "雨课堂 · 最近一周考试提醒";
    panel.appendChild(heading);
    const close = root.document.createElement("button");
    close.type = "button";
    close.textContent = "关闭";
    close.style.cssText = "float:right;cursor:pointer";
    close.addEventListener("click", () => panel.remove());
    panel.appendChild(close);
    const detail = root.document.createElement("p");
    if (result.status === "checked" && Number.isInteger(result.count)) {
      detail.textContent = `页面显示：最近一周 ${result.count} 门考试。`;
    } else if (result.status === "checked") {
      detail.textContent = result.assignments.length
        ? `读取到 ${result.assignments.length} 条考试提醒：`
        : "接口确认：最近一周没有考试提醒。";
    } else if (result.status === "user_action_required") {
      detail.textContent = "当前页面未登录或登录已失效。请完成登录后重试。";
    } else {
      detail.textContent = "读取失败或网站接口已变化，不能据此判断没有考试。";
    }
    panel.appendChild(detail);
    if (result.status === "checked" && result.assignments?.length) {
      const list = root.document.createElement("ol");
      for (const item of result.assignments) {
        const row = root.document.createElement("li");
        row.textContent = item.course ? `${item.title} · ${item.course}` : item.title;
        list.appendChild(row);
      }
      panel.appendChild(list);
    }
    if (result.status === "checked") {
      const hint = root.document.createElement("p");
      hint.textContent = "把读取结果复制到工作台的雨课堂卡片；仅传递页面显示的考试数量。";
      panel.appendChild(hint);
      const transfer = root.document.createElement("textarea");
      transfer.readOnly = true;
      transfer.setAttribute("aria-label", "可复制到工作台的雨课堂读取结果");
      transfer.value = JSON.stringify(Number.isInteger(result.count) ?
        {format: "workstation.rain.visible-count.v1", status: "checked", count: result.count} :
        {format: "workstation.rain.upcoming-exams.v1", status: "checked", assignments: result.assignments});
      transfer.style.cssText = "display:block;width:100%;box-sizing:border-box;min-height:72px;margin:8px 0;font:11px/1.3 monospace";
      panel.appendChild(transfer);
      const copy = root.document.createElement("button");
      copy.type = "button";
      copy.textContent = "复制结果";
      copy.style.cssText = "cursor:pointer;padding:5px 10px";
      copy.addEventListener("click", async () => {
        try {
          await root.navigator.clipboard.writeText(transfer.value);
          copy.textContent = "已复制，返回工作台导入";
        } catch {
          transfer.focus();
          transfer.select();
          copy.textContent = "请按 Ctrl+C 复制选中的结果";
        }
      });
      panel.appendChild(copy);
    }
    root.document.documentElement.appendChild(panel);
  }

  const api = { readUpcomingExams, readVisibleExamCount, visibleExamCount, normalize, showResult };
  if (typeof module === "object" && module.exports) module.exports = api;
  else {
    root.WorkstationRainReader = api;
    if (!(root.chrome && root.chrome.runtime && root.chrome.runtime.id)) {
      void readVisibleExamCount().then(result => {
        root.WorkstationRainReader.lastResult = result;
        showResult(result);
      });
    }
  }
})(globalThis);
