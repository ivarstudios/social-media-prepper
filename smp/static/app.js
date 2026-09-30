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
  $$(".version-tag").forEach(el => (el.textContent = "v" + s.version));
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
    (o.approx_gb ? `, about ${gb(o.approx_gb)} to download` : ", not downloaded yet") +
    ` into <code>${esc(s.folders.models)}</code>.</div>`;
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
const DETECTED = ["ollama_model", "ollama_url", "ollama_exe", "exiftool"];
const FOLDERS = [["tools", "Programs (uv, Python, ExifTool, Ollama)"], ["models", "Vision models"],
                 ["data", "Settings, cache, thumbnails, place names, undo"]];

const DENSITIES = ["comfortable", "medium", "tight"];
function applyDensity(d) {
  document.documentElement.dataset.density = DENSITIES.includes(d) ? d : "comfortable";
}
$("#densitySelect").onchange = () => applyDensity($("#densitySelect").value);   // live preview

async function loadSettings() {
  state.settings = await api("/api/settings");
  applyDensity(state.settings.density);
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
  const folders = (await loadStatus())?.folders || {};
  $("#locationList").innerHTML = FOLDERS.map(([k, label]) => `<dt>${label}</dt><dd><code>${esc(folders[k])}</code></dd>`).join("");
  $("#settingsDlg").showModal();
};
$("#settingsDlg").addEventListener("close", async () => {
  if ($("#settingsDlg").returnValue !== "save") { applyDensity(state.settings.density); return; }   // cancelled
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
  $("#folderList").innerHTML = r.folders.map(f => {
    const s = steps(f);
    return `<li data-p="${esc(f.path)}" style="padding-left:${14 + f.depth * 14}px" class="${f.path === state.folder ? "sel" : ""}">
      <span class="name" title="${esc(f.rel)}">${esc(f.rel.split("/").pop())}</span>
      <span class="steps" title="${esc(s.title)}">${s.dots.map(c => `<span class="dot3 ${c}"></span>`).join("")}</span>
      <span class="count ${s.done ? "done" : ""}">${f.images ? `${f.written}/${f.images}` : ""}</span>
    </li>`;
  }).join("");
  $$("#folderList li").forEach(li => li.onclick = () => selectFolder(li.dataset.p));
}

// Step dots: brief · generated · written. Green only when that step is complete for every image.
function steps(f) {
  const n = f.images, briefOk = f.brief !== "missing" && !f.stale;
  const brief = briefOk ? "on" : "warn";
  const gen = f.pending ? "blue" : n && f.written === n ? "on" : f.written ? "half" : "";
  const written = n && f.written === n ? "on" : f.written ? "half" : "";
  const title = [
    { own: "Brief: this folder's own brief.md", inherited: "Brief: inherited from a folder above",
      missing: "Brief: none yet (captions would describe only what's visible)" }[f.brief],
    f.stale ? `Brief changed since ${f.stale} image${f.stale === 1 ? " was" : "s were"} written: generate again` : "",
    n ? (f.pending ? `Generated: ${f.pending} waiting in Review & write, not written yet` :
         f.written === n ? "Generated: all" : "Generated: not yet") : "",
    n ? `Written: ${f.written} of ${n} images have caption and alt text` : "No images directly in this folder",
  ].filter(Boolean).join("\n");
  return { dots: n ? [brief, gen, written] : [brief], title, done: n && f.written === n && briefOk };
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
    // watch it happen: Review & write shows each image's text as the model writes it
    $("#scopeAll").checked = all;
    state.finishedSeen = 0;
    state.streamingPath = "";
    openTab("preview");
    poll();
  } catch (e) { toast(e.message); }
}
// A card's Generate button: just that image, shown in place without leaving the list.
async function generateOne(i) {
  try {
    const path = state.preview[i].path;
    // the folder too: a server older than this page ignores paths, and then does only this folder, not everything
    await api("/api/generate", { paths: [path], folder: path.replace(/[\\/][^\\/]*$/, ""), backend: $("#backend").value });
    state.jobRunning = true;
    $$("#previewList .img-gen").forEach(b => (b.disabled = true));
    state.finishedSeen = 0;
    state.streamingPath = "";
    poll();
  } catch (e) { toast(e.message); }
}

