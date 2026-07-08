/* Bindery frontend — a small fetch-driven state machine, no framework. */
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = {
  docId: null, fileName: "", meta: null,
  align: "justify", para: "indent",
  provider: "google", keys: {},
  aiDone: false,
  epubId: null, kindle: { configured: false },
};

// Curated per provider, cheapest-that-does-the-job first (it's a light,
// structure-only task). Value = model id sent to the API.
const MODELS = {
  google: [
    ["gemini-2.5-flash", "gemini-2.5-flash — recommended, free tier"],
    ["gemini-2.5-flash-lite", "gemini-2.5-flash-lite — fastest"],
    ["gemini-2.5-pro", "gemini-2.5-pro — best quality"],
  ],
  anthropic: [
    ["claude-haiku-4-5", "claude-haiku-4-5 — recommended, cheapest"],
    ["claude-sonnet-5", "claude-sonnet-5 — balanced"],
    ["claude-opus-4-8", "claude-opus-4-8 — best quality"],
  ],
  openai: [
    ["gpt-5-mini", "gpt-5-mini — recommended"],
    ["gpt-5-nano", "gpt-5-nano — cheapest"],
    ["gpt-5", "gpt-5 — best quality"],
  ],
};

function fillModelSelect() {
  const sel = $("#ai-model");
  sel.innerHTML = "";
  for (const [id, label] of MODELS[state.provider]) {
    const opt = document.createElement("option");
    opt.value = id;
    opt.textContent = label;
    sel.appendChild(opt);
  }
}
fillModelSelect();

/* ------------------------------------------------------------- theme */

function applyTheme() {
  const saved = new URLSearchParams(location.search).get("theme")
    || localStorage.getItem("bindery-theme");
  const mode = saved || (matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  document.documentElement.dataset.theme = mode;
}
applyTheme();
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  if (!localStorage.getItem("bindery-theme")) applyTheme();
});
$("#theme-toggle").addEventListener("click", () => {
  const next = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
  localStorage.setItem("bindery-theme", next);
  document.documentElement.dataset.theme = next;
});

/* ------------------------------------------------------------ helpers */

const PANELS = ["upload", "options", "working", "review", "done"];
function show(name) {
  for (const p of PANELS) {
    const el = $(`#panel-${p}`);
    el.hidden = p !== name;
  }
  const el = $(`#panel-${name}`);
  el.style.animation = "none";
  void el.offsetHeight; // restart the entrance animation
  el.style.animation = "";
  hideError();
}

function showError(msg) {
  $("#error-text").textContent = msg;
  $("#error-slip").hidden = false;
  $("#error-slip").scrollIntoView({ block: "nearest", behavior: "smooth" });
}
function hideError() { $("#error-slip").hidden = true; }
$("#error-dismiss").addEventListener("click", hideError);

let toastTimer;
function toast(msg) {
  const t = $("#toast");
  t.textContent = msg;
  t.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { t.hidden = true; }, 2400);
}

async function api(path, opts = {}) {
  const res = await fetch(path, opts);
  let data = null;
  try { data = await res.json(); } catch { /* non-JSON error body */ }
  if (!res.ok) throw new Error(data?.error || `Request failed (${res.status})`);
  return data;
}

function fmtSize(bytes) {
  return bytes > 1048576 ? (bytes / 1048576).toFixed(1) + " MB"
                         : Math.max(1, Math.round(bytes / 1024)) + " KB";
}

/* ------------------------------------------------------------- upload */

const dropwell = $("#dropwell");
const fileInput = $("#file-input");
const OK_EXT = /\.(pdf|docx|txt|md|markdown|html?)$/i;
const EPUB_EXT = /\.epub$/i;

function handleDroppedFile(file) {
  if (EPUB_EXT.test(file.name)) openEpubSend(file);
  else uploadFile(file);
}

// files can be dropped anywhere on the page, not just on the well
const draggingFiles = (e) => e.dataTransfer?.types?.includes("Files");
let dragDepth = 0;
document.addEventListener("dragenter", (e) => {
  e.preventDefault();
  if (draggingFiles(e) && !$("#panel-upload").hidden && ++dragDepth === 1)
    dropwell.classList.add("dragover");
});
document.addEventListener("dragleave", () => {
  if (--dragDepth <= 0) { dragDepth = 0; dropwell.classList.remove("dragover"); }
});
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  e.preventDefault();
  dragDepth = 0;
  dropwell.classList.remove("dragover");
  const file = e.dataTransfer?.files?.[0];
  if (file && !$("#panel-upload").hidden) handleDroppedFile(file);
});
fileInput.addEventListener("change", () => {
  if (fileInput.files[0]) handleDroppedFile(fileInput.files[0]);
});

