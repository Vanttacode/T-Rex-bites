"use strict";

const $ = (id) => document.getElementById(id);
let channelsCache = [];
let pin = "";

// ---------- helpers ----------

async function api(path, options = {}) {
  const opts = { credentials: "same-origin", ...options };
  if (opts.json !== undefined) {
    opts.method = opts.method || "POST";
    opts.headers = { "Content-Type": "application/json" };
    opts.body = JSON.stringify(opts.json);
    delete opts.json;
  }
  const resp = await fetch(path, opts);
  let data = {};
  try { data = await resp.json(); } catch (_) { /* empty body */ }
  if (resp.status === 401 && path !== "/api/login" && path !== "/api/pin") {
    showLogin();
  }
  if (!resp.ok) {
    throw new Error(data.detail || `Error ${resp.status}`);
  }
  return data;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { t.hidden = true; }, 2600);
}

function formatSize(bytes) {
  if (bytes >= 1024 ** 3) return (bytes / 1024 ** 3).toFixed(1) + " GB";
  if (bytes >= 1024 ** 2) return Math.round(bytes / 1024 ** 2) + " MB";
  return Math.max(1, Math.round(bytes / 1024)) + " KB";
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  for (const c of children) node.append(c);
  return node;
}

// ---------- login ----------

function showLogin() {
  $("view-app").hidden = true;
  $("view-login").hidden = false;
  pin = "";
  renderDots();
}

function renderDots() {
  const dots = $("pin-dots");
  const n = Math.max(4, pin.length);
  dots.replaceChildren(...Array.from({ length: n }, (_, i) => el("span", { class: i < pin.length ? "on" : "" })));
}

function buildKeypad() {
  const keys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"];
  $("keypad").replaceChildren(...keys.map((k) => el("button", {
    class: "key", type: "button", "aria-label": k === "⌫" ? "Borrar" : k,
    onclick: () => pressKey(k),
  }, k)));
}

function pressKey(k) {
  $("login-error").textContent = "";
  if (k === "⌫") pin = pin.slice(0, -1);
  else if (k === "OK") return submitPin();
  else if (pin.length < 8) pin += k;
  renderDots();
}

async function submitPin() {
  try {
    const res = await api("/api/login", { json: { pin } });
    pin = "";
    startApp(res.pin_is_default);
  } catch (e) {
    pin = "";
    renderDots();
    $("login-error").textContent = e.message;
  }
}

// ---------- tabs ----------

const PAGES = {
  remote: ["Control", "Cambia de canal y el volumen. En el teléfono, abre http://control.local: es solo el control remoto."],
  library: ["Biblioteca", "Todos los videos de la tele, en categorías y programas. Arrastra videos a una carpeta para subirlos."],
  channels: ["Canales", "Cada canal elige qué pasar de la biblioteca, y tiene sus comerciales, logo y ajustes."],
  settings: ["Ajustes", "WiFi, hora de dormir, opciones de la tele, canal guía, respaldo y actualizaciones."],
};
// old addresses (#upload, #more, ...) still open something sensible
const PAGE_ALIASES = { upload: "library", schedule: "channels", more: "settings" };
const wide = window.matchMedia("(min-width: 1000px)");
let currentTab = "remote";

function showTab(name) {
  name = PAGE_ALIASES[name] || name;
  if (!PAGES[name]) name = "remote";
  currentTab = name;
  document.querySelectorAll(".tab").forEach((t) => { t.hidden = t.id !== `tab-${name}`; });
  document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  $("page-title").textContent = PAGES[name][0];
  $("page-sub").textContent = PAGES[name][1];
  if (location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);
  if (name === "library") openLibraryTab();
  if (name === "channels") openChannelsTab();
  if (name === "settings") openSettingsTab();
}

// ---------- remote ----------

async function sendRemote(action, channel) {
  const qs = channel !== undefined ? `?channel=${channel}` : "";
  try {
    await api(`/api/remote/${action}${qs}`, { method: "POST" });
    if (navigator.vibrate) navigator.vibrate(25);
    setTimeout(refreshStatus, 800);
  } catch (e) {
    toast(e.message);
  }
}