$("#genFolder").onclick = () => generate(false);
$("#genAll").onclick = () => generate(true);
$("#stopBtn").onclick = () => api("/api/stop", {});

async function poll() {
  clearTimeout(state.pollTimer);
  let j;
  try { j = await api(`/api/job?since=${state.finishedSeen || 0}`); }
  catch (e) { state.pollTimer = setTimeout(poll, 2000); return; }
  $("#jobBar").hidden = false;
  $("#jobFill").style.width = j.total ? (100 * j.done / j.total) + "%" : "3%";
  const now = j.current ? j.current.split(/[\\/]/).pop() : "";
  $("#jobText").innerHTML = esc(`${j.message}${j.total ? ` · ${j.done} / ${j.total}` : ""}${j.cached ? ` · ${j.cached} cached` : ""}${j.errors ? ` · ${j.errors} failed` : ""}`) +
    (now ? ` · now: <a href="#" id="jumpNow">${esc(now)}</a>` : "");
  const jump = $("#jumpNow");
  if (jump) jump.onclick = e => { e.preventDefault(); scrollToImage(j.current); };
  $("#stopBtn").hidden = !j.running;
  $("#genFolder").disabled = $("#genAll").disabled = j.running;
  state.jobRunning = j.running;
  $$("#previewList .img-gen").forEach(b => (b.disabled = j.running));

  await state.previewReady;
  state.finishedSeen = j.finished_total;
  for (const path of j.finished) await showAnswer(path);
  streamInto(j.current, j.partial);

  if (j.running) { state.pollTimer = setTimeout(poll, 350); return; }
  await refreshFolders();
}

const cardIndex = path => (state.preview || []).findIndex(x => x.path === path);
function scrollToImage(path) {
  const card = $(`#previewList [data-card="${cardIndex(path)}"]`);
  if (card) card.scrollIntoView({ behavior: "smooth", block: "center" });
}

// The model finished an image: its card becomes a normal, editable one with the suggestions.
async function showAnswer(path) {
  const i = cardIndex(path);
  if (i < 0) return;
  const fresh = (await api("/api/preview", previewOpts({ path }))).images[0];
  if (!fresh) return;
  // keep anything you typed into this card before the model got to it
  const mine = state.preview[i].rows.filter(r => r.edited);
  const minef = new Set(mine.map(r => r.field));
  fresh.rows = fresh.rows.filter(r => !minef.has(r.field)).concat(mine);
  state.preview[i] = fresh;
  if (state.streamingPath === path) state.streamingPath = "";
  updateCard(i);
  refreshFolders();
}

// The image being described: put the text so far into its fields.
function streamInto(path, partial) {
  if (!path) return;
  const i = cardIndex(path);
  if (i < 0) return;
  const img = state.preview[i];
  img.partial = partial || {};
  if (state.streamingPath !== path || !img.streaming) {
    state.streamingPath = path;
    img.streaming = true;
    updateCard(i);
  }
  const card = $(`#previewList [data-card="${i}"]`);
  if (!card) return;
  for (const f of STREAM_FIELDS) {
    const box = card.querySelector(`[data-stream="${f}"]`);
    const text = show(img.partial[f] || "");
    if (box && box.value !== text) {
      box.value = text;
      box.rows = f === "title" ? 1 : Math.min(8, Math.ceil(text.length / 70) + 1);
    }
  }
}

// ---- preview & write ----------------------------------------------------------------------------------------
// Every image is a card with its fields as the file holds them, all editable. Changes waiting to be written
// (the model's suggestions, or your edits) show on top with what's in the file now. Each card has its own
// Write button: orange with unwritten changes, green once the file matches what you see.
const ACT = { new: "new", update: "update", replace: "replace", keep: "keep (person wrote)", fill: "fill",
  differs: "differs", remove: "remove", edited: "your edit" };
const FIELD_LABELS = { title: "Title", caption: "Caption", alt_text: "Alt text", keywords: "Keywords",
  place: "Place", city: "City", region: "Region", country: "Country", creator: "Creator", credit: "Credit line",
  copyright: "Copyright", usage: "Usage terms" };
