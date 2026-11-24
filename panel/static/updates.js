"use strict";
// "Actualizaciones" card (tab "Más"). Uses $, api, toast from app.js.

const updUI = { poll: null, latest: null };

function renderUpdate(info) {
  const state = info.state || {};
  const status = $("upd-status");
  const apply = $("upd-apply");
  $("upd-error").textContent = info.error || (state.status === "error" ? state.message : "");
  updUI.latest = info.latest;

  if (state.status === "running") {
    status.textContent = `⏳ ${state.message || "Actualizando…"} No apagues la tele.`;
    apply.hidden = true;
    startUpdatePoll();
    return;
  }
  stopUpdatePoll();
  if (info.available) {
    status.textContent = `✨ Hay una versión nueva: ${info.latest.tag} (tienes ${info.current}).`;
    apply.hidden = false;
    apply.textContent = `Actualizar a ${info.latest.tag}`;
  } else {
    apply.hidden = true;
    let text = `✅ Versión ${info.current}`;
    if (state.status === "done") text += " · actualizada recién";
    else if (info.checked_at) text += " · es la última";
    status.textContent = text;
  }
}

async function loadUpdate(check) {
  try {
    renderUpdate(await api(`/api/update${check ? "?check=true" : ""}`));
  } catch (e) {
    $("upd-error").textContent = e.message;
  }
}

async function applyUpdate() {
  const tag = updUI.latest ? updUI.latest.tag : "";
  if (!confirm(`¿Actualizar T-Rex Bites a ${tag}?\n\nTus videos, canales y horarios no se tocan. La tele puede cortarse un par de minutos.`)) return;
  try {
    await api("/api/update", { method: "POST" });
    toast("Actualización iniciada");
    $("upd-apply").hidden = true;
    $("upd-status").textContent = "⏳ Actualizando… No apagues la tele.";
    startUpdatePoll();
  } catch (e) {
    $("upd-error").textContent = e.message;
  }
}

function startUpdatePoll() {
  if (updUI.poll) return;
  // while updating, the panel itself restarts: errors in between are expected
  updUI.poll = setInterval(() => { loadUpdate(false).catch(() => {}); }, 5000);
}

function stopUpdatePoll() {
  clearInterval(updUI.poll);
  updUI.poll = null;
}

$("upd-check").addEventListener("click", () => {
  $("upd-status").textContent = "🔎 Buscando…";
  loadUpdate(true);
});
$("upd-apply").addEventListener("click", applyUpdate);