/* ------------------------------------------------------- direct epub send */

const epubWell = $("#epub-well");
let pendingEpub = null;

function openEpubSend(file) {
  pendingEpub = file;
  $("#epub-name").textContent = `${file.name} · ${fmtSize(file.size)}`;
  $("#epub-title").value = file.name.replace(/\.epub$/i, "").replace(/[-_]+/g, " ").trim();
  $("#epub-author").value = "";
  epubWell.hidden = false;
  epubWell.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

$("#epub-cancel").addEventListener("click", () => {
  pendingEpub = null;
  epubWell.hidden = true;
  fileInput.value = "";
});

$("#epub-send-btn").addEventListener("click", async () => {
  if (!pendingEpub) return;
  if (!state.kindle.configured) {
    showError("Send to Kindle isn't set up yet — add your email details in Settings first.");
    return;
  }
  const btn = $("#epub-send-btn");
  btn.disabled = true;
  btn.textContent = "Sending…";
  try {
    const form = new FormData();
    form.append("file", pendingEpub);
    form.append("title", $("#epub-title").value.trim());
    form.append("author", $("#epub-author").value.trim());
    await api("/api/send-epub", { method: "POST", body: form });
    toast("Sent — it'll show up on your Kindle in a minute or two");
    epubWell.hidden = true;
    pendingEpub = null;
    fileInput.value = "";
  } catch (err) {
    showError(err.message);
  } finally {
    btn.disabled = false;
    btn.textContent = "Send to Kindle";
  }
});

async function uploadFile(file) {
  if (!OK_EXT.test(file.name)) {
    showError(`“${file.name}” isn't a supported format. Use PDF, DOCX, TXT, Markdown or HTML.`);
    return;
  }
  hideError();
  $(".dropwell-idle").hidden = true;
  $(".dropwell-busy").hidden = false;
  $("#reading-name").textContent = file.name;
  try {
    const form = new FormData();
    form.append("file", file);
    const data = await api("/api/extract", { method: "POST", body: form });
    state.docId = data.doc_id;
    state.fileName = file.name;
    state.meta = data;
    state.aiDone = false;
    fillOptions(file, data);
    show("options");
  } catch (err) {
    showError(err.message);
  } finally {
    $(".dropwell-idle").hidden = false;
    $(".dropwell-busy").hidden = true;
    fileInput.value = "";
  }
}

/* ------------------------------------------------------- paste markdown */

const mdPaste = $("#md-paste");
const mdPasteBtn = $("#md-paste-btn");
mdPaste.addEventListener("input", () => { mdPasteBtn.disabled = !mdPaste.value.trim(); });
mdPasteBtn.addEventListener("click", () => {
  const text = mdPaste.value.trim();
  if (!text) return;
  // first heading becomes the filename, so the fallback title reads nicely
  const name = (text.match(/^#\s+(.+)$/m)?.[1] || "Pasted notes")
    .replace(/[^\w \-]/g, "").trim().slice(0, 60) || "Pasted notes";
  uploadFile(new File([text], `${name}.md`, { type: "text/markdown" }));
  mdPaste.value = "";
  mdPasteBtn.disabled = true;
});
// Ctrl+V anywhere on the upload panel lands the clipboard in the textarea
document.addEventListener("paste", (e) => {
  if ($("#panel-upload").hidden || e.target.closest("textarea, input")) return;
  const text = e.clipboardData?.getData("text/plain");
  if (text) {
    mdPaste.value = text;
    mdPasteBtn.disabled = false;
    mdPaste.focus();
  }
});

/* ------------------------------------------------------------ options */

function fillOptions(file, data) {
  const words = data.chapters.reduce((n, c) => n + c.words, 0);
  const secs = data.chapters.length;
  $("#file-facts").textContent =
    `${file.name} · ${fmtSize(file.size)} · ${secs} section${secs === 1 ? "" : "s"} · ${words.toLocaleString()} words`;
  $("#meta-title").value = data.title || "";
  $("#meta-author").value = data.author || "";
  updateBindButton();
}

$("#file-replace").addEventListener("click", () => show("upload"));

document.querySelectorAll(".seg").forEach((btn) => {
  btn.addEventListener("click", () => {
    const group = btn.dataset.group;
    document.querySelectorAll(`.seg[data-group="${group}"]`)
      .forEach((b) => b.classList.toggle("selected", b === btn));
    if (group === "align") state.align = btn.dataset.value;
    if (group === "para") state.para = btn.dataset.value;
    if (group === "provider") {
      state.provider = btn.dataset.value;
      fillModelSelect();
      updateBindButton();
    }
  });
});

const aiToggle = $("#ai-toggle");
aiToggle.addEventListener("change", () => {
  $("#ai-config").hidden = !aiToggle.checked;
  updateBindButton();
});

function updateBindButton() {
  const ai = aiToggle.checked;
  const hasKey = !!state.keys[state.provider];
  $("#key-hint").hidden = !ai || hasKey;
  $("#bind-btn").disabled = ai && !hasKey;
  $("#bind-btn").textContent = ai && !state.aiDone ? "Tidy, then bind" : "Bind book";
}

$("#key-hint-open").addEventListener("click", openSettings);
$("#bind-btn").addEventListener("click", () => {
  if (aiToggle.checked && !state.aiDone) runAiFormat();
  else build(false);
});

/* -------------------------------------------------------- working view */

function setStages(map) {
  // map: {extract:"done", ai:"active"|"skip"..., build:"", validate:""}
  document.querySelectorAll(".stitch").forEach((li) => {
    li.className = "stitch" + (map[li.dataset.stage] ? " " + map[li.dataset.stage] : "");
  });
}

/* -------------------------------------------------------------- AI run */

async function runAiFormat() {
  show("working");
  $("#ai-progress").textContent = "";
  setStages({ extract: "done", ai: "active" });
  try {
    const res = await fetch("/api/ai-format", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doc_id: state.docId, provider: state.provider,
        model: $("#ai-model").value.trim(),
      }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => null);
      throw new Error(data?.error || `Request failed (${res.status})`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let final = null;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      const lines = buf.split("\n");
      buf = lines.pop();
      for (const line of lines) {
        if (!line.trim()) continue;
        const ev = JSON.parse(line);
        if (ev.error) throw new Error(ev.error);
        if (ev.chunk) $("#ai-progress").textContent = `section ${ev.chunk} of ${ev.total}`;
        if (ev.done) final = ev;
      }
    }
    if (!final) throw new Error("AI formatting ended unexpectedly — try again.");
    setStages({ extract: "done", ai: "done" });
    $("#proof-original").textContent = final.original;
    $("#proof-formatted").textContent = final.formatted;
    show("review");
  } catch (err) {
    show("options");
    showError(err.message);
  }
}

$("#use-formatted").addEventListener("click", () => { state.aiDone = true; build(true); });
$("#keep-original").addEventListener("click", () => { state.aiDone = true; build(false); });

/* --------------------------------------------------------------- build */

async function build(useAi) {
  show("working");
  const aiState = aiToggle.checked ? (useAi ? "done" : "skip") : "skip";
  setStages({ extract: "done", ai: aiState, build: "active" });
  try {
    const data = await api("/api/build", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        doc_id: state.docId, use_ai: useAi,
        title: $("#meta-title").value, author: $("#meta-author").value,
        language: $("#meta-lang").value || "en",
        text_align: state.align, paragraph_style: state.para,
      }),
    });
    setStages({ extract: "done", ai: aiState, build: "done", validate: "active" });
    await new Promise((r) => setTimeout(r, 450)); // let the last stitch land
    setStages({ extract: "done", ai: aiState, build: "done", validate: "done" });
    await new Promise((r) => setTimeout(r, 350));
    fillDone(data);
    show("done");
  } catch (err) {
    show("options");
    showError(err.message);
  }
}

