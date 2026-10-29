// cogni frontend - vanilla JS, no build step, no framework. Talks to
// POST /api/translate (see server.py), which just calls core.py's
// translate() - the same function the CLI uses.

// --- Access key (see server.py's require_access_key) ---------------------
// The paid API call is gated by a shared key. First visit: grab it from
// ?key=... in the URL, save it, then scrub it from the visible URL (so it
// doesn't linger in browser history/bookmarks as plain text) - every
// later visit just reuses the saved one.
const ACCESS_KEY_STORAGE = "cogni.accessKey";
(function loadAccessKeyFromUrl() {
  const params = new URLSearchParams(location.search);
  const key = params.get("key");
  if (key) {
    localStorage.setItem(ACCESS_KEY_STORAGE, key);
    params.delete("key");
    const rest = params.toString();
    history.replaceState({}, "", location.pathname + (rest ? `?${rest}` : ""));
  }
})();
function getAccessKey() {
  return localStorage.getItem(ACCESS_KEY_STORAGE) || "";
}

const OTHER_VALUE = "__other__";

function populateLanguageSelect(select, { includeAuto = false } = {}) {
  select.innerHTML = "";
  if (includeAuto) {
    const opt = document.createElement("option");
    opt.value = "";
    opt.textContent = "🌐 Auto-detect";
    select.appendChild(opt);
  }
  for (const lang of LANGUAGES) {
    const opt = document.createElement("option");
    opt.value = lang.name;
    opt.textContent = `${lang.flag} ${lang.name}`;
    select.appendChild(opt);
  }
  const other = document.createElement("option");
  other.value = OTHER_VALUE;
  other.textContent = "✏️ Other…";
  select.appendChild(other);
}

// Wires a <select> + its companion "Other…" free-text <input> so picking
// "Other…" reveals the text field, and reading the effective value checks
// the text field first when it's visible.
function wireCustomLangField(select, customInput) {
  select.addEventListener("change", () => {
    const isOther = select.value === OTHER_VALUE;
    customInput.hidden = !isOther;
    if (isOther) customInput.focus();
  });
}

function effectiveLangValue(select, customInput) {
  if (select.value === OTHER_VALUE) return customInput.value.trim();
  return select.value;
}

const fromSelect = document.getElementById("from-select");
const fromCustom = document.getElementById("from-custom");
const toSelect = document.getElementById("to-select");
const toCustom = document.getElementById("to-custom");
const profileLangSelect = document.getElementById("profile-lang-select");
const profileLangCustom = document.getElementById("profile-lang-custom");

populateLanguageSelect(fromSelect, { includeAuto: true });
populateLanguageSelect(toSelect);
populateLanguageSelect(profileLangSelect);
wireCustomLangField(fromSelect, fromCustom);
wireCustomLangField(toSelect, toCustom);
wireCustomLangField(profileLangSelect, profileLangCustom);

// --- Profile (base language), persisted client-side only -----------------
// No accounts/login/database - this is a personal local tool, so
// localStorage is enough. See README "Status" for what'd need to change to make
// this a real multi-user deployment.
const PROFILE_KEY = "cogni.baseLanguage";

function loadProfileLanguage() {
  return localStorage.getItem(PROFILE_KEY) || "English";
}

function applyDefaultToLanguage() {
  const base = loadProfileLanguage();
  const known = LANGUAGES.some((l) => l.name === base);
  if (known) {
    toSelect.value = base;
    toCustom.hidden = true;
  } else {
    toSelect.value = OTHER_VALUE;
    toCustom.hidden = false;
    toCustom.value = base;
  }
}
applyDefaultToLanguage();

const profileBtn = document.getElementById("profile-btn");
const profileOverlay = document.getElementById("profile-overlay");
const profileSaveBtn = document.getElementById("profile-save-btn");
const profileCloseBtn = document.getElementById("profile-close-btn");

