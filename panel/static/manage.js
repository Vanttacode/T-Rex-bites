"use strict";
// Management screens: bedtime, weekly schedule, channels and history.
// Uses $, api, el, toast, loadChannels and channelsCache from app.js.

const DAYS = [
  ["monday", "L", "Lunes"], ["tuesday", "M", "Martes"], ["wednesday", "X", "Miércoles"],
  ["thursday", "J", "Jueves"], ["friday", "V", "Viernes"], ["saturday", "S", "Sábado"],
  ["sunday", "D", "Domingo"],
];
const CATEGORY_COLORS = [
  "#ffb347", "#7ed6ff", "#9cff8a", "#ff8fc7", "#c9a7ff", "#ffe066",
  "#6ef0d0", "#ff9d7a", "#a3c4ff", "#d4ff7a", "#ffc4e1", "#b5f0ff",
];
const OFF = "";
const SIGNOFF = "signoff";

function fmtTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const hhmm = d.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
  const today = new Date();
  const tomorrow = new Date(); tomorrow.setDate(today.getDate() + 1);
  if (d.toDateString() === today.toDateString()) return `hoy a las ${hhmm}`;
  if (d.toDateString() === tomorrow.toDateString()) return `mañana a las ${hhmm}`;
  return d.toLocaleDateString("es", { weekday: "long" }) + ` a las ${hhmm}`;
}

function powerText(power) {
  if (power && power.state === "setup") return "📶 La tele espera que le configures el WiFi (Más → WiFi).";
  if (!power || power.state === "on") {
    if (power && power.reason === "extra") return `⏰ Hora extra hasta ${fmtTime(power.until)}`;
    return "📺 La tele está encendida.";
  }
  if (power.reason === "manual") return `😴 Apagada por ti hasta ${fmtTime(power.until)}`;
  return `😴 Hora de dormir: vuelve ${fmtTime(power.until)}`;
}

// ---------- bedtime ----------

const BT_KEYS = ["sleep_school", "sleep_weekend", "wake_school", "wake_weekend"];

function renderPower(power) {
  $("power-line").textContent = powerText(power);
  const buttons = [];
  const btn = (label, mode, cls = "btn small") =>
    el("button", { class: cls, onclick: () => setPower(mode) }, label);
  if (power.state === "on" && power.reason !== "extra") {
    buttons.push(btn("😴 Apagar hasta mañana", "off", "btn small ghost"));
  }
  if (power.state === "off" && power.reason === "bedtime") {
    buttons.push(btn("⏰ Dar 1 hora extra", "on", "btn small ghost"));
  }
  if (power.reason === "manual" || power.reason === "extra") {
    buttons.push(btn("↩ Volver al horario normal", "auto", "btn small ghost"));
  }
  $("power-buttons").replaceChildren(...buttons);
}

async function loadBedtime() {
  try {
    const data = await api("/api/bedtime");
    $("bt-enabled").checked = data.settings.enabled;
    BT_KEYS.forEach((k) => { $(`bt-${k}`).value = data.settings[k]; });
    renderPower(data.power);
  } catch (e) { toast(e.message); }
}

async function saveBedtime() {
  const body = { enabled: $("bt-enabled").checked };
  BT_KEYS.forEach((k) => { body[k] = $(`bt-${k}`).value; });
  $("bt-msg").textContent = "";
  try {
    const data = await api("/api/bedtime", { method: "PUT", json: body });
    renderPower(data.power);
    toast("Hora de dormir guardada");
  } catch (e) { $("bt-msg").textContent = e.message; }
}

async function setPower(mode) {
  if (mode === "off" && !confirm("¿Apagar la tele hasta mañana?")) return;
  try {
    const data = await api("/api/power", { json: { mode } });
    renderPower(data.power);
    refreshStatus();
  } catch (e) { toast(e.message); }
}

// ---------- schedule tab ----------
// The timeline editor lives in /programacion (made for a computer); on the
// phone this tab keeps bedtime and a link to it.

function openScheduleTab() {
  loadBedtime();
  $("editor-url").textContent = `http://${location.host}/programacion`;
}

