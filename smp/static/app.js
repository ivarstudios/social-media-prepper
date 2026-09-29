// IVAR SMP front end: plain JS, no build step.
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const state = { root: "", folders: [], folder: "", preview: [], settings: {}, pollTimer: null };

async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (_) {}
    throw new Error(msg);
  }
  return r.json();
}

function esc(s) { return String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function show(v) { return Array.isArray(v) ? v.join(", ") : (v ?? ""); }

function toast(msg, action) {
  const t = $("#toast");
  t.innerHTML = `<span>${esc(msg)}</span>`;
  if (action) {
    const b = document.createElement("button");
    b.textContent = action.label;
    b.onclick = () => { t.hidden = true; action.fn(); };
    t.appendChild(b);
  }
  t.hidden = false;
  clearTimeout(t._h);
  t._h = setTimeout(() => (t.hidden = true), action ? 15000 : 4000);
}

function ask(title, text, buttons) {
  return new Promise(resolve => {
    const d = $("#confirmDlg");
    $("#confirmTitle").textContent = title;
    $("#confirmText").textContent = text;
    const box = $("#confirmActions");
    box.innerHTML = "";
    buttons.forEach(([label, value, ghost]) => {
      const b = document.createElement("button");
      b.textContent = label; b.value = value; if (ghost) b.className = "ghost";
      box.appendChild(b);
    });
    d.onclose = () => resolve(d.returnValue);
    d.showModal();
  });
}

// ---- status & settings --------------------------------------------------------------------------------------
const gb = n => `${Math.round(n)} GB`;

async function loadStatus() {
  let s;
  try { s = await api("/api/status"); } catch (e) { $("#statusDot").className = "dot bad"; return null; }
  state.status = s;
  $("#versionTag").textContent = "v" + s.version;
  $("#statusDot").className = "dot " + (!s.exiftool ? "bad" : s.ready ? "ok" : "warn");
  $("#setupBtn").title = s.ready ? "Ready" : "Something needs setting up";
  renderSetup(s);
  return s;
}

function renderSetup(s) {
  const ex = $("#suExif");
  ex.className = "check-row " + (s.exiftool ? "ok" : "bad");
  ex.textContent = s.exiftool ? `ExifTool ${s.exiftool}: ready` :
    "ExifTool is missing. Run install.bat (Windows) or install.sh (Mac/Linux) again.";
  $$("input[name=suBackend]").forEach(r => (r.checked = r.value === s.backend));
  $("#suLocal").hidden = s.backend !== "ollama";
  $("#suClaude").hidden = s.backend !== "claude";

  const g = s.gpu, o = s.ollama;
  $("#suGpu").textContent = g.name ? `${g.name}: about ${gb(g.memory_gb)} for models.` :
    "No suitable GPU found: a local model will be very slow here. The Claude API is the better choice.";
  let model;
  if (!o.exe) model = `<div class="check-row bad">Ollama isn't installed. Run the installer again, or use the Claude API.</div>`;
  else if (o.ready) model = `<div class="check-row ok">Model <b>${esc(o.model)}</b> is downloaded and ready.</div>`;
  else model = `<div class="check-row">Model for this computer: <b>${esc(o.model)}</b>` +
    (o.approx_gb ? `, about ${gb(o.approx_gb)} to download.` : ", not downloaded yet.") + `</div>`;
  $("#suModel").innerHTML = model;
  const p = s.pull || {};
  $("#suPullBtn").hidden = !o.exe || o.ready;
  $("#suPullBtn").disabled = !!p.running;
  $("#suPull").hidden = !p.running && !p.error;
  if (p.running || p.error) {
    $("#suPullFill").style.width = p.total ? (100 * p.done / p.total) + "%" : "2%";
    $("#suPullText").textContent = p.error ? "Failed: " + p.error :
      `${p.status || ""}${p.total ? ` · ${gb(p.done / 1e9)} of ${gb(p.total / 1e9)}` : ""}`;
  }
  $("#suKeyState").innerHTML = s.claude_key
    ? `<div class="check-row ok">A key is set${s.claude_key_saved ? " (saved in SMP)" : " (from the environment)"}. Model: ${esc(s.claude_model)}.</div>`
    : `<div class="check-row">No API key yet. Create one at console.anthropic.com and paste it here.</div>`;
  $("#suPlaces").textContent = s.places ? "Place names for GPS positions are installed." :
    "Place names for GPS positions (about 10 MB) download on the first run.";
}

$("#setupBtn").onclick = async () => { await loadStatus(); $("#setupDlg").showModal(); };
$$("input[name=suBackend]").forEach(r => r.onchange = async () => {
  state.settings = await api("/api/settings", { backend: r.value });
  $("#backend").value = r.value;
  loadStatus();
});
$("#suPullBtn").onclick = async () => {
  try { await api("/api/model/pull", { model: state.status?.ollama?.model }); } catch (e) { toast(e.message); }
  pollPull();
};
async function pollPull() {
  const s = await loadStatus();
  if (s && s.pull && s.pull.running) setTimeout(pollPull, 1500);
  else if (s && s.ollama.ready) toast("Vision model downloaded");
}
$("#suKeyBtn").onclick = async () => {
  await api("/api/claude-key", { key: $("#suKey").value });
  $("#suKey").value = "";
  loadStatus();
};

// fields SMP works out by itself: empty unless the user typed something; the detected value is the placeholder
const DETECTED = ["ollama_model", "ollama_url", "ollama_exe", "ollama_models_dir", "exiftool"];

async function loadSettings() {
  state.settings = await api("/api/settings");
  $("#backend").value = state.settings.backend || "ollama";
  $("#recent").innerHTML = (state.settings.recent_folders || []).map(f => `<option value="${esc(f)}">`).join("");
  if (!$("#folder").value && state.settings.recent_folders?.length) $("#folder").value = state.settings.recent_folders[0];
}

$("#settingsBtn").onclick = async () => {
  await loadSettings();
  const explicit = state.settings._explicit || [];
  for (const el of $("#settingsForm").elements) {
    if (!el.name || !(el.name in state.settings)) continue;
    if (DETECTED.includes(el.name) && !explicit.includes(el.name)) {
      el.value = "";
      el.placeholder = el.name === "ollama_model" ? (state.status?.ollama?.model || "") : state.settings[el.name];
    } else el.value = state.settings[el.name];
  }
  $("#settingsDlg").showModal();
};
$("#settingsDlg").addEventListener("close", async () => {
  if ($("#settingsDlg").returnValue !== "save") return;
  const out = {};
  for (const el of $("#settingsForm").elements) if (el.name) out[el.name] = el.value;
  state.settings = await api("/api/settings", out);
  $("#backend").value = state.settings.backend;
  toast("Settings saved");
  loadStatus();
});
$("#backend").onchange = () => api("/api/settings", { backend: $("#backend").value }).then(loadStatus);

// ---- choose & scan ------------------------------------------------------------------------------------------
// The server opens the operating system's own folder dialog (it may appear behind the browser on some systems).
$("#browseBtn").onclick = async () => {
  const btn = $("#browseBtn");
  btn.disabled = true;
  btn.textContent = "Choosing...";
  try {
    const r = await api("/api/pick-folder", { initial: $("#folder").value.trim() || state.root });
    if (r.path) { $("#folder").value = r.path; scan(); }
  } catch (e) { toast(e.message); }
  btn.disabled = false;
  btn.textContent = "Choose folder";
};
$("#scanForm").onsubmit = e => { e.preventDefault(); scan(); };

async function scan() {
  const folder = $("#folder").value.trim();
  if (!folder) return;
  $("#rootName").textContent = "Scanning...";
  try {
    const r = await api("/api/scan", { folder, recursive: $("#recursive").checked });
    setFolders(r);
    selectFolder(r.root);
    loadSettings();
  } catch (e) { $("#rootName").textContent = "No folder scanned"; toast(e.message); }
}

function setFolders(r) {
  state.root = r.root;
  state.folders = r.folders;
  $("#rootName").textContent = r.root.split(/[\\/]/).filter(Boolean).pop() || r.root;
  $("#rootName").title = r.root;
  const total = r.folders.reduce((a, f) => a + f.images, 0);
  $("#rootCount").textContent = `${total} images in ${r.folders.length} folder${r.folders.length === 1 ? "" : "s"}`;
  const label = { own: "brief", inherited: "inherited", missing: "no brief" };
  $("#folderList").innerHTML = r.folders.map(f => `
    <li data-p="${esc(f.path)}" style="padding-left:${14 + f.depth * 14}px" class="${f.path === state.folder ? "sel" : ""}">
      <span class="name" title="${esc(f.rel)}">${esc(f.rel.split("/").pop())}</span>
      <span class="n">${f.images}${f.done ? " · " + f.done + "✓" : ""}</span>
      <span class="badge ${f.brief}">${label[f.brief]}</span>
    </li>`).join("");
  $$("#folderList li").forEach(li => li.onclick = () => selectFolder(li.dataset.p));
}

async function refreshFolders() { setFolders(await api("/api/folders")); }

async function selectFolder(path) {
  state.folder = path;
  $$("#folderList li").forEach(li => li.classList.toggle("sel", li.dataset.p === path));
  const f = state.folders.find(x => x.path === path) || { images: 0, rel: path, brief: "missing" };
  $("#empty").hidden = true;
  $("#work").hidden = false;
  $("#folderName").textContent = f.rel.split("/").pop();
  $("#folderMeta").textContent = `${f.rel} · ${f.images} image${f.images === 1 ? "" : "s"} here`;
  $("#genFolder").disabled = !f.images;
  await loadBrief();
  const tab = $(".tabs .active").dataset.tab;
  if (tab === "images") loadImages();
  if (tab === "preview") loadPreview();
}

// ---- tabs ---------------------------------------------------------------------------------------------------
$$(".tabs button").forEach(b => b.onclick = () => {
  $$(".tabs button").forEach(x => x.classList.toggle("active", x === b));
  $$(".tab").forEach(t => (t.hidden = t.id !== "tab-" + b.dataset.tab));
  if (b.dataset.tab === "images") loadImages();
  if (b.dataset.tab === "preview") loadPreview();
});
function openTab(name) { $(`.tabs button[data-tab="${name}"]`).click(); }

// ---- brief --------------------------------------------------------------------------------------------------
async function loadBrief() {
  const b = await api("/api/brief?folder=" + encodeURIComponent(state.folder));
  $("#parents").innerHTML = b.parents.map(p => `<div class="parent-brief"><b>From ${esc(p.name)}/brief.md</b>
    ${Object.entries(p.meta).map(([k, v]) => `${esc(k)}: ${esc(show(v))}`).join(" · ")}
    ${p.body ? "\n" + esc(p.body) : ""}</div>`).join("");
  const form = $("#briefForm");
  const own = b.own ? b.own.meta : {};
  const eff = b.effective;
  for (const el of form.elements) {
    if (!el.name) continue;
    if (el.type === "checkbox") el.checked = !!own[el.name];
    else if (el.name === "body") el.value = b.own ? b.own.body : "";
    else {
      el.value = show(own[el.name] ?? "");
      el.placeholder = el.dataset.ph ?? el.placeholder;
      if (!own[el.name] && eff[el.name]) el.placeholder = show(eff[el.name]) + " (inherited)";
    }
  }
  if (!own.set && !eff.set) form.elements.set.placeholder = b.name;
  $("#langInherit").textContent = `Inherited: ${{ en: "English", sv: "Swedish" }[eff.language] || "English"}`;
  const st = $("#briefState");
  if (b.own) { st.className = "note"; st.textContent = "This folder has its own brief.md. Empty fields fall back to the placeholder (inherited or default) values."; }
  else if (b.parents.length) { st.className = "note"; st.textContent = "No brief.md here: the brief above applies. Add details for this folder and save to create one."; }
  else { st.className = "note warn"; st.textContent = "No brief.md for this folder yet. Without one, captions describe only what's visible. Write a few sentences, or press Draft from photos."; }
  $("#briefMsg").textContent = "";
}

$("#briefForm").onsubmit = async e => {
  e.preventDefault();
  const meta = {};
  let body = "";
  for (const el of e.target.elements) {
    if (!el.name) continue;
    if (el.name === "body") body = el.value;
    else if (el.type === "checkbox") meta[el.name] = el.checked;
    else if (el.value.trim()) meta[el.name] = el.value.trim();
  }
  try {
    const r = await api("/api/brief", { folder: state.folder, meta, body });
    $("#briefMsg").textContent = "Saved " + r.saved;
    await refreshFolders();
    await loadBrief();
  } catch (err) { toast(err.message); }
};

$("#draftBtn").onclick = async () => {
  const btn = $("#draftBtn");
  btn.disabled = true;
  $("#briefMsg").textContent = "Looking at sample images... (the local model can take a minute to start)";
  try {
    const r = await api("/api/brief/draft", { folder: state.folder, backend: $("#backend").value });
    const ta = $("#briefForm").elements.body;
    ta.value = (ta.value.trim() ? ta.value.trim() + "\n\n" : "") + r.body;
    $("#briefMsg").textContent = "Draft added. Check anything marked [check], then save.";
  } catch (e) { $("#briefMsg").textContent = ""; toast(e.message); }
  btn.disabled = false;
};

// ---- images -------------------------------------------------------------------------------------------------
async function loadImages() {
  const list = await api("/api/images?folder=" + encodeURIComponent(state.folder));
  const mark = { described: "✓", error: "⚠" };
  $("#imageGrid").innerHTML = list.map(i => `<figure>
      <img loading="lazy" src="${i.thumb}" data-full="${esc(i.path)}" alt="">
      <figcaption><span class="st">${mark[i.status] || ""}</span><div class="t">${esc(i.title || i.name)}</div>
      <div class="muted">${esc((i.caption || "").slice(0, 140))}</div></figcaption></figure>`).join("")
    || `<p class="muted">No images directly in this folder.</p>`;
  $$("#imageGrid img").forEach(img => img.onclick = () => zoom(img.dataset.full));
}

function zoom(path) {
  const z = document.createElement("div");
  z.className = "zoom";
  z.innerHTML = `<img src="/full?path=${encodeURIComponent(path)}">`;
  z.onclick = () => z.remove();
  document.body.appendChild(z);
}

// ---- generate -----------------------------------------------------------------------------------------------
async function generate(all) {
  const scope = all ? state.folders : state.folders.filter(f => f.path === state.folder);
  const missing = scope.filter(f => f.images && f.brief === "missing");
  if (missing.length) {
    const v = await ask("No brief for " + (missing.length === 1 ? "this folder" : missing.length + " folders"),
      "Without a brief.md the model only describes what it sees: no project, place or story context. " +
      "Missing: " + missing.map(f => f.rel.split("/").pop()).slice(0, 8).join(", ") + (missing.length > 8 ? "..." : ""),
      [["Write a brief first", "brief", true], ["Generate anyway", "go"]]);
    if (v !== "go") { if (!all || missing.length) { selectFolder(missing[0].path); openTab("brief"); } return; }
  }
  try {
    await api("/api/generate", { folder: all ? null : state.folder, backend: $("#backend").value });
    poll();
  } catch (e) { toast(e.message); }
}
$("#genFolder").onclick = () => generate(false);
$("#genAll").onclick = () => generate(true);
$("#stopBtn").onclick = () => api("/api/stop", {});

async function poll() {
  clearTimeout(state.pollTimer);
  const j = await api("/api/job");
  $("#jobBar").hidden = false;
  $("#jobFill").style.width = j.total ? (100 * j.done / j.total) + "%" : "3%";
  $("#jobText").textContent = `${j.message}${j.total ? ` · ${j.done} / ${j.total}` : ""}${j.cached ? ` · ${j.cached} cached` : ""}${j.errors ? ` · ${j.errors} failed` : ""}`;
  $("#stopBtn").hidden = !j.running;
  $("#genFolder").disabled = $("#genAll").disabled = j.running;
  if (j.running) { state.pollTimer = setTimeout(poll, 1200); return; }
  await refreshFolders();
  if (j.done) { openTab("preview"); }
}

// ---- preview & write ----------------------------------------------------------------------------------------
const GROUPS = { text: "Text", keywords: "Keywords", classify: "Classification", credits: "Credits", location: "Location", gps: "Privacy" };
const ACT = { new: "new", update: "update", replace: "replace", keep: "keep (person wrote)", fill: "fill", differs: "differs", remove: "remove" };

async function loadPreview() {
  const r = await api("/api/preview", {
    folder: $("#scopeAll").checked ? null : state.folder,
    replace_human: $("#replaceHuman").checked, override_credits: $("#overrideCredits").checked,
  });
  state.preview = r.images;
  renderPreview();
}
["#replaceHuman", "#overrideCredits", "#scopeAll"].forEach(s => $(s).onchange = loadPreview);

function renderPreview() {
  const list = $("#previewList");
  if (!state.preview.length) {
    list.innerHTML = `<p class="muted">Nothing to change yet. Generate metadata for this folder first.</p>`;
    updateCount();
    return;
  }
  list.innerHTML = state.preview.map((img, i) => {
    let last = "";
    const rows = img.rows.map((r, j) => {
      const head = r.group !== last ? `<tr class="group-head"><td colspan="5">${GROUPS[r.group]}</td></tr>` : "";
      last = r.group;
      const isText = ["title", "caption", "alt_text", "extended_description", "keywords"].includes(r.field);
      const val = show(r.proposed);
      const input = isText
        ? `<textarea rows="${r.field === "title" ? 1 : Math.min(6, Math.ceil(val.length / 80) + 1)}" data-i="${i}" data-j="${j}">${esc(val)}</textarea>`
        : `<span>${esc(r.field === "gps" ? "(removed)" : val)}</span>`;
      return head + `<tr class="${r.selected ? "" : "off"}">
        <td class="tick"><input type="checkbox" data-i="${i}" data-j="${j}" ${r.selected ? "checked" : ""}></td>
        <td class="f">${esc(r.label)}</td><td class="cur">${esc(show(r.current)) || "<i>empty</i>"}</td>
        <td class="new">${input}</td><td class="act"><span class="a-${r.action}">${ACT[r.action]}</span></td></tr>`;
    }).join("");
    return `<div class="card"><div><img loading="lazy" src="${img.thumb}" data-full="${esc(img.path)}">
        <div class="fname">${esc(img.rel)}</div>${img.error ? `<div class="err">${esc(img.error)}</div>` : ""}
        <div class="actions"><button class="ghost small" data-all="${i}">All</button><button class="ghost small" data-none="${i}">None</button></div></div>
      <table class="rows">${rows}</table></div>`;
  }).join("");
  $$("#previewList .card img").forEach(im => im.onclick = () => zoom(im.dataset.full));
  $$("#previewList input[type=checkbox]").forEach(cb => cb.onchange = () => {
    state.preview[cb.dataset.i].rows[cb.dataset.j].selected = cb.checked;
    cb.closest("tr").classList.toggle("off", !cb.checked);
    updateCount();
  });
  $$("#previewList textarea").forEach(ta => ta.oninput = () => {
    const r = state.preview[ta.dataset.i].rows[ta.dataset.j];
    r.proposed = r.field === "keywords" ? ta.value.split(",").map(s => s.trim()).filter(Boolean) : ta.value;
    r.edited = true;
    if (!r.selected) { r.selected = true; const cb = ta.closest("tr").querySelector("input"); cb.checked = true; ta.closest("tr").classList.remove("off"); }
    updateCount();
  });
  $$("#previewList [data-all], #previewList [data-none]").forEach(b => b.onclick = () => {
    const i = b.dataset.all ?? b.dataset.none, on = b.dataset.all !== undefined;
    state.preview[i].rows.forEach(r => (r.selected = on));
    renderPreview();
  });
  updateCount();
}

function selectedItems() {
  return state.preview.map(img => ({
    path: img.path,
    rows: img.rows.filter(r => r.selected).map(r => ({ field: r.field, proposed: r.proposed, edited: !!r.edited })),
  })).filter(i => i.rows.length);
}
function updateCount() {
  const items = selectedItems();
  const n = items.reduce((a, i) => a + i.rows.length, 0);
  $("#selCount").textContent = n ? `${n} change${n === 1 ? "" : "s"} in ${items.length} file${items.length === 1 ? "" : "s"}` : "";
  $("#writeBtn").disabled = !n;
}

$("#writeBtn").onclick = async () => {
  const items = selectedItems();
  const n = items.reduce((a, i) => a + i.rows.length, 0);
  const v = await ask("Write to files?", `${n} changes go into ${items.length} files. The old values are kept, so you can undo this.`, [["Cancel", "no", true], ["Write", "yes"]]);
  if (v !== "yes") return;
  $("#writeBtn").disabled = true;
  try {
    const r = await api("/api/write", { items });
    const errs = Object.keys(r.errors || {}).length;
    const box = $("#lastRun");
    box.hidden = false;
    box.className = errs ? "note warn" : "note";
    box.textContent = `Wrote ${r.written} file${r.written === 1 ? "" : "s"}${errs ? `, ${errs} failed: ` + Object.values(r.errors).slice(0, 3).join("; ") : ""}.`;
    if (r.run_id) toast(`Wrote ${r.written} files`, { label: "Undo", fn: () => undo(r.run_id) });
    await loadPreview();
  } catch (e) { toast(e.message); }
  updateCount();
};

async function undo(runId) {
  try {
    const r = await api("/api/undo", { run_id: runId });
    toast(`Restored ${r.restored} files`);
    $("#lastRun").hidden = true;
    loadPreview();
  } catch (e) { toast(e.message); }
}

// ---- start --------------------------------------------------------------------------------------------------
(async () => {
  await loadSettings();
  const st = await loadStatus();
  if (st && !st.ready) $("#setupDlg").showModal();          // first start, or something missing
  if (st && st.pull && st.pull.running) pollPull();
  const r = await api("/api/folders");
  if (r.root) { setFolders(r); $("#folder").value = r.root; selectFolder(r.root); }
  const j = await api("/api/job");
  if (j.running) poll();
})();