profileBtn.addEventListener("click", () => {
  const current = loadProfileLanguage();
  const known = LANGUAGES.some((l) => l.name === current);
  profileLangSelect.value = known ? current : OTHER_VALUE;
  profileLangCustom.hidden = known;
  if (!known) profileLangCustom.value = current;
  profileOverlay.hidden = false;
});
profileCloseBtn.addEventListener("click", () => (profileOverlay.hidden = true));
profileOverlay.addEventListener("click", (e) => {
  if (e.target === profileOverlay) profileOverlay.hidden = true;
});
profileSaveBtn.addEventListener("click", () => {
  const value = effectiveLangValue(profileLangSelect, profileLangCustom);
  if (value) localStorage.setItem(PROFILE_KEY, value);
  applyDefaultToLanguage();
  profileOverlay.hidden = true;
});

// --- Swap From/To ----------------------------------------------------------
document.getElementById("swap-btn").addEventListener("click", () => {
  const fromVal = effectiveLangValue(fromSelect, fromCustom);
  const toVal = effectiveLangValue(toSelect, toCustom);
  if (!fromVal) return; // nothing sensible to swap when "From" is auto-detect
  setLangField(fromSelect, fromCustom, toVal);
  setLangField(toSelect, toCustom, fromVal);
});

function setLangField(select, customInput, name) {
  const known = LANGUAGES.some((l) => l.name === name);
  if (known) {
    select.value = name;
    customInput.hidden = true;
  } else {
    select.value = OTHER_VALUE;
    customInput.hidden = false;
    customInput.value = name;
  }
}

// --- Mode toggle -------------------------------------------------------
let selectedMode = "auto";
const modeButtons = document.querySelectorAll(".mode-btn");
modeButtons.forEach((btn) => {
  btn.addEventListener("click", () => {
    modeButtons.forEach((b) => {
      b.classList.remove("active");
      b.setAttribute("aria-checked", "false");
    });
    btn.classList.add("active");
    btn.setAttribute("aria-checked", "true");
    selectedMode = btn.dataset.mode;
  });
});

// --- Submit --------------------------------------------------------------
const MODE_LABELS = { expression: "Word & Idiom", text: "Translate" };

const inputText = document.getElementById("input-text");
const goBtn = document.getElementById("go-btn");
const resultCard = document.getElementById("result-card");
const correctionNote = document.getElementById("correction-note");
const headline = document.getElementById("headline");
const resultBody = document.getElementById("result-body");
const languageBadge = document.getElementById("language-badge");
const modeUsedBadge = document.getElementById("mode-used-badge");
const detailsPanel = document.getElementById("details-panel");
const detailsBody = document.getElementById("details-body");
const errorCard = document.getElementById("error-card");
const errorText = document.getElementById("error-text");