async function refreshStatus() {
  try {
    const s = await api("/api/status");
    const asleep = s.power && s.power.state === "off";
    const notTv = s.power && s.power.state !== "on";
    $("onair").hidden = !s.online || notTv;
    $("onair-desk").hidden = !s.online || notTv;
    const playing = s.online && !notTv ? (s.player || {}).channel_number : null;
    if (playing !== currentChannel) { currentChannel = playing; renderChannelButtons(); }
    $("sleeping").hidden = !asleep;
    const p = s.player || {};
    const now = $("now-playing");
    if (notTv) {
      now.textContent = powerText(s.power);
    } else if (!s.online) {
      now.textContent = "La tele está apagada o reiniciándose…";
    } else {
      now.replaceChildren(
        "Canal ", el("b", {}, String(p.channel_number ?? "?")),
        ` · ${(channelsCache.find((c) => c.number === p.channel_number) || {}).long_name || p.network_name || ""}`, el("br"),
        p.title ? `Ahora: ${p.title}` : "Sin programa en este momento",
      );
    }
    $("pin-pad-card").hidden = !(s.online && !notTv && p.awaiting_pin);
    const working = Object.entries(s.rebuilds || {}).filter(([, r]) => r.status === "waiting" || r.status === "running");
    if (working.length) now.append(el("br"), el("span", { class: "muted" }, "Actualizando la programación…"));
  } catch (_) { /* toast already shown or logged out */ }
}

let currentChannel = null;

function renderChannelButtons() {
  $("channel-buttons").replaceChildren(...channelsCache.map((c) => el("button", {
    class: "chbtn" + (c.number === currentChannel ? " current" : ""), onclick: () => sendRemote("channel", c.number),
    title: `Poner el canal ${c.number}`,
  }, el("img", { class: "chlogo", alt: "", loading: "lazy",
    src: `/api/channels/${encodeURIComponent(c.name)}/logo?v=${c.logo && c.logo.custom ? "c" : "d"}` }),
  el("span", { class: "chtext" }, el("span", { class: "num" }, String(c.number)), el("span", {}, c.long_name)))));
}

async function sendDigit(d) {
  try {
    await api(`/api/remote/digit/${d}`, { method: "POST" });
    if (navigator.vibrate) navigator.vibrate(20);
    setTimeout(refreshStatus, 900);
  } catch (e) { toast(e.message); }
}

// ---------- channels / upload ----------

let libraryCache = { categories: [], content: [], folders: [] };
let whenNames = null;

async function loadChannels() {
  const data = await api("/api/channels");
  channelsCache = data.channels;
  libraryCache = data.library;
  whenNames = data.when;
  renderChannelButtons();
  showProblems(data.problems || {});
  return data;
}

function showProblems(problems) {
  const names = Object.keys(problems);
  let box = $("problems");
  if (!names.length) { if (box) box.remove(); return; }
  if (!box) {
    box = el("div", { class: "card warning", id: "problems" });
    $("tab-remote").prepend(box);
  }
  const long = (n) => (channelsCache.find((c) => c.name === n) || { long_name: n }).long_name;
  box.replaceChildren(el("b", {}, "⚠️ No se pudo armar la programación de: " + names.map(long).join(", ")),
    el("br"), el("small", {}, "Revisa que tengan videos. Se reintenta solo al subir, mover o guardar."));
}

function fmtDuration(sec) {
  if (sec == null) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

// ---------- uploads: one at a time, shown in a small dock ----------

let uploadQueue = Promise.resolve();
let uploadsPending = 0;
const afterUpload = [];   // callbacks to refresh whatever screen is open

function uploadFiles(files, channel, tag, where, when = {}) {
  [...files].forEach((file) => uploadOne(file, channel, tag, where, when));
}

function uploadOne(file, channel, tag, where, when) {
  const bar = el("div");
  const label = el("span", {}, "En espera…");
  const item = el("li", {}, el("b", {}, file.name), el("small", { class: "muted" }, `  → ${where}`), el("br"), label,
    el("div", { class: "bar" }, bar));
  $("upload-list").prepend(item);
  $("uploads-dock").hidden = false;
  uploadsPending += 1;
  $("uploads-title").textContent = `Subiendo ${uploadsPending}…`;

  uploadQueue = uploadQueue.then(() => new Promise((resolve) => {
    const form = new FormData();
    if (channel) form.append("channel", channel);
    form.append("tag", tag || "");
    for (const [k, v] of Object.entries(when || {})) if (v) form.append(k, v);
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      const pct = Math.round((ev.loaded / ev.total) * 100);
      bar.style.width = pct + "%";
      label.textContent = `Subiendo… ${pct}% (${formatSize(ev.loaded)} de ${formatSize(ev.total)})`;
    };
    const done = () => {
      uploadsPending -= 1;
      $("uploads-title").textContent = uploadsPending ? `Subiendo ${uploadsPending}…` : "✅ Subidas terminadas";
      resolve();
      if (!uploadsPending) afterUpload.forEach((fn) => fn());
    };
    xhr.onload = () => {
      let detail = "";
      try { detail = JSON.parse(xhr.responseText).detail || ""; } catch (_) { /* ignore */ }
      if (xhr.status === 200) {
        bar.style.width = "100%";
        label.textContent = "✅ Listo. Los canales que lo usan lo pasan en unos minutos.";
      } else {
        item.classList.add("failed");
        label.textContent = `❌ ${detail || "Error " + xhr.status}`;
        if (xhr.status === 401) showLogin();
      }
      done();
    };
    xhr.onerror = () => {
      item.classList.add("failed");
      label.textContent = "❌ Se cortó la conexión con la tele.";
      done();
    };
    xhr.send(form);
  }));
}