/* ---------------------------------------------------------------- done */

function fillDone(data) {
  const title = $("#meta-title").value || state.meta.title || "Untitled";
  $("#done-title").textContent = title;
  $("#cover-title").textContent = title;
  $("#cover-author").textContent = $("#meta-author").value;
  $("#download-btn").href = `/api/download/${data.epub_id}`;
  $("#download-size").textContent = fmtSize(data.size);
  state.epubId = data.epub_id;
  $("#kindle-title").value = title;
  $("#kindlerow").hidden = !state.kindle.configured;
  $("#sendnote").hidden = state.kindle.configured;

  const v = data.validation;
  const rows = [];
  if (v.ok) rows.push(`<p class="vline v-ok">✓ ${v.epubcheck ? "epubcheck and structure checks passed" : "Structure checks passed"}</p>`);
  for (const w of v.warnings) rows.push(`<p class="vline v-warn">△ ${esc(w)}</p>`);
  for (const e of v.errors) rows.push(`<p class="vline v-err">✕ ${esc(e)}</p>`);
  for (const i of v.info) if (!v.ok || v.warnings.length) rows.push(`<p class="vline">${esc(i)}</p>`);
  $("#validation").innerHTML = rows.join("");

  $("#proof-frame").srcdoc = data.preview_html;
}