const MAIN_FIELDS = ["title", "caption", "alt_text", "keywords"];
const MORE_FIELDS = ["place", "city", "region", "country", "creator", "credit", "copyright", "usage"];
const LIST_FIELDS = ["keywords", "creator"];
const LONG_FIELDS = ["caption", "alt_text", "keywords"];

// Only the newest load is shown, and polling waits for it (state.previewReady), so an answer that arrives
// while the list is loading is never lost or overwritten by an older copy.
function loadPreview() {
  const seq = state.previewSeq = (state.previewSeq || 0) + 1;
  state.previewReady = api("/api/preview", previewOpts({ folder: $("#scopeAll").checked ? null : state.folder }))
    .then(r => {
      if (seq !== state.previewSeq) return;
      state.preview = r.images;
      renderPreview();
    });
  return state.previewReady;
}
function previewOpts(extra) {
  return { replace_human: $("#replaceHuman").checked, override_credits: $("#overrideCredits").checked, ...extra };
}
["#replaceHuman", "#overrideCredits", "#scopeAll"].forEach(s => $(s).onchange = loadPreview);
$("#pvFilter").onchange = renderPreview;

const pending = img => img.rows.filter(r => r.selected);
function cardState(img) {
  if (pending(img).length) return "dirty";
  return img.done ? "saved" : "empty";
}
function parseValue(field, text) {
  return LIST_FIELDS.includes(field) ? text.split(",").map(s => s.trim()).filter(Boolean) : text;
}
function sameValue(a, b) { return show(a).trim() === show(b).trim(); }

function badgeFor(img, field) {
  const r = img.rows.find(x => x.field === field);
  if (r) return `<span class="a-${r.action}">${ACT[r.action] || r.action}</span>`;
  return `<span class="a-saved">${show(img.current[field]) ? "in file" : "empty"}</span>`;
}

function fieldRow(img, i, field) {
  const r = img.rows.find(x => x.field === field);
  // ticked: the box shows what will be written; unticked: what's in the file, with the suggestion as a hint
  const text = show(r && r.selected ? r.proposed : img.current[field]);
  const input = LONG_FIELDS.includes(field)
    ? `<textarea rows="${Math.min(6, Math.ceil(text.length / 70) + 1)}" data-i="${i}" data-f="${field}">${esc(text)}</textarea>`
    : `<input value="${esc(text)}" data-i="${i}" data-f="${field}">`;
  const was = !r ? "" : r.selected ? `<div class="was">In file: ${esc(show(r.current)) || "<i>empty</i>"}</div>`
    : `<div class="was">Suggested: ${esc(show(r.proposed))}</div>`;
  const tick = r && !r.fromEdit ? `<input type="checkbox" data-i="${i}" data-f="${field}" ${r.selected ? "checked" : ""}>` : "";
  return `<tr class="${r && !r.selected ? "off" : ""}"><td class="tick">${tick}</td>
    <td class="f">${FIELD_LABELS[field]}</td><td class="new">${input}${was}</td><td class="act">${badgeFor(img, field)}</td></tr>`;
}

function otherRows(img, i) {    // GPS removal and old fields: a tick, nothing to edit
  const gps = img.rows.findIndex(r => r.field === "gps");
  const old = img.rows.filter(r => r.group === "cleanup");
  let html = "";
  if (gps >= 0) {
    const r = img.rows[gps];
    html += `<tr class="${r.selected ? "" : "off"}"><td class="tick"><input type="checkbox" data-i="${i}" data-j="${gps}" ${r.selected ? "checked" : ""}></td>
      <td class="f">GPS position</td><td class="new"><span class="muted">removed from the file (the brief asks for it)</span>
      <div class="was">In file: ${esc(show(r.current))}</div></td><td class="act"><span class="a-remove">remove</span></td></tr>`;
  }
  if (old.length) {
    const on = old.every(r => r.selected);
    const names = old.map(r => r.label.replace(" (old)", "").toLowerCase()).join(", ");
    html += `<tr class="${on ? "" : "off"}"><td class="tick"><input type="checkbox" data-i="${i}" data-old="1" ${on ? "checked" : ""}></td>
      <td class="f">Old fields</td><td class="new"><span class="muted">removed: an earlier version of SMP wrote these and they're no longer used</span>
      <div class="was">${esc(names)}</div></td><td class="act"><span class="a-remove">remove</span></td></tr>`;
  }
  return html;
}

