/* Bridges extension messages into the local workbench page; no control token is read. */
(() => {
  "use strict";
  if (location.origin !== "http://127.0.0.1:8765" ||
      !(/^\/$|^\/workbench(?:\/|$)/).test(location.pathname)) return;
  chrome.runtime.onMessage.addListener(message => {
    if (message?.type === "WORKSTATION_RAIN_RESULT")
      window.postMessage({source: "workstation-rain-extension", type: "result", result: message.result}, location.origin);
    else if (message?.type === "WORKSTATION_THEOL_RESULT")
      window.postMessage({source: "workstation-theol-extension", type: "result", result: message.result}, location.origin);
  });
  window.addEventListener("message", event => {
    if (event.source !== window || event.origin !== location.origin || event.data?.type !== "check") return;
    if (event.data.source === "workstation-rain-workbench") chrome.runtime.sendMessage({type: "WORKSTATION_RAIN_CHECK_NOW"});
    else if (event.data.source === "workstation-theol-workbench") chrome.runtime.sendMessage({type: "WORKSTATION_THEOL_CHECK_NOW"});
  });
  window.postMessage({source: "workstation-rain-extension", type: "checking"}, location.origin);
  chrome.runtime.sendMessage({type: "WORKSTATION_WORKBENCH_READY"});
})();