// ---------- channels ----------

const editor = { channel: null, cats: [], pautas: [] };

function typeLabel(c) {
  if (c.type === "loop") return "🔁 Todo el día";
  const progs = c.categories.reduce((n, cat) => n + (cat.programs || []).length, 0);
  const base = c.kind === "music" ? "🎵 Música" : "🗓 Con horario";
  return `${base} · ${c.categories.length} categorías${progs ? ` · ${progs} programas` : ""}${c.parental ? " · 🔒" : ""}`;
}

async function openMoreTab() {
  loadWifi();
  loadTvSettings();
  loadGuide();
  loadUpdate(false);
  renderHistory();
  try { await loadChannels(); } catch (e) { toast(e.message); return; }
  $("ch-list").replaceChildren(...channelsCache.map((c) => el("div", { class: "ch-row" },
    el("span", { class: "num" }, String(c.number)),
    el("span", { class: "info" }, c.long_name, el("small", {}, typeLabel(c))),
    el("button", { class: "btn small ghost", onclick: () => openEditor(c) }, "Editar"))));
}

function nextFreeNumber() {
  const used = new Set(channelsCache.map((c) => c.number));
  for (let n = 2; n < 100; n++) if (!used.has(n)) return n;
  return 99;
}

function openEditor(channel) {
  editor.channel = channel;
  editor.cats = channel
    ? channel.categories.map((c) => ({ ...c, programs: (c.programs || []).map((p) => ({ ...p })) }))
    : [{ label: "Dibujos animados", programs: [] }];
  editor.pautas = channel ? (channel.pautas || []).map((x) => ({ ...x })) : [];
  $("ch-editor-title").textContent = channel ? `Editar: ${channel.long_name}` : "Nuevo canal";
  $("ch-name").value = channel ? channel.long_name : "";
  $("ch-number").value = channel ? channel.number : nextFreeNumber();
  $("ch-type-field").hidden = !!channel;
  document.querySelector('input[name="ch-type"][value="standard"]').checked = true;
  $("ch-delete").hidden = !channel;
  $("ch-msg").textContent = "";
  // commercials and logo are set once the channel exists
  const scheduled = channel && channel.type === "standard";
  $("ch-ads-field").hidden = !scheduled;
  $("ch-logo-field").hidden = !channel;
  $("ch-new-note").hidden = !!channel;
  $("ch-parental-field").hidden = !channel;
  $("ch-parental").checked = !!(channel && channel.parental);
  if (scheduled) {
    const ads = channel.ads || { enabled: false, strategy: "end", duration: 120 };
    $("ch-ads-on").checked = ads.enabled;
    $("ch-ads-strategy").value = ads.strategy;
    const dur = $("ch-ads-duration");
    if (![...dur.options].some((o) => Number(o.value) === ads.duration)) {
      dur.append(el("option", { value: String(ads.duration) }, `${ads.duration} segundos`));
    }
    dur.value = String(ads.duration);
    $("ch-ads-opts").hidden = !ads.enabled;
  }
  if (channel) {
    const logo = channel.logo || { show: true, permanent: true, custom: false };
    $("ch-logo-show").checked = logo.show;
    $("ch-logo-permanent").checked = logo.permanent;
    $("ch-logo-reset").hidden = !logo.custom;
    refreshLogoPreview(channel.name);
  }
  renderCats();
  $("ch-editor").hidden = false;
  $("ch-editor").scrollIntoView({ behavior: "smooth" });
}

function editorType() {
  return editor.channel ? editor.channel.type : document.querySelector('input[name="ch-type"]:checked').value;
}

function nameInput(item, label) {
  const input = el("input", { type: "text", maxlength: "30", value: item.label, "aria-label": label });
  input.addEventListener("input", () => { item.label = input.value; });
  return input;
}

