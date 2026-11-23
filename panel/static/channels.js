"use strict";
// Channels: the list, one page per channel (Programación, Comerciales,
// Apariencia, Ajustes) and the "new channel" wizard.
// Uses helpers from app.js and folderView/redrawCurrent from library.js.

let chOpen = null;      // network name of the open channel
let chSub = "prog";     // its open tab

const DAY_NAMES = [["monday", "Lunes"], ["tuesday", "Martes"], ["wednesday", "Miércoles"], ["thursday", "Jueves"],
  ["friday", "Viernes"], ["saturday", "Sábado"], ["sunday", "Domingo"]];

const contentLabel = (tag) => (libraryCache.content.find((c) => c.tag === tag) || { label: tag }).label;
const logoUrl = (c) => `/api/channels/${encodeURIComponent(c.name)}/logo?v=${Date.now() % 100000}`;

function channelSummary(c) {
  if (c.kind === "allday") {
    const what = c.allday && c.allday.tags.length ? c.allday.tags.map(contentLabel).join(" + ") : "nada elegido";
    return `🔁 Todo el día · ${what}`;
  }
  const hours = Object.values(c.blocks || {}).flat().filter((b) => b.kind === "show").reduce((t, b) => t + b.end - b.start, 0);
  return `🗓 Con horario · ${hours} h por semana${c.ads && c.ads.enabled ? " · 📺 comerciales" : ""}`;
}

async function openChannelsTab() {
  redrawCurrent = drawChannels;
  const fromHash = decodeURIComponent(location.hash.split("/")[1] || "");
  if (fromHash) chOpen = fromHash;
  try { await loadChannels(); } catch (e) { toast(e.message); return; }
  drawChannels();
}

function drawChannels() {
  if (currentTab !== "channels") return;
  const ch = channelsCache.find((c) => c.name === chOpen);
  if (chOpen && !ch) chOpen = null;
  $("wizard").hidden = true;
  $("ch-list-view").hidden = !!ch;
  $("ch-page").hidden = !ch;
  if (ch) drawChannelPage(ch); else drawChannelList();
  updateSelbar();
}

function drawChannelList() {
  history.replaceState(null, "", "#channels");
  $("ch-cards").replaceChildren(...channelsCache.map((c) => el("button", {
    class: "ch-card" + (c.number === currentChannel ? " live" : ""), type: "button",
    onclick: () => { chOpen = c.name; chSub = "prog"; drawChannels(); },
  }, el("img", { class: "chlogo", alt: "", loading: "lazy", src: logoUrl(c) }),
  el("span", { class: "chtext" }, el("span", { class: "num" }, String(c.number)), el("b", {}, c.long_name),
    el("small", {}, channelSummary(c)),
    c.number === currentChannel ? el("span", { class: "live-tag" }, "● En pantalla") : ""))),
  el("button", { class: "ch-card new", type: "button", onclick: openWizard }, el("span", { class: "big" }, "＋"), el("b", {}, "Nuevo canal")));
}

// ---------- one channel ----------

function drawChannelPage(c) {
  history.replaceState(null, "", `#channels/${encodeURIComponent(c.name)}`);
  $("ch-page-logo").src = logoUrl(c);
  $("ch-page-title").textContent = `${c.number} · ${c.long_name}`;
  $("ch-page-sub").textContent = channelSummary(c);
  document.querySelectorAll("#ch-subtabs button").forEach((b) => b.classList.toggle("active", b.dataset.sub === chSub));
  ["prog", "ads", "look", "conf"].forEach((s) => { $(`sub-${s}`).hidden = s !== chSub; });
  if (chSub === "prog") drawProg(c);
  if (chSub === "ads") drawAds(c);
  if (chSub === "look") drawLook(c);
  if (chSub === "conf") drawConf(c);
}

async function saveChannel(c, changes, message = "Guardado") {
  const body = { long_name: c.long_name, number: c.number, ...changes };
  try {
    const r = await api(`/api/channels/${encodeURIComponent(c.name)}`, { method: "PUT", json: body });
    if (r.name) chOpen = r.name;
    toast(message);
    await loadChannels();
    drawChannels();
    return true;
  } catch (e) {
    toast(e.message);
    return false;
  }
}

