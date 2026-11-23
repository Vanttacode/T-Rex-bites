"use strict";
// TV options, guide channel, backup and USB import.
// Uses $, api, el, toast, formatSize, loadChannels and channelsCache from app.js.

// ---------- TV options ----------

function convertingText(c) {
  if (!c) return "";
  const n = c.waiting.length + (c.current ? 1 : 0);
  if (!n) return "";
  const name = c.current ? c.current.split("/").pop() : "";
  return `⚙️ Convirtiendo ${n} video(s)${name ? ` · ahora: ${name}` : ""}`;
}

async function loadTvSettings() {
  try {
    const s = await api("/api/tv-settings");
    $("tv-transition").replaceChildren(...Object.entries(s.transitions).map(([k, v]) => el("option", { value: k }, v)));
    $("tv-transition").value = s.transition;
    $("tv-convert").checked = s.convert;
    $("tv-normalize").checked = s.normalize;
    $("tv-pin").value = "";
    $("tv-pin").placeholder = s.channel_pin_set ? "•••• (déjalo vacío para no cambiarlo)" : "Sin PIN";
    $("tv-converting").textContent = convertingText(s.converting);
  } catch (e) { $("tv-msg").textContent = e.message; }
}

async function saveTvSettings() {
  $("tv-msg").textContent = "";
  const body = {
    transition: $("tv-transition").value,
    convert: $("tv-convert").checked,
    normalize: $("tv-normalize").checked,
  };
  const pin = $("tv-pin").value.trim();
  if (pin) body.channel_pin = pin;
  try {
    await api("/api/tv-settings", { method: "PUT", json: body });
    toast("Opciones guardadas. La tele se reinicia en unos segundos.");
    loadTvSettings();
  } catch (e) { $("tv-msg").textContent = e.message; }
}

async function removeChannelPin() {
  if (!confirm("¿Quitar el PIN de canales? Los canales con candado se verán sin pedir nada.")) return;
  try {
    await api("/api/tv-settings", { method: "PUT", json: { channel_pin: "" } });
    toast("PIN de canales quitado");
    loadTvSettings();
  } catch (e) { $("tv-msg").textContent = e.message; }
}

async function convertAll() {
  if (!confirm("Se revisan todos los videos y se convierten los que haga falta. En un computador lento puede tardar horas (la tele sigue funcionando). ¿Seguir?")) return;
  try {
    const r = await api("/api/library/convert", { json: {} });
    toast(`${r.queued} videos en revisión`);
    loadTvSettings();
  } catch (e) { toast(e.message); }
}

// ---------- guide channel ----------

function renderGuideMusic(music) {
  $("guide-music").replaceChildren(...(music.length ? music : []).map((m) => el("li", {},
    el("span", {}, `🎵 ${m.name}`), el("small", { class: "muted" }, ` ${formatSize(m.size)}`),
    el("button", { class: "btn small danger", type: "button", "aria-label": `Borrar ${m.name}`,
      onclick: () => deleteGuideMusic(m.name) }, "✕"))));
  if (!music.length) $("guide-music").append(el("li", { class: "muted small" }, "Sin música: la guía se ve en silencio."));
}

async function loadGuide() {
  try {
    const g = await api("/api/guide");
    $("guide-on").checked = g.enabled;
    $("guide-number").value = g.number ?? 1;
    renderGuideMusic(g.music);
  } catch (e) { $("guide-msg").textContent = e.message; }
}

async function saveGuide() {
  $("guide-msg").textContent = "";
  try {
    await api("/api/guide", { method: "PUT", json: { enabled: $("guide-on").checked, number: Number($("guide-number").value) || 1 } });
    toast($("guide-on").checked ? "Canal guía listo. La tele se reinicia en unos segundos." : "Canal guía quitado");
    loadGuide();
    loadChannels().catch(() => {});
  } catch (e) { $("guide-msg").textContent = e.message; }
}

