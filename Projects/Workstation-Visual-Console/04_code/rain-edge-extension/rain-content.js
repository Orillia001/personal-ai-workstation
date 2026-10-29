/* Runs in Edge's isolated world on Rain Classroom pages. */
(() => {
  "use strict";
  if (location.protocol !== "https:" || !/(^|\.)yuketang\.cn$/.test(location.hostname)) return;
  const reader = globalThis.WorkstationRainReader;
  chrome.runtime.onMessage.addListener((message, _sender, respond) => {
    if (message?.type !== "WORKSTATION_RAIN_CHECK") return;
    if (!reader || typeof reader.readVisibleExamCount !== "function") {
      respond({status: "site_error", reason: "reader_not_available"});
      return;
    }
    void reader.readVisibleExamCount().then(respond, () => respond({status: "site_error", reason: "reader_failed"}));
    return true;
  });
  chrome.runtime.sendMessage({type: "WORKSTATION_RAIN_READY"});
})();
