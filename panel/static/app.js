"use strict";

const $ = (id) => document.getElementById(id);
let channelsCache = [];
let whenOptions = null;
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
    const notTv = s.power && s.power.state !== "on";
    $("onair").hidden = !s.online || notTv;
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
        ` · ${p.network_name || ""}`, el("br"),
        p.title ? `Ahora: ${p.title}` : "Sin programa en este momento",
      );
    }
    $("pin-pad-card").hidden = !(s.online && !notTv && p.awaiting_pin);
    const working = Object.entries(s.rebuilds || {}).filter(([, r]) => r.status === "waiting" || r.status === "running");
    if (working.length) now.append(el("br"), el("span", { class: "muted" }, "Actualizando la programación…"));
  } catch (_) { /* toast already shown or logged out */ }
}

function renderChannelButtons() {
  $("channel-buttons").replaceChildren(...channelsCache.map((c) => el("button", {
    class: "chbtn", onclick: () => sendRemote("channel", c.number),
  }, el("span", { class: "num" }, String(c.number)), c.long_name)));
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

async function loadChannels() {
  const data = await api("/api/channels");
  channelsCache = data.channels;
  libraryCache = data.library;
  if (data.when && !whenOptions) { whenOptions = data.when; fillWhen(); }
  renderChannelButtons();
  fillDest();
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

// "where to upload": the library (shared) or one channel's own folders
const destValue = (channel, tag) => `${channel || ""}|${tag ?? ""}`;
function parseDest(value) {
  const i = value.indexOf("|");
  return { channel: value.slice(0, i) || null, tag: value.slice(i + 1) || null };
}

function destGroups(selected, includeChannels = true) {
  const groups = [];
  const lib = el("optgroup", { label: "📚 Biblioteca" });
  for (const c of libraryCache.content) {
    const program = c.tag.includes("/");
    lib.append(el("option", { value: destValue(null, c.tag) }, program ? `   ↳ ${c.label.split(" › ").pop()}` : c.label));
  }
  groups.push(lib);
  if (includeChannels) {
    for (const ch of channelsCache) {
      if (!ch.folders.length) continue;
      const g = el("optgroup", { label: `📺 ${ch.number} · ${ch.long_name}` });
      ch.folders.forEach((f) => g.append(el("option", { value: destValue(ch.name, f.tag) }, f.label)));
      groups.push(g);
    }
  }
  groups.forEach((g) => [...g.children].forEach((o) => { if (o.value === selected) o.selected = true; }));
  return groups;
}

function destLabel(value) {
  const { channel, tag } = parseDest(value);
  if (!channel) return (libraryCache.content.find((c) => c.tag === tag) || { label: tag }).label;
  const ch = channelsCache.find((c) => c.name === channel);
  const f = ch && ch.folders.find((x) => x.tag === tag);
  return ch ? `${ch.long_name} › ${f ? f.label : tag}` : value;
}

function fillDest() {
  const sel = $("up-dest");
  const prev = sel.value;
  sel.replaceChildren(el("option", { value: "" }, "— Elige dónde —"), ...destGroups(prev));
  updateDropLabel();
}

function updateDropLabel() {
  const v = $("up-dest").value;
  $("up-drop-label").textContent = v ? `📼 Subir a: ${destLabel(v)}` : "📼 Primero elige dónde guardarlo (arriba)";
  $("dropzone").classList.toggle("disabled", !v);
}

function fillWhen() {
  const opts = (sel, first, map) => $(sel).replaceChildren(el("option", { value: "" }, first),
    ...Object.entries(map).map(([k, v]) => el("option", { value: k }, v)));
  opts("up-when-part", "Todo el día", whenOptions.parts);
  opts("up-when-day", "Todos los días", whenOptions.days);
  opts("up-when-month", "Todo el año", whenOptions.months);
}

function whenSummary() {
  const bits = ["up-when-part", "up-when-day", "up-when-month"]
    .map((id) => $(id)).filter((s) => s.value).map((s) => s.selectedOptions[0].textContent.split(" (")[0]);
  $("up-when-sum").textContent = bits.length ? bits.join(" · ") : "Siempre";
}

async function refreshDisk() {
  try {
    const d = await api("/api/disk");
    $("disk-info").textContent = `Espacio libre en la tele: ${formatSize(d.free)} de ${formatSize(d.total)}`;
  } catch (_) { /* ignore */ }
}

function uploadFiles(files) {
  const dest = $("up-dest").value;
  if (!dest) { toast("Primero elige dónde guardarlo"); $("up-dest").focus(); return; }
  const { channel, tag } = parseDest(dest);
  const when = { when_part: $("up-when-part").value, when_day: $("up-when-day").value, when_month: $("up-when-month").value };
  [...files].forEach((file) => uploadOne(file, channel, tag, when, destLabel(dest)));
}

// one upload at a time keeps an old laptop and the home WiFi responsive
let uploadQueue = Promise.resolve();

function uploadOne(file, channel, tag, when = {}, where = "") {
  const bar = el("div");
  const label = el("span", {}, "En espera…");
  const item = el("li", {}, el("b", {}, file.name), el("small", { class: "muted" }, `  → ${where}`), el("br"), label,
    el("div", { class: "bar" }, bar));
  $("upload-list").prepend(item);

  uploadQueue = uploadQueue.then(() => new Promise((resolve) => {
    const form = new FormData();
    if (channel) form.append("channel", channel);
    form.append("tag", tag || "");
    for (const [k, v] of Object.entries(when)) if (v) form.append(k, v);
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
        label.textContent = "✅ Listo. Los canales que lo usan lo pasan en unos minutos.";
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

function fmtDuration(sec) {
  if (sec == null) return "";
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`;
}

const probed = new Set();
const selection = new Map();   // key -> {channel, tag, name}
const openFolders = new Set();
const selKey = (channel, tag, name) => `${channel || ""}|${tag || ""}|${name}`;

async function renderLibrary() {
  try {
    await loadChannels();
  } catch (e) {
    $("library").replaceChildren(el("p", { class: "error" }, e.message));
    return;
  }
  drawLibrary();
}

function folderBlock(channel, f, q, sizes) {
  const videos = f.videos.filter((v) => !q || v.name.toLowerCase().includes(q));
  if (q && !videos.length) return null;
  const total = f.videos.reduce((s, v) => s + (v.duration || 0), 0);
  const real = f.videos.filter((v) => !v.placeholder).length;
  const isProgram = f.tag && f.tag.includes("/");
  const key = `${channel || ""}|${f.tag}`;
  const label = isProgram ? `↳ ${f.label.split(" › ").pop()}` : f.label;
  const head = el("summary", {}, el("span", {}, label),
    el("small", { class: "muted" }, ` ${real} videos${total ? " · " + fmtDuration(total) : ""}`));
  const block = el("details", { class: "lib-folder" + (isProgram ? " program" : "") }, head);
  block.open = !!q || openFolders.has(key);
  block.addEventListener("toggle", () => {
    if (block.open) { openFolders.add(key); probeFolder(channel, f); } else openFolders.delete(key);
  });
  if (!videos.length) block.append(el("p", { class: "muted" }, "Todavía no hay videos aquí."));
  if (videos.some((v) => !v.placeholder)) {
    const all = el("input", { type: "checkbox", "aria-label": "Elegir todos" });
    all.checked = videos.filter((v) => !v.placeholder).every((v) => selection.has(selKey(channel, f.tag, v.name)));
    all.addEventListener("change", () => {
      videos.filter((v) => !v.placeholder).forEach((v) => {
        const k = selKey(channel, f.tag, v.name);
        if (all.checked) selection.set(k, { channel, tag: f.tag, name: v.name }); else selection.delete(k);
      });
      drawLibrary();
    });
    block.append(el("label", { class: "switch selall" }, all, " Elegir todos"));
  }
  for (const v of videos) {
    const k = selKey(channel, f.tag, v.name);
    const name = el("span", { class: "name" }, v.file || v.name);
    if (v.placeholder) name.append(el("span", { class: "badge" }, "de ejemplo"));
    if (v.when) name.append(el("span", { class: "badge when" }, "🕒 " + v.when));
    if (!v.placeholder && sizes[v.size] > 1) name.append(el("span", { class: "badge dup" }, "repetido"));
    const qs = `channel=${encodeURIComponent(channel || "")}&tag=${encodeURIComponent(f.tag ?? "")}&name=${encodeURIComponent(v.name)}`;
    const thumb = el("img", { class: "thumb", loading: "lazy", alt: "", src: `/api/library/thumb?${qs}` });
    const meta = el("span", { class: "size" }, [fmtDuration(v.duration), formatSize(v.size)].filter(Boolean).join(" · "));
    const box = el("input", { type: "checkbox", "aria-label": `Elegir ${v.name}` });
    box.checked = selection.has(k);
    box.disabled = v.placeholder;
    box.addEventListener("change", () => {
      if (box.checked) selection.set(k, { channel, tag: f.tag, name: v.name }); else selection.delete(k);
      updateSelbar();
    });
    block.append(el("label", { class: "video-row" + (box.checked ? " picked" : "") }, box, thumb,
      el("span", { class: "vinfo" }, name, meta)));
  }
  return block;
}

function drawLibrary() {
  const q = $("lib-search").value.trim().toLowerCase();
  const sizes = {};
  const count = (folders) => folders.forEach((f) => f.videos.forEach((v) => { if (!v.placeholder) sizes[v.size] = (sizes[v.size] || 0) + 1; }));
  count(libraryCache.folders);
  const libCard = el("div", { class: "card" });
  libraryCache.folders.forEach((f) => { const b = folderBlock(null, f, q, sizes); if (b) libCard.append(b); });
  const cards = [libCard];
  for (const c of channelsCache) {
    if (!c.folders.length) continue;
    const card = el("div", { class: "card" }, el("h2", {}, `📺 ${c.number} · ${c.long_name}`),
      el("p", { class: "muted small" }, "Lo propio de este canal."));
    let any = false;
    c.folders.forEach((f) => { const b = folderBlock(c.name, f, q, {}); if (b) { card.append(b); any = true; } });
    if (any) cards.push(card);
  }
  $("library").replaceChildren(...cards);
  updateSelbar();
}

function updateSelbar() {
  const n = selection.size;
  $("selbar").hidden = n === 0;
  $("sel-count").textContent = `${n} elegido${n === 1 ? "" : "s"}`;
  const sel = $("sel-dest");
  const prev = sel.value;
  sel.replaceChildren(el("option", { value: "" }, "Mover a…"), ...destGroups(prev));
}

async function moveSelected() {
  const dest = $("sel-dest").value;
  if (!dest) { toast("Elige a dónde moverlos"); return; }
  const { channel, tag } = parseDest(dest);
  try {
    const r = await api("/api/library/move-many", { json: { items: [...selection.values()], to_channel: channel, to_tag: tag } });
    selection.clear();
    toast(`${r.moved} videos movidos a ${destLabel(dest)}`);
    renderLibrary();
  } catch (e) { toast(e.message); }
}

async function deleteSelected() {
  const n = selection.size;
  if (!confirm(`¿Borrar ${n} video${n === 1 ? "" : "s"}? No se puede deshacer.`)) return;
  try {
    const r = await api("/api/library/delete-many", { json: { items: [...selection.values()] } });
    selection.clear();
    toast(`${r.deleted} videos borrados`);
    renderLibrary();
  } catch (e) { toast(e.message); }
}

async function probeFolder(channel, f) {
  const key = `${channel}|${f.tag}`;
  if (probed.has(key) || !f.videos.some((v) => v.duration == null && !v.placeholder)) return;
  probed.add(key);
  try {
    const res = await api("/api/library/probe", { json: { channel, tag: f.tag } });
    let changed = false;
    f.videos.forEach((v) => { if (res.durations[v.name] != null && v.duration == null) { v.duration = res.durations[v.name]; changed = true; } });
    if (changed) drawLibrary();
  } catch (_) { /* durations are a nice-to-have */ }
}

// ---------- categories and programs ----------

let libEdit = [];

function openLibEditor() {
  libEdit = libraryCache.categories.map((c) => ({ ...c, programs: c.programs.map((p) => ({ ...p })) }));
  $("lib-msg").textContent = "";
  $("lib-editor").hidden = false;
  renderLibEditor();
  $("lib-editor").scrollIntoView({ behavior: "smooth" });
}

function nameField(item, label) {
  const input = el("input", { type: "text", maxlength: "30", value: item.label, "aria-label": label });
  input.addEventListener("input", () => { item.label = input.value; });
  return input;
}

function renderLibEditor() {
  $("lib-cats").replaceChildren(...libEdit.map((cat, i) => {
    const li = el("li", { class: "cat-item" },
      el("div", { class: "cat-row" }, el("span", { class: "swatch" }, "📁"), nameField(cat, "Nombre de la categoría"),
        el("button", { class: "btn small danger", type: "button", "aria-label": `Quitar ${cat.label}`,
          onclick: () => { libEdit.splice(i, 1); renderLibEditor(); } }, "✕")));
    const progs = el("ul", { class: "prog-list" }, ...cat.programs.map((p, j) => el("li", {},
      el("span", { class: "muted" }, "↳"), nameField(p, "Nombre del programa"),
      el("button", { class: "btn small danger", type: "button", "aria-label": `Quitar ${p.label}`,
        onclick: () => { cat.programs.splice(j, 1); renderLibEditor(); } }, "✕"))));
    const add = el("input", { type: "text", maxlength: "30", placeholder: "＋ Programa (ej: Bluey)" });
    // Enter and leaving the box both add it: clear first so it is added once
    const addIt = () => { const v = add.value.trim(); add.value = ""; if (v) { cat.programs.push({ label: v }); renderLibEditor(); } };
    add.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addIt(); } });
    add.addEventListener("change", addIt);
    progs.append(el("li", { class: "prog-add" }, el("span", { class: "muted" }, "↳"), add));
    li.append(progs);
    return li;
  }));
}

function addLibCat() {
  const label = $("lib-cat-new").value.trim();
  if (!label) return;
  libEdit.push({ label, programs: [] });
  $("lib-cat-new").value = "";
  renderLibEditor();
}

async function saveLibEditor() {
  const named = (x) => (x.tag ? { tag: x.tag, label: x.label } : x.label);
  const categories = libEdit.map((c) => ({ ...(c.tag ? { tag: c.tag } : {}), label: c.label, programs: c.programs.map(named) }));
  $("lib-msg").textContent = "";
  try {
    await api("/api/library", { method: "PUT", json: { categories } });
    toast("Biblioteca guardada");
    $("lib-editor").hidden = true;
    renderLibrary();
  } catch (e) { $("lib-msg").textContent = e.message; }
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
  let wifiSetup = false;
  try {
    const w = await api("/api/wifi");
    wifiSetup = !!(w.hotspot || w.needs_setup);
  } catch (_) { /* panel without WiFi support */ }
  if (wifiSetup) {
    // opened from the "T-Rex Bites Config" network: WiFi first
    showTab("more");
    $("wifi-card").scrollIntoView();
  } else if (pinIsDefault) {
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
  $("up-dest").addEventListener("change", updateDropLabel);
  $("lib-organize").addEventListener("click", openLibEditor);
  $("lib-cancel").addEventListener("click", () => { $("lib-editor").hidden = true; });
  $("lib-save").addEventListener("click", saveLibEditor);
  $("lib-cat-add").addEventListener("click", addLibCat);
  $("lib-cat-new").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addLibCat(); } });
  $("sel-move").addEventListener("click", moveSelected);
  $("sel-delete").addEventListener("click", deleteSelected);
  $("sel-clear").addEventListener("click", () => { selection.clear(); drawLibrary(); });
  ["up-when-part", "up-when-day", "up-when-month"].forEach((id) => $(id).addEventListener("change", whenSummary));
  $("lib-search").addEventListener("input", drawLibrary);
  const tvKeys = ["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", ""];
  $("tv-keypad").replaceChildren(...tvKeys.map((k) => el("button", {
    class: "key", type: "button", onclick: () => k && sendDigit(k === "⌫" ? "clear" : k),
  }, k)));
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
