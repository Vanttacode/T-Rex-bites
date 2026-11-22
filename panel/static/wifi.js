"use strict";
// WiFi setup card (tab "Más"). Uses $, api, el, toast from app.js.

const wifiUI = { info: null, poll: null };

function bars(signal) {
  const n = signal >= 75 ? 4 : signal >= 50 ? 3 : signal >= 25 ? 2 : 1;
  return "▂▄▆█".slice(0, n).padEnd(4, "·");
}

function wifiStatusText(info) {
  if (!info.has_wifi && info.ethernet) return "🔌 Conectada por cable de red.";
  if (info.has_wifi === false) return "Este equipo no tiene WiFi. Usa un cable de red.";
  if (info.connecting) return "⏳ Conectando…";
  if (info.connected && info.ssid) return `✅ Conectada a "${info.ssid}"` + (info.ip ? ` · ${info.ip}` : "");
  if (info.connected) return "🔌 Conectada por cable de red." + (info.ip ? ` · ${info.ip}` : "");
  if (info.hotspot) return `📡 Modo configuración: la tele creó la red "${info.hotspot_ssid}". Elige tu WiFi de casa:`;
  return "Sin conexión. En unos segundos la tele abrirá su red de configuración.";
}

function renderWifi(info) {
  wifiUI.info = info;
  $("wifi-status").textContent = wifiStatusText(info);
  $("wifi-error").textContent = info.last_error || "";
  const list = info.networks || [];
  $("wifi-list").replaceChildren(...list.map((n) => el("button", {
    class: "wifi-net" + (info.ssid === n.ssid ? " current" : ""),
    onclick: () => openWifiForm(n.ssid, n.secure),
  }, el("span", { class: "bars" }, bars(n.signal)), el("span", { class: "ssid" }, n.ssid), n.secure ? "🔒" : "")));
  if (!list.length && info.has_wifi !== false) {
    $("wifi-list").replaceChildren(el("p", { class: "muted small" },
      info.hotspot ? "No se encontraron redes antes de abrir la configuración. Usa \"Otra red\"." : "Toca \"Buscar redes\"."));
  }
  // while the TV is its own setup network, the WiFi chip can't search again
  $("wifi-scan").hidden = !!info.hotspot || info.has_wifi === false;
}

async function loadWifi() {
  try { renderWifi(await api("/api/wifi")); } catch (e) { $("wifi-status").textContent = e.message; }
}

async function scanWifi() {
  $("wifi-status").textContent = "🔎 Buscando redes…";
  try { renderWifi(await api("/api/wifi/scan", { method: "POST" })); } catch (e) { toast(e.message); }
}

function openWifiForm(ssid, secure) {
  $("wifi-form").hidden = false;
  $("wifi-ssid").value = ssid || "";
  $("wifi-ssid").readOnly = !!ssid;
  $("wifi-pass").value = "";
  $("wifi-pass").parentElement.hidden = secure === false;
  (ssid ? $("wifi-pass") : $("wifi-ssid")).focus();
}

async function connectWifi() {
  const ssid = $("wifi-ssid").value.trim();
  const password = $("wifi-pass").parentElement.hidden ? "" : $("wifi-pass").value;
  try {
    await api("/api/wifi/connect", { json: { ssid, password } });
  } catch (e) { $("wifi-error").textContent = e.message; return; }
  $("wifi-form").hidden = true;
  const after = $("wifi-after");
  after.hidden = false;
  if (wifiUI.info && wifiUI.info.hotspot) {
    // the phone loses this page: the setup network turns off
    after.replaceChildren(
      el("b", {}, `Conectando la tele a "${ssid}"…`), el("br"),
      "La red \"T-Rex Bites Config\" se va a apagar. Ahora:", el("br"),
      `1. Conecta tu teléfono a tu WiFi "${ssid}".`, el("br"),
      "2. Abre ", el("b", {}, "http://trexbites.local"), el("br"),
      "Si no abre, la tele mostrará su dirección en pantalla. ",
      "Si la clave estaba mal, la red de configuración vuelve en un minuto.");
  } else {
    after.textContent = `Conectando la tele a "${ssid}"… Esta página puede dejar de responder un momento.`;
    clearInterval(wifiUI.poll);
    wifiUI.poll = setInterval(loadWifi, 5000);
    setTimeout(() => clearInterval(wifiUI.poll), 90000);
  }
}

function wireWifi() {
  $("wifi-scan").addEventListener("click", scanWifi);
  $("wifi-other").addEventListener("click", () => openWifiForm("", true));
  $("wifi-cancel").addEventListener("click", () => { $("wifi-form").hidden = true; });
  $("wifi-connect").addEventListener("click", connectWifi);
  $("wifi-show").addEventListener("change", (e) => { $("wifi-pass").type = e.target.checked ? "text" : "password"; });
  $("wifi-pass").addEventListener("keydown", (e) => { if (e.key === "Enter") connectWifi(); });
}

wireWifi();