// a hidden file picker shared by every "Subir" button
function pickFiles(onFiles) {
  const picker = $("file-picker");
  picker.onchange = () => { onFiles(picker.files); picker.value = ""; };
  picker.click();
}

// ---------- settings: PIN ----------

async function savePin() {
  const msg = $("pin-msg");
  msg.textContent = "";
  try {
    const res = await api("/api/pin", { json: { current_pin: $("pin-current").value, new_pin: $("pin-new").value } });
    $("pin-current").value = "";
    $("pin-new").value = "";
    $("pin-default-warning").hidden = !res.pin_is_default;
    toast("PIN guardado");
  } catch (e) {
    msg.textContent = e.message;
  }
}

// ---------- start ----------

// ---------- start ----------

async function startApp(pinIsDefault) {
  $("view-login").hidden = true;
  $("view-app").hidden = false;
  $("pin-default-warning").hidden = !pinIsDefault;
  let wifiSetup = false;
  try {
    const w = await api("/api/wifi");
    wifiSetup = !!(w.hotspot || w.needs_setup);
  } catch (_) { /* panel without WiFi support */ }
  try { await loadChannels(); } catch (e) { toast(e.message); }
  if (wifiSetup) {
    // opened from the "T-Rex Bites Config" network: WiFi first
    showTab("settings");
    $("wifi-card").scrollIntoView();
  } else if (pinIsDefault) {
    showTab("settings");
    $("pin-card").scrollIntoView();
    toast("Por seguridad, cambia el PIN de fábrica");
  } else {
    showTab(location.hash.slice(1).split("/")[0] || "remote");
  }
  refreshStatus();
  clearInterval(startApp.timer);
  startApp.timer = setInterval(() => { if (!document.hidden) refreshStatus(); }, 10000);
}

function wireUp() {
  buildKeypad();
  document.querySelectorAll("[data-remote]").forEach((b) => b.addEventListener("click", () => sendRemote(b.dataset.remote)));
  document.querySelectorAll(".tabbar button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  const tvKeys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", ""];
  $("tv-keypad").replaceChildren(...tvKeys.map((k) => el("button", {
    class: "key", type: "button", onclick: () => k && sendDigit(k === "⌫" ? "clear" : k),
  }, k)));
  $("uploads-close").addEventListener("click", () => {
    $("uploads-dock").hidden = true;
    if (!uploadsPending) $("upload-list").replaceChildren();
  });
  $("pin-save").addEventListener("click", savePin);
  $("logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }); showLogin(); });
  $("advanced-link").href = `http://${location.hostname}:4242/`;
  window.addEventListener("hashchange", () => {
    const t = location.hash.slice(1).split("/")[0];
    if (t && t !== currentTab && !$("view-app").hidden) showTab(t);
  });
  document.addEventListener("keydown", (e) => {
    if ($("view-login").hidden) return;
    if (/^[0-9]$/.test(e.key)) pressKey(e.key);
    else if (e.key === "Backspace") pressKey("⌫");
    else if (e.key === "Enter") pressKey("OK");
  });
}

// every script is loaded by DOMContentLoaded (library.js, channels.js, ...)
window.addEventListener("DOMContentLoaded", async function init() {
  wireUp();
  try {
    const s = await api("/api/session");
    if (s.logged_in) startApp(s.pin_is_default);
    else showLogin();
  } catch (_) {
    showLogin();
  }
});
