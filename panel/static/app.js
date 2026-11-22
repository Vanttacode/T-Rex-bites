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

function showTab(name) {
  document.querySelectorAll(".tab").forEach((t) => { t.hidden = t.id !== `tab-${name}`; });
  document.querySelectorAll(".tabbar button").forEach((b) => b.classList.toggle("active", b.dataset.tab === name));
  if (name === "library") renderLibrary();
  if (name === "upload") refreshDisk();
  if (name === "schedule") openScheduleTab();
  if (name === "more") openMoreTab();
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
    $("onair").hidden = !s.online || asleep;
    $("sleeping").hidden = !asleep;
    const p = s.player || {};
    const now = $("now-playing");
    if (asleep) {
      now.textContent = powerText(s.power);
    } else if (!s.online) {
      now.textContent = "La tele está apagada o reiniciándose…";
    } else {
      now.replaceChildren(
        "Canal ", el("b", {}, String(p.channel_number ?? "?")),
        ` · ${p.network_name || ""}`, el("br"),
        p.title ? `Ahora: ${p.title}` : "Sin programa en este momento",
      );
    }
    const working = Object.entries(s.rebuilds || {}).filter(([, r]) => r.status === "waiting" || r.status === "running");
    if (working.length) now.append(el("br"), el("span", { class: "muted" }, "Actualizando la programación…"));
  } catch (_) { /* toast already shown or logged out */ }
}

function renderChannelButtons() {
  $("channel-buttons").replaceChildren(...channelsCache.map((c) => el("button", {
    class: "chbtn", onclick: () => sendRemote("channel", c.number),
  }, el("span", { class: "num" }, String(c.number)), c.long_name)));
}

// ---------- channels / upload ----------

async function loadChannels() {
  const data = await api("/api/channels");
  channelsCache = data.channels;
  renderChannelButtons();
  const sel = $("up-channel");
  const previous = sel.value;
  sel.replaceChildren(...channelsCache.map((c) => el("option", { value: c.name }, `${c.number} · ${c.long_name}`)));
  if (previous) sel.value = previous;
  fillTags();
}

function fillTags() {
  const ch = channelsCache.find((c) => c.name === $("up-channel").value);
  const tagSel = $("up-tag");
  tagSel.replaceChildren(...(ch ? ch.folders : []).map((f) => el("option", { value: f.tag ?? "" }, f.label)));
  tagSel.parentElement.hidden = !ch || (ch.folders.length === 1 && ch.folders[0].tag === null);
}

async function refreshDisk() {
  try {
    const d = await api("/api/disk");
    $("disk-info").textContent = `Espacio libre en la tele: ${formatSize(d.free)} de ${formatSize(d.total)}`;
  } catch (_) { /* ignore */ }
}

function uploadFiles(files) {
  const channel = $("up-channel").value;
  const tag = $("up-tag").value;
  if (!channel) { toast("Primero elige un canal"); return; }
  [...files].forEach((file) => uploadOne(file, channel, tag));
}

// one upload at a time keeps an old laptop and the home WiFi responsive
let uploadQueue = Promise.resolve();

function uploadOne(file, channel, tag) {
  const bar = el("div");
  const label = el("span", {}, "En espera…");
  const item = el("li", {}, el("b", {}, file.name), el("br"), label, el("div", { class: "bar" }, bar));
  $("upload-list").prepend(item);

  uploadQueue = uploadQueue.then(() => new Promise((resolve) => {
    const form = new FormData();
    form.append("channel", channel);
    form.append("tag", tag);
    form.append("file", file);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (ev) => {
      if (!ev.lengthComputable) return;
      const pct = Math.round((ev.loaded / ev.total) * 100);
      bar.style.width = pct + "%";
      label.textContent = `Subiendo… ${pct}% (${formatSize(ev.loaded)} de ${formatSize(ev.total)})`;
    };
    xhr.onload = () => {
      let detail = "";
      try { detail = JSON.parse(xhr.responseText).detail || ""; } catch (_) { /* ignore */ }
      if (xhr.status === 200) {
        bar.style.width = "100%";
        label.textContent = "✅ Listo. Aparecerá en la programación en unos minutos.";
      } else {
        item.classList.add("failed");
        label.textContent = `❌ ${detail || "Error " + xhr.status}`;
        if (xhr.status === 401) showLogin();
      }
      refreshDisk();
      resolve();
    };
    xhr.onerror = () => {
      item.classList.add("failed");
      label.textContent = "❌ Se cortó la conexión con la tele.";
      resolve();
    };
    xhr.send(form);
  }));
}

