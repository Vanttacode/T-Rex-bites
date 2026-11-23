"use strict";
// T-Rex Bites schedule editor: a weekly timeline of blocks, made for a computer.

const $ = (id) => document.getElementById(id);
const DAYS = [
  ["monday", "Lunes"], ["tuesday", "Martes"], ["wednesday", "Miércoles"], ["thursday", "Jueves"],
  ["friday", "Viernes"], ["saturday", "Sábado"], ["sunday", "Domingo"],
];
const DAY_NAME = Object.fromEntries(DAYS);
const COLORS = ["#ffb347", "#7ed6ff", "#9cff8a", "#ff8fc7", "#c9a7ff", "#ffe066",
  "#6ef0d0", "#ff9d7a", "#a3c4ff", "#d4ff7a", "#ffc4e1", "#b5f0ff"];
const SIGNOFF = "signoff";
const BREAKS = { end: "al final", standard: "repartidos", center: "a la mitad" };
const DURATIONS = {
  any: [null, null], short10: [null, 10], upto30: [null, 30], ep: [15, 45], movie: [60, null],
};

const st = {
  channels: [], channel: null, week: null, saved: "", brush: null,
  selected: null,        // {day, index}
  undo: [], redo: [], clipboard: null, drag: null,
  viewFrom: "auto",
};

// visible part of the day: from the first hour anything is scheduled (or 6:00)
function viewStart() {
  if (st.viewFrom !== "auto") return Number(st.viewFrom);
  let first = 6;
  for (const [d] of DAYS) for (const b of st.week[d] || []) first = Math.min(first, b.start);
  return first;
}
const span = () => 24 - viewStart();
const pos = (h) => ((h - viewStart()) / span()) * 100;

// ---------- small helpers ----------

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
  if (resp.status === 401 && path !== "/api/login") { showLogin(); throw new Error("Ingresa el PIN."); }
  if (!resp.ok) throw new Error(data.detail || `Error ${resp.status}`);
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") node.className = v;
    else if (k.startsWith("on")) node.addEventListener(k.slice(2), v);
    else if (v !== false && v != null) node.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children) if (c != null) node.append(c);
  return node;
}