function contentChecks(selected, mode, onChange) {
  const box = el("div", { class: "content-picker" });
  for (const cat of libraryCache.categories) {
    const group = el("div", { class: "cp-group" });
    for (const tag of [cat.tag, ...cat.programs.map((p) => `${cat.tag}/${p.tag}`)]) {
      const input = el("input", { type: "checkbox", value: tag });
      input.checked = selected.includes(tag);
      input.addEventListener("change", onChange || (() => {}));
      const program = tag.includes("/");
      const f = libraryCache.folders.find((x) => x.tag === tag);
      const count = f ? f.videos.filter((v) => !v.placeholder).length : 0;
      group.append(el("label", { class: "cp-item" + (program ? " program" : "") }, input,
        el("span", {}, program ? `↳ ${contentLabel(tag).split(" › ").pop()}` : contentLabel(tag)),
        el("small", { class: "muted" }, ` ${count} videos`)));
    }
    box.append(group);
  }
  if (!libraryCache.categories.length) box.append(el("p", { class: "muted" }, "La biblioteca está vacía: crea categorías en 📚 Biblioteca."));
  return box;
}

const picked = (root) => [...root.querySelectorAll(".content-picker input:checked")].map((i) => i.value);

function drawProg(c) {
  const root = $("sub-prog");
  if (c.kind === "allday") {
    const current = c.allday || { tags: [], mode: "random" };
    const modeRadios = el("div", { class: "radios" },
      el("label", { class: "radio" }, el("input", { type: "radio", name: "ad-mode", value: "random" }), " 🎲 Al azar"),
      el("label", { class: "radio" }, el("input", { type: "radio", name: "ad-mode", value: "order" }),
        " 🔁 En orden ", el("small", {}, "(capítulos 01, 02, 03…; con un solo programa)")));
    modeRadios.querySelector(`input[value="${current.mode}"]`).checked = true;
    root.replaceChildren(el("div", { class: "card" },
      el("h3", {}, "¿Qué pasa este canal todo el día?"),
      el("p", { class: "muted small" }, "Elige categorías completas o programas. Lo que subas después a esas carpetas aparece solo."),
      contentChecks(current.tags), modeRadios,
      el("button", { class: "btn", type: "button", onclick: () => saveChannel(c, {
        allday: { tags: picked(root), mode: root.querySelector('input[name="ad-mode"]:checked').value },
      }, "Programación guardada. La tele la aplica en unos minutos.") }, "Guardar")));
    return;
  }
  if (wide.matches) {
    // the timeline editor, right here
    const frame = el("iframe", { class: "editor-frame", title: "Editor de programación",
      src: `/programacion?canal=${encodeURIComponent(c.name)}&embed=1` });
    root.replaceChildren(frame);
    return;
  }
  // phone: read the week; editing the timeline needs a bigger screen
  const hh = (h) => `${String(h).padStart(2, "0")}:00`;
  const days = DAY_NAMES.map(([d, name]) => {
    const blocks = (c.blocks[d] || []);
    return el("details", { class: "day-list" }, el("summary", {}, name, el("small", { class: "muted" }, ` ${blocks.filter((b) => b.kind === "show").length} bloques`)),
      ...(blocks.length ? blocks.map((b) => el("div", { class: "day-block" }, el("b", {}, `${hh(b.start)}–${hh(b.end)}`),
        b.kind === "signoff" ? " 🌙 Fin de transmisión" : ` ${b.tags.map(contentLabel).join(" + ")}${b.mode === "order" ? " 🔁" : ""}`))
        : [el("p", { class: "muted" }, "Fuera del aire todo el día.")]));
  });
  root.replaceChildren(el("div", { class: "card" },
    el("p", { class: "warning" }, "💻 Para armar la programación (arrastrar bloques por hora) abre este panel en un computador: Canales → este canal → Programación."),
    ...days));
}