function genButton(img, i) {
  return `<button class="img-gen ghost" data-g="${i}" ${state.jobRunning ? "disabled" : ""}>${img.described ? "Generate again" : "Generate"}</button>`;
}

function writeButton(img, i) {
  const st = cardState(img);
  const label = { dirty: "Write", saved: "Written ✓", empty: "Nothing to write" }[st];
  return `<button class="img-write ${st}" data-w="${i}" ${st === "dirty" ? "" : "disabled"}>${label}</button>`;
}

function renderPreview() {
  const list = $("#previewList");
  const onlyDirty = $("#pvFilter").value === "unsaved";
  const shown = state.preview.map((img, i) => [img, i])
    .filter(([img]) => !onlyDirty || img.streaming || cardState(img) === "dirty");
  if (!shown.length) {
    list.innerHTML = `<p class="muted">${state.preview.length ? "Nothing unsaved: every image shown is written." :
      "No images here. Pick a folder with images, or tick All folders."}</p>`;
    updateCount();
    return;
  }
  list.innerHTML = shown.map(([img, i]) => cardHtml(img, i)).join("");
  $$("#previewList .card").forEach(bindCard);
  updateCount();
}

function cardHtml(img, i) {
  if (img.streaming) return streamingCardHtml(img, i);
  const moreOpen = img.rows.some(r => MORE_FIELDS.includes(r.field));
  return `<div class="card" data-card="${i}"><div class="card-side">
      <img loading="lazy" src="${img.thumb}" data-full="${esc(img.path)}">
      <div class="fname">${esc(img.rel)}</div>${img.error ? `<div class="err">${esc(img.error)}</div>` : ""}
      ${genButton(img, i)}${writeButton(img, i)}</div>
    <div><table class="rows">${MAIN_FIELDS.map(f => fieldRow(img, i, f)).join("")}${otherRows(img, i)}</table>
      <details class="more" ${moreOpen ? "open" : ""}><summary>Location and credits</summary>
        <table class="rows">${MORE_FIELDS.map(f => fieldRow(img, i, f)).join("")}</table></details></div></div>`;
}

// The image the model is working on: its text appears as it's written, read-only until the answer is complete.
const STREAM_FIELDS = ["title", "caption", "alt_text", "keywords"];
function streamingCardHtml(img, i) {
  const p = img.partial || {};
  const rows = STREAM_FIELDS.map(f => `<tr><td class="tick"></td><td class="f">${FIELD_LABELS[f]}</td>
    <td class="new"><textarea readonly class="streaming" rows="${f === "title" ? 1 : 3}" data-stream="${f}">${esc(show(p[f] || ""))}</textarea></td>
    <td class="act"><span class="a-writing">writing…</span></td></tr>`).join("");
  return `<div class="card is-streaming" data-card="${i}"><div class="card-side">
      <img src="${img.thumb}" data-full="${esc(img.path)}"><div class="fname">${esc(img.rel)}</div>
      <button class="img-write busy" disabled>Generating…</button></div>
    <div><table class="rows">${rows}</table></div></div>`;
}

function bindCard(card) {
  const i = +card.dataset.card;
  card.querySelectorAll("img").forEach(im => im.onclick = () => zoom(im.dataset.full));
  card.querySelectorAll("input[type=checkbox]").forEach(cb => cb.onchange = () => {
    const img = state.preview[i];
    if (cb.dataset.old) img.rows.filter(r => r.group === "cleanup").forEach(r => (r.selected = cb.checked));
    else (cb.dataset.f ? img.rows.find(x => x.field === cb.dataset.f) : img.rows[cb.dataset.j]).selected = cb.checked;
    updateCard(i);                         // the box switches between the suggestion and the file's value
  });
  card.querySelectorAll("textarea:not([readonly]), input[data-f]:not([type=checkbox])").forEach(el => el.oninput = () => edit(el));
  card.querySelectorAll("[data-w]").forEach(b => b.onclick = () => writeOne(i));
  card.querySelectorAll("[data-g]").forEach(b => b.onclick = () => generateOne(i));
}