// Expression-mode answers put a hidden-by-default "Grammar & usage" panel
// (noun/verb grammar facts, short usage notes) after a "## Details"
// heading in the markdown - see core.py's _expression_prompt. Split it
// out client-side rather than asking the model to emit it as a separate
// stream event, since it's still just prose the model writes as part of
// the same answer. Re-run on every delta (cheap at this text size) so it
// keeps working correctly as the answer streams in - matches how the
// rest of the result is already re-rendered from the full accumulated
// text on every chunk.
//
// Same idea for the optional headline (a single bold "term → translation"
// line - see _expression_prompt): pulled out of the markdown into its own
// styled element rather than left as a plain <strong> inside the body,
// so it can look visually distinct (larger, darker) instead of blending
// in with every other bold word in the answer. Only present when the
// word has one clear translation - absent (multi-sense case) leaves the
// headline element empty/hidden.
//
// The optional typo-correction note ("(interpreted as X)" - see
// _expression_prompt) comes before the headline when both are present,
// so it has to be extracted first. The prompt asks the model for a very
// specific format for exactly this reason: a *single-asterisk* italic
// line, never double-asterisk bold (that's reserved for the headline) -
// this keeps the two patterns unambiguous to tell apart (a string
// starting "**" can never match the single-asterisk regex, since the
// character right after the first "*" would itself be a "*", which
// [^*]+ excludes) regardless of which one is actually present.
function renderResult(markdown) {
  let body = markdown;
  const correctionMatch = body.match(/^\*([^*]+)\*\n+/);
  if (correctionMatch) {
    correctionNote.textContent = correctionMatch[1];
    correctionNote.hidden = false;
    body = body.slice(correctionMatch[0].length);
  } else {
    correctionNote.hidden = true;
    correctionNote.textContent = "";
  }

  const headlineMatch = body.match(/^\*\*(.+)\*\*\n+/);
  if (headlineMatch) {
    headline.innerHTML = markupXrefs(DOMPurify.sanitize(marked.parseInline(headlineMatch[1])));
    headline.hidden = false;
    body = body.slice(headlineMatch[0].length);
  } else {
    headline.hidden = true;
    headline.innerHTML = "";
  }

  const match = body.match(/^##\s*Details\s*$/im);
  if (!match) {
    resultBody.innerHTML = markupXrefs(DOMPurify.sanitize(marked.parse(body)));
  } else {
    resultBody.innerHTML = markupXrefs(DOMPurify.sanitize(marked.parse(body.slice(0, match.index))));
    detailsBody.innerHTML = markupXrefs(DOMPurify.sanitize(marked.parse(body.slice(match.index + match[0].length))));
    detailsPanel.hidden = false;
  }
  openLinksInNewTab(resultBody);
  openLinksInNewTab(detailsBody);
}

// Source links (see _expression_prompt's point 4) should open in a new
// tab rather than navigating away from an in-progress or already-typed
// lookup. Done as a plain DOM pass after insertion, not via a
// DOMPurify ALLOWED_ATTR tweak - setting properties directly on already-
// sanitized, already-inserted elements sidesteps any uncertainty about
// exactly which attributes DOMPurify's default config lets through.
// Excludes .xref-link (see markupXrefs) - those are handled by the click
// listener below and must stay same-tab/same-page.
function openLinksInNewTab(container) {
  container.querySelectorAll("a:not(.xref-link)").forEach((a) => {
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  });
}

// Turns core.py's {{lang:X}} / {{word:X}} markers (see _expression_prompt's
// point 6) into real clickable links - applied to the final HTML string
// rather than the markdown, so it works no matter what markup ends up
// surrounding the marker (inside a table cell, bold text, wherever). Only
// escaped, plain-text content is ever inserted via the captured value, so
// this can't reopen anything DOMPurify already closed off - it's adding
// new, fully-controlled markup after sanitization already ran, not
// re-introducing unsanitized input.
function escapeHtml(s) {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}
function xrefAnchor(kind, value) {
  const esc = escapeHtml(value.trim());
  return `<a href="#" class="xref-link" data-kind="${kind}" data-value="${esc}">${esc}</a>`;
}
function markupXrefs(html) {
  return html
    .replace(/\{\{lang:([^}]+)\}\}/g, (_, v) => xrefAnchor("lang", v))
    .replace(/\{\{word:([^}]+)\}\}/g, (_, v) => xrefAnchor("word", v));
}

// Clicking a cross-reference re-runs a lookup instead of navigating
// anywhere: {{lang:X}} keeps the same word but switches the source
// language to X; {{word:X}} looks up X itself, in whatever language the
// current lookup was identified as (not necessarily what the From field
// was set to - e.g. it could've been left on Auto-detect). Both cases
// go through the normal submit()/API/cache path, so a word that's
// already been looked up in that language comes back instantly rather
// than searching again.
let lastLookupText = "";
let lastLookupLanguage = "";
resultCard.addEventListener("click", (e) => {
  const link = e.target.closest(".xref-link");
  if (!link) return;
  e.preventDefault();
  const { kind, value } = link.dataset;
  if (kind === "lang") {
    submit({ text: lastLookupText, sourceLang: value, mode: "expression" });
  } else if (kind === "word") {
    submit({ text: value, sourceLang: lastLookupLanguage || undefined, mode: "expression" });
  }
});

