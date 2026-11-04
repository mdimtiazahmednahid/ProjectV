const BRIDGE_PORTS = [19876, 19877, 19878];

async function postBatchToDesktopApp(payloadStr) {
  for (const port of BRIDGE_PORTS) {
    try {
      const resp = await fetch(`http://127.0.0.1:${port}/batch`, {
        method: "POST",
        headers: { "Content-Type": "text/plain;charset=UTF-8" },
        body: payloadStr
      });
      if (resp && resp.ok) {
        return true;
      }
    } catch (e) {
      // Try next port if unavailable
    }
  }
  return false;
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg && msg.cmd === "SEND_BATCH" && msg.payloadStr) {
    postBatchToDesktopApp(msg.payloadStr)
      .then((ok) => sendResponse({ ok }))
      .catch(() => sendResponse({ ok: false }));
    return true;
  }
  return false;
});