// Redraw one card (and nothing else, so a card you're typing in is never disturbed).
function updateCard(i) {
  const old = $(`#previewList [data-card="${i}"]`);
  if (!old) return;
  const tmp = document.createElement("div");
  tmp.innerHTML = cardHtml(state.preview[i], i);
  const card = tmp.firstElementChild;
  old.replaceWith(card);
  bindCard(card);
  updateCount();
}

function edit(el) {
  const i = el.dataset.i, field = el.dataset.f, img = state.preview[i];
  const value = parseValue(field, el.value);
  let r = img.rows.find(x => x.field === field);
  if (!r) {
    r = { field, label: FIELD_LABELS[field], current: img.current[field], action: "edited", group: "edit", fromEdit: true };
    img.rows.push(r);
  }
  if (!r.fromEdit && r.suggested === undefined) r.suggested = r.proposed;
  Object.assign(r, { proposed: value, edited: true, selected: true });
  if (sameValue(value, r.current)) {       // typed back to what's in the file: nothing to write
    if (r.fromEdit) img.rows.splice(img.rows.indexOf(r), 1);
    else Object.assign(r, { proposed: r.suggested, edited: false, selected: false });
  }
  const tr = el.closest("tr"), now = img.rows.find(x => x.field === field);
  tr.classList.toggle("off", !!now && !now.selected);
  const cb = tr.querySelector("input[type=checkbox]");
  if (cb) cb.checked = !!now && now.selected;
  tr.querySelector(".act").innerHTML = badgeFor(img, field);
  refreshCard(i);
}

function refreshCard(i) {
  const old = $(`#previewList [data-card="${i}"] .img-write`);
  if (old) {
    old.outerHTML = writeButton(state.preview[i], i);
    $(`#previewList [data-card="${i}"] .img-write`).onclick = () => writeOne(+i);
  }
  updateCount();
}

function rowsToWrite(img) {
  return pending(img).map(r => ({ field: r.field, proposed: r.proposed, edited: !!r.edited }));
}
function selectedItems() {
  return state.preview.map(img => ({ path: img.path, rows: rowsToWrite(img) })).filter(i => i.rows.length);
}
function updateCount() {
  const items = selectedItems();
  const n = items.reduce((a, i) => a + i.rows.length, 0);
  $("#selCount").textContent = n ? `${n} change${n === 1 ? "" : "s"} in ${items.length} file${items.length === 1 ? "" : "s"}` : "";
  $("#writeBtn").disabled = !n;
}

async function writeOne(i) {
  const img = state.preview[i];
  try {
    const r = await api("/api/write", { items: [{ path: img.path, rows: rowsToWrite(img) }] });
    if (Object.keys(r.errors || {}).length) { toast("Couldn't write: " + Object.values(r.errors)[0]); return; }
    const fresh = await api("/api/preview", previewOpts({ path: img.path }));
    if (fresh.images[0]) state.preview[i] = fresh.images[0];
    updateCard(i);
    refreshFolders();
    if (r.run_id) toast(`Wrote ${img.name}`, { label: "Undo", fn: () => undo(r.run_id) });
  } catch (e) { toast(e.message); }
}

$("#writeBtn").onclick = async () => {
  const items = selectedItems();
  const n = items.reduce((a, i) => a + i.rows.length, 0);
  const v = await ask("Write to files?", `${n} changes go into ${items.length} files. The old values are kept, so you can undo this.`, [["Cancel", "no", true], ["Write all", "yes"]]);
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
    refreshFolders();
  } catch (e) { toast(e.message); }
  updateCount();
};

async function undo(runId) {
  try {
    const r = await api("/api/undo", { run_id: runId });
    toast(`Restored ${r.restored} files`);
    $("#lastRun").hidden = true;
    loadPreview();
    refreshFolders();
  } catch (e) { toast(e.message); }
}

// ---- start --------------------------------------------------------------------------------------------------
(async () => {
  await loadSettings();
  const st = await loadStatus();
  if (st && !st.ready) $("#setupDlg").showModal();          // first start, or something missing
  if (st && st.pull && st.pull.running) pollPull();
  const r = await api("/api/folders");
  if (r.root) {
    setFolders(r); $("#folder").value = r.root;
    await selectFolder(r.root);
    if (location.hash === "#review") openTab("preview");        // a link straight to Review & write
  }
  const j = await api("/api/job");
  if (j.running) poll();
})();