function pautaList(c) {
  const list = el("ul", { class: "cat-list" });
  const save = (pautas, msg) => saveChannel(c, { pautas }, msg);
  const current = () => c.pautas.map((p) => ({ tag: p.tag, label: p.label }));
  for (const p of c.pautas) {
    list.append(el("li", {}, el("span", {}, `📺 ${p.label}`),
      el("button", { class: "btn small ghost", type: "button", title: "Cambiar nombre", onclick: () => {
        const label = (prompt("Nuevo nombre de la pauta:", p.label) || "").trim();
        if (label) save(current().map((x) => (x.tag === p.tag ? { ...x, label } : x)), "Pauta renombrada");
      } }, "✏️"),
      el("button", { class: "btn small danger", type: "button", title: "Quitar", onclick: () => {
        if (confirm(`¿Quitar la pauta "${p.label}"? Sus videos quedan guardados en el disco.`)) save(current().filter((x) => x.tag !== p.tag), "Pauta quitada");
      } }, "✕")));
  }
  list.append(el("li", {}, el("button", { class: "btn small ghost", type: "button", onclick: () => {
    const label = (prompt("Nombre de la pauta nueva (ej: Juguetes, Cereales):") || "").trim();
    if (label) save([...current(), label], `Pauta "${label}" creada`);
  } }, "＋ Nueva pauta")));
  return list;
}

function drawAds(c) {
  const root = $("sub-ads");
  if (c.kind === "allday") {
    root.replaceChildren(el("div", { class: "card" }, el("p", { class: "muted" },
      "Los canales \"Todo el día\" pasan un video tras otro, sin tandas de comerciales. Si quieres comerciales, crea un canal \"Con horario\".")));
    return;
  }
  const ads = c.ads || { enabled: false, strategy: "end", duration: 120 };
  const on = el("input", { type: "checkbox" });
  on.checked = ads.enabled;
  const strategy = el("select", {}, ...Object.entries({
    end: "Al final de cada programa", standard: "Repartidos durante el programa", center: "Una tanda a la mitad del programa",
  }).map(([k, v]) => el("option", { value: k }, v)));
  strategy.value = ads.strategy;
  const durations = [30, 60, 120, 180, 300];
  if (!durations.includes(ads.duration)) durations.push(ads.duration);
  const duration = el("select", {}, ...durations.map((d) => el("option", { value: String(d) }, d < 60 ? `${d} segundos` : `${d / 60} minuto${d === 60 ? "" : "s"}`)));
  duration.value = String(ads.duration);
  const settings = el("div", { class: "card" },
    el("label", { class: "switch" }, on, " 📺 Pasar comerciales en este canal"),
    el("div", { class: "row2" }, el("label", { class: "field" }, "Cuándo", strategy), el("label", { class: "field" }, "Duración de cada tanda", duration)),
    el("button", { class: "btn", type: "button", onclick: () => saveChannel(c, {
      ads: { enabled: on.checked, strategy: strategy.value, duration: Number(duration.value) },
    }, on.checked ? "Comerciales activados" : "Comerciales apagados") }, "Guardar"));
  const parts = [settings];
  if (ads.enabled) {
    const folder = (tag) => c.folders.find((f) => f.tag === tag);
    const general = folder("_comerciales");
    if (general) {
      parts.push(el("div", { class: "card" }, folderView(c.name, general, {
        title: "📺 Comerciales del canal", where: `${c.long_name} › Comerciales`, showWhen: true, small: true,
        subtitle: "Salen en todas las tandas (salvo en bloques con pauta propia).",
      })));
    }
    parts.push(el("div", { class: "card" }, el("h3", {}, "Pautas"),
      el("p", { class: "muted small" }, "Tandas propias para algunos bloques: en el editor de programación eliges qué pauta usa cada bloque."),
      pautaList(c)));
    for (const p of c.pautas) {
      const f = folder(`_pauta/${p.tag}`);
      if (f) parts.push(el("div", { class: "card" }, folderView(c.name, f, { title: `📺 Pauta: ${p.label}`, where: `${c.long_name} › ${p.label}`, showWhen: true, small: true })));
    }
  }
  root.replaceChildren(...parts);
}

