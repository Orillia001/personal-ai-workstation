/* Reads only the THEOL personal-page reminder DOM. */
(() => {
  "use strict";
  if (location.hostname !== "eol.imut.edu.cn" || !location.pathname.startsWith("/meol/personal/")) return;
  const reader = globalThis.WorkstationTheolReader;
  chrome.runtime.onMessage.addListener((message, _sender, respond) => {
    if (message?.type !== "WORKSTATION_THEOL_CHECK") return;
    if (!reader || typeof reader.readPendingHomework !== "function") {
      respond({status: "site_error", reason: "reader_not_available"});
      return;
    }
    void reader.readPendingHomework().then(respond, () => respond({status: "site_error", reason: "reader_failed"}));
    return true;
  });
  chrome.runtime.sendMessage({type: "WORKSTATION_THEOL_READY"});
})();
