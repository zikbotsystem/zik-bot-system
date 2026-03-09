/* global API_BASE_URL */

function getTokenFromUrl() {
  const url = new URL(window.location.href);
  return url.searchParams.get("zik_token") || url.searchParams.get("t") || "";
}

function findEmailInput() {
  return (
    document.querySelector("input[type='email']") ||
    document.querySelector("input[name*='email' i]") ||
    document.querySelector("input[id*='email' i]")
  );
}

function findPasswordInput() {
  return (
    document.querySelector("input[type='password']") ||
    document.querySelector("input[name*='pass' i]") ||
    document.querySelector("input[id*='pass' i]")
  );
}

function setInputValue(input, value) {
  if (!input) return;
  input.focus();
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
  input.dispatchEvent(new Event("change", { bubbles: true }));
}

function fmt(sec) {
  const s = Math.max(0, sec);
  const h = String(Math.floor(s / 3600)).padStart(2, "0");
  const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
  const ss = String(s % 60).padStart(2, "0");
  return `${h} : ${m} : ${ss}`;
}

function ensureOverlay() {
  let el = document.getElementById("zikbot-timer");
  if (el) return el;
  el = document.createElement("div");
  el.id = "zikbot-timer";
  el.style.position = "fixed";
  el.style.top = "12px";
  el.style.left = "50%";
  el.style.transform = "translateX(-50%)";
  el.style.zIndex = "999999";
  el.style.background = "rgba(0,0,0,0.75)";
  el.style.color = "#fff";
  el.style.padding = "8px 12px";
  el.style.borderRadius = "10px";
  el.style.fontFamily = "system-ui, -apple-system, Segoe UI, Roboto, Arial";
  el.style.fontSize = "14px";
  el.style.boxShadow = "0 2px 10px rgba(0,0,0,0.35)";
  el.textContent = "ZIK Bot: --:--:--";
  document.documentElement.appendChild(el);
  return el;
}

async function fetchSession(token) {
  const res = await fetch(`${API_BASE_URL}/api/session/${token}`);
  if (!res.ok) throw new Error(`session_fetch_failed_${res.status}`);
  return res.json();
}

async function sendHeartbeat(token) {
  try {
    await fetch(`${API_BASE_URL}/api/heartbeat/${token}`, { method: "POST" });
  } catch (e) {
    // ignore
  }
}

(async function main() {
  const token = getTokenFromUrl();
  if (!token) return; // do nothing if not opened from bot link

  // Remember token for popup
  chrome.storage.local.set({ zik_token: token });

  let data;
  try {
    data = await fetchSession(token);
  } catch (e) {
    return;
  }

  // Autofill
  const emailInput = findEmailInput();
  const passInput = findPasswordInput();
  setInputValue(emailInput, data.email);
  setInputValue(passInput, data.password);

  // Timer overlay
  const overlay = ensureOverlay();
  let remaining = Number(data.remaining_seconds || 0);
  overlay.textContent = `ZIK Bot: ${fmt(remaining)}`;

  setInterval(() => {
    remaining = Math.max(0, remaining - 1);
    overlay.textContent = `ZIK Bot: ${fmt(remaining)}`;
    if (remaining === 15 * 60) {
      // small warning in-page at 15 minutes left
      const warn = document.createElement("div");
      warn.textContent = "⏰ 15 минут осталось (проверьте бота для продления)";
      warn.style.position = "fixed";
      warn.style.top = "52px";
      warn.style.left = "50%";
      warn.style.transform = "translateX(-50%)";
      warn.style.zIndex = "999999";
      warn.style.background = "rgba(255, 140, 0, 0.9)";
      warn.style.color = "#000";
      warn.style.padding = "6px 10px";
      warn.style.borderRadius = "10px";
      warn.style.fontFamily = "system-ui, -apple-system, Segoe UI, Roboto, Arial";
      warn.style.fontSize = "13px";
      document.documentElement.appendChild(warn);
      setTimeout(() => warn.remove(), 8000);
    }
  }, 1000);

  // Heartbeat
  await sendHeartbeat(token);
  setInterval(() => sendHeartbeat(token), 30000);
  window.addEventListener("beforeunload", () => sendHeartbeat(token));
})();
