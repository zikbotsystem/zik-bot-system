/* global API_BASE_URL */

function fmt(sec) {
  const s = Math.max(0, sec);
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${h} : ${m} : ${ss}`;
}

async function load() {
  const statusEl = document.getElementById("status");
  const accountEl = document.getElementById("account");
  const timerEl = document.getElementById("timer");

  chrome.storage.local.get(["zik_token"], async (data) => {
    const token = data.zik_token;
    if (!token) {
      statusEl.textContent = "No active token. Open ZIK from the bot link.";
      return;
    }
    try {
      const res = await fetch(`${API_BASE_URL}/api/session/${token}`);
      if (!res.ok) {
        statusEl.textContent = "Session not active";
        return;
      }
      const s = await res.json();
      statusEl.textContent = "Active session";
      accountEl.textContent = `Account: ${s.account_name}`;
      timerEl.textContent = `Remaining: ${fmt(Number(s.remaining_seconds || 0))}`;
    } catch (e) {
      statusEl.textContent = "Failed to load session";
    }
  });
}

load();
