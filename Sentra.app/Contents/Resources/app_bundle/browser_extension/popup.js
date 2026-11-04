function sendCmd(cmd, action = null) {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || !tabs[0]) return;
    chrome.tabs.sendMessage(tabs[0].id, { cmd, action }, () => {
      refreshCounts();
    });
  });
}

function refreshCounts() {
  chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
    if (!tabs || !tabs[0]) return;
    chrome.tabs.sendMessage(tabs[0].id, { cmd: "GET_COUNTS" }, (res) => {
      if (res) {
        document.getElementById("counts").textContent =
          `👍 ${res.likes || 0} | 💬 ${res.comments || 0} | 🔄 ${res.shares || 0}`;
      }
    });
  });
}

document.getElementById("btn-like").addEventListener("click", () => sendCmd("START", "like"));
document.getElementById("btn-comment").addEventListener("click", () => sendCmd("START", "comment"));
document.getElementById("btn-share").addEventListener("click", () => sendCmd("START", "share"));
document.getElementById("btn-stop").addEventListener("click", () => sendCmd("STOP"));
document.getElementById("btn-copy").addEventListener("click", () => sendCmd("COPY_ALL"));

refreshCounts();