async function uploadGuideMusic(file) {
  if (!file) return;
  const form = new FormData();
  form.append("file", file);
  try {
    const resp = await fetch("/api/guide/music", { method: "POST", body: form, credentials: "same-origin" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `Error ${resp.status}`);
    renderGuideMusic(data.music);
    toast("Música agregada a la guía");
  } catch (e) { $("guide-msg").textContent = e.message; }
}

async function deleteGuideMusic(name) {
  try {
    const data = await api("/api/guide/music/delete", { json: { name } });
    renderGuideMusic(data.music);
  } catch (e) { $("guide-msg").textContent = e.message; }
}

// ---------- backup ----------

async function restoreBackup(file) {
  if (!file) return;
  if (!confirm(`¿Restaurar "${file.name}"? Los canales y horarios se reemplazan por los del respaldo. Los videos no se tocan.`)) return;
  const form = new FormData();
  form.append("file", file);
  $("backup-msg").textContent = "Restaurando…";
  try {
    const resp = await fetch("/api/backup", { method: "POST", body: form, credentials: "same-origin" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `Error ${resp.status}`);
    $("backup-msg").textContent = "";
    toast(`Respaldo restaurado: ${data.channels} canales. La tele se reinicia.`);
    openMoreTab();
  } catch (e) { $("backup-msg").textContent = e.message; }
}

// ---------- USB stick ----------

const usbState = { device: null, files: [], timer: null };

async function usbRefresh() {
  $("usb-status").textContent = "Buscando…";
  try {
    const r = await api("/api/usb");
    showUsbJob(r.job);
    if (!r.drives.length) {
      $("usb-drives").replaceChildren(el("p", { class: "muted" }, "No encuentro ningún pendrive. Conéctalo al computador de la tele y vuelve a buscar."));
      $("usb-browser").hidden = true;
      if (!r.job.running) $("usb-status").textContent = "";
      return;
    }
    $("usb-drives").replaceChildren(...r.drives.map((d) => el("button", {
      class: "chbtn" + (d.device === usbState.device ? " active" : ""), type: "button", onclick: () => usbOpen(d.device),
    }, el("span", { class: "num" }, "💾"), `${d.label} · ${formatSize(d.size)}`)));
    if (!r.job.running) $("usb-status").textContent = "";
  } catch (e) { $("usb-status").textContent = e.message; }
}

async function usbOpen(device) {
  usbState.device = device;
  $("usb-status").textContent = "Abriendo el pendrive…";
  try {
    const r = await api("/api/usb/open", { json: { device } });
    usbState.files = r.files;
    $("usb-all").checked = false;
    let lastFolder = null;
    const rows = [];
    for (const f of r.files) {
      if (f.folder !== lastFolder) { rows.push(el("div", { class: "usb-folder" }, `📁 ${f.folder || "(principal)"}`)); lastFolder = f.folder; }
      rows.push(el("label", { class: "switch usb-file" }, el("input", { type: "checkbox", value: f.path }),
        ` ${f.name} `, el("small", { class: "muted" }, formatSize(f.size))));
    }
    $("usb-files").replaceChildren(...(rows.length ? rows : [el("p", { class: "muted" }, "Este pendrive no tiene videos.")]));
    $("usb-browser").hidden = false;
    $("usb-status").textContent = `${r.files.length} videos encontrados.`;
  } catch (e) { $("usb-status").textContent = e.message; }
}

function showUsbJob(job) {
  if (!job || (!job.running && !job.finished_at)) return;
  if (job.running) {
    const pct = job.bytes_total ? Math.round((job.bytes_done / job.bytes_total) * 100) : 0;
    $("usb-status").textContent = `Copiando ${job.done + 1} de ${job.total} (${pct}%): ${job.current || ""}`;
    clearTimeout(usbState.timer);
    usbState.timer = setTimeout(async () => {
      try { showUsbJob(await api("/api/usb/import")); } catch (_) { /* ignore */ }
    }, 2000);
  } else if (usbState.timer) {
    usbState.timer = null;
    const errs = job.errors.length ? ` (${job.errors.length} con error)` : "";
    $("usb-status").textContent = `✅ Listo: ${job.done} videos copiados${errs}. Ya puedes expulsar el pendrive.`;
    loadChannels().catch(() => {});
  }
}

async function usbImport() {
  const files = [...$("usb-files").querySelectorAll("input:checked")].map((i) => i.value);
  if (!files.length) { toast("Elige al menos un video"); return; }
  const channel = $("up-channel").value;
  const tag = $("up-tag").value;
  if (!channel) { toast("Primero elige un canal arriba"); return; }
  try {
    const r = await api("/api/usb/import", { json: { device: usbState.device, files, channel, tag: tag || null } });
    usbState.timer = 1;
    showUsbJob(r.job);
  } catch (e) { $("usb-status").textContent = e.message; }
}

async function usbEject() {
  try {
    await api("/api/usb/eject", { json: { device: usbState.device } });
    usbState.device = null;
    $("usb-browser").hidden = true;
    $("usb-status").textContent = "Ya puedes sacar el pendrive.";
    usbRefresh();
  } catch (e) { $("usb-status").textContent = e.message; }
}

// ---------- wiring ----------

(function wireExtras() {
  $("tv-save").addEventListener("click", saveTvSettings);
  $("tv-convert-all").addEventListener("click", convertAll);
  $("tv-pin").addEventListener("keydown", (e) => { if (e.key === "Delete") removeChannelPin(); });
  const pinCard = $("tv-pin").closest(".field");
  pinCard.after(el("button", { class: "btn small ghost", type: "button", onclick: removeChannelPin }, "Quitar PIN de canales"));
  $("guide-save").addEventListener("click", saveGuide);
  $("guide-music-file").addEventListener("change", (e) => { uploadGuideMusic(e.target.files[0]); e.target.value = ""; });
  $("backup-file").addEventListener("change", (e) => { restoreBackup(e.target.files[0]); e.target.value = ""; });
  $("usb-refresh").addEventListener("click", usbRefresh);
  $("usb-import").addEventListener("click", usbImport);
  $("usb-eject").addEventListener("click", usbEject);
  $("usb-all").addEventListener("change", (e) => {
    $("usb-files").querySelectorAll("input[type=checkbox]").forEach((b) => { b.checked = e.target.checked; });
  });
}());