function drawLook(c) {
  const root = $("sub-look");
  const logo = c.logo || { show: true, permanent: true, custom: false };
  const show = el("input", { type: "checkbox" });
  show.checked = logo.show;
  const permanent = el("input", { type: "checkbox" });
  permanent.checked = logo.permanent;
  const file = el("input", { type: "file", accept: "image/png,image/jpeg,image/gif", hidden: true });
  file.addEventListener("change", async () => {
    const f = file.files[0];
    if (!f) return;
    const form = new FormData();
    form.append("file", f);
    const resp = await fetch(`/api/channels/${encodeURIComponent(c.name)}/logo`, { method: "POST", body: form, credentials: "same-origin" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) { toast(data.detail || `Error ${resp.status}`); return; }
    toast("Logo guardado. La tele lo muestra en unos segundos.");
    await loadChannels();
    drawChannels();
  });
  const logoCard = el("div", { class: "card" }, el("h3", {}, "Logo del canal"),
    el("p", { class: "muted small" }, "Aparece en una esquina de la pantalla. Mejor un PNG con fondo transparente."),
    el("div", { class: "logo-row" }, el("img", { id: "ch-logo-img", alt: "Logo del canal", src: logoUrl(c) }),
      el("div", { class: "logo-actions" },
        el("label", { class: "btn small ghost" }, "Cambiar logo", file),
        logo.custom ? el("button", { class: "btn small ghost", type: "button", onclick: async () => {
          try { await api(`/api/channels/${encodeURIComponent(c.name)}/logo`, { method: "DELETE" }); toast("Ahora usa el logo de T-Rex Bites"); await loadChannels(); drawChannels(); } catch (e) { toast(e.message); }
        } }, "Usar logo T-Rex") : "")),
    el("label", { class: "switch" }, show, " Mostrar logo en pantalla"),
    el("label", { class: "switch" }, permanent, " Siempre visible ", el("small", {}, "(si no, aparece unos segundos al cambiar de programa)")),
    el("button", { class: "btn", type: "button", onclick: () => saveChannel(c, { logo: { show: show.checked, permanent: permanent.checked } }, "Logo guardado") }, "Guardar"));
  const parts = [logoCard];
  const bumps = c.folders.find((f) => f.tag === "_cortinillas");
  if (bumps) {
    parts.push(el("div", { class: "card" }, folderView(c.name, bumps, {
      title: "🎬 Cortinillas", where: `${c.long_name} › Cortinillas`, small: true,
      subtitle: "Videos cortos entre programas: \"Ya volvemos\", la presentación del canal…",
    })));
  }
  const fixed = c.folders.find((f) => f.tag === "_fijos");
  if (fixed) {
    parts.push(el("div", { class: "card" }, folderView(c.name, fixed, {
      title: "📌 Videos fijos", where: `${c.long_name} › Videos fijos`, small: true,
      subtitle: "Para el inicio o el final de un bloque (ej: \"¡Comienza la hora de Bluey!\"). Se eligen en el editor de programación.",
    })));
  }
  root.replaceChildren(...parts);
}

function drawConf(c) {
  const root = $("sub-conf");
  const name = el("input", { type: "text", maxlength: "30", value: c.long_name });
  const number = el("input", { type: "number", min: "1", max: "99", value: String(c.number), inputmode: "numeric" });
  const parental = el("input", { type: "checkbox" });
  parental.checked = !!c.parental;
  root.replaceChildren(
    el("div", { class: "card" },
      el("label", { class: "field" }, "Nombre (así aparece en la tele)", name),
      el("label", { class: "field" }, "Número", number),
      el("label", { class: "switch" }, parental, " 🔒 Pedir PIN para ver este canal ",
        el("small", {}, "(el PIN se define en Ajustes → Opciones de la tele)")),
      el("button", { class: "btn", type: "button", onclick: () => saveChannel(c, {
        long_name: name.value, number: Number(number.value), parental: parental.checked,
      }, "Canal guardado. La tele se reinicia en unos segundos.") }, "Guardar")),
    el("div", { class: "card" },
      el("h3", {}, "Duplicar"),
      el("p", { class: "muted small" }, "Crea otro canal igual: misma programación, comerciales, cortinillas y logo."),
      el("button", { class: "btn ghost", type: "button", onclick: () => duplicateChannel(c) }, "⧉ Duplicar este canal")),
    el("div", { class: "card" },
      el("h3", {}, "Borrar"),
      el("p", { class: "muted small" }, "Los videos de la biblioteca no se borran."),
      el("button", { class: "btn danger", type: "button", onclick: () => deleteChannel(c) }, "Borrar este canal")));
}

function nextFreeNumber() {
  const used = new Set(channelsCache.map((c) => c.number));
  for (let n = 2; n < 100; n++) if (!used.has(n)) return n;
  return 99;
}

async function duplicateChannel(c) {
  const long = (prompt("Nombre del canal nuevo:", `${c.long_name} 2`) || "").trim();
  if (!long) return;
  try {
    const r = await api(`/api/channels/${encodeURIComponent(c.name)}/duplicate`, { json: { long_name: long, number: nextFreeNumber() } });
    toast("Canal creado. La tele se reinicia en unos segundos.");
    chOpen = r.name;
    chSub = "conf";
    await loadChannels();
    drawChannels();
  } catch (e) { toast(e.message); }
}

async function deleteChannel(c) {
  if (!confirm(`¿Borrar el canal ${c.number} · ${c.long_name}?\n\nLos videos de la biblioteca NO se borran.`)) return;
  try {
    await api(`/api/channels/${encodeURIComponent(c.name)}`, { method: "DELETE" });
    toast("Canal borrado");
    chOpen = null;
    await loadChannels();
    drawChannels();
  } catch (e) { toast(e.message); }
}

// ---------- new channel, step by step ----------

const wz = { step: 1, kind: null };

function openWizard() {
  wz.step = 1;
  wz.kind = null;
  $("wz-name").value = "";
  $("wz-number").value = nextFreeNumber();
  $("wz-msg").textContent = "";
  $("ch-list-view").hidden = true;
  $("ch-page").hidden = true;
  $("wizard").hidden = false;
  drawWizard();
  $("wz-name").focus();
}

function drawWizard() {
  [1, 2, 3].forEach((n) => { $(`wz-${n}`).hidden = n !== wz.step; });
  [...$("wz-steps").children].forEach((li, i) => li.classList.toggle("on", i < wz.step));
  $("wz-prev").hidden = wz.step === 1;
  $("wz-next").textContent = wz.step === 3 ? "✓ Crear canal" : "Siguiente →";
  document.querySelectorAll("#wz-2 .choice").forEach((b) => b.classList.toggle("active", b.dataset.kind === wz.kind));
  if (wz.step === 3) {
    $("wz-3-title").replaceChildren(el("b", {}, wz.kind === "allday" ? "¿Qué pasa este canal todo el día?"
      : "¿Con qué empieza? Después lo armas por hora en Programación."));
    $("wz-mode").hidden = wz.kind !== "allday";
    $("wz-content").replaceChildren(contentChecks([]));
  }
}

async function wizardNext() {
  $("wz-msg").textContent = "";
  if (wz.step === 1) {
    if (!$("wz-name").value.trim()) { $("wz-msg").textContent = "Escribe un nombre."; return; }
    if (channelsCache.some((c) => c.number === Number($("wz-number").value))) { $("wz-msg").textContent = "Ese número ya lo usa otro canal."; return; }
  }
  if (wz.step === 2 && !wz.kind) { $("wz-msg").textContent = "Elige un tipo."; return; }
  if (wz.step < 3) { wz.step += 1; drawWizard(); return; }
  const tags = picked($("wz-content"));
  if (!tags.length) { $("wz-msg").textContent = "Elige al menos una categoría o programa."; return; }
  const mode = document.querySelector('input[name="wz-mode"]:checked').value;
  try {
    const r = await api("/api/channels", { json: { long_name: $("wz-name").value, number: Number($("wz-number").value), kind: wz.kind, tags, mode } });
    toast("¡Canal creado! La tele se reinicia en unos segundos.");
    chOpen = r.name;
    chSub = "prog";
    await loadChannels();
    drawChannels();
  } catch (e) { $("wz-msg").textContent = e.message; }
}

(function wireChannels() {
  $("ch-back").addEventListener("click", () => { chOpen = null; drawChannels(); });
  document.querySelectorAll("#ch-subtabs button").forEach((b) => b.addEventListener("click", () => {
    chSub = b.dataset.sub;
    drawChannels();
  }));
  $("wz-next").addEventListener("click", wizardNext);
  $("wz-prev").addEventListener("click", () => { wz.step -= 1; drawWizard(); });
  $("wz-cancel").addEventListener("click", () => { $("wizard").hidden = true; drawChannels(); });
  document.querySelectorAll("#wz-2 .choice").forEach((b) => b.addEventListener("click", () => { wz.kind = b.dataset.kind; drawWizard(); }));
  $("wz-name").addEventListener("keydown", (e) => { if (e.key === "Enter") wizardNext(); });
}());
