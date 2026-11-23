"use strict";
// Settings screens: bedtime and history.
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
  if (power && power.state === "setup") return "📶 La tele espera que le configures el WiFi (Ajustes → WiFi).";
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

// ---------- settings tab ----------

function openSettingsTab() {
  redrawCurrent = () => {};
  loadBedtime();
  loadWifi();
  loadTvSettings();
  loadGuide();
  loadUpdate(false);
  renderHistory();
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
}

wireManagement();
