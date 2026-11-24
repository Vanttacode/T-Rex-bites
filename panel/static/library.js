"use strict";
// Library: every video of the TV, by category and program. Also the folder
// view (upload by dragging, pick several, move, delete) that channel pages
// reuse for their commercials, cortinillas and fixed videos.
// Uses $, api, el, toast, formatSize, fmtDuration, uploadFiles, pickFiles,
// loadChannels, channelsCache, libraryCache, whenNames, wide, currentTab from app.js.

const selection = new Map();   // key -> {channel, tag, name}
const probed = new Set();
const selKey = (channel, tag, name) => `${channel || ""}|${tag || ""}|${name}`;
let libCurrent = null;         // tag of the open library folder
let libMobileOpen = false;     // phone: folder list or one folder
let redrawCurrent = () => {};  // re-render whatever screen shows folders

// ---------- destinations (move to…) ----------

const destValue = (channel, tag) => `${channel || ""}|${tag ?? ""}`;
function parseDest(value) {
  const i = value.indexOf("|");
  return { channel: value.slice(0, i) || null, tag: value.slice(i + 1) || null };
}

function destGroups(selected) {
  const groups = [];
  const lib = el("optgroup", { label: "📚 Biblioteca" });
  for (const c of libraryCache.content) {
    const program = c.tag.includes("/");
    lib.append(el("option", { value: destValue(null, c.tag) }, program ? `   ↳ ${c.label.split(" › ").pop()}` : c.label));
  }
  groups.push(lib);
  for (const ch of channelsCache) {
    if (!ch.folders.length) continue;
    const g = el("optgroup", { label: `📺 ${ch.number} · ${ch.long_name}` });
    ch.folders.forEach((f) => g.append(el("option", { value: destValue(ch.name, f.tag) }, f.label)));
    groups.push(g);
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

// ---------- one folder: header, upload, videos ----------

function sameSizeCount(folders) {
  const sizes = {};
  folders.forEach((f) => f.videos.forEach((v) => { if (!v.placeholder) sizes[v.size] = (sizes[v.size] || 0) + 1; }));
  return sizes;
}

function thumbUrl(channel, tag, name) {
  return `/api/library/thumb?channel=${encodeURIComponent(channel || "")}&tag=${encodeURIComponent(tag ?? "")}&name=${encodeURIComponent(name)}`;
}

function videoItem(channel, f, v, sizes) {
  const k = selKey(channel, f.tag, v.name);
  const box = el("input", { type: "checkbox", "aria-label": `Elegir ${v.file || v.name}` });
  box.checked = selection.has(k);
  box.disabled = v.placeholder;
  const badges = el("span", { class: "vmeta" }, [fmtDuration(v.duration), formatSize(v.size)].filter(Boolean).join(" · "));
  if (v.placeholder) badges.append(el("span", { class: "badge" }, "de ejemplo"));
  if (v.when) badges.append(el("span", { class: "badge when" }, "🕒 " + v.when));
  if (!v.placeholder && sizes[v.size] > 1) badges.append(el("span", { class: "badge dup" }, "repetido"));
  const img = el("img", { alt: "", loading: "lazy", src: thumbUrl(channel, f.tag, v.name) });
  const item = el("label", { class: "vcard" + (box.checked ? " picked" : ""), title: v.file || v.name },
    box, img, el("span", { class: "vbody" }, el("span", { class: "vname" }, v.file || v.name), badges));
  box.addEventListener("change", () => {
    if (box.checked) selection.set(k, { channel, tag: f.tag, name: v.name }); else selection.delete(k);
    item.classList.toggle("picked", box.checked);
    updateSelbar();
  });
  return item;
}

function whenPicker() {
  if (!whenNames) return { node: null, value: () => ({}) };
  const mk = (first, map) => el("select", {}, el("option", { value: "" }, first),
    ...Object.entries(map).map(([k, v]) => el("option", { value: k }, v)));
  const part = mk("Todo el día", whenNames.parts);
  const day = mk("Todos los días", whenNames.days);
  const month = mk("Todo el año", whenNames.months);
  const summary = el("small", {}, "Siempre");
  const update = () => {
    const bits = [part, day, month].filter((s) => s.value).map((s) => s.selectedOptions[0].textContent.split(" (")[0]);
    summary.textContent = bits.length ? bits.join(" · ") : "Siempre";
  };
  [part, day, month].forEach((s) => s.addEventListener("change", update));
  const node = el("details", { class: "when-box" }, el("summary", {}, "🕒 ¿Cuándo pueden salir los videos que subas? ", summary),
    el("p", { class: "muted small" }, "Ej: el comercial de cereales solo en la mañana, el especial de Navidad solo en diciembre."),
    el("div", { class: "time-grid" }, el("label", {}, "Momento del día", part), el("label", {}, "Día", day), el("label", {}, "Mes", month)));
  return { node, value: () => ({ when_part: part.value, when_day: day.value, when_month: month.value }) };
}

/**
 * A folder of videos: title, "Subir videos", optional "when" picker, a drop
 * zone and the videos. opts: {title, subtitle, showWhen, actions: [nodes], onBack}
 */
function folderView(channel, f, opts = {}) {
  const real = f.videos.filter((v) => !v.placeholder);
  const total = real.reduce((t, v) => t + (v.duration || 0), 0);
  const where = opts.where || f.label;
  const when = opts.showWhen ? whenPicker() : { node: null, value: () => ({}) };
  const upload = (files) => {
    if (!files || !files.length) return;
    uploadFiles(files, channel, f.tag, where, when.value());
    toast(`${files.length} video${files.length === 1 ? "" : "s"} subiendo a ${where}`);
  };
  const all = el("input", { type: "checkbox" });
  all.checked = real.length > 0 && real.every((v) => selection.has(selKey(channel, f.tag, v.name)));
  all.disabled = !real.length;
  all.addEventListener("change", () => {
    real.forEach((v) => {
      const k = selKey(channel, f.tag, v.name);
      if (all.checked) selection.set(k, { channel, tag: f.tag, name: v.name }); else selection.delete(k);
    });
    redrawCurrent();
  });
  const head = el("div", { class: "pane-head" });
  if (opts.onBack) head.append(el("button", { class: "btn small ghost", type: "button", onclick: opts.onBack }, "←"));
  head.append(el("div", { class: "grow" }, el(opts.small ? "h3" : "h2", {}, opts.title || f.label),
    el("span", { class: "muted small" }, opts.subtitle || `${real.length} videos${total ? " · " + fmtDuration(total) : ""}`)));
  (opts.actions || []).forEach((a) => head.append(a));
  head.append(el("button", { class: "btn small", type: "button", onclick: () => pickFiles(upload) }, "📤 Subir videos"));

  const zone = el("div", { class: "drop" }, el("span", {}, "📼 Arrastra videos aquí para subirlos a ", el("b", {}, where)));
  const box = el("div", { class: "folder" + (opts.small ? " small" : "") }, head);
  if (when.node) box.append(when.node);
  if (real.length) box.append(el("label", { class: "switch selall" }, all, " Elegir todos"));
  const sizes = opts.sizes || sameSizeCount([f]);
  if (f.videos.length) {
    box.append(el("div", { class: "vgrid" }, ...f.videos.map((v) => videoItem(channel, f, v, sizes))));
  }
  box.append(zone);
  // the whole folder accepts dropped files
  box.addEventListener("dragover", (e) => { e.preventDefault(); box.classList.add("over"); });
  box.addEventListener("dragleave", (e) => { if (!box.contains(e.relatedTarget)) box.classList.remove("over"); });
  box.addEventListener("drop", (e) => { e.preventDefault(); box.classList.remove("over"); upload(e.dataTransfer.files); });
  zone.addEventListener("click", () => pickFiles(upload));
  if (f.videos.some((v) => v.duration == null && !v.placeholder)) probeFolder(channel, f);
  return box;
}

async function probeFolder(channel, f) {
  const key = `${channel}|${f.tag}`;
  if (probed.has(key)) return;
  probed.add(key);
  try {
    const res = await api("/api/library/probe", { json: { channel, tag: f.tag } });
    let changed = false;
    f.videos.forEach((v) => { if (res.durations[v.name] != null && v.duration == null) { v.duration = res.durations[v.name]; changed = true; } });
    if (changed) redrawCurrent();
  } catch (_) { /* durations are a nice-to-have */ }
}

// ---------- selection bar ----------

function updateSelbar() {
  const n = selection.size;
  $("selbar").hidden = n === 0;
  $("sel-count").textContent = `${n} elegido${n === 1 ? "" : "s"}`;
  const sel = $("sel-dest");
  const prev = sel.value;
  sel.replaceChildren(el("option", { value: "" }, "Mover a…"), ...destGroups(prev));
}

async function refreshAfterChange() {
  await loadChannels();
  redrawCurrent();
}

async function moveSelected() {
  const dest = $("sel-dest").value;
  if (!dest) { toast("Elige a dónde moverlos"); return; }
  const { channel, tag } = parseDest(dest);
  try {
    const r = await api("/api/library/move-many", { json: { items: [...selection.values()], to_channel: channel, to_tag: tag } });
    selection.clear();
    toast(`${r.moved} videos movidos a ${destLabel(dest)}`);
    refreshAfterChange();
  } catch (e) { toast(e.message); }
}

async function deleteSelected() {
  const n = selection.size;
  if (!confirm(`¿Borrar ${n} video${n === 1 ? "" : "s"}? No se puede deshacer.`)) return;
  try {
    const r = await api("/api/library/delete-many", { json: { items: [...selection.values()] } });
    selection.clear();
    toast(`${r.deleted} videos borrados`);
    refreshAfterChange();
  } catch (e) { toast(e.message); }
}

// ---------- categories and programs, edited in place ----------

function treeCopy() {
  return libraryCache.categories.map((c) => ({ tag: c.tag, label: c.label, programs: c.programs.map((p) => ({ tag: p.tag, label: p.label })) }));
}

async function saveTree(tree, message) {
  try {
    const r = await api("/api/library", { method: "PUT", json: { categories: tree } });
    if (message) toast(message);
    await loadChannels();
    return r.categories;
  } catch (e) {
    toast(e.message);
    return null;
  }
}

async function addCategory() {
  const label = (prompt("Nombre de la categoría nueva (ej: Videos musicales, Cuentos):") || "").trim();
  if (!label) return;
  const tree = treeCopy();
  tree.push(label);
  const saved = await saveTree(tree, `Categoría "${label}" creada`);
  if (saved) { libCurrent = saved[saved.length - 1].tag; libMobileOpen = true; drawLibrary(); }
}

async function addProgram(catTag) {
  const cat = libraryCache.categories.find((c) => c.tag === catTag);
  const label = (prompt(`Nombre del programa nuevo dentro de "${cat.label}" (ej: Bluey, Oliver Tree):`) || "").trim();
  if (!label) return;
  const tree = treeCopy();
  tree.find((c) => c.tag === catTag).programs.push(label);
  const saved = await saveTree(tree, `Programa "${label}" creado`);
  if (saved) {
    const progs = saved.find((c) => c.tag === catTag).programs;
    libCurrent = `${catTag}/${progs[progs.length - 1].tag}`;
    libMobileOpen = true;
    drawLibrary();
  }
}

async function renameFolder(tag) {
  const [catTag, progTag] = tag.split("/");
  const tree = treeCopy();
  const cat = tree.find((c) => c.tag === catTag);
  const item = progTag ? cat.programs.find((p) => p.tag === progTag) : cat;
  const label = (prompt("Nuevo nombre:", item.label) || "").trim();
  if (!label || label === item.label) return;
  item.label = label;
  if (await saveTree(tree, "Nombre cambiado")) drawLibrary();
}

async function removeFolder(tag) {
  const [catTag, progTag] = tag.split("/");
  const tree = treeCopy();
  const cat = tree.find((c) => c.tag === catTag);
  const label = progTag ? cat.programs.find((p) => p.tag === progTag).label : cat.label;
  if (!confirm(`¿Quitar "${label}" de la biblioteca? Solo se puede si ya no tiene videos ni la usa ningún canal.`)) return;
  if (progTag) cat.programs = cat.programs.filter((p) => p.tag !== progTag);
  else tree.splice(tree.indexOf(cat), 1);
  if (await saveTree(tree, `"${label}" quitada`)) { libCurrent = null; libMobileOpen = false; drawLibrary(); }
}

// ---------- the library screen ----------

async function openLibraryTab() {
  redrawCurrent = drawLibrary;
  try {
    await loadChannels();
  } catch (e) {
    $("library").replaceChildren(el("p", { class: "error" }, e.message));
    return;
  }
  drawLibrary();
}

function libFolder(tag) {
  return libraryCache.folders.find((f) => f.tag === tag);
}

function usedBy(tag) {
  return channelsCache.filter((c) => (c.tags || []).some((t) => t === tag || t.startsWith(tag + "/") || tag.startsWith(t + "/")))
    .map((c) => c.long_name);
}

function drawTree() {
  const tree = el("div", { class: "card lib-tree" });
  for (const cat of libraryCache.categories) {
    for (const tag of [cat.tag, ...cat.programs.map((p) => `${cat.tag}/${p.tag}`)]) {
      const f = libFolder(tag);
      if (!f) continue;
      const program = tag.includes("/");
      const real = f.videos.filter((v) => !v.placeholder).length;
      const row = el("div", { class: "tree-row" + (program ? " program" : "") },
        el("button", {
          class: "tree-item" + (tag === libCurrent ? " active" : ""), type: "button",
          onclick: () => { libCurrent = tag; libMobileOpen = true; $("lib-search").value = ""; drawLibrary(); },
        }, el("span", {}, program ? `↳ ${f.label.split(" › ").pop()}` : `📁 ${f.label}`), el("span", { class: "count" }, String(real))));
      if (!program) {
        row.append(el("button", { class: "tree-add", type: "button", title: `Nuevo programa en ${cat.label}`,
          "aria-label": `Nuevo programa en ${cat.label}`, onclick: () => addProgram(cat.tag) }, "＋"));
      }
      tree.append(row);
    }
  }
  tree.append(el("button", { class: "btn small ghost wide", type: "button", onclick: addCategory }, "＋ Nueva categoría"));
  return tree;
}

function drawLibrary() {
  if (currentTab !== "library") return;
  const q = $("lib-search").value.trim().toLowerCase();
  const folders = libraryCache.folders;
  if (!libCurrent || !libFolder(libCurrent)) {
    const first = folders.find((f) => f.videos.some((v) => !v.placeholder)) || folders[0];
    libCurrent = first ? first.tag : null;
  }
  const sizes = sameSizeCount(folders);
  const pane = el("section", { class: "card lib-pane" });
  if (q) {
    pane.append(el("h2", {}, `🔎 "${$("lib-search").value.trim()}"`));
    let found = 0;
    for (const f of folders) {
      const videos = f.videos.filter((v) => v.name.toLowerCase().includes(q));
      if (!videos.length) continue;
      found += videos.length;
      pane.append(el("h3", { class: "group-title" }, f.label),
        el("div", { class: "vgrid" }, ...videos.map((v) => videoItem(null, f, v, sizes))));
    }
    if (!found) pane.append(el("p", { class: "muted" }, "Ningún video coincide."));
  } else if (libCurrent) {
    const f = libFolder(libCurrent);
    const users = usedBy(libCurrent);
    const actions = [
      el("button", { class: "btn small ghost", type: "button", title: "Cambiar nombre", onclick: () => renameFolder(libCurrent) }, "✏️"),
      el("button", { class: "btn small ghost", type: "button", title: "Quitar", onclick: () => removeFolder(libCurrent) }, "🗑"),
    ];
    const real = f.videos.filter((v) => !v.placeholder);
    const subtitle = `${real.length} videos` + (users.length ? ` · la usa: ${users.join(", ")}` : " · ningún canal la usa todavía");
    pane.append(folderView(null, f, {
      title: f.tag.includes("/") ? f.label.split(" › ").pop() : f.label, subtitle, actions, sizes, showWhen: true,
      onBack: wide.matches ? null : () => { libMobileOpen = false; drawLibrary(); },
    }));
  } else {
    pane.append(el("p", { class: "muted" }, "Crea tu primera categoría con \"＋ Nueva categoría\"."));
  }
  const showPane = wide.matches || libMobileOpen || q;
  const showTree = wide.matches || !(libMobileOpen || q);
  $("library").replaceChildren(el("div", { class: "lib2" }, ...(showTree ? [drawTree()] : []), ...(showPane ? [pane] : [])));
  $("usb-dest").textContent = libCurrent ? `Se copian a: ${libFolder(libCurrent).label}` : "";
  updateSelbar();
}

function currentUploadTarget() {
  // the USB import copies into the open library folder
  return libCurrent ? { channel: null, tag: libCurrent, label: libFolder(libCurrent).label } : null;
}

(function wireLibrary() {
  $("lib-search").addEventListener("input", () => drawLibrary());
  $("lib-usb").addEventListener("click", () => { $("usb-card").hidden = !$("usb-card").hidden; if (!$("usb-card").hidden) usbRefresh(); });
  $("sel-move").addEventListener("click", moveSelected);
  $("sel-delete").addEventListener("click", deleteSelected);
  $("sel-clear").addEventListener("click", () => { selection.clear(); redrawCurrent(); updateSelbar(); });
  wide.addEventListener("change", () => redrawCurrent());
  afterUpload.push(refreshAfterChange);
}());