// `overrides` lets a cross-reference click (see the resultCard listener
// above) drive a lookup programmatically without fighting the From
// field's select/custom-input toggle state - it bypasses reading from
// the DOM inputs for whichever fields it provides, but still updates
// those same inputs afterward so the visible UI matches what was
// actually looked up.
async function submit(overrides = {}) {
  const text = (overrides.text ?? inputText.value).trim();
  if (!text) return;

  const targetLang = effectiveLangValue(toSelect, toCustom);
  if (!targetLang) {
    showError("Pick (or type) a language to explain/translate into.");
    return;
  }

  const sourceLang = overrides.sourceLang !== undefined ? overrides.sourceLang : effectiveLangValue(fromSelect, fromCustom);
  const mode = overrides.mode || selectedMode;
  if (overrides.text !== undefined) inputText.value = text;
  if (overrides.sourceLang) setLangField(fromSelect, fromCustom, overrides.sourceLang);
  lastLookupText = text;

  goBtn.disabled = true;
  goBtn.textContent = "Thinking…";
  errorCard.hidden = true;
  correctionNote.hidden = true;
  correctionNote.textContent = "";
  headline.hidden = true;
  headline.innerHTML = "";
  resultBody.innerHTML = "";
  languageBadge.hidden = true;
  languageBadge.textContent = "";
  modeUsedBadge.textContent = "Starting…";
  detailsPanel.hidden = true;
  detailsPanel.open = false;
  detailsBody.innerHTML = "";
  resultCard.hidden = false; // show early - status updates land here as they happen

  let accumulated = "";
  try {
    const response = await fetch("/api/translate", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Cogni-Key": getAccessKey() },
      body: JSON.stringify({
        text,
        source_lang: sourceLang || null,
        target_lang: targetLang,
        mode,
      }),
    });
    if (response.status === 401) {
      throw new Error("Missing or invalid access key - reopen the link you were given (with ?key=... in it).");
    }
    if (!response.ok) {
      const body = await response.json().catch(() => ({}));
      throw new Error(body.detail || `Request failed (${response.status})`);
    }

    // The response is newline-delimited JSON, one event per line, streamed
    // as the lookup progresses (see server.py) - not a single JSON body.
    // This is what actually fixes both "looks stuck" (status updates show
    // up immediately) and the Cloudflare 524s (a continuously-streaming
    // response doesn't look like a stalled connection to the tunnel).
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop(); // last (possibly incomplete) line stays buffered
      for (const line of lines) {
        if (!line.trim()) continue;
        handleStreamEvent(JSON.parse(line));
      }
    }
  } catch (err) {
    showError(err.message || "Something went wrong.");
  } finally {
    goBtn.disabled = false;
    goBtn.textContent = "Explain / Translate";
  }

  function handleStreamEvent(evt) {
    if (evt.type === "status") {
      modeUsedBadge.textContent = evt.message;
    } else if (evt.type === "language") {
      languageBadge.textContent = evt.name;
      languageBadge.hidden = false;
      lastLookupLanguage = evt.name;
    } else if (evt.type === "delta") {
      accumulated += evt.text;
      renderResult(accumulated);
    } else if (evt.type === "done") {
      const label = MODE_LABELS[evt.mode_used] || evt.mode_used;
      modeUsedBadge.textContent = evt.cached ? `${label} · instant (cached)` : label;
    } else if (evt.type === "error") {
      throw new Error(evt.message || "Something went wrong.");
    }
  }
}

function showError(message) {
  errorText.textContent = message;
  errorCard.hidden = false;
}

goBtn.addEventListener("click", () => submit());
inputText.addEventListener("keydown", (e) => {
  if (e.key !== "Enter" || e.shiftKey) return; // Shift+Enter: let the textarea insert a newline as normal
  e.preventDefault(); // plain Enter submits instead of inserting a newline
  submit();
});