function toast(msg) {
  const t = $("toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toast.t);
  toast.t = setTimeout(() => { t.hidden = true; }, 2800);
}

const hh = (h) => `${String(h).padStart(2, "0")}:00`;
const clone = (x) => JSON.parse(JSON.stringify(x));
// the shared library: categories and "category/program" tags, in order
const categories = () => (st.library ? st.library.categories : []);
const contentList = () => (st.library ? st.library.content : []);
const labelOf = (tag) => (contentList().find((c) => c.tag === tag) || { label: tag }).label;
const shortLabel = (tag) => (tag.includes("/") ? labelOf(tag).split(" › ").pop() : labelOf(tag));
const colorOf = (tag) => {
  const i = categories().findIndex((c) => c.tag === tag.split("/")[0]);
  return COLORS[(i < 0 ? 0 : i) % COLORS.length];
};
const pautaLabel = (tag) => ((st.channel.pautas || []).find((x) => x.tag === tag) || { label: tag }).label;
const fixedVideos = () => {
  const f = (st.channel.folders || []).find((x) => x.tag === "_fijos");
  return f ? f.videos.filter((v) => !v.placeholder && !v.name.includes("/")).map((v) => v.name) : [];
};

function blockColor(b) {
  if (b.kind === SIGNOFF) return null;
  if (b.tags.length === 1) return colorOf(b.tags[0]);
  const stops = b.tags.map((t, i) => `${colorOf(t)} ${(i / b.tags.length) * 100}% ${((i + 1) / b.tags.length) * 100}%`);
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}

function blockTitle(b) {
  if (b.kind === SIGNOFF) return "🌙 Cierre";
  return b.tags.map(shortLabel).join(" + ");
}

function blockMeta(b) {
  if (b.kind === SIGNOFF) return "fin de transmisión";
  const bits = [`${hh(b.start)}–${hh(b.end)}`];
  if (b.tags.length > 1) bits.push("🎲");
  if (b.mode === "order") bits.push("🔁");
  if (b.breaks) bits.push(`📺 ${BREAKS[b.breaks]}`);
  if (b.pauta) bits.push(`📺 ${pautaLabel(b.pauta)}`);
  if (b.start_video || b.end_video) bits.push("📌");
  if (b.min_minutes || b.max_minutes) {
    bits.push(`⏱ ${b.min_minutes ? b.min_minutes + "+" : ""}${b.min_minutes && b.max_minutes ? " " : ""}${b.max_minutes ? "≤" + b.max_minutes : ""} min`);
  }
  return bits.join("  ");
}

// ---------- history and saving ----------

function snapshot() { return JSON.stringify(st.week); }

function commit(mutator) {
  const before = snapshot();
  mutator();
  const after = snapshot();
  if (after === before) return;
  st.undo.push(before);
  if (st.undo.length > 80) st.undo.shift();
  st.redo = [];
  refresh();
}

function undo() {
  if (!st.undo.length) return;
  st.redo.push(snapshot());
  st.week = JSON.parse(st.undo.pop());
  st.selected = null;
  refresh();
}

function redo() {
  if (!st.redo.length) return;
  st.undo.push(snapshot());
  st.week = JSON.parse(st.redo.pop());
  st.selected = null;
  refresh();
}

const isDirty = () => st.week && snapshot() !== st.saved;

async function save() {
  if (!isDirty()) return;
  $("save").disabled = true;
  $("save-state").textContent = "Guardando…";
  try {
    await api(`/api/channels/${encodeURIComponent(st.channel.name)}/schedule`, { method: "PUT", json: { blocks: st.week } });
    st.saved = snapshot();
    toast("Programación guardada. La tele la aplica en unos minutos.");
  } catch (e) {
    toast(e.message);
  }
  $("save-state").textContent = "";
  refresh();
}

// ---------- block operations ----------

function sortDay(day) { st.week[day].sort((a, b) => a.start - b.start); }

/** Put a block on [start, end) of a day, trimming whatever was there. */
function paint(day, block) {
  const a = block.start;
  const b = block.kind === SIGNOFF ? block.start + 1 : block.end;
  const out = [];
  for (const old of st.week[day]) {
    if (old.end <= a || old.start >= b) { out.push(old); continue; }
    if (old.kind === SIGNOFF) continue;
    if (old.start < a) out.push({ ...old, end: a });
    if (old.end > b) out.push({ ...old, start: b });
  }
  out.push({ ...block, start: a, end: b });
  st.week[day] = out;
  sortDay(day);
  st.selected = { day, index: st.week[day].indexOf(out[out.length - 1]) };
}

function fits(day, start, end, ignoreIndex) {
  return st.week[day].every((b, i) => i === ignoreIndex || b.end <= start || b.start >= end);
}

function brushBlock(start, end) {
  if (st.brush === SIGNOFF) return { start, end: start + 1, kind: SIGNOFF };
  return { start, end, kind: "show", tags: [st.brush], mode: "random", breaks: null, min_minutes: null, max_minutes: null,
    pauta: null, start_video: null, end_video: null };
}

function selectedBlock() {
  if (!st.selected) return null;
  return st.week[st.selected.day][st.selected.index] || null;
}

function deleteSelected() {
  const sel = st.selected;
  if (!sel) return;
  commit(() => { st.week[sel.day].splice(sel.index, 1); st.selected = null; });
}

// ---------- rendering ----------

function render() {
  const tl = $("timeline");
  tl.style.setProperty("--hours", span());
  const hours = el("div", { class: "t-hours" });
  for (let h = viewStart(); h <= 24; h += 1) {
    const s = el("span", {}, h === 24 ? "24" : String(h).padStart(2, "0"));
    s.style.left = `${pos(h)}%`;
    hours.append(s);
  }
  const rows = [el("div", { class: "t-head" }, el("div"), hours)];
  const todayKey = DAYS[(new Date().getDay() + 6) % 7][0];

  for (const [day, name] of DAYS) {
    const onAir = st.week[day].filter((b) => b.kind !== SIGNOFF).reduce((s, b) => s + b.end - b.start, 0);
    const label = el("div", {
      class: "t-day" + (day === todayKey ? " today" : "") + (st.selected && st.selected.day === day ? " selected" : ""),
      title: "Copiar este día a otros",
      onclick: () => openCopy(day),
    }, el("b", {}, name), el("small", {}, onAir ? `${onAir} h al aire` : "sin programación"));
    const track = el("div", { class: "t-track", "data-day": day });
    st.week[day].forEach((b, index) => { if (b.end > viewStart()) track.append(renderBlock(day, b, index)); });
    if (day === todayKey) {
      const now = new Date();
      const line = el("div", { class: "now", title: "Ahora" });
      const nowH = now.getHours() + now.getMinutes() / 60;
      line.style.left = `${pos(nowH)}%`;
      if (nowH >= viewStart()) track.append(line);
    }
    rows.push(el("div", { class: "t-row" }, label, track));
  }
  tl.replaceChildren(...rows);
}

function renderBlock(day, b, index) {
  const sel = st.selected && st.selected.day === day && st.selected.index === index;
  const node = el("div", {
    class: "block" + (b.kind === SIGNOFF ? " signoff" : "") + (sel ? " selected" : ""),
    "data-day": day, "data-index": String(index),
    title: `${blockTitle(b)} · ${hh(b.start)}–${hh(b.end)}`,
  },
  el("span", { class: "name" }, blockTitle(b)),
  el("span", { class: "meta" }, blockMeta(b)));
  const from = Math.max(b.start, viewStart());
  node.style.left = `${pos(from)}%`;
  node.style.width = `calc(${((b.end - from) / span()) * 100}% - 3px)`;
  if (b.kind !== SIGNOFF) {
    node.style.background = blockColor(b);
    node.append(el("i", { class: "h l", "data-edge": "start" }), el("i", { class: "h r", "data-edge": "end" }));
  }
  return node;
}

function renderPalette() {
  const items = contentList().map((c) => ({ value: c.tag, label: shortLabel(c.tag), color: colorOf(c.tag), program: c.tag.includes("/") }));
  items.push({ value: SIGNOFF, label: "🌙 Fin de transmisión", color: "#3d4170" });
  if (!items.some((i) => i.value === st.brush)) st.brush = items[0].value;
  $("palette").replaceChildren(...items.map((it) => {
    const swatch = el("i");
    swatch.style.background = it.color;
    return el("button", {
      class: "brush" + (st.brush === it.value ? " active" : "") + (it.program ? " program" : ""), type: "button",
      onclick: () => { st.brush = it.value; renderPalette(); },
    }, swatch, it.program ? `↳ ${it.label}` : it.label);
  }));
  const ads = st.channel.ads || {};
  $("ads-info").textContent = ads.enabled
    ? `Activados: ${BREAKS[ads.strategy] || ads.strategy}, tandas de ${Math.round(ads.duration / 60 * 10) / 10} min. Cada bloque puede usar otro estilo.`
    : "Apagados. Se activan en el panel: Más → Canales → Editar.";
}

function renderInspector() {
  const b = selectedBlock();
  $("insp-empty").hidden = !!b;
  $("insp-body").hidden = !b;
  $("insp-copy-days").hidden = true;
  if (!b) return;
  const { day } = st.selected;
  const isShow = b.kind !== SIGNOFF;
  $("insp-title").textContent = `${DAY_NAME[day]} · ${hh(b.start)}–${hh(b.end)}`;
  $("insp-show").hidden = !isShow;
  $("insp-signoff").hidden = isShow;

  const startSel = $("insp-start");
  const endSel = $("insp-end");
  startSel.replaceChildren(...Array.from({ length: 24 }, (_, h) => el("option", { value: h }, hh(h))));
  endSel.replaceChildren(...Array.from({ length: 24 }, (_, h) => el("option", { value: h + 1 }, hh(h + 1))));
  startSel.value = b.start;
  endSel.value = b.end;
  endSel.disabled = !isShow;
  if (!isShow) return;

  $("insp-tags").replaceChildren(...contentList().map((c) => {
    const box = el("input", { type: "checkbox", value: c.tag });
    box.checked = b.tags.includes(c.tag);
    box.addEventListener("change", () => {
      const tags = contentList().map((x) => x.tag).filter((t) => (t === c.tag ? box.checked : b.tags.includes(t)));
      if (!tags.length) { box.checked = true; toast("El bloque necesita al menos una categoría o programa."); return; }
      updateSelected({ tags, mode: tags.length > 1 ? "random" : b.mode });
    });
    const sw = el("i", { class: "sw" });
    sw.style.background = colorOf(c.tag);
    const program = c.tag.includes("/");
    return el("label", { class: program ? "program" : null }, box, sw, program ? `↳ ${shortLabel(c.tag)}` : c.label);
  }));
  $("insp-mix-note").hidden = b.tags.length < 2;
  document.querySelectorAll('input[name="insp-mode"]').forEach((r) => {
    r.checked = r.value === b.mode;
    r.disabled = r.value === "order" && b.tags.length > 1;
  });
  const preset = Object.entries(DURATIONS).find(([, [mn, mx]]) => mn === b.min_minutes && mx === b.max_minutes);
  $("insp-duration").value = preset ? preset[0] : "custom";
  $("insp-custom").hidden = !!preset;
  $("insp-min").value = b.min_minutes || "";
  $("insp-max").value = b.max_minutes || "";
  $("insp-breaks").value = b.breaks || "";
  const adsOn = st.channel.ads && st.channel.ads.enabled;
  $("insp-breaks").disabled = !adsOn;
  $("insp-ads-off").hidden = !!adsOn;
  const pautas = st.channel.pautas || [];
  $("insp-pauta").replaceChildren(el("option", { value: "" }, "Comerciales del canal"),
    ...pautas.map((x) => el("option", { value: x.tag }, `Pauta: ${x.label}`)));
  $("insp-pauta").value = b.pauta || "";
  $("insp-pauta").disabled = !adsOn || !pautas.length;
  const vids = fixedVideos();
  for (const key of ["start_video", "end_video"]) {
    const sel = $(key === "start_video" ? "insp-start-video" : "insp-end-video");
    const names = b[key] && !vids.includes(b[key]) ? [...vids, b[key]] : vids;
    sel.replaceChildren(el("option", { value: "" }, "Ninguno"), ...names.map((n) => el("option", { value: n }, n)));
    sel.value = b[key] || "";
    sel.disabled = !names.length;
  }
  $("insp-fixed-note").hidden = vids.length > 0;
}

function renderStatus() {
  const dirty = isDirty();
  $("save").disabled = !dirty;
  $("undo").disabled = !st.undo.length;
  $("redo").disabled = !st.redo.length;
  const s = $("save-state");
  if (s.textContent !== "Guardando…") s.textContent = dirty ? "● Cambios sin guardar" : "Todo guardado";
  s.classList.toggle("dirty", dirty);
}

function refresh() {
  render();
  renderInspector();
  renderStatus();
}

function updateSelected(changes) {
  const sel = st.selected;
  commit(() => { Object.assign(st.week[sel.day][sel.index], changes); });
}

// ---------- mouse: create, move, resize ----------

function hourAt(track, clientX) {
  const r = track.getBoundingClientRect();
  return Math.max(viewStart(), Math.min(23, viewStart() + Math.floor(((clientX - r.left) / r.width) * span())));
}

function trackAt(clientX, clientY) {
  const node = document.elementFromPoint(clientX, clientY);
  return node && node.closest(".t-track");
}

function showGhost(track, start, end, bad) {
  document.querySelectorAll(".ghost").forEach((g) => g.remove());
  if (!track) return;
  const g = el("div", { class: "ghost" + (bad ? " bad" : "") });
  g.style.left = `${pos(start)}%`;
  g.style.width = `calc(${((end - start) / span()) * 100}% - 3px)`;
  track.append(g);
}

function onPointerDown(e) {
  if (e.button !== 0) return;
  const track = e.target.closest(".t-track");
  if (!track) return;
  const blockNode = e.target.closest(".block");
  const day = track.dataset.day;
  const hour = hourAt(track, e.clientX);
  e.preventDefault();

  if (!blockNode) {
    st.drag = { type: "create", day, anchor: hour, start: hour, end: hour + 1, track };
    showGhost(track, hour, hour + 1, false);
  } else {
    const index = Number(blockNode.dataset.index);
    const b = st.week[day][index];
    st.selected = { day, index };
    const edge = e.target.dataset.edge;
    st.drag = edge
      ? { type: "resize", edge, day, index, start: b.start, end: b.end, track, moved: false }
      : { type: "move", day, index, offset: hour - b.start, len: b.end - b.start, start: b.start, end: b.end, target: day, track, moved: false };
    refresh();
    // refresh() redraws the timeline: keep working with the new row
    st.drag.track = document.querySelector(`.t-track[data-day="${day}"]`);
  }
  window.addEventListener("pointermove", onPointerMove);
  window.addEventListener("pointerup", onPointerUp, { once: true });
}

function onPointerMove(e) {
  const d = st.drag;
  if (!d) return;
  if (d.type === "create") {
    const h = hourAt(d.track, e.clientX);
    d.start = Math.min(d.anchor, h);
    d.end = Math.max(d.anchor, h) + 1;
    if (st.brush === SIGNOFF) d.end = d.start + 1;
    showGhost(d.track, d.start, d.end, false);
  } else if (d.type === "move") {
    const track = trackAt(e.clientX, e.clientY) || d.track;
    const h = hourAt(track, e.clientX);
    d.target = track.dataset.day;
    d.start = Math.max(0, Math.min(24 - d.len, h - d.offset));
    d.end = d.start + d.len;
    d.moved = true;
    const ignore = d.target === d.day ? d.index : -1;
    d.ok = fits(d.target, d.start, d.end, ignore);
    showGhost(track, d.start, d.end, !d.ok);
  } else if (d.type === "resize") {
    const h = hourAt(d.track, e.clientX);
    const b = st.week[d.day][d.index];
    if (d.edge === "start") d.start = Math.min(h, b.end - 1);
    else d.end = Math.max(h + 1, b.start + 1);
    d.moved = true;
    d.ok = fits(d.day, d.start, d.end, d.index);
    showGhost(d.track, d.start, d.end, !d.ok);
  }
}

function onPointerUp() {
  window.removeEventListener("pointermove", onPointerMove);
  document.querySelectorAll(".ghost").forEach((g) => g.remove());
  const d = st.drag;
  st.drag = null;
  if (!d) return;
  if (d.type === "create") {
    commit(() => paint(d.day, brushBlock(d.start, d.end)));
  } else if (d.type === "move" && d.moved) {
    if (!d.ok) { toast("Ahí ya hay otro bloque. Bórralo o achícalo primero."); return; }
    commit(() => {
      const [b] = st.week[d.day].splice(d.index, 1);
      const moved = { ...b, start: d.start, end: d.end };
      st.week[d.target].push(moved);
      sortDay(d.target);
      st.selected = { day: d.target, index: st.week[d.target].indexOf(moved) };
    });
  } else if (d.type === "resize" && d.moved) {
    if (!d.ok) { toast("No puede pisar otro bloque."); return; }
    updateSelected({ start: d.start, end: d.end });
  }
}

// ---------- inspector actions ----------

function wireInspector() {
  $("insp-start").addEventListener("change", (e) => {
    const b = selectedBlock();
    const start = Number(e.target.value);
    const len = b.end - b.start;
    let end = b.kind === SIGNOFF ? start + 1 : Math.max(start + 1, Math.min(24, b.end));
    if (b.kind !== SIGNOFF && end <= start) end = Math.min(24, start + len);
    if (!fits(st.selected.day, start, end, st.selected.index)) { toast("Ahí ya hay otro bloque."); renderInspector(); return; }
    updateSelected({ start, end });
  });
  $("insp-end").addEventListener("change", (e) => {
    const b = selectedBlock();
    const end = Number(e.target.value);
    if (end <= b.start) { toast("Tiene que terminar después de empezar."); renderInspector(); return; }
    if (!fits(st.selected.day, b.start, end, st.selected.index)) { toast("Ahí ya hay otro bloque."); renderInspector(); return; }
    updateSelected({ end });
  });
  document.querySelectorAll('input[name="insp-mode"]').forEach((r) => r.addEventListener("change", () => updateSelected({ mode: r.value })));
  $("insp-duration").addEventListener("change", (e) => {
    if (e.target.value === "custom") { $("insp-custom").hidden = false; return; }
    const [min_minutes, max_minutes] = DURATIONS[e.target.value];
    updateSelected({ min_minutes, max_minutes });
  });
  const custom = () => {
    const mn = Number($("insp-min").value) || null;
    const mx = Number($("insp-max").value) || null;
    if (mn && mx && mn > mx) { toast("El mínimo no puede ser mayor que el máximo."); return; }
    updateSelected({ min_minutes: mn, max_minutes: mx });
  };
  $("insp-min").addEventListener("change", custom);
  $("insp-max").addEventListener("change", custom);
  $("insp-breaks").addEventListener("change", (e) => updateSelected({ breaks: e.target.value || null }));
  $("insp-pauta").addEventListener("change", (e) => updateSelected({ pauta: e.target.value || null }));
  $("insp-start-video").addEventListener("change", (e) => updateSelected({ start_video: e.target.value || null }));
  $("insp-end-video").addEventListener("change", (e) => updateSelected({ end_video: e.target.value || null }));
  $("insp-delete").addEventListener("click", deleteSelected);
  $("insp-copy").addEventListener("click", () => {
    const box = $("insp-copy-days");
    box.hidden = !box.hidden;
    $("insp-copy-checks").replaceChildren(...DAYS.filter(([d]) => d !== st.selected.day)
      .map(([d, n]) => el("label", {}, el("input", { type: "checkbox", value: d }), n)));
  });
  $("insp-copy-go").addEventListener("click", () => {
    const b = selectedBlock();
    const days = [...$("insp-copy-checks").querySelectorAll("input:checked")].map((i) => i.value);
    if (!days.length) { toast("Elige al menos un día."); return; }
    const from = st.selected;
    commit(() => { days.forEach((d) => paint(d, clone(b))); st.selected = from; });
    toast(`Bloque copiado a ${days.length} día(s).`);
  });
}

// ---------- dialogs: copy day, random, duplicate ----------

function dayChecks(container, checked = []) {
  container.replaceChildren(...DAYS.map(([d, n]) => {
    const box = el("input", { type: "checkbox", value: d });
    box.checked = checked.includes(d);
    return el("label", {}, box, n);
  }));
}

const picked = (container) => [...container.querySelectorAll("input:checked")].map((i) => i.value);

function openCopy(day) {
  $("copy-from").replaceChildren(...DAYS.map(([d, n]) => el("option", { value: d }, n)));
  $("copy-from").value = day || (st.selected ? st.selected.day : "monday");
  dayChecks($("copy-to"));
  $("dlg-copy").showModal();
}

function wireDialogs() {
  $("open-copy").addEventListener("click", () => openCopy());
  document.querySelectorAll("[data-pick]").forEach((b) => b.addEventListener("click", () => {
    const sets = {
      weekdays: ["monday", "tuesday", "wednesday", "thursday", "friday"],
      weekend: ["saturday", "sunday"], all: DAYS.map((d) => d[0]), none: [],
    };
    dayChecks($("copy-to"), sets[b.dataset.pick].filter((d) => d !== $("copy-from").value));
  }));
  $("copy-go").addEventListener("click", () => {
    const from = $("copy-from").value;
    const to = picked($("copy-to")).filter((d) => d !== from);
    if (!to.length) return;
    commit(() => { to.forEach((d) => { st.week[d] = clone(st.week[from]); }); st.selected = null; });
    toast(`${DAY_NAME[from]} copiado a ${to.length} día(s).`);
  });

  $("open-random").addEventListener("click", () => {
    const hours = Array.from({ length: 25 }, (_, h) => el("option", { value: h }, hh(h)));
    $("rnd-from").replaceChildren(...hours.slice(0, 24));
    $("rnd-to").replaceChildren(...hours.map((o) => o.cloneNode(true)).slice(1));
    $("rnd-from").value = 7;
    $("rnd-to").value = 20;
    $("rnd-tags").replaceChildren(...categories().map((c) => el("label", {}, el("input", { type: "checkbox", value: c.tag, checked: true }), c.label)));
    dayChecks($("rnd-days"), DAYS.map((d) => d[0]));
    $("dlg-random").showModal();
  });
  $("rnd-go").addEventListener("click", (e) => {
    const from = Number($("rnd-from").value);
    const to = Number($("rnd-to").value);
    const tags = picked($("rnd-tags"));
    const days = picked($("rnd-days"));
    if (to <= from || !tags.length || !days.length) {
      e.preventDefault();
      toast("Revisa las horas, las categorías y los días.");
      return;
    }
    const lenMode = $("rnd-len").value;
    const mix = $("rnd-mix").checked;
    const signoff = $("rnd-signoff").checked;
    const pick = (list) => list[Math.floor(Math.random() * list.length)];
    commit(() => {
      for (const day of days) {
        const blocks = [];
        let h = from;
        let last = null;
        while (h < to) {
          const len = lenMode === "mix" ? 1 + Math.floor(Math.random() * 3) : Number(lenMode);
          const end = Math.min(to, h + len);
          let choice = tags.length > 1 ? pick(tags.filter((t) => t !== last)) : tags[0];
          const blockTags = [choice];
          if (mix && tags.length > 1 && Math.random() < 0.3) blockTags.push(pick(tags.filter((t) => t !== choice)));
          blocks.push({ start: h, end, kind: "show", tags: blockTags, mode: "random", breaks: null, min_minutes: null, max_minutes: null,
            pauta: null, start_video: null, end_video: null });
          last = choice;
          h = end;
        }
        if (signoff && to < 24) blocks.push({ start: to, end: to + 1, kind: SIGNOFF });
        st.week[day] = blocks;
      }
      st.selected = null;
    });
    toast("Programación al azar lista. Revísala y guarda.");
  });

  $("open-dup").addEventListener("click", () => {
    $("dup-src").textContent = st.channel.long_name;
    $("dup-name").value = `${st.channel.long_name} 2`;
    const used = new Set(st.channels.map((c) => c.number));
    let n = 2;
    while (used.has(n) && n < 99) n += 1;
    $("dup-number").value = n;
    $("dup-error").textContent = "";
    $("dlg-dup").showModal();
  });
  $("dup-go").addEventListener("click", async (e) => {
    e.preventDefault();
    if (isDirty()) { $("dup-error").textContent = "Primero guarda los cambios de este canal."; return; }
    try {
      const res = await api(`/api/channels/${encodeURIComponent(st.channel.name)}/duplicate`, {
        json: { long_name: $("dup-name").value, number: Number($("dup-number").value) },
      });
      $("dlg-dup").close();
      toast("Canal creado. La tele se reinicia en unos segundos.");
      await loadChannels(res.name);
    } catch (err) {
      $("dup-error").textContent = err.message;
    }
  });
}

// ---------- keyboard ----------

function onKey(e) {
  const typing = ["INPUT", "SELECT", "TEXTAREA"].includes(document.activeElement.tagName);
  const mod = e.ctrlKey || e.metaKey;
  if (mod && e.key.toLowerCase() === "s") { e.preventDefault(); save(); return; }
  if (typing || document.querySelector("dialog[open]")) return;
  if (mod && e.key.toLowerCase() === "z" && !e.shiftKey) { e.preventDefault(); undo(); }
  else if (mod && (e.key.toLowerCase() === "y" || (e.key.toLowerCase() === "z" && e.shiftKey))) { e.preventDefault(); redo(); }
  else if ((e.key === "Delete" || e.key === "Backspace") && st.selected) { e.preventDefault(); deleteSelected(); }
  else if (mod && e.key.toLowerCase() === "c" && selectedBlock()) { st.clipboard = clone(selectedBlock()); toast("Bloque copiado. Elige un día y pega con Ctrl+V."); }
  else if (mod && e.key.toLowerCase() === "v" && st.clipboard) {
    // pastes on the day after the selected block (pasting again keeps moving forward)
    const target = st.selected ? nextDay(st.selected.day) : DAYS[(new Date().getDay() + 6) % 7][0];
    commit(() => paint(target, clone(st.clipboard)));
    toast(`Pegado en ${DAY_NAME[target]}.`);
  } else if (e.key === "Escape") { st.selected = null; refresh(); }
}

function nextDay(day) {
  const i = DAYS.findIndex((d) => d[0] === day);
  return DAYS[(i + 1) % 7][0];
}

// ---------- loading ----------

async function loadChannels(selectName) {
  const data = await api("/api/channels");
  st.channels = data.channels;
  st.library = data.library;
  const scheduled = st.channels.filter((c) => c.kind === "schedule");
  const sel = $("channel");
  sel.replaceChildren(...scheduled.map((c) => el("option", { value: c.name }, `${c.number} · ${c.long_name}`)));
  if (!scheduled.length) {
    $("layout").hidden = true;
    toast("No hay canales con horario. Crea uno en el panel: Más → Canales → Nuevo → Con horario.");
    return;
  }
  const name = selectName && scheduled.some((c) => c.name === selectName) ? selectName
    : (st.channel && scheduled.some((c) => c.name === st.channel.name) ? st.channel.name : scheduled[0].name);
  sel.value = name;
  openChannel(name);
}

function openChannel(name) {
  st.channel = st.channels.find((c) => c.name === name);
  st.week = clone(st.channel.blocks);
  for (const [d] of DAYS) st.week[d] = st.week[d] || [];
  st.saved = snapshot();
  st.undo = [];
  st.redo = [];
  st.selected = null;
  $("layout").hidden = false;
  renderPalette();
  refresh();
}

function showLogin() {
  $("login").hidden = false;
  $("login-pin").focus();
}

async function start() {
  try {
    const s = await api("/api/session");
    if (!s.logged_in) { showLogin(); return; }
    $("login").hidden = true;
    await loadChannels();
  } catch (e) {
    toast(e.message);
  }
}

function wire() {
  $("timeline").addEventListener("pointerdown", onPointerDown);
  $("view-from").addEventListener("change", (e) => { st.viewFrom = e.target.value; render(); });
  window.addEventListener("keydown", onKey);
  $("save").addEventListener("click", save);
  $("undo").addEventListener("click", undo);
  $("redo").addEventListener("click", redo);
  $("channel").addEventListener("change", (e) => {
    if (isDirty() && !confirm("Hay cambios sin guardar en este canal. ¿Descartarlos?")) {
      e.target.value = st.channel.name;
      return;
    }
    openChannel(e.target.value);
  });
  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      await api("/api/login", { json: { pin: $("login-pin").value } });
      $("login-error").textContent = "";
      start();
    } catch (err) {
      $("login-error").textContent = err.message;
    }
  });
  window.addEventListener("beforeunload", (e) => { if (isDirty()) e.preventDefault(); });
  // keep the "now" line moving
  setInterval(() => { if (st.week && !st.drag) render(); }, 60000);
  wireInspector();
  wireDialogs();
}

wire();
start();