// ---------- library ----------

async function renderLibrary() {
  const root = $("library");
  try {
    await loadChannels();
  } catch (e) {
    root.replaceChildren(el("p", { class: "error" }, e.message));
    return;
  }
  root.replaceChildren(...channelsCache.map((c) => {
    const card = el("div", { class: "card" }, el("h2", {}, `${c.number} · ${c.long_name}`));
    for (const f of c.folders) {
      const block = el("div", { class: "lib-folder" }, el("h3", {}, `${f.label} (${f.videos.length})`));
      if (!f.videos.length) block.append(el("p", { class: "muted" }, "Todavía no hay videos aquí."));
      for (const v of f.videos) {
        const name = el("span", { class: "name" }, v.name);
        if (v.placeholder) name.append(el("span", { class: "badge" }, "de ejemplo"));
        block.append(el("div", { class: "video-row" }, name,
          el("span", { class: "size" }, formatSize(v.size)),
          el("button", { class: "btn danger", "aria-label": `Borrar ${v.name}`, onclick: () => deleteVideo(c, f, v) }, "🗑")));
      }
      card.append(block);
    }
    return card;
  }));
}

async function deleteVideo(channel, folder, video) {
  if (!confirm(`¿Borrar "${video.name}" de ${channel.long_name}?`)) return;
  try {
    await api("/api/library/delete", { json: { channel: channel.name, tag: folder.tag, name: video.name } });
    toast("Video borrado");
    renderLibrary();
  } catch (e) {
    toast(e.message);
  }
}

// ---------- settings ----------

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

async function startApp(pinIsDefault) {
  $("view-login").hidden = true;
  $("view-app").hidden = false;
  $("pin-default-warning").hidden = !pinIsDefault;
  if (pinIsDefault) {
    showTab("more");
    $("pin-card").scrollIntoView();
    toast("Por seguridad, cambia el PIN de fábrica");
  } else {
    showTab("remote");
  }
  try { await loadChannels(); } catch (e) { toast(e.message); }
  refreshStatus();
  clearInterval(startApp.timer);
  startApp.timer = setInterval(() => { if (!document.hidden) refreshStatus(); }, 10000);
}

function wireUp() {
  buildKeypad();
  document.querySelectorAll("[data-remote]").forEach((b) => b.addEventListener("click", () => sendRemote(b.dataset.remote)));
  document.querySelectorAll(".tabbar button").forEach((b) => b.addEventListener("click", () => showTab(b.dataset.tab)));
  $("up-channel").addEventListener("change", fillTags);
  $("up-files").addEventListener("change", (e) => { uploadFiles(e.target.files); e.target.value = ""; });
  const dz = $("dropzone");
  dz.addEventListener("dragover", (e) => { e.preventDefault(); dz.classList.add("over"); });
  dz.addEventListener("dragleave", () => dz.classList.remove("over"));
  dz.addEventListener("drop", (e) => { e.preventDefault(); dz.classList.remove("over"); uploadFiles(e.dataTransfer.files); });
  $("pin-save").addEventListener("click", savePin);
  $("logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }); showLogin(); });
  $("advanced-link").href = `http://${location.hostname}:4242/`;
  document.addEventListener("keydown", (e) => {
    if ($("view-login").hidden) return;
    if (/^[0-9]$/.test(e.key)) pressKey(e.key);
    else if (e.key === "Backspace") pressKey("⌫");
    else if (e.key === "Enter") pressKey("OK");
  });
}

(async function init() {
  wireUp();
  try {
    const s = await api("/api/session");
    if (s.logged_in) startApp(s.pin_is_default);
    else showLogin();
  } catch (_) {
    showLogin();
  }
})();