function esc(s) {
  return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

const sendBtn = $("#send-kindle");
sendBtn.addEventListener("click", async () => {
  sendBtn.disabled = true;
  sendBtn.textContent = "Sending…";
  try {
    await api(`/api/send/${state.epubId}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: $("#kindle-title").value.trim() }),
    });
    toast("Sent — it'll show up on your Kindle in a minute or two");
  } catch (err) {
    showError(err.message);
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = "Send to Kindle";
  }
});

$("#start-over").addEventListener("click", () => {
  state.docId = null; state.aiDone = false;
  aiToggle.checked = false;
  $("#ai-config").hidden = true;
  show("upload");
});

/* ------------------------------------------------------------ settings */

const PROVIDER_NAMES = { anthropic: "Anthropic — Claude", openai: "OpenAI — ChatGPT", google: "Google — Gemini" };

function openSettings() {
  $("#scrim").hidden = false;
  $("#settings").hidden = false;
  renderKeys();
  fillKindleForm();
}
function closeSettings() {
  $("#scrim").hidden = true;
  $("#settings").hidden = true;
  updateBindButton();
}
$("#settings-open").addEventListener("click", openSettings);
$("#settings-close").addEventListener("click", closeSettings);
$("#scrim").addEventListener("click", closeSettings);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !$("#settings").hidden) closeSettings();
});

async function loadKeys() {
  try {
    const data = await api("/api/keys");
    state.keys = data.keys;
    updateBindButton();
  } catch { /* server not ready; keys stay unknown */ }
}

function renderKeys() {
  const list = $("#key-list");
  list.innerHTML = "";
  for (const [prov, label] of Object.entries(PROVIDER_NAMES)) {
    const saved = state.keys[prov];
    const block = document.createElement("div");
    block.className = "keyblock";
    block.innerHTML = `
      <div class="keyblock-head">
        <span class="keyblock-name">${label}</span>
        <span class="keyblock-status mono ${saved ? "saved" : ""}">${saved ? "saved · " + esc(saved) : "not set"}</span>
      </div>
      <div class="keyrow">
        <input type="password" placeholder="${saved ? "replace key…" : "paste API key…"}" autocomplete="off" spellcheck="false">
        <button class="btn btn-primary btn-small" type="button">Save</button>
      </div>
      ${saved ? '<button class="ghostlink keydel" type="button">remove key</button>' : ""}`;
    const input = block.querySelector("input");
    block.querySelector(".btn").addEventListener("click", async () => {
      if (!input.value.trim()) return;
      try {
        const data = await api(`/api/keys/${prov}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ key: input.value }),
        });
        state.keys = data.keys;
        renderKeys();
        toast(`${label.split(" — ")[0]} key saved`);
      } catch (err) { showError(err.message); closeSettings(); }
    });
    block.querySelector(".keydel")?.addEventListener("click", async () => {
      const data = await api(`/api/keys/${prov}`, { method: "DELETE" });
      state.keys = data.keys;
      renderKeys();
      toast(`${label.split(" — ")[0]} key removed`);
    });
    list.appendChild(block);
  }
}

/* ------------------------------------------------------ send to kindle */

function fillKindleForm() {
  const k = state.kindle;
  $("#k-user").value = k.smtp_user || "";
  $("#k-to").value = k.kindle_email || "";
  $("#k-host").value = k.smtp_host || "";
  $("#k-pass").value = "";
  $("#k-pass").placeholder = k.has_pass ? "saved — paste to replace" : "paste app password…";
  $("#k-status").textContent = k.configured ? "ready" : "";
  $("#k-status").classList.toggle("saved", !!k.configured);
}

async function loadKindle() {
  try {
    state.kindle = await api("/api/kindle");
  } catch { /* server not ready */ }
}

$("#k-save").addEventListener("click", async () => {
  try {
    state.kindle = await api("/api/kindle", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        smtp_user: $("#k-user").value, smtp_pass: $("#k-pass").value,
        kindle_email: $("#k-to").value, smtp_host: $("#k-host").value,
      }),
    });
    fillKindleForm();
    toast(state.kindle.configured ? "Send to Kindle ready" : "Saved — some fields still missing");
  } catch (err) {
    showError(err.message);
    closeSettings();
  }
});

loadKeys();
loadKindle();
if (location.hash === "#settings") openSettings(); // handy for headless screenshots