function renderCats() {
  const type = editorType();
  $("ch-cats-field").hidden = type === "loop";
  if (!editor.channel && type === "music" && editor.cats.length === 1 && editor.cats[0].label === "Dibujos animados") {
    editor.cats = [{ label: "Videos musicales", programs: [] }];
  } else if (!editor.channel && type === "standard" && editor.cats.length === 1 && editor.cats[0].label === "Videos musicales") {
    editor.cats = [{ label: "Dibujos animados", programs: [] }];
  }
  $("ch-cats").replaceChildren(...editor.cats.map((cat, i) => {
    const swatch = el("span", { class: "swatch" });
    swatch.style.background = CATEGORY_COLORS[i % CATEGORY_COLORS.length];
    const li = el("li", { class: "cat-item" },
      el("div", { class: "cat-row" }, swatch, nameInput(cat, "Nombre de la categoría"),
        el("button", { class: "btn small danger", type: "button", "aria-label": `Quitar ${cat.label}`,
          onclick: () => { editor.cats.splice(i, 1); renderCats(); } }, "✕")));
    if (editor.channel) {
      const progs = el("ul", { class: "prog-list" }, ...cat.programs.map((p, j) => el("li", {},
        el("span", { class: "muted" }, "↳"), nameInput(p, "Nombre del programa"),
        el("button", { class: "btn small danger", type: "button", "aria-label": `Quitar ${p.label}`,
          onclick: () => { cat.programs.splice(j, 1); renderCats(); } }, "✕"))));
      const add = el("input", { type: "text", maxlength: "30", placeholder: "＋ Programa (ej: Bluey)" });
      const addIt = () => { const v = add.value.trim(); if (v) { cat.programs.push({ label: v }); renderCats(); } };
      add.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addIt(); } });
      add.addEventListener("change", addIt);
      progs.append(el("li", { class: "prog-add" }, el("span", { class: "muted" }, "↳"), add));
      li.append(progs);
    }
    return li;
  }));
  renderPautas();
}

function renderPautas() {
  $("ch-pautas").replaceChildren(...editor.pautas.map((pa, i) => el("li", {},
    el("span", { class: "swatch" }, "📺"), nameInput(pa, "Nombre de la pauta"),
    el("button", { class: "btn small danger", type: "button", "aria-label": `Quitar ${pa.label}`,
      onclick: () => { editor.pautas.splice(i, 1); renderPautas(); } }, "✕"))));
}

function addPauta() {
  const label = $("ch-pauta-new").value.trim();
  if (!label) return;
  editor.pautas.push({ label });
  $("ch-pauta-new").value = "";
  renderPautas();
}

function addCat() {
  const label = $("ch-cat-new").value.trim();
  if (!label) return;
  editor.cats.push({ label, programs: [] });
  $("ch-cat-new").value = "";
  renderCats();
}

async function saveChannel() {
  const named = (x) => (x.tag ? { tag: x.tag, label: x.label } : x.label);
  const categories = editor.cats.map((c) => ({
    ...(c.tag ? { tag: c.tag } : {}), label: c.label, programs: (c.programs || []).map(named),
  }));
  const body = { long_name: $("ch-name").value, number: Number($("ch-number").value) };
  $("ch-msg").textContent = "";
  try {
    if (editor.channel) {
      body.parental = $("ch-parental").checked;
      if (editor.channel.type === "standard") {
        body.categories = categories;
        body.pautas = editor.pautas.map(named);
        body.ads = {
          enabled: $("ch-ads-on").checked,
          strategy: $("ch-ads-strategy").value,
          duration: Number($("ch-ads-duration").value),
        };
      }
      body.logo = { show: $("ch-logo-show").checked, permanent: $("ch-logo-permanent").checked };
      await api(`/api/channels/${encodeURIComponent(editor.channel.name)}`, { method: "PUT", json: body });
      toast("Canal guardado");
    } else {
      body.type = editorType();
      if (body.type !== "loop") body.categories = editor.cats.map((c) => c.label);
      await api("/api/channels", { json: body });
      toast("Canal creado. La tele se reinicia en unos segundos.");
    }
    $("ch-editor").hidden = true;
    openMoreTab();
  } catch (e) { $("ch-msg").textContent = e.message; }
}

