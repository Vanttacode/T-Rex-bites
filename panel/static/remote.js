"use strict";
// The phone remote (http://control.local): channels, volume, power. Nothing else.

const $ = (id) => document.getElementById(id);
let channels = [];
let pin = "";
let power = null;
let playing = null;

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
  try { data = await resp.json(); } catch (_) { /* empty */ }
  if (resp.status === 401 && path !== "/api/login") showLogin();
  if (!resp.ok) throw new Error(data.detail || `Error ${resp.status}`);
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v);
  }
  node.append(...children);
  return node;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { t.hidden = true; }, 2500);
}

const buzz = () => { if (navigator.vibrate) navigator.vibrate(25); };
const logoOf = (c) => `/api/channels/${encodeURIComponent(c.name)}/logo?v=${c.custom_logo ? "c" : "d"}`;

// ---------- PIN ----------

function showLogin() {
  $("remote").hidden = true;
  $("login").hidden = false;
  pin = "";
  drawDots();
}

function drawDots() {
  $("dots").replaceChildren(...Array.from({ length: Math.max(4, pin.length) }, (_, i) => el("span", { class: i < pin.length ? "on" : "" })));
}

function press(k) {
  $("login-error").textContent = "";
  if (k === "⌫") pin = pin.slice(0, -1);
  else if (k === "OK") { login(); return; }
  else if (pin.length < 8) pin += k;
  drawDots();
}

async function login() {
  try {
    await api("/api/login", { json: { pin } });
    start();
  } catch (e) {
    $("login-error").textContent = e.message;
  }
  pin = "";
  drawDots();
}

// ---------- remote ----------

async function send(action, channel) {
  buzz();
  const qs = channel !== undefined ? `?channel=${channel}` : "";
  try {
    await api(`/api/remote/${action}${qs}`, { method: "POST" });
    setTimeout(refresh, 700);
  } catch (e) { toast(e.message); }
}

async function digit(d) {
  buzz();
  try { await api(`/api/remote/digit/${d}`, { method: "POST" }); setTimeout(refresh, 800); } catch (e) { toast(e.message); }
}

function drawChannels() {
  $("channels").replaceChildren(...channels.map((c) => el("button", {
    class: "ch-btn" + (c.number === playing ? " on" : ""), onclick: () => send("channel", c.number),
  }, c.guide ? el("span", { class: "n" }, "🗒") : el("img", { src: logoOf(c), alt: "", loading: "lazy" }),
  el("span", {}, el("span", { class: "n" }, String(c.number)), el("span", { class: "t" }, c.long_name)))));
}

async function refresh() {
  try {
    const s = await api("/api/status");
    power = s.power || { state: "on" };
    const p = s.player || {};
    const tvOn = power.state === "on";
    $("power").classList.toggle("off", !tvOn);
    $("power").setAttribute("aria-label", tvOn ? "Apagar la tele" : "Encender la tele");
    $("pinpad").hidden = !(s.online && tvOn && p.awaiting_pin);
    const ch = channels.find((c) => c.number === p.channel_number);
    const now = tvOn && s.online ? p.channel_number : null;
    if (now !== playing) { playing = now; drawChannels(); }
    if (!tvOn) {
      $("now-logo").hidden = true;
      $("now-ch").textContent = power.state === "setup" ? "📶 Falta configurar el WiFi" : "😴 La tele está durmiendo";
      $("now-title").textContent = power.state === "setup" ? "Hazlo desde el computador: trexbites.local" : "Toca ⏻ para encenderla";
    } else if (!s.online) {
      $("now-logo").hidden = true;
      $("now-ch").textContent = "La tele está reiniciándose…";
      $("now-title").textContent = "";
    } else {
      $("now-logo").hidden = !ch || !!ch.guide;
      if (ch && !ch.guide) $("now-logo").src = logoOf(ch);
      $("now-ch").replaceChildren("Canal ", el("b", {}, String(p.channel_number ?? "?")), ` · ${ch ? ch.long_name : (p.network_name || "")}`);
      $("now-title").textContent = p.title ? `Ahora: ${p.title}` : "";
    }
  } catch (_) {
    $("now-ch").textContent = "No encuentro la tele…";
    $("now-title").textContent = "";
  }
}

async function togglePower() {
  if (!power) return;
  const on = power.state === "on";
  if (on && !confirm("¿Apagar la tele hasta mañana?")) return;
  buzz();
  try {
    const r = await api("/api/power", { json: { mode: on ? "off" : (power.reason === "bedtime" ? "on" : "auto") } });
    power = r.power;
    toast(on ? "😴 Tele apagada hasta mañana" : "📺 Tele encendida");
    setTimeout(refresh, 1500);
  } catch (e) { toast(e.message); }
}

async function start() {
  $("login").hidden = true;
  $("remote").hidden = false;
  try {
    channels = (await api("/api/remote-channels")).channels;
  } catch (e) { toast(e.message); }
  drawChannels();
  refresh();
  clearInterval(start.timer);
  start.timer = setInterval(() => { if (!document.hidden) refresh(); }, 5000);
}

document.addEventListener("DOMContentLoaded", async () => {
  $("login-keys").replaceChildren(...["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", "OK"]
    .map((k) => el("button", { type: "button", onclick: () => press(k) }, k)));
  $("tv-keys").replaceChildren(...["1", "2", "3", "4", "5", "6", "7", "8", "9", "⌫", "0", ""]
    .map((k) => el("button", { type: "button", onclick: () => k && digit(k === "⌫" ? "clear" : k) }, k)));
  document.querySelectorAll("[data-a]").forEach((b) => b.addEventListener("click", () => send(b.dataset.a)));
  $("power").addEventListener("click", togglePower);
  document.addEventListener("visibilitychange", () => { if (!document.hidden && !$("remote").hidden) refresh(); });
  try {
    const s = await api("/api/session");
    if (s.logged_in) start(); else showLogin();
  } catch (_) { showLogin(); }
});