async function deleteChannel() {
  const c = editor.channel;
  if (!confirm(`¿Borrar el canal ${c.number} · ${c.long_name}?\n\nSus videos NO se borran del disco.`)) return;
  try {
    await api(`/api/channels/${encodeURIComponent(c.name)}`, { method: "DELETE" });
    toast("Canal borrado");
    $("ch-editor").hidden = true;
    openMoreTab();
  } catch (e) { $("ch-msg").textContent = e.message; }
}

function refreshLogoPreview(name) {
  $("ch-logo-img").src = `/api/channels/${encodeURIComponent(name)}/logo?t=${Date.now()}`;
}

async function uploadLogo(file) {
  if (!file || !editor.channel) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const resp = await fetch(`/api/channels/${encodeURIComponent(editor.channel.name)}/logo`,
      { method: "POST", body: form, credentials: "same-origin" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `Error ${resp.status}`);
    toast("Logo guardado. La tele lo muestra en unos segundos.");
    $("ch-logo-reset").hidden = false;
    refreshLogoPreview(editor.channel.name);
  } catch (e) { $("ch-msg").textContent = e.message; }
}

async function resetLogo() {
  if (!editor.channel) return;
  try {
    await api(`/api/channels/${encodeURIComponent(editor.channel.name)}/logo`, { method: "DELETE" });
    toast("Ahora usa el logo de T-Rex Bites");
    $("ch-logo-reset").hidden = true;
    refreshLogoPreview(editor.channel.name);
  } catch (e) { $("ch-msg").textContent = e.message; }
}

// ---------- history ----------

function dayName(iso, index) {
  if (index === 0) return "Hoy";
  if (index === 1) return "Ayer";
  const d = new Date(iso + "T12:00:00");
  const s = d.toLocaleDateString("es", { weekday: "long", day: "numeric", month: "short" });
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function fmtMinutes(m) {
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${m % 60 ? (m % 60) + " min" : ""}`.trim();
}

async function renderHistory() {
  try {
    const data = await api("/api/history?days=7");
    const max = Math.max(60, ...data.days.map((d) => d.total_minutes));
    $("history").replaceChildren(...data.days.map((d, i) => {
      const bar = el("div", { class: "hist-bar" });
      bar.style.width = `${Math.round((d.total_minutes / max) * 100)}%`;
      const box = el("details", { class: "hist-day" },
        el("summary", {}, el("span", {}, dayName(d.day, i)), el("b", {}, fmtMinutes(d.total_minutes))), bar);
      if (!d.programs.length) box.append(el("div", { class: "hist-prog" }, "Sin registros"));
      d.programs.forEach((p) => box.append(el("div", { class: "hist-prog" },
        el("span", {}, `${p.title} · ${p.channel_name}`), el("span", {}, fmtMinutes(p.minutes)))));
      if (i === 0) box.open = true;
      return box;
    }));
  } catch (e) { $("history").textContent = e.message; }
}

// ---------- wiring ----------

function wireManagement() {
  $("bt-save").addEventListener("click", saveBedtime);
  $("ch-new").addEventListener("click", () => openEditor(null));
  $("ch-cancel").addEventListener("click", () => { $("ch-editor").hidden = true; });
  $("ch-save").addEventListener("click", saveChannel);
  $("ch-delete").addEventListener("click", deleteChannel);
  $("ch-cat-add").addEventListener("click", addCat);
  $("ch-pauta-add").addEventListener("click", addPauta);
  $("ch-pauta-new").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addPauta(); } });
  $("ch-cat-new").addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); addCat(); } });
  document.querySelectorAll('input[name="ch-type"]').forEach((r) => r.addEventListener("change", renderCats));
  $("ch-ads-on").addEventListener("change", (e) => { $("ch-ads-opts").hidden = !e.target.checked; });
  $("ch-logo-file").addEventListener("change", (e) => { uploadLogo(e.target.files[0]); e.target.value = ""; });
  $("ch-logo-reset").addEventListener("click", resetLogo);
}

wireManagement();
