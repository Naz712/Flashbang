/* Flashbang v3 front-end — renders the design against the live API. */

const GOOD = "#009E73", WARN = "#E69F00", LOW = "#D55E00", MUT = "#8A8F9C";
const SUBJ = ["#0072B2", "#E69F00", "#009E73", "#CC79A7"];
const SHOW_EVIDENCE = true;

const S = {
  view: "home",
  state: null,          // /api/state payload
  pdfId: null,          // current doc
  navOpen: localStorage.getItem("fbNavOpen") === "1",   // icon sidenav expanded?
  courseId: null,       // course open on the course page
  forceVision: false,   // ingest: read every page as an image (diagram decks)
  asstSuggest: [],      // assistant input: current name suggestions
  asstSuggestIdx: -1,   // highlighted suggestion
  docOpen: new Set(),   // expanded documents on the course page
  reviewView: "decks",  // review screen: "decks" picker | "chat" live session
  deckOpen: new Set(),  // expanded courses in the deck rail
  editSplit: null,      // pdf_id whose topic-split editor is open
  readSel: new Set(),   // reading library: topics ticked for a merged PDF
  pendingConf: null,    // "sure" | "unsure" attached to next message
  qShownAt: null,       // Date.now() when the current question card appeared
  sessionLen: 25,
  focusStart: null,     // Date when focus timer started
  recap: null,
  blockDone: false,     // reading sidebar: last block ended -> show "logged"
  busy: false,
  pdfSort: localStorage.getItem("fbPdfSort") || "weakest",  // progress-card order
  cardFilter: { course_id: null, pdf_id: null, topic_id: null },
  showImport: false,    // cards screen: paste-import panel open?
  importText: "",       // survives re-renders
  importPreview: null,  // {cards, source} from the dry-run parse
  cards: [],            // cards screen data
  cardTopics: [],       // topics for the move-to select
};

const $ = (id) => document.getElementById(id);
// for titles inside inline onclick='...' strings: encodeURIComponent leaves
// apostrophes alone, which breaks the attribute for titles like "'self'"
const encT = (s) => encodeURIComponent(s ?? "").replace(/'/g, "%27");
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* markdown-lite for agent replies: escape first (XSS-safe), then transform.
   Supports **bold**, *italic*, `code`, ### headings, bullet/numbered lists. */
function md(s) {
  const lines = esc(s).split("\n");
  const out = [];
  let list = null; // "ul" | "ol"
  const closeList = () => { if (list) { out.push(`</${list}>`); list = null; } };
  for (const raw of lines) {
    const line = raw.trimEnd();
    const bullet = line.match(/^\s*[-*•]\s+(.*)/);
    const numbered = line.match(/^\s*(\d+)[.)]\s+(.*)/);
    const heading = line.match(/^(#{1,4})\s+(.*)/);
    if (bullet) {
      if (list !== "ul") { closeList(); out.push("<ul>"); list = "ul"; }
      out.push(`<li>${inline(bullet[1])}</li>`);
    } else if (numbered) {
      if (list !== "ol") { closeList(); out.push(`<ol start="${numbered[1]}">`); list = "ol"; }
      out.push(`<li>${inline(numbered[2])}</li>`);
    } else if (heading) {
      closeList();
      out.push(`<div class="md-head">${inline(heading[2])}</div>`);
    } else if (line.trim() === "") {
      closeList();
      out.push('<div class="md-gap"></div>');
    } else {
      closeList();
      out.push(`<div>${inline(line)}</div>`);
    }
  }
  closeList();
  return out.join("");

  function inline(t) {
    return t
      .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
      .replace(/(^|[^*])\*([^*\s][^*]*)\*/g, "$1<em>$2</em>")
      .replace(/`([^`]+)`/g, "<code>$1</code>");
  }
}
const retColor = (pct) => pct >= 70 ? GOOD : pct >= 40 ? WARN : pct > 0 ? LOW : "#C9CCD4";
const fmtMin = (m) => { m = Math.round(m || 0); return m >= 60 ? `${Math.floor(m / 60)}h ${m % 60}m` : `${m}m`; };
const deltaBits = (d) => d === 0 ? { label: "±0", color: MUT }
  : d > 0 ? { label: `▲${d} wk`, color: GOOD } : { label: `▼${-d} wk`, color: LOW };

async function fetchState() {
  const q = S.pdfId ? `?pdf_id=${S.pdfId}` : "";
  const res = await fetch(`/api/state${q}`);
  S.state = await res.json();
  if (S.state.current) S.pdfId = S.state.current.pdf_id;
  if (!RV.sid) S.qShownAt = null;   // latency only means something mid-review
  render();
}

async function fetchHistory() {
  const res = await fetch("/api/history");
  const history = await res.json();
  const scroll = $("chatScroll");
  scroll.innerHTML = history.map(renderMsg).join("");
  scroll.scrollTop = scroll.scrollHeight;
}

/* ---------------------------------------------------------------- chat */

/* question-card marker emitted by the review/pretest agents:
   [CARD 2/4 · Topic Title]\n<question> */
const CARD_RE = /\[CARD\s+(\d+)\s*(?:\/|of)\s*(\d+)\s*[·\-–:]\s*([^\]]+)\]/i;

function renderMsg(m) {
  if (m.role === "user") {
    const meta = m.meta ? `<div class="grade-head"><span class="grade-meta" style="color:#B9BDC7">${esc(m.meta)}</span></div>` : "";
    return `<div class="msg-row-user"><div class="bubble-user">${meta}${esc(m.text)}</div></div>`;
  }
  if (m.role === "grade") {
    const good = m.grade >= 4;
    const cls = good ? "good" : "warn";
    const verdict = good ? "Correct" : m.grade === 3 ? "Partially correct" : "Not quite";
    // structured feedback (right/gap/model answer/why/hook/calibration) with
    // plain-text fallback for pre-upgrade history entries
    const section = (label, text, extraClass = "") => text
      ? `<div class="gsec ${extraClass}"><span class="gsec-label">${label}</span><span>${esc(text)}</span></div>` : "";
    const structured = m.right || m.gap || m.answer;
    const body = structured
      ? section("✓ YOU HAD", m.right, "g-right")
        + section("✗ THE GAP", m.gap, "g-gap")
        + section("MODEL ANSWER", m.answer)
        + section("WHY", m.why)
        + section("REMEMBER", m.hook, "g-hook")
        + (m.calibration ? `<div class="g-cal">${esc(m.calibration)}</div>` : "")
      : `<div style="padding:12px 16px; font-size:13.5px; line-height:1.6">${md(m.text)}</div>`;
    return `<div class="msg-row-bot"><div class="gcard ${cls}">
      <div class="gcard-head ${cls}">
        <span class="gcard-pill ${cls}">✓ GRADE ${m.grade}/5</span>
        <span class="gcard-verdict">${verdict}</span>
        <span style="flex:1"></span>
        <button class="undo-btn" data-card="${m.card_id || ""}" onclick="undoGrade(this)" title="Mis-graded? Restore the card's previous schedule">undo</button>
      </div>
      ${body}
      ${m.meta ? `<div class="gcard-meta">${esc(m.meta)}</div>` : ""}
    </div></div>`;
  }
  // ingest preview: the course card for a just-saved pdf, like Progress shows
  if (m.role === "pdfcard" && m.pdf) {
    const p = m.pdf;
    const rows = p.topics.map((t) => `
      <div class="trow">
        <span class="dot" style="background:${t.kind === "general" ? "#C9CCD4" : "#0072B2"}"></span>
        <span class="name">${esc(t.title)}</span>
        ${t.kind === "general" ? `<span class="info-tag">info</span>` : ""}
        <span class="time" style="margin-left:auto; flex:none">p.${t.pages} · ${fmtMin(t.est_minutes)}</span>
      </div>`).join("");
    return `<div class="msg-row-bot"><div class="chat-pdfcard" onclick="openDoc(${p.pdf_id})" title="Open in Study">
      <div style="font-size:13px; font-weight:600; line-height:1.4">📄 ${esc(p.filename)}</div>
      <div class="doc-meta" style="margin-bottom:10px">${p.total_pages} pages · ${esc(p.est)} est · ${p.topics.length} topics</div>
      <div style="display:flex; flex-direction:column; gap:6px">${rows}</div>
    </div></div>`;
  }
  // session gap report: what was missed, where to re-read, what to paste
  // into an external tutor chat — the token-heavy explaining happens THERE
  if (m.role === "report" && m.report) {
    const rep = m.report;
    window.__reports = window.__reports || {};
    window.__reports[rep.session_id] = rep.text;
    const missedRows = rep.missed.map((it, i) => `
      <div class="gsec g-gap" style="align-items:flex-start">
        <span class="gsec-label" style="flex:none">${i + 1}</span>
        <span style="flex:1">
          <b>${esc(it.question)}</b><br>
          <span style="color:#5C616E">Expected: ${esc(it.answer)}</span>
          ${it.gap ? `<br><span style="color:#8A3B00">Gap: ${esc(it.gap)}</span>` : ""}
        </span>
        <button class="conf-btn" style="flex:none" title="Open ${esc(it.topic_title)} at these pages in the reader"
          onclick="openTopic(${it.pdf_id}, ${it.page_start}, ${it.page_end}, '${encT(it.topic_title)}')">📖 p.${it.page_start}–${it.page_end}</button>
      </div>`).join("");
    return `<div class="msg-row-bot"><div class="gcard ${rep.missed.length ? "warn" : "good"}" style="max-width:min(85%, 820px)">
      <div class="gcard-head ${rep.missed.length ? "warn" : "good"}">
        <span class="gcard-pill ${rep.missed.length ? "warn" : "good"}">SESSION REPORT</span>
        <span class="gcard-verdict">${rep.cards} cards · ${rep.accuracy != null ? rep.accuracy + "% recall · " : ""}${rep.missed.length} gap${rep.missed.length === 1 ? "" : "s"}</span>
        <span style="flex:1"></span>
        <button class="conf-btn" onclick="copyReport(${rep.session_id}, this)"
          title="Copy a ready-made coaching prompt — paste it into Claude/ChatGPT and let THEM burn the tokens explaining">⧉ Copy tutor prompt</button>
      </div>
      ${rep.missed.length ? missedRows : `<div style="padding:12px 16px; font-size:13px">Clean sweep — nothing to re-study from this session.</div>`}
    </div></div>`;
  }
  // assistant: question marker → styled card (plain bubble for any lead-in text)
  const match = m.text.match(CARD_RE);
  if (match) {
    const at = m.text.search(CARD_RE);
    const pre = m.text.slice(0, at).trim();
    const question = m.text.slice(at + match[0].length).trim();
    return (pre ? `<div class="msg-row-bot"><div class="bubble-bot">${md(pre)}</div></div>` : "") + `
      <div class="msg-row-bot"><div class="qcard">
        <div class="qcard-head">
          <span class="qcard-label">Q · CARD ${match[1]} OF ${match[2]}</span>
          <span class="qcard-topic">· ${esc(match[3].trim())}</span>
        </div>
        <div class="qcard-body">${md(question)}</div>
        <div class="qcard-hint">TYPE YOUR ANSWER BELOW</div>
      </div></div>`;
  }
  return `<div class="msg-row-bot"><div class="bubble-bot">${md(m.text)}</div></div>`;
}

window.copyReport = async (sessionId, btn) => {
  btn.disabled = true;
  btn.textContent = "Tailoring…";
  // one small model call writes a prompt shaped to THESE gaps; the
  // deterministic report is the fallback if it fails
  const res = await fetch("/api/tutor_prompt", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId }) })
    .then((r) => r.ok ? r.json() : null).catch(() => null);
  const text = res?.text || window.__reports?.[sessionId];
  btn.disabled = false;
  if (!text) { btn.textContent = "⧉ Copy tutor prompt"; alert("Couldn't build the prompt."); return; }
  try {
    await navigator.clipboard.writeText(text);
    btn.textContent = res?.source === "ai" ? "Copied ✓ (tailored)" : "Copied ✓";
    window.__lastPrompt = text;
    setTimeout(() => { btn.textContent = "⧉ Copy tutor prompt"; }, 2400);
  } catch {
    btn.textContent = "⧉ Copy tutor prompt";
    alert("Clipboard blocked — click the page once, then try again.");
  }
};

window.undoGrade = async (btn) => {
  const cardId = +btn.dataset.card;
  if (!cardId) return;
  btn.disabled = true;
  const res = await fetch("/api/review/undo", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ card_id: cardId }) });
  if (res.ok) { btn.textContent = "undone ✓"; fetchState(); }
  else btn.disabled = false;
};

/* deck picker: courses drop down to documents; start a review on either,
   or take today's recommended (all due, budget-capped) */
function renderReviewHome() {
  const st = S.state;
  const home = $("reviewHome");
  if (!st || S.view !== "study" || S.reviewView !== "decks") return;

  const decks = st.libCourses.map((c) => {
    const open = S.deckOpen.has(c.id);
    const docs = open ? c.pdfs.map((p) => `
      <div class="deck-doc">
        <span class="deck-name" title="${esc(p.filename)}">${esc(p.filename.replace(/\.pdf$/i, ""))}</span>
        <span class="deck-due ${p.due ? "" : "zero"}">${p.due} due</span>
        <button class="deck-go" ${p.due ? "" : "disabled"} title="Review this document's due cards"
          onclick="event.stopPropagation(); startReviewSession({ pdf_id: ${p.pdf_id} })">▶</button>
      </div>`).join("") : "";
    return `<div class="deck-course">
      <div class="deck-head" onclick="toggleDeck(${c.id})">
        <span class="deck-caret">${open ? "▾" : "▸"}</span>
        <span class="course-tile" style="background:${SUBJ[c.ci % 4]}; width:16px; height:16px; border-radius:5px"></span>
        <span class="deck-name">${esc(c.name)}</span>
        <span class="deck-due ${c.dueCount ? "" : "zero"}">${c.dueCount} due</span>
        <button class="deck-go" ${c.dueCount ? "" : "disabled"} title="Review this course's due cards"
          onclick="event.stopPropagation(); startReviewSession({ course_id: ${c.id} })">▶</button>
      </div>${docs}
    </div>`;
  }).join("");

  const b = st.budget || { daily_minutes: 0, sec_per_card: 84 };
  const fit = b.daily_minutes ? Math.max(1, Math.floor(b.daily_minutes * 60 / b.sec_per_card)) : null;
  const dealing = fit ? Math.min(fit, st.dueTotal) : st.dueTotal;
  home.innerHTML = `
    <div class="deck-rail">
      <div class="mono-label" style="padding:2px 4px 4px">DECKS</div>
      ${decks || `<div class="card" style="font-size:12px; color:#8A8F9C">No decks yet — add PDFs in the Reading tab.</div>`}
    </div>
    <div class="today-panel">
      <div class="card" style="padding:20px 22px">
        <div class="mono-label" style="margin-bottom:10px">TODAY'S REVIEW</div>
        <div class="stat-num" style="color:${st.dueTotal ? LOW : "#00794F"}">${st.dueTotal}<span style="font-size:14px; color:#8A8F9C; font-weight:500"> cards due</span></div>
        <div class="stat-sub">${st.dueTotal === 0 ? "all caught up — nothing owed today"
          : fit ? `dealing ${dealing} (your ${b.daily_minutes}-min budget · ~${b.sec_per_card}s/card)` : "no daily budget set — deals everything due"}</div>
        <button class="btn-block" style="margin-top:14px" ${st.dueTotal ? "" : "disabled"}
          onclick="startReviewSession({})">▶ Start today's review</button>
        ${evidence("Due order = most at risk first; courses interleave naturally, which beats blocking (Rohrer &amp; Taylor, 2007).")}
      </div>
      ${st.best ? `<div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:8px">WEAKEST DUE TOPIC</div>
        <div style="font-size:13px; font-weight:600">${esc(st.best.title)}</div>
        <div class="stat-sub">${st.best.pct.toFixed(0)}% retention — most in need of a rep</div>
        <button class="btn-block ghost" style="margin-top:10px" onclick="startReviewSession({ topic_id: ${st.best.topic_id} })">Review just this topic</button>
      </div>` : ""}
    </div>`;
}

window.toggleDeck = (courseId) => {
  S.deckOpen.has(courseId) ? S.deckOpen.delete(courseId) : S.deckOpen.add(courseId);
  renderReviewHome();
};

window.backToDecks = () => {
  if (RV.sid) {
    if (!confirm("End the session and go back to your decks?")) return;
    endSession();
  }
  S.reviewView = "decks";
  render();
};

/* ---------------------------------------------------------------- review driver */
/* De-agented 2026-07-29: the app deals cards, you type answers, and the only
   model call per answer is the fast-tier grader. Skip / Undo / End are
   buttons. The router and agent loop are gone from the runtime. */

const RV = { sid: null, kind: null, card: null };

function chatLine(html) {
  const scroll = $("chatScroll");
  scroll.insertAdjacentHTML("beforeend", html);
  scroll.scrollTop = scroll.scrollHeight;
}

function showQuestion(card) {
  RV.card = card;
  chatLine(renderMsg({ role: "assistant",
    text: `[CARD ${card.n}/${card.total} · ${card.topic_title}]\n${card.question}` }));
  S.qShownAt = Date.now();
  $("chatInput").placeholder = card.phase === "relearn"
    ? "Re-ask (not scored) — type what you remember…"
    : "Type your answer…";
  renderConfRow();
  $("chatInput").focus();
}

function reviewIdle(extraHtml) {
  RV.sid = RV.kind = RV.card = null;
  S.qShownAt = null;
  $("chatInput").placeholder = "Start a review to begin — cards get dealt here.";
  $("agentName").textContent = "Review";
  $("sessionLabel").textContent = "";
  renderConfRow();
  if (extraHtml) chatLine(extraHtml);
  fetchState();
}

window.startReviewSession = async (scope = {}, kind = "review") => {
  if (RV.sid || S.busy) return;
  S.view = "study";
  S.reviewView = "chat";   // the chat only appears once a review starts
  render();
  S.busy = true;
  const res = await fetch("/api/review/start", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...scope, kind }) })
    .then((r) => r.ok ? r.json() : null).catch(() => null);
  S.busy = false;
  if (!res) return chatLine(renderMsg({ role: "assistant", text: "Couldn't start the session — is the server up?" }));
  if (res.empty) return chatLine(renderMsg({ role: "assistant",
    text: kind === "cram" ? "Nothing to cram in that scope." : "Nothing due right now — come back when the schedule says so." }));
  RV.sid = res.session_id;
  RV.kind = kind;
  $("agentName").textContent = kind === "cram" ? "Cram session" : "Review session";
  $("sessionLabel").textContent = `· ${res.card.total} card${res.card.total === 1 ? "" : "s"}`;
  if (res.budget_capped) chatLine(renderMsg({ role: "assistant",
    text: `Dealing ${res.card.total} of ${res.total_due} due — the rest wait, per your daily budget.` }));
  showQuestion(res.card);
};

async function submitAnswer(text) {
  if (!RV.sid || S.busy || !text.trim()) return;
  S.busy = true;
  const confidence = S.pendingConf;
  S.pendingConf = null;
  const latency_ms = S.qShownAt ? Date.now() - S.qShownAt : null;
  chatLine(renderMsg({ role: "user", text, meta: confidence ? `confidence: ${confidence}` : "" }));
  chatLine(`<div id="thinking" class="msg-row-bot"><div class="bubble-bot"><span class="status-line working">Grading…</span></div></div>`);
  $("chatInput").value = "";
  renderConfRow();
  const res = await fetch("/api/review/answer", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: RV.sid, answer: text, confidence, latency_ms }) })
    .then((r) => r.ok ? r.json() : null).catch(() => null);
  document.getElementById("thinking")?.remove();
  S.busy = false;
  if (!res) return chatLine(renderMsg({ role: "assistant", text: "Grading failed — send that answer again." }));
  chatLine(renderMsg(res.grade));
  if (res.entering_relearn) chatLine(renderMsg({ role: "assistant",
    text: `Re-asking the ${res.relearn_count} you missed — retrieval practice only, not scored.` }));
  if (res.done) return finishSession();
  showQuestion(res.next);
}

window.skipCard = async () => {
  if (!RV.sid || S.busy) return;
  const res = await fetch("/api/review/skip", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: RV.sid }) })
    .then((r) => r.ok ? r.json() : null).catch(() => null);
  if (!res) return;
  chatLine(renderMsg({ role: "assistant", text: "Skipped — it stays due." }));
  if (res.entering_relearn) chatLine(renderMsg({ role: "assistant", text: "Re-asking this session's misses — not scored." }));
  if (res.done) return finishSession();
  showQuestion(res.next);
};

window.endSession = () => { if (RV.sid && !S.busy) finishSession(); };

async function finishSession() {
  const sid = RV.sid;
  RV.sid = null;   // guard against double-end
  const res = await fetch("/api/review/end", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sid }) })
    .then((r) => r.ok ? r.json() : null).catch(() => null);
  let html = "";
  if (res) {
    const s = res.summary;
    html = renderMsg({ role: "assistant",
      text: `Session done — ${s.cards} card${s.cards === 1 ? "" : "s"}${s.accuracy != null ? `, ${s.accuracy}% recall` : ""}.` });
    if (res.report) html += renderMsg({ role: "report", report: res.report });
  }
  reviewIdle(html);
}


function renderConfRow() {
  const active = !!RV.sid;
  $("sessionBar").style.display = active ? "flex" : "none";
  $("confRow").style.display = active && RV.card?.phase !== "relearn" ? "flex" : "none";
  document.querySelectorAll(".conf-btn[data-conf]").forEach((b) =>
    b.classList.toggle("picked", b.dataset.conf === S.pendingConf));
}

/* ---------------------------------------------------------------- rail */

function evidence(text) {
  return SHOW_EVIDENCE ? `<div class="evidence">${text}</div>` : "";
}

/* 85%-rule flag (Wilson et al., 2019): recall running >95% = harden the cards,
   <60% = struggling — optimal difficulty sits near 85%. */
function flagTag(topicId) {
  const flag = S.state?.topicFlags?.[topicId];
  if (flag === "easy") return `<span class="flag-tag easy" title="Recall >95% — too easy; consider harder cards">too easy</span>`;
  if (flag === "hard") return `<span class="flag-tag hard" title="Recall <60% — struggling; smaller steps or re-read first">struggling</span>`;
  return "";
}

/* The old right rail and the floating timer pill are both gone. Study blocks
   are started from the reader's sidebar (reading) and review sessions log
   their own time — nothing needs to hover over the app. */

/* ---------------------------------------------------------------- progress */

function renderProgress() {
  const st = S.state;
  if (!st) return;
  const inner = $("progressInner");
  const stats = st.stats;

  const weekDots = stats.week.map((d) => `
    <div class="week-day">
      <span class="wdot" style="${d.lit ? `background:${GOOD}` : d.future ? "background:#fff; border:1.5px dashed #D9D9D4" : "background:#ECECE8"}"></span>
      <span class="lbl">${d.day}</span>
    </div>`).join("");

  const fMax = Math.max(1, ...st.forecast.map((f) => f.count));
  const forecastTotal = st.forecast.reduce((a, f) => a + f.count, 0);
  const forecastCols = st.forecast.map((f, i) => `
    <div class="forecast-col">
      <span class="forecast-n">${f.count}</span>
      <div class="forecast-bar" style="height:${Math.max(4, f.count / fMax * 64)}px; background:${i === 0 ? "#0072B2" : "rgba(0,114,178,.45)"}"></div>
      <span class="forecast-day">${i === 0 ? "today" : `+${i}d`}</span>
    </div>`).join("");

  const segs = st.subjectTime.map((r) =>
    `<div style="width:${r.share}%; background:${SUBJ[r.ci % 4]}"></div>`).join("");
  const legend = st.subjectTime.map((r) => `
    <div style="display:flex; align-items:center; gap:9px">
      <span style="flex:none; width:9px; height:9px; border-radius:3px; background:${SUBJ[r.ci % 4]}"></span>
      <span style="font-size:12.5px; flex:1">${esc(r.name)}</span>
      <span class="mono" style="font-size:11px; color:#8A8F9C">${r.time} · ${r.share}%</span>
    </div>`).join("");

  // ---- ordering follows the learning-analytics evidence: a few north-star
  // numbers with reference frames and an action first, then pacing (spacing
  // made visible), then outcome trends, then drill-down diagnostics.
  // Cognitive-load research caps a useful view around 5-9 items per layer.
  const mx = renderMetrics(st.metrics) || {};
  const b = st.budget || { daily_minutes: 0, sec_per_card: 84 };
  const fit = b.daily_minutes ? Math.max(1, Math.floor(b.daily_minutes * 60 / b.sec_per_card)) : 0;
  const exams = Object.entries(st.metrics?.exams || {})
    .map(([cid, e]) => ({ ...e, course: st.courses.find((c) => c.id === +cid)?.name || "course" }))
    .filter((e) => e.today != null)
    .sort((a, b2) => a.days_left - b2.days_left);
  const nextExam = exams[0];
  const latest = mx.latestRetention;

  inner.innerHTML = `
    <div class="section-head"><span class="mono-label">WHERE YOU STAND</span><div class="rule"></div>
      <span style="font-size:11px; color:#8A8F9C">the four numbers worth acting on</span></div>
    <div class="grid2">
      <div class="card" style="padding:18px 20px">
        <div class="mono-label" style="margin-bottom:9px">DUE NOW</div>
        <div class="stat-num" style="color:${st.dueTotal ? LOW : "#00794F"}">${st.dueTotal}</div>
        <div class="stat-sub">across ${st.courses.length} course${st.courses.length === 1 ? "" : "s"}${fit ? ` · your budget fits ~${fit}` : ""}</div>
        <div style="display:flex; align-items:center; gap:6px; margin-top:12px; flex-wrap:wrap">
          <span style="font-size:11px; color:#5C616E">Daily budget</span>
          ${[15, 25, 45, 60].map((m) => `<button class="dur-btn ${b.daily_minutes === m ? "on" : ""}" onclick="setBudget(${b.daily_minutes === m ? 0 : m})">${m}m</button>`).join("")}
          <span style="font-size:10.5px; color:#8A8F9C">${b.sec_per_card}s/card ${b.sec_per_card === 84 ? "(est.)" : "(measured)"}</span>
        </div>
        ${fit && st.dueTotal > fit ? `<button class="btn-block ghost" style="margin-top:10px" onclick="spreadBacklog()"
          title="Keep the ${fit} most overdue due today; push the other ${st.dueTotal - fit} onto the coming days">Spread ${st.dueTotal - fit} onto later days</button>`
          : st.dueTotal ? `<button class="btn-block" style="margin-top:10px" onclick="startReviewSession({})">▶ Start today's review</button>` : ""}
      </div>
      <div class="card" style="padding:18px 20px">
        <div class="mono-label" style="margin-bottom:9px">EXAM READINESS</div>
        ${nextExam ? `
          <div class="stat-num" style="color:${nextExam.onPlan >= 70 ? "#00794F" : LOW}">${nextExam.onPlan}%</div>
          <div class="stat-sub">${esc(nextExam.course)} · projected recall on exam day if you keep to the schedule</div>
          <div style="font-size:11.5px; color:#5C616E; margin-top:8px">${nextExam.days_left} days left · <b style="color:${nextExam.today >= 70 ? "#00794F" : LOW}">${nextExam.today}%</b> if you stopped studying today</div>
          ${exams.length > 1 ? `<div style="font-size:11px; color:#8A8F9C; margin-top:6px">${exams.slice(1).map((e) => `${esc(e.course)}: ${e.onPlan}% in ${e.days_left}d`).join(" · ")}</div>` : ""}`
        : `<div style="font-size:12px; color:#8A8F9C; line-height:1.6">No exam dates set. Add one on a course page and this becomes the number that tells you whether the current pace is enough.</div>`}
        ${evidence("A goal with a deadline and a projection beats a raw score: it turns 'how am I doing' into 'is this pace enough' (Kluger &amp; DeNisi, 1996).")}
      </div>
    </div>
    <div class="grid2">
      ${mx.knowledge || ""}
      <div class="card" style="padding:18px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:9px">RETENTION RIGHT NOW</div>
        ${latest ? `<div class="stat-num" style="color:${latest.rate >= 80 ? "#00794F" : latest.rate >= 60 ? "#8A6100" : LOW}">${latest.rate}%</div>
          <div class="stat-sub">of cards recalled at review time this week · aim ≈85%</div>`
        : `<div style="font-size:12px; color:#8A8F9C; flex:1">No graded answers yet — review a deck and this fills in.</div>`}
        ${evidence("True retention is the outcome measure: everything else on this page is a means to it.")}
      </div>
    </div>

    <div class="section-head" style="margin-top:14px"><span class="mono-label">PACING</span><div class="rule"></div>
      <span style="font-size:11px; color:#8A8F9C">is the work spread out?</span></div>
    <div class="grid2">
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:14px">
          <span class="mono-label">REVIEW FORECAST · NEXT 7 DAYS</span>
          <span class="mono" style="font-size:10.5px; color:#8A8F9C">${forecastTotal} scheduled</span>
        </div>
        <div class="forecast-row">${forecastCols}</div>
        ${evidence("Spacing effect: each successful recall pushes the next one further out, so daily load stays small (Cepeda et al., 2006).")}
      </div>
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:12px">THIS WEEK</div>
        <div class="week-dots">${weekDots}</div>
        <div style="font-size:11.5px; color:#5C616E; margin-bottom:14px"><span style="font-weight:600; color:#1C1E26">${stats.litCount} of last 7 days</span> · streak ${stats.streak}d · ${stats.weekTime} in ${stats.sessionCount} session${stats.sessionCount === 1 ? "" : "s"}</div>
        <div class="mono-label" style="margin-bottom:10px">TIME BY COURSE · ALL TIME</div>
        <div class="seg-track">${segs}</div>
        <div style="display:flex; flex-direction:column; gap:8px">${legend}</div>
      </div>
    </div>
    ${mx.heatmap || ""}

    <div class="section-head" style="margin-top:14px"><span class="mono-label">TRENDS</span><div class="rule"></div>
      <span style="font-size:11px; color:#8A8F9C">is it sticking over time?</span></div>
    <div class="grid2">
      ${mx.retention || ""}
      ${mx.maturity || ""}
    </div>

    <div class="section-head" style="margin-top:14px"><span class="mono-label">DIAGNOSTICS</span><div class="rule"></div>
      <span style="font-size:11px; color:#8A8F9C">where exactly it's going wrong</span></div>
    <div class="grid2">
      ${mx.hardest || ""}
      ${mx.fluency || ""}
    </div>
    <div class="grid2">
      ${mx.sweet || ""}
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:14px">CALIBRATION · CONFIDENCE VS RECALL</div>
        ${renderCalibration(st.calibration)}
        ${evidence("Comparing predicted vs actual recall improves self-regulated study — and confident errors are the most correctable.")}
      </div>
    </div>
    <div class="card" style="padding:16px 20px">
      <div class="mono-label" style="margin-bottom:14px">RECENT SESSIONS</div>
      ${renderRecentSessions(st.recentSessions)}
    </div>

    <div class="section-head" style="margin-top:14px"><span class="mono-label">READING</span><div class="rule"></div>
      <span style="font-size:11px; color:#8A8F9C">tracked separately — reading never moves mastery</span></div>
    ${readingBandHTML(st)}

    <div class="section-head" style="margin-top:14px"><span class="mono-label">SPEND</span><div class="rule"></div>
      <span style="font-size:11px; color:#8A8F9C">what running this has cost</span></div>
    ${spendBandHTML(st)}`;
}

/* spend: estimated from logged token usage × list prices. Every number here
   is the app's own accounting, not a bill — labelled as such. */
function spendBandHTML(st) {
  const sp = st.spend;
  if (!sp) return "";
  const usd = (n) => n == null ? "–" : n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(n < 0.01 ? 4 : 3)}`;
  if (!sp.calls) {
    return `<div class="card" style="padding:16px 20px">
      <div style="font-size:12.5px; color:#8A8F9C; line-height:1.6">
        No model calls logged yet. Grading, card generation, ingestion and the assistant
        all record their tokens here from now on.</div></div>`;
  }
  const maxDay = Math.max(0.0001, ...sp.days.map((d) => d.usd));
  const dayCols = sp.days.map((d) => `
    <div class="forecast-col" title="${d.date} · ${usd(d.usd)}">
      <div class="forecast-bar" style="height:${Math.max(3, d.usd / maxDay * 54)}px;
        background:${d.usd ? "#0072B2" : "#ECECE8"}"></div>
    </div>`).join("");
  const rows = sp.by_purpose.map((p) => {
    const share = sp.total ? p.usd / sp.total * 100 : 0;
    return `<div class="fn-row" title="${p.calls} call${p.calls === 1 ? "" : "s"} · ${p.tokens.toLocaleString()} tokens">
      <span class="fn-label" style="width:118px">${esc(p.purpose)}</span>
      <div class="fn-track"><div class="fn-fill" style="width:${Math.max(2, share)}%; background:#0072B2"></div></div>
      <span class="fn-n" style="width:62px">${usd(p.usd)}</span>
    </div>`;
  }).join("");

  return `
    <div class="grid3">
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:9px">ALL TIME</div>
        <div class="stat-num">${usd(sp.total)}</div>
        <div class="stat-sub">${sp.calls} model call${sp.calls === 1 ? "" : "s"}${sp.biggest ? ` · mostly ${esc(sp.biggest)}` : ""}</div>
      </div>
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:9px">LAST 7 DAYS</div>
        <div class="stat-num">${usd(sp.week)}</div>
        <div class="stat-sub">${usd(sp.today)} today</div>
      </div>
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:9px">UNIT COST</div>
        <div style="display:flex; gap:20px">
          <div><div class="stat-num" style="font-size:20px">${usd(sp.per_answer)}</div><div class="stat-sub">per graded answer</div></div>
          <div><div class="stat-num" style="font-size:20px">${usd(sp.per_card)}</div><div class="stat-sub">per card made</div></div>
        </div>
      </div>
    </div>
    <div class="grid2">
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:14px">WHERE IT WENT</div>
        <div style="display:flex; flex-direction:column; gap:9px">${rows}</div>
      </div>
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:14px">LAST 14 DAYS</div>
        <div class="forecast-row">${dayCols}</div>
        ${evidence("Estimated from each call's token counts at published list prices — your provider dashboard is the actual bill. Embeddings and search cost $0 here: they run locally.")}
      </div>
    </div>`;
}

function renderCalibration(weeks) {
  const hasData = (weeks || []).some((w) => w.sure_n + w.unsure_n > 0);
  if (!hasData) {
    return `<div style="font-size:12px; color:#8A8F9C; line-height:1.6; flex:1">
      No confidence-tagged answers yet. Pick <em>Sure</em> or <em>Unsure</em> before
      answering during reviews and this chart fills in.</div>`;
  }
  const cols = weeks.map((w) => {
    const bar = (rate, color, n, label) => rate == null
      ? `<div class="cal-bar" style="height:4px; background:#ECECE8" title="${label}: no data"></div>`
      : `<div class="cal-bar" style="height:${Math.max(4, rate * 0.56)}px; background:${color}"
           title="${label}: ${rate}% recall over ${n} answers"></div>`;
    return `<div class="cal-col">
      <div class="cal-bars">
        ${bar(w.sure_rate, "#0072B2", w.sure_n, "Sure")}
        ${bar(w.unsure_rate, "#CC79A7", w.unsure_n, "Unsure")}
      </div>
      <span class="forecast-day">${w.label}</span>
    </div>`;
  }).join("");
  // calibration verdict from the most recent week with both series
  const latest = [...weeks].reverse().find((w) => w.sure_rate != null && w.unsure_rate != null);
  let verdict = "";
  if (latest) {
    const gap = latest.sure_rate - latest.unsure_rate;
    verdict = gap >= 15 ? "Well calibrated — your confidence tracks your recall."
      : gap <= 0 ? "Miscalibrated: you recall MORE when unsure — trust yourself less when “sure”."
      : "Slightly compressed — confidence and recall barely differ.";
  }
  return `<div style="display:flex; align-items:center; gap:14px; margin-bottom:10px">
      <span class="cal-key"><span class="cal-dot" style="background:#0072B2"></span>Sure</span>
      <span class="cal-key"><span class="cal-dot" style="background:#CC79A7"></span>Unsure</span>
    </div>
    <div class="cal-row">${cols}</div>
    ${verdict ? `<div style="font-size:11.5px; color:#5C616E; margin-top:10px">${verdict}</div>` : ""}`;
}

function renderRecentSessions(sessions) {
  if (!sessions || !sessions.length) {
    return `<div style="font-size:12px; color:#8A8F9C; flex:1">No sessions yet.</div>`;
  }
  return `<div style="display:flex; flex-direction:column; gap:8px">` + sessions.map((s) => {
    const day = new Date(s.at).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    const acc = s.accuracy == null ? "" :
      `<span class="mono" style="font-size:10.5px; font-weight:600; color:${s.accuracy >= 80 ? GOOD : s.accuracy >= 60 ? "#8A6100" : LOW}">${s.accuracy}%</span>`;
    const accBar = s.accuracy == null ? "" :
      `<div class="sess-track"><div style="height:100%; width:${s.accuracy}%; border-radius:2px; background:${s.accuracy >= 80 ? GOOD : s.accuracy >= 60 ? WARN : LOW}"></div></div>`;
    return `<div class="sess-row">
      <span class="mono" style="font-size:10.5px; color:#8A8F9C; width:74px; flex:none">${day}</span>
      <span style="font-size:11.5px; width:64px; flex:none">${esc(s.kind)}</span>
      <span class="mono" style="font-size:10.5px; color:#8A8F9C; width:118px; flex:none">${s.cards} cards · ${fmtMin(s.minutes)}</span>
      ${accBar}${acc}
    </div>`;
  }).join("") + "</div>";
}

/* ---------------------------------------------------------------- study metrics */

function renderMetrics(mx) {
  if (!mx) return "";

  // heatmap: 26 columns of weeks, Monday-first rows, green scale by minutes
  const shade = (mins) => mins <= 0 ? "#ECECE8"
    : mins < 10 ? "rgba(0,158,115,.25)" : mins < 25 ? "rgba(0,158,115,.5)"
    : mins < 45 ? "rgba(0,158,115,.75)" : "#009E73";
  const cols = [];
  for (let w = 0; w < mx.weeks; w++) {
    const cells = mx.heatmap.slice(w * 7, w * 7 + 7).map((c) => `
      <div class="hm-cell" title="${c.date} · ${c.minutes} min"
        style="${c.future ? "background:transparent" : `background:${shade(c.minutes)}`}"></div>`).join("");
    cols.push(`<div class="hm-col">${cells}</div>`);
  }
  const activeDays = mx.heatmap.filter((c) => c.minutes > 0).length;

  // maturity funnel
  const f = mx.funnel;
  const fTotal = f.new + f.learning + f.young + f.mature || 1;
  const stages = [
    ["New", f.new, "#C9CCD4", "never reviewed"],
    ["Learning", f.learning, "#E69F00", "interval under 7d"],
    ["Young", f.young, "rgba(0,158,115,.55)", "interval 7–21d"],
    ["Mature", f.mature, "#009E73", "interval 21d+ — stable"],
  ];
  const funnelRows = stages.map(([label, n, color, hint]) => `
    <div class="fn-row" title="${hint}">
      <span class="fn-label">${label}</span>
      <div class="fn-track"><div class="fn-fill" style="width:${Math.max(2, n / fTotal * 100)}%; background:${color}"></div></div>
      <span class="fn-n">${n}</span>
    </div>`).join("");

  // retention trend
  const rMax = 100;
  const retCols = mx.retention.map((r) => `
    <div class="forecast-col" title="${r.n} answers">
      <span class="forecast-n">${r.rate == null ? "–" : r.rate + "%"}</span>
      <div class="forecast-bar" style="height:${r.rate == null ? 4 : Math.max(4, r.rate / rMax * 64)}px;
        background:${r.rate == null ? "#ECECE8" : r.rate >= 80 ? "#009E73" : r.rate >= 60 ? "#E69F00" : "#D55E00"}"></div>
      <span class="forecast-day">${r.label}</span>
    </div>`).join("");
  const latest = [...mx.retention].reverse().find((r) => r.rate != null);

  // hardest cards
  const hardRows = mx.hardest.length ? mx.hardest.map((h) => `
    <div class="hard-row" title="${esc(h.topic || "")}">
      <span class="mono" style="font-size:10px; color:#D55E00; font-weight:700; flex:none">${h.fails}×</span>
      <span class="hard-q">${esc(h.question || "(deleted card)")}</span>
      <span class="mono" style="font-size:9.5px; color:#8A8F9C; flex:none">${h.fail_rate}% fail</span>
    </div>`).join("")
    : `<div style="font-size:11.5px; color:#8A8F9C">No repeat-failed cards — nothing is beating you yet.</div>`;

  // knowledge in memory (retrievability-weighted, FSRS-style)
  const kn = mx.knowledge;
  // retrieval fluency: 2×2 of fast/slow (vs personal median) × right/wrong
  const fl = mx.fluency || { n: 0, needed: 6, fluent_pct: null };
  const sec = (ms) => ms == null ? "–" : `${(ms / 1000).toFixed(1)}s`;
  let fluencyBody;
  if (fl.fluent_pct == null) {
    fluencyBody = `<div style="font-size:12px; color:#8A8F9C; line-height:1.6; flex:1">
      Collecting timing data — ${fl.n} of ${fl.needed} timed answers.
      Each question card you answer in a review adds one.</div>`;
  } else {
    const q = fl.quads, total = fl.n || 1;
    const quadRow = (label, n, color, hint) => `
      <div class="fn-row" title="${hint}">
        <span class="fn-label">${label}</span>
        <div class="fn-track"><div class="fn-fill" style="width:${Math.max(2, n / total * 100)}%; background:${color}"></div></div>
        <span class="fn-n">${n}</span>
      </div>`;
    fluencyBody = `
      <div class="stat-num" style="color:${fl.fluent_pct >= 50 ? "#00794F" : "#8A6100"}">${fl.fluent_pct}%</div>
      <div class="stat-sub">fast AND correct · right answers take ${sec(fl.pass_ms)}${fl.fail_ms != null ? ` · wrong ${sec(fl.fail_ms)}` : ""}</div>
      <div style="display:flex; flex-direction:column; gap:8px; margin-top:10px">
        ${quadRow("Fluent", q.fluent, "#009E73", "faster than your median AND correct — strong memories")}
        ${quadRow("Effortful", q.effortful, "rgba(0,158,115,.55)", "correct but slower than your median — still fragile, keep spacing")}
        ${quadRow("Hasty miss", q.fast_wrong, "#D55E00", "fast but wrong — check for a misconception")}
        ${quadRow("Slow miss", q.slow_wrong, "#C9CCD4", "slow and wrong — not there yet")}
      </div>`;
  }

  // sweet spot
  const sw = mx.sweet;
  const sweetBody = sw.rate == null
    ? `<div style="font-size:12px; color:#8A8F9C; flex:1">Needs 5+ recent answers.</div>`
    : `<div class="stat-num" style="color:${sw.rate > 95 ? "#005A8E" : sw.rate >= 70 ? "#00794F" : "#D55E00"}">${sw.rate}%</div>
       <div class="stat-sub">recent recall · optimal ≈ 85%</div>
       <div class="sweet-track"><div class="sweet-band"></div>
         <div class="sweet-pin" style="left:${Math.min(98, Math.max(2, sw.rate))}%"></div></div>
       <div style="font-size:11px; color:#5C616E; margin-top:7px">${
         sw.rate > 95 ? "Too easy — harden cards or stretch intervals." :
         sw.rate < 70 ? "Overloaded — smaller sessions or re-read first." :
         "In the productive-struggle zone."}</div>`;

  // fragments, so the Analytics page can order them by evidence rather than
  // by whatever order they happened to be written in
  return {
    latestRetention: latest,
    knowledge: `
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:9px">KNOWLEDGE IN MEMORY</div>
        <div class="stat-num">${kn.held} <span style="font-size:14px; color:#8A8F9C; font-weight:500">/ ${kn.total} facts</span></div>
        <div class="stat-sub">${kn.pct}% of your cards, decay-weighted, held right now</div>
        ${evidence("Retrievability-weighted total (the FSRS 'knowledge' metric): each card counts as its current recall probability.")}
      </div>`,
    sweet: `
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:9px">CHALLENGE SWEET SPOT</div>
        ${sweetBody}
        ${evidence("~85% success is the optimal difficulty for learning (Wilson et al., 2019; Bjork's desirable difficulties).")}
      </div>`,
    heatmap: `
      <div class="card" style="padding:16px 20px">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px">
          <span class="mono-label">CONSISTENCY · LAST ${mx.weeks} WEEKS</span>
          <span class="mono" style="font-size:10.5px; color:#8A8F9C">${activeDays} active days</span>
        </div>
        <div class="hm-grid">${cols.join("")}</div>
        ${evidence("Distributed practice: many short sessions beat few long ones (Cepeda et al., 2006).")}
      </div>`,
    retention: `
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:14px">
          <span class="mono-label">RETENTION TREND · WEEKLY RECALL</span>
          ${latest ? `<span class="mono" style="font-size:11px; font-weight:600; color:${latest.rate >= 80 ? "#00794F" : "#8A6100"}">${latest.rate}% now</span>` : ""}
        </div>
        <div class="forecast-row">${retCols}</div>
        ${evidence("The truest signal the system works: recall rate at review time, week over week.")}
      </div>`,
    maturity: `
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:14px">CARD MATURITY</div>
        <div style="display:flex; flex-direction:column; gap:9px">${funnelRows}</div>
        ${evidence("Stability, not just coverage: mature cards (21d+ intervals) are knowledge that survives exams.")}
      </div>`,
    hardest: `
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:12px">HARDEST CARDS · MOST FAILED</div>
        <div style="display:flex; flex-direction:column; gap:8px">${hardRows}</div>
        ${evidence("Leeches: a handful of cards eat most of your failures. Blackout them in the reader or rewrite them — don't just keep failing them.")}
      </div>`,
    fluency: `
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:9px">RETRIEVAL FLUENCY · 28 DAYS</div>
        ${fluencyBody}
        ${evidence("How fast a correct answer comes predicts retention beyond accuracy alone (Benjamin &amp; Bjork, 1996) — slow rights are the ones to keep spacing.")}
      </div>`,
  };
}

/* ---------------------------------------------------------------- reading hub */

function readingBandHTML(st) {
  const rd = st.reading;
  const courseIdx = {};
  st.courses.forEach((c, i) => { courseIdx[c.id] = i; });
  const cColor = (id) => SUBJ[(courseIdx[id] ?? 3) % 4];

  const segTotal = rd.by_course.reduce((a, r) => a + r.minutes, 0) || 1;
  const segs = rd.by_course.map((r) =>
    `<div style="flex:${r.minutes}; background:${cColor(r.course_id)}"></div>`).join("");
  const legend = rd.by_course.map((r) => `
    <div style="display:flex; align-items:center; gap:8px; font-size:11.5px">
      <span class="cal-dot" style="background:${cColor(r.course_id)}"></span>
      <span style="flex:1">${esc(r.name)}</span>
      <span class="mono" style="font-size:10.5px; color:#8A8F9C">${fmtMin(r.minutes)} · ${Math.round(r.minutes / segTotal * 100)}%</span>
    </div>`).join("");

  return `
    <div class="grid3">
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:9px">TIME READ · ALL TIME</div>
        <div class="stat-num">${fmtMin(rd.total_minutes)}</div>
        <div class="stat-sub">${fmtMin(rd.week_minutes)} in the last 7 days · ${rd.block_count} blocks</div>
      </div>
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:9px">READING STREAK</div>
        <div class="stat-num">${rd.streak_days}<span style="font-size:14px; color:#8A8F9C; font-weight:500"> day${rd.streak_days === 1 ? "" : "s"}</span></div>
        <div class="stat-sub">${rd.week_blocks} block${rd.week_blocks === 1 ? "" : "s"} this week</div>
      </div>
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:11px">READING TIME BY COURSE</div>
        ${rd.by_course.length ? `<div class="seg-track">${segs}</div><div style="display:flex; flex-direction:column; gap:8px">${legend}</div>`
          : `<div style="font-size:12px; color:#8A8F9C; flex:1">Nothing logged yet.</div>`}
      </div>
    </div>`;
}

/* course-level numbers, derived from the state payload (no extra endpoint):
   completion weights CONTENT topics by their study-time estimate, same as
   the pdf math, so admin pages can't hold a course under 100%. */
function courseStats(c, st) {
  const rd = st.reading || { by_course: [], by_pdf: [], notes_by_pdf: {} };
  const topics = c.pdfs.flatMap((p) => p.topics);
  const content = topics.filter((t) => t.kind !== "general");
  const weight = (t) => t.est_minutes || 1;
  const wTotal = content.reduce((a, t) => a + weight(t), 0) || 1;
  return {
    completion: content.reduce((a, t) => a + weight(t) * t.mastery_pct, 0) / wTotal,
    due: c.dueCount,
    cards: topics.reduce((a, t) => a + (t.cards_total || 0), 0),
    topicsTotal: content.length,
    covered: content.filter((t) => t.status === "covered").length,
    started: content.filter((t) => t.status === "in_progress").length,
    readMin: rd.by_course?.find((r) => r.course_id === c.id)?.minutes || 0,
    notes: c.pdfs.reduce((a, p) => a + (rd.notes_by_pdf?.[p.pdf_id] || 0), 0),
    exam: st.metrics?.exams?.[c.id],
  };
}

/* ---------------------------------------------------------------- home: course canvas */

function renderHome() {
  const st = S.state;
  if (!st || S.view !== "home") return;

  const cards = st.libCourses.map((c) => {
    const s = courseStats(c, st);
    const color = SUBJ[c.ci % 4];
    return `<div class="course-tile-card" onclick="openCourse(${c.id})">
      <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px">
        <span class="course-tile" style="background:${color}; width:26px; height:26px; border-radius:8px"></span>
        <span style="flex:1; min-width:0; font-size:15px; font-weight:700; letter-spacing:-.2px">${esc(c.name)}</span>
        ${s.due ? `<span class="deck-due">${s.due} due</span>` : ""}
      </div>
      <div style="display:flex; align-items:center; gap:10px; margin-bottom:12px">
        <div class="bar-track" style="flex:1"><div class="bar-fill" style="width:${s.completion}%; background:${retColor(s.completion)}"></div></div>
        <span class="mono" style="font-size:13px; font-weight:600">${s.completion.toFixed(0)}%</span>
      </div>
      <div style="font-size:11.5px; color:#5C616E; line-height:1.7">
        ${c.pdfCount} document${c.pdfCount === 1 ? "" : "s"} · ${s.topicsTotal} topics · ${s.cards} cards<br>
        ${s.covered} covered · ${s.started} in progress · ${fmtMin(s.readMin)} read
      </div>
      ${s.exam ? `<div class="exam-chip" style="margin-top:12px">🎓 ${s.exam.days_left}d to exam${s.exam.today != null ? ` · ${s.exam.today}% if you stop now` : ""}</div>` : ""}
    </div>`;
  }).join("");

  const r = S.recap;
  const recap = r ? `<div class="card" style="border-color:#9BD4BE; margin-bottom:14px">
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px">
      <span class="mono-label" style="color:#00794F; font-weight:600">LAST FOCUS BLOCK</span>
      <button class="icon-btn" title="Dismiss" onclick="dismissRecap()">✕</button>
    </div>
    <div class="recap-grid">
      <div><div class="recap-num">${r.mins}m</div><div class="recap-lbl">focused</div></div>
      <div><div class="recap-num">${r.cards}</div><div class="recap-lbl">cards</div></div>
      <div><div class="recap-num" style="color:#00794F">${r.acc == null ? "—" : r.acc + "%"}</div><div class="recap-lbl">recall</div></div>
    </div>
    <div style="font-size:11.5px; color:#5C616E">${r.ext} intervals extended · <span style="color:${LOW}">${r.reset} reset to 1d</span></div>
  </div>` : "";

  const nudge = new Date().getHours() >= 18 && st.dueTotal > 0 && !S.focusStart
    ? `<div class="nudge" style="margin-bottom:14px">🌙 ${st.dueTotal} cards due — a short review before sleep helps consolidation. Even 10 minutes counts.</div>` : "";

  $("homeInner").innerHTML = `
    <div class="section-head"><span class="mono-label">COURSES</span><div class="rule"></div>
      ${st.dueTotal ? `<button class="conf-btn" onclick="startReviewSession({})" title="Review everything due, capped at your daily budget">▶ ${st.dueTotal} due</button>` : ""}
      ${visionToggle()}
      <button class="conf-btn" onclick="pickPdfs()" title="Upload PDFs — they segment into topics and save automatically">＋ Add PDFs</button></div>
    ${S.ingesting ? ingestBanner() : ""}
    ${recap}${nudge}
    <div class="course-canvas">${cards || `<div class="card" style="font-size:12.5px; color:#8A8F9C">No courses yet — hit ＋ Add PDFs and Flashbang will read, split and file them for you.</div>`}</div>`;
}

/* opt-in for diagram-heavy decks: read every page as an image instead of
   only the pages whose text came back sparse */
function visionToggle() {
  return `<label class="vision-toggle" title="Default reads only pages with almost no text. Turn this on for slide decks whose content is in the diagrams — a vision model reads every page (~$0.11 per 8 pages).">
    <input type="checkbox" ${S.forceVision ? "checked" : ""} onchange="setForceVision(this.checked)">
    read images on every page</label>`;
}

window.setForceVision = (on) => { S.forceVision = !!on; render(); };

function ingestBanner() {
  return `<div class="card" style="padding:12px 16px; margin-bottom:12px; display:flex; align-items:center; gap:10px">
    <span style="width:8px; height:8px; border-radius:50%; background:#E69F00; animation:fbPulse 1.6s infinite"></span>
    <span style="font-size:12.5px">Ingesting ${S.ingesting.done + 1} of ${S.ingesting.total}: <b>${esc(S.ingesting.current)}</b> — reading, splitting into topics, saving (~30–90s per file)</span>
  </div>`;
}

window.openCourse = (courseId) => {
  S.courseId = courseId;
  S.view = "course";
  S.docOpen = new Set();
  S.readSel = new Set();
  S.editSplit = null;
  render();
};

/* ---------------------------------------------------------------- one course */

function renderCoursePage() {
  const st = S.state;
  if (!st || S.view !== "course") return;
  const c = st.libCourses.find((x) => x.id === S.courseId);
  if (!c) { S.view = "home"; render(); return; }
  const s = courseStats(c, st);
  const rd = st.reading || { by_pdf: [], notes_by_pdf: {} };
  const courseInfo = st.courses.find((x) => x.id === c.id);
  const docs = [...c.pdfs].sort((a, b) => a.pdf_id - b.pdf_id);   // upload order
  if (!S.docOpen.size && docs.length) S.docOpen.add(docs[0].pdf_id);

  // ---- left: documents → topics
  const docBlocks = docs.map((p) => {
    const open = S.docOpen.has(p.pdf_id);
    const readMin = rd.by_pdf?.find((e) => e.pdf_id === p.pdf_id)?.minutes || 0;
    const notes = rd.notes_by_pdf?.[p.pdf_id] || 0;
    const editing = S.editSplit === p.pdf_id;
    const sel = [...S.readSel].map((id) => p.topics.find((t) => t.id === id)).filter(Boolean);

    let body = "";
    if (open && editing) {
      const inp = `border:1px solid #E3E3DE; border-radius:7px; padding:5px 7px; font-family:'IBM Plex Sans',sans-serif; font-size:12px`;
      body = `<div style="font-size:11px; color:#8A8F9C; padding:4px 2px 8px">Your split, your rules — ranges may overlap or leave gaps. Splitting keeps existing cards with the original topic.</div>`
        + p.topics.map((t) => {
          const [ps, pe] = t.pages.split("-").map(Number);
          return `<div class="topic-row-edit ts-row" data-id="${t.id}">
            <input class="ts-title" style="${inp}; flex:1; min-width:110px" value="${esc(t.title)}">
            <input class="ts-start" type="number" min="1" value="${ps}" style="${inp}; width:52px">
            <span style="color:#8A8F9C">–</span>
            <input class="ts-end" type="number" min="1" value="${pe}" style="${inp}; width:52px">
            <select class="ts-kind sort-select" style="font-size:11px">
              <option value="content" ${t.kind !== "general" ? "selected" : ""}>content</option>
              <option value="general" ${t.kind === "general" ? "selected" : ""}>general</option>
            </select>
            <button class="conf-btn" onclick="saveTopicEdit(${t.id}, this)">Save</button>
            <button class="conf-btn" title="Split into two at a page" onclick="splitTopicAsk(${t.id}, ${ps}, ${pe})">Split…</button>
            <button class="pdf-del" title="Delete this topic and its ${t.cards_total} card${t.cards_total === 1 ? "" : "s"}"
              onclick="deleteTopicAsk(${t.id}, '${encT(t.title)}', ${t.cards_total})">✕</button>
          </div>`;
        }).join("");
    } else if (open) {
      body = (sel.length ? `<a class="btn-block" style="margin:2px 0 8px; text-align:center; text-decoration:none; box-sizing:border-box"
          href="/api/pdf/${p.pdf_id}/slice?ranges=${sel.map((t) => t.pages).join(",")}" download>
          ⬇ ${sel.length} topic${sel.length === 1 ? "" : "s"} as one PDF</a>` : "")
        + p.topics.map((t) => `
        <div class="topic-row2" onclick="openTopic(${p.pdf_id}, ${t.pages.split("-")[0]}, ${t.pages.split("-")[1]}, '${encT(t.title)}')"
             title="Open p.${t.pages} in the reader">
          <input type="checkbox" class="rt-check" title="Tick topics, then download them together as one PDF"
            onclick="event.stopPropagation(); toggleReadSel(${t.id})" ${S.readSel.has(t.id) ? "checked" : ""}>
          <span class="ret-dot" style="background:${t.kind === "general" ? "#C9CCD4" : retColor(t.mastery_pct)}"></span>
          <span style="flex:1; min-width:0">
            <span style="display:block; font-size:12.5px; font-weight:600; line-height:1.35">${esc(t.title)}</span>
            <span style="display:block; font-size:10.5px; color:#8A8F9C; margin-top:2px">p.${t.pages} · ~${fmtMin(t.est_minutes)}${t.kind === "general" ? "" : ` · ${t.mastery_pct.toFixed(0)}%`}</span>
          </span>
          ${t.cards_due ? `<span class="due-tag">${t.cards_due} due</span>` : ""}
          ${t.kind === "general" ? `<span class="info-tag">info</span>`
            : t.cards_total ? `<span class="mono" style="font-size:10px; color:#8A8F9C; flex:none">${t.cards_total} cards</span>`
            : `<button class="conf-btn" style="flex:none" title="Generate flashcards for this topic (~$0.05, ~30s)"
                onclick="event.stopPropagation(); generateCards(${t.id}, this)">⚡ Cards</button>`}
        </div>`).join("");
    }

    return `<div class="doc-block">
      <div class="doc-head" onclick="toggleDoc(${p.pdf_id})">
        <span class="deck-caret">${open ? "▾" : "▸"}</span>
        <span style="flex:1; min-width:0">
          <span style="display:block; font-size:12.5px; font-weight:600; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${esc(p.filename)}</span>
          <span style="display:block; font-size:10.5px; color:#8A8F9C; margin-top:2px">${p.total_pages}p · ${p.topics.length} topics · ${fmtMin(readMin)} read${notes ? ` · ${notes} note${notes === 1 ? "" : "s"}` : ""}</span>
        </span>
        ${p.status === "pending" ? `<span class="badge" style="background:rgba(213,94,0,.12); color:#D55E00">Ingest incomplete</span>` : ""}
        ${p.due ? `<span class="deck-due">${p.due} due</span>` : ""}
        ${open ? `<button class="conf-btn ${editing ? "picked" : ""}" title="Rename topics, fix page ranges, split or delete"
          onclick="event.stopPropagation(); toggleEditSplit(${p.pdf_id})">✎ Split</button>` : ""}
        <button class="pdf-del" title="Delete this document and everything under it"
          onclick="event.stopPropagation(); deletePdf(${p.pdf_id}, '${encT(p.filename)}')">✕</button>
      </div>
      ${body}
    </div>`;
  }).join("");

  // ---- right: this course's numbers
  const metrics = `
    <div class="card" style="padding:18px 20px">
      <div class="mono-label" style="margin-bottom:10px">COMPLETION</div>
      <div class="stat-num" style="color:${retColor(s.completion)}">${s.completion.toFixed(0)}%</div>
      <div class="bar-track" style="margin:10px 0 8px"><div class="bar-fill" style="width:${s.completion}%; background:${retColor(s.completion)}"></div></div>
      <div class="stat-sub">${s.covered} of ${s.topicsTotal} topics covered · ${s.started} in progress</div>
      ${evidence("Completion is retrieval-weighted: a topic only counts once its cards are actually recalled, not once it's been read.")}
    </div>
    <div class="card" style="padding:18px 20px">
      <div class="mono-label" style="margin-bottom:10px">DUE NOW</div>
      <div class="stat-num" style="color:${s.due ? LOW : "#00794F"}">${s.due}</div>
      <div class="stat-sub">${s.cards} cards in this course</div>
      <button class="btn-block" style="margin-top:12px" ${s.due ? "" : "disabled"}
        onclick="startReviewSession({ course_id: ${c.id} })">▶ Review this course</button>
    </div>
    <div class="card" style="padding:18px 20px">
      <div class="mono-label" style="margin-bottom:10px">TIME INVESTED</div>
      <div style="display:flex; gap:18px">
        <div><div class="stat-num" style="font-size:20px">${c.timeSpent}</div><div class="stat-sub">flashcards</div></div>
        <div><div class="stat-num" style="font-size:20px">${fmtMin(s.readMin)}</div><div class="stat-sub">reading</div></div>
        <div><div class="stat-num" style="font-size:20px">${s.notes}</div><div class="stat-sub">notes</div></div>
      </div>
    </div>
    ${(() => {
      // reading analytics for THIS course: where the reading time went, and
      // which documents are still untouched
      const perDoc = docs.map((p) => ({
        name: p.filename.replace(/\.pdf$/i, ""),
        min: rd.by_pdf?.find((e) => e.pdf_id === p.pdf_id)?.minutes || 0,
        notes: rd.notes_by_pdf?.[p.pdf_id] || 0,
        last: rd.by_pdf?.find((e) => e.pdf_id === p.pdf_id)?.last_read,
      })).sort((a, b) => b.min - a.min);
      const read = perDoc.filter((d) => d.min > 0);
      const maxMin = Math.max(1, ...perDoc.map((d) => d.min));
      const lastRead = read.map((d) => d.last).filter(Boolean).sort().pop();
      return `<div class="card" style="padding:18px 20px">
        <div class="mono-label" style="margin-bottom:12px">READING · THIS COURSE</div>
        ${read.length ? `
          <div style="display:flex; flex-direction:column; gap:8px; margin-bottom:12px">
            ${read.slice(0, 6).map((d) => `
              <div class="fn-row" title="${esc(d.name)}${d.notes ? ` · ${d.notes} notes` : ""}">
                <span class="fn-label" style="width:96px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${esc(d.name)}</span>
                <div class="fn-track"><div class="fn-fill" style="width:${Math.max(3, d.min / maxMin * 100)}%; background:#0072B2"></div></div>
                <span class="fn-n">${fmtMin(d.min)}</span>
              </div>`).join("")}
          </div>
          <div style="font-size:11.5px; color:#5C616E">${read.length} of ${docs.length} documents opened${lastRead ? ` · last read ${new Date(lastRead).toLocaleDateString(undefined, { day: "numeric", month: "short" })}` : ""}</div>`
        : `<div style="font-size:12px; color:#8A8F9C; line-height:1.6">No reading blocks logged for this course yet. Open a topic and start a block in the reader's sidebar.</div>`}
        ${evidence("Reading time is tracked apart from recall on purpose: hours in the PDF never move mastery — only retrieval does.")}
      </div>`;
    })()}
    <div class="card" style="padding:18px 20px">
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px">
        <span class="mono-label">EXAM</span>
        <input type="date" class="exam-input" value="${courseInfo?.exam_date || ""}"
          title="Exam date — drives the readiness projection" onchange="setExam(${c.id}, this.value)">
      </div>
      ${s.exam && s.exam.today != null ? `
        <div class="stat-num" style="color:${s.exam.onPlan >= 70 ? "#00794F" : LOW}">${s.exam.onPlan}%</div>
        <div class="stat-sub">projected recall on exam day if you keep to the schedule · ${s.exam.today}% if you stop today · ${s.exam.days_left} days left</div>`
      : s.exam ? `<div class="stat-sub">${s.exam.days_left} days left — generate some cards to get a readiness projection.</div>`
      : `<div class="stat-sub">Set a date and you'll get a projected exam-day recall.</div>`}
    </div>`;

  $("courseInner").innerHTML = `
    <div class="crumbs">
      <button class="crumb" onclick="goHome()">Courses</button>
      <span class="crumb-sep">›</span>
      <span class="crumb on">${esc(c.name)}</span>
      <span style="flex:1"></span>
      ${visionToggle()}
      <button class="conf-btn" onclick="pickPdfs()" title="Upload PDFs straight into ${esc(c.name)}">＋ Add PDFs</button>
    </div>
    ${S.ingesting ? ingestBanner() : ""}
    <div class="course-grid">
      <div style="display:flex; flex-direction:column; gap:8px">
        <div class="mono-label" style="padding:2px">DOCUMENTS &amp; TOPICS · CLICK A TOPIC TO READ</div>
        ${docBlocks || `<div class="card" style="font-size:12.5px; color:#8A8F9C">Nothing in this course yet.</div>`}
      </div>
      <div style="display:flex; flex-direction:column; gap:12px">${metrics}</div>
    </div>`;
}

/* ---- assistant bubble: a scoped agent, only when you open it ---- */
window.toggleAsst = () => {
  const open = $("asstPanel").style.display === "none";
  $("asstPanel").style.display = open ? "flex" : "none";
  $("asstBubble").classList.toggle("on", open);
  if (open) {
    if (!$("asstScroll").children.length) {
      $("asstScroll").insertAdjacentHTML("beforeend",
        `<div class="asst-msg-bot">Ask about anything in your notes, or tell me to tidy the library —
         rename a topic, move a card, set an exam date, show your stats.<br><br>
         <span style="color:#8A8F9C">Reviews, ingesting PDFs and generating cards are buttons now — I'll point you at them.</span></div>`);
    }
    $("asstInput").focus();
  }
};

/* ---- name autocomplete for the assistant box ----
   Everything you might name — courses, documents, topics — is already in the
   state payload, so suggesting them costs nothing and needs no round trip.
   Deliberately NOT wired into the review answer box: completing an answer
   mid-recall would hand you the card and make the grade meaningless. */
function asstNames() {
  const st = S.state;
  if (!st) return [];
  const out = [], seen = new Set();
  const add = (label, kind) => {
    const key = `${kind}:${label}`;
    if (label && !seen.has(key)) { seen.add(key); out.push({ label, kind }); }
  };
  st.libCourses.forEach((c) => {
    add(c.name, "course");
    c.pdfs.forEach((p) => {
      add(p.filename.replace(/\.pdf$/i, ""), "doc");
      p.topics.forEach((t) => add(t.title, "topic"));
    });
  });
  return out;
}

/* the word being typed: everything after the last space, or after an opening
   quote so multi-word names can be completed inside quotes */
function asstFragment(value) {
  const upto = value.slice(0, $("asstInput").selectionStart ?? value.length);
  const m = upto.match(/(?:^|\s)"([^"]*)$/) || upto.match(/(\S+)$/);
  return m ? { text: m[1], start: upto.length - m[1].length } : null;
}

function renderAsstSuggest() {
  const box = $("asstSuggest");
  if (!S.asstSuggest.length) { box.style.display = "none"; return; }
  box.innerHTML = S.asstSuggest.map((s, i) => `
    <div class="sg-item ${i === S.asstSuggestIdx ? "on" : ""}" onmousedown="acceptAsstSuggest(${i})">
      <span class="sg-kind">${s.kind}</span>
      <span style="flex:1">${esc(s.label)}</span>
    </div>`).join("") + `<div class="sg-hint">tab to accept · ↑↓ to pick · esc to dismiss</div>`;
  box.style.display = "block";
}

function updateAsstSuggest() {
  const input = $("asstInput");
  const frag = asstFragment(input.value);
  const q = (frag?.text || "").toLowerCase();
  S.asstSuggest = q.length >= 2
    ? asstNames().filter((n) => n.label.toLowerCase().includes(q)).slice(0, 6) : [];
  S.asstSuggestIdx = S.asstSuggest.length ? 0 : -1;
  renderAsstSuggest();
}

window.acceptAsstSuggest = (i) => {
  const pick = S.asstSuggest[i];
  const input = $("asstInput");
  const frag = asstFragment(input.value);
  if (!pick || !frag) return;
  const needsQuotes = /\s/.test(pick.label);
  const before = input.value.slice(0, frag.start);
  const after = input.value.slice(frag.start + frag.text.length);
  // if we're completing inside an opening quote, close it; else add both
  const openQuote = before.endsWith('"');
  const inserted = openQuote ? `${pick.label}"` : (needsQuotes ? `"${pick.label}"` : pick.label);
  input.value = before + inserted + after;
  const caret = (before + inserted).length;
  input.setSelectionRange(caret, caret);
  S.asstSuggest = [];
  S.asstSuggestIdx = -1;
  renderAsstSuggest();
  input.focus();
};

function dismissAsstSuggest() {
  S.asstSuggest = [];
  S.asstSuggestIdx = -1;
  renderAsstSuggest();
}

async function sendAsst(text) {
  text = (text || "").trim();
  if (!text || S.asstBusy) return;
  const scroll = $("asstScroll");
  S.asstBusy = true;
  $("asstInput").value = "";
  scroll.insertAdjacentHTML("beforeend", `<div class="asst-msg-user">${esc(text)}</div>`);
  scroll.insertAdjacentHTML("beforeend", `<div class="asst-msg-bot" id="asstThinking"><span class="status-line working">Working…</span></div>`);
  scroll.scrollTop = scroll.scrollHeight;
  const res = await fetch("/api/assistant", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ message: text }) })
    .then((r) => r.ok ? r.json() : null).catch(() => null);
  document.getElementById("asstThinking")?.remove();
  scroll.insertAdjacentHTML("beforeend",
    `<div class="asst-msg-bot">${md(res?.reply || "Couldn't reach the assistant.")}</div>`);
  scroll.scrollTop = scroll.scrollHeight;
  S.asstBusy = false;
  fetchState();   // it may have changed the library
}

window.goHome = () => { S.view = "home"; S.courseId = null; render(); };
window.toggleDoc = (pdfId) => {
  S.docOpen.has(pdfId) ? S.docOpen.delete(pdfId) : S.docOpen.add(pdfId);
  if (S.editSplit === pdfId) S.editSplit = null;
  renderCoursePage();
};
window.toggleReadSel = (topicId) => {
  S.readSel.has(topicId) ? S.readSel.delete(topicId) : S.readSel.add(topicId);
  renderCoursePage();
};
window.toggleEditSplit = (pdfId) => {
  S.editSplit = S.editSplit === pdfId ? null : pdfId;
  renderCoursePage();
};

window.generateCards = async (topicId, btn) => {
  btn.disabled = true;
  btn.textContent = "Writing…";
  const res = await fetch(`/api/topics/${topicId}/generate_cards`, { method: "POST" })
    .then((r) => r.ok ? r.json() : null).catch(() => null);
  if (!res) {
    btn.textContent = "Failed — retry";
    btn.disabled = false;
    return;
  }
  btn.textContent = `+${res.inserted} ✓`;
  fetchState();   // topic row now shows its card count; prune on the Cards screen
};

window.saveTopicEdit = async (topicId, btn) => {
  const row = btn.closest(".ts-row");
  btn.textContent = "Saving…";
  const res = await fetch(`/api/topics/${topicId}`, { method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: row.querySelector(".ts-title").value,
      page_start: +row.querySelector(".ts-start").value,
      page_end: +row.querySelector(".ts-end").value,
      kind: row.querySelector(".ts-kind").value,
    }) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.error || "Save failed");
    btn.textContent = "Save";
    return;
  }
  fetchState();
};

window.deleteTopicAsk = async (topicId, encTitle, cardCount) => {
  const title = decodeURIComponent(encTitle);
  if (!confirm(`Delete "${title}"${cardCount ? ` and its ${cardCount} card${cardCount === 1 ? "" : "s"}` : ""}?\nNotes and blackouts on its pages stay with the document. This cannot be undone.`)) return;
  const res = await fetch(`/api/topics/${topicId}`, { method: "DELETE" });
  if (!res.ok) { alert("Delete failed"); return; }
  fetchState();
};

window.splitTopicAsk = async (topicId, pageStart, pageEnd) => {
  const at = +prompt(`Split at which page? The NEW topic starts there (pick ${pageStart + 1}–${pageEnd}).`);
  if (!at) return;
  const newTitle = prompt("Title for the new topic (leave blank for auto):") || "";
  const res = await fetch(`/api/topics/${topicId}/split`, { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ at_page: at, new_title: newTitle }) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    alert(err.error || "Split failed");
    return;
  }
  fetchState();
};

/* ---------------------------------------------------------------- cards screen */

async function loadCards() {
  const f = S.cardFilter;
  const params = new URLSearchParams();
  if (f.topic_id) params.set("topic_id", f.topic_id);
  else if (f.pdf_id) params.set("pdf_id", f.pdf_id);
  else if (f.course_id) params.set("course_id", f.course_id);
  const [cards, topics] = await Promise.all([
    fetch(`/api/cards?${params}`).then((r) => r.json()),
    fetch(`/api/topics?${f.course_id ? `course_id=${f.course_id}` : ""}`).then((r) => r.json()),
  ]);
  S.cards = cards;
  S.cardTopics = topics;
  renderCardsScreen();
}

function renderCardsScreen() {
  const st = S.state;
  if (!st) return;
  const f = S.cardFilter;
  const inner = $("cardsInner");

  const courseOpts = [`<option value="">All courses</option>`,
    ...st.courses.map((c) => `<option value="${c.id}" ${f.course_id === c.id ? "selected" : ""}>${esc(c.name)}</option>`)];
  const coursePdfs = st.libCourses.filter((c) => !f.course_id || c.id === f.course_id)
    .flatMap((c) => c.pdfs);
  const pdfOpts = [`<option value="">All documents</option>`,
    ...coursePdfs.map((p) => `<option value="${p.pdf_id}" ${f.pdf_id === p.pdf_id ? "selected" : ""}>${esc(p.filename)}</option>`)];
  // topics grouped under a bold header per source pdf (optgroup renders bold)
  const pdfName = {};
  st.libCourses.forEach((c) => c.pdfs.forEach((p) => { pdfName[p.pdf_id] = p.filename; }));
  const groupedTopicOptions = (topics, selectedId) => {
    const groups = new Map();
    topics.forEach((t) => {
      if (!groups.has(t.pdf_id)) groups.set(t.pdf_id, []);
      groups.get(t.pdf_id).push(t);
    });
    return [...groups.entries()].map(([pid, list]) => `
      <optgroup label="${esc(pdfName[pid] || `document ${pid}`)}">
        ${list.map((t) => `<option value="${t.id}" ${selectedId === t.id ? "selected" : ""}>${esc(t.title)}</option>`).join("")}
      </optgroup>`).join("");
  };

  const pdfTopics = S.cardTopics.filter((t) => !f.pdf_id || t.pdf_id === f.pdf_id);
  const topicOpts = [`<option value="">All topics</option>`,
    groupedTopicOptions(pdfTopics, f.topic_id)];

  const rows = S.cards.map((c) => {
    const due = (c.next_review || "").slice(0, 10);
    const moveOpts = groupedTopicOptions(S.cardTopics, c.topic_id);
    return `
    <div class="cardedit" data-id="${c.id}">
      <div class="cardedit-head">
        <span class="mono" style="font-size:10px; color:#8A8F9C">#${c.id} · ${esc(c.course_name)}</span>
        <select class="sort-select ce-topic" title="Move to topic">${moveOpts}</select>
        <span class="mono" style="font-size:10px; color:#8A8F9C">interval ${c.interval_days}d · due ${due}</span>
        <span style="flex:1"></span>
        <button class="ce-save conf-btn" disabled>Save</button>
        <button class="ce-del icon-btn" title="Delete card">🗑</button>
      </div>
      <textarea class="ce-q" rows="2">${esc(c.question)}</textarea>
      <textarea class="ce-a" rows="3">${esc(c.answer)}</textarea>
    </div>`;
  }).join("");

  // new-card form: topic select (grouped by pdf, defaults to the active filter)
  const newCardBox = S.showNewCard ? `
    <div class="cardedit" id="newCard" style="border-color:#0072B2">
      <div class="cardedit-head">
        <span class="mono" style="font-size:10px; letter-spacing:1.4px; color:#005A8E; font-weight:600">NEW CARD</span>
        <select class="sort-select" id="ncTopic">${groupedTopicOptions(S.cardTopics, f.topic_id)}</select>
        <span style="flex:1"></span>
        <button class="conf-btn" id="ncCreate" style="border-color:#1C1E26; background:#1C1E26; color:#fff">Create</button>
        <button class="icon-btn" id="ncCancel" title="Cancel">✕</button>
      </div>
      <textarea class="ce-q" id="ncQ" rows="2" placeholder="Question…"></textarea>
      <textarea class="ce-a" id="ncA" rows="3" placeholder="Answer…"></textarea>
      <div style="display:flex; align-items:center; gap:10px">
        <span style="font-size:10.5px; color:#8A8F9C">Files under the chosen topic — its PDF and course link automatically. First review: tomorrow.</span>
        <span id="ncMsg" style="font-size:10.5px; color:#D55E00; font-weight:600"></span>
      </div>
    </div>` : "";

  // paste-import panel (NotebookLM output, Anki exports, hand lists)
  const ip = S.importPreview;
  const previewRows = ip && ip.cards.length ? ip.cards.slice(0, 8).map((c, i) => `
    <div style="display:flex; gap:8px; font-size:11.5px; line-height:1.5; padding:6px 0; border-top:1px dashed #ECECE8">
      <span class="mono" style="color:#8A8F9C; flex:none">${i + 1}.</span>
      <span style="flex:1"><b>${esc(c.question)}</b><br>${esc(c.answer)}</span>
    </div>`).join("") + (ip.cards.length > 8 ? `<div style="font-size:10.5px; color:#8A8F9C; padding-top:6px">…and ${ip.cards.length - 8} more</div>` : "") : "";
  const importBox = S.showImport ? `
    <div class="cardedit" id="importCard" style="border-color:#009E73">
      <div class="cardedit-head">
        <span class="mono" style="font-size:10px; letter-spacing:1.4px; color:#00794F; font-weight:600">IMPORT CARDS</span>
        <select class="sort-select" id="imTopic">${groupedTopicOptions(S.cardTopics, f.topic_id)}</select>
        <span style="flex:1"></span>
        <button class="conf-btn" id="imPreview">Preview</button>
        <button class="conf-btn" id="imInsert" ${ip && ip.cards.length ? `style="border-color:#1C1E26; background:#1C1E26; color:#fff"` : "disabled"}>Add ${ip ? ip.cards.length : 0} cards</button>
        <button class="icon-btn" id="imCancel" title="Close">✕</button>
      </div>
      <textarea class="ce-a" id="imText" rows="6" placeholder="Paste flashcards here — NotebookLM output, Q:/A: pairs, or one card per line with a TAB, ' :: ', ';;' or '|' between question and answer.">${esc(S.importText)}</textarea>
      <div style="font-size:10.5px; color:${ip && ip.source === "ai" ? "#8A6100" : "#8A8F9C"}" id="imMsg">${
        ip ? (ip.cards.length
          ? `${ip.cards.length} card${ip.cards.length === 1 ? "" : "s"} ${ip.source === "ai" ? "AI-parsed — read them before adding" : "parsed"} · they file under the chosen topic, first review tomorrow`
          : "Nothing parsed — check the format or add Q:/A: markers.")
        : "Preview parses without saving. Clean formats parse instantly; free-form text falls back to one cheap AI call."}</div>
      ${previewRows}
    </div>` : "";

  inner.innerHTML = `
    <div class="section-head"><span class="mono-label">CARDS</span><div class="rule"></div>
      <span class="mono" style="font-size:10.5px; color:#8A8F9C">${S.cards.length} shown</span>
      <button id="importBtn" class="conf-btn">⇪ Import</button>
      <button id="newCardBtn" class="conf-btn">+ New card</button></div>
    <div style="display:flex; gap:10px; flex-wrap:wrap">
      <select id="cfCourse" class="sort-select">${courseOpts.join("")}</select>
      <select id="cfPdf" class="sort-select">${pdfOpts.join("")}</select>
      <select id="cfTopic" class="sort-select">${topicOpts.join("")}</select>
    </div>
    ${importBox}
    ${newCardBox}
    ${rows || `<div class="card" style="color:#8A8F9C; font-size:12.5px">No cards match this filter — generate some from the Study chat ("make cards for &lt;topic&gt;"), or use + New card.</div>`}`;

  $("newCardBtn").onclick = () => { S.showNewCard = !S.showNewCard; renderCardsScreen(); };
  $("importBtn").onclick = () => { S.showImport = !S.showImport; renderCardsScreen(); };
  if (S.showImport) {
    $("imText").oninput = (e) => { S.importText = e.target.value; S.importPreview = null; };
    $("imCancel").onclick = () => { S.showImport = false; S.importPreview = null; renderCardsScreen(); };
    $("imPreview").onclick = async () => {
      const topic_id = +$("imTopic").value;
      S.importText = $("imText").value;
      if (!topic_id || !S.importText.trim()) return;
      $("imPreview").textContent = "Parsing…";
      const res = await fetch("/api/cards/import", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic_id, text: S.importText, dry_run: true }) });
      S.importPreview = res.ok ? await res.json() : { cards: [], source: "parsed" };
      renderCardsScreen();
    };
    $("imInsert").onclick = async () => {
      const topic_id = +$("imTopic").value;
      if (!topic_id || !S.importPreview?.cards.length) return;
      $("imInsert").textContent = "Adding…";
      const res = await fetch("/api/cards/import", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic_id, cards: S.importPreview.cards }) });
      if (res.ok) {
        S.showImport = false;
        S.importText = "";
        S.importPreview = null;
        loadCards();
        fetchState();
      } else { $("imInsert").textContent = "Failed — retry"; }
    };
  }
  if (S.showNewCard) {
    $("ncCancel").onclick = () => { S.showNewCard = false; renderCardsScreen(); };
    $("ncCreate").onclick = async () => {
      const topic_id = +$("ncTopic").value;
      const question = $("ncQ").value.trim();
      const answer = $("ncA").value.trim();
      const msg = $("ncMsg");
      if (!topic_id || !question || !answer) {
        msg.textContent = "Pick a topic and fill in both fields.";
        return;
      }
      msg.textContent = "";
      $("ncCreate").textContent = "Creating…";
      const res = await fetch("/api/cards", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ topic_id, question, answer }) });
      if (res.ok) { S.showNewCard = false; loadCards(); fetchState(); }
      else {
        $("ncCreate").textContent = "Create";
        msg.textContent = "Create failed — try again.";
      }
    };
  }

  $("cfCourse").onchange = (e) => {
    S.cardFilter = { course_id: e.target.value ? +e.target.value : null, pdf_id: null, topic_id: null };
    loadCards();
  };
  $("cfPdf").onchange = (e) => {
    S.cardFilter.pdf_id = e.target.value ? +e.target.value : null;
    S.cardFilter.topic_id = null;
    loadCards();
  };
  $("cfTopic").onchange = (e) => {
    S.cardFilter.topic_id = e.target.value ? +e.target.value : null;
    loadCards();
  };

  inner.querySelectorAll(".cardedit").forEach((box) => {
    const id = +box.dataset.id;
    const original = S.cards.find((c) => c.id === id);
    const saveBtn = box.querySelector(".ce-save");
    const changed = () =>
      box.querySelector(".ce-q").value !== original.question ||
      box.querySelector(".ce-a").value !== original.answer ||
      +box.querySelector(".ce-topic").value !== original.topic_id;
    box.addEventListener("input", () => { saveBtn.disabled = !changed(); });
    box.querySelector(".ce-topic").addEventListener("change", () => { saveBtn.disabled = !changed(); });

    saveBtn.onclick = async () => {
      saveBtn.textContent = "Saving…";
      await fetch(`/api/cards/${id}`, { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          question: box.querySelector(".ce-q").value,
          answer: box.querySelector(".ce-a").value,
          topic_id: +box.querySelector(".ce-topic").value,
        }) });
      saveBtn.textContent = "Saved ✓";
      setTimeout(() => loadCards(), 500);
    };
    box.querySelector(".ce-del").onclick = async () => {
      if (!confirm("Delete this card permanently?")) return;
      await fetch(`/api/cards/${id}`, { method: "DELETE" });
      loadCards();
    };
  });
}

/* ---------------------------------------------------------------- shell */

function render() {
  const st = S.state;
  if (!st) return;
  $("dueTotal").textContent = st.dueTotal;
  $("doNext").title = st.best
    ? `Weakest due topic: ${st.best.title} (${st.best.pct.toFixed(0)}% retention)` : "All caught up";
  if (st.currentCourse) {
    $("agentDot").style.background = SUBJ[st.currentCourse.ci % 4];
    $("sessionLabel").textContent =
      `· ${st.currentCourse.name} · ${st.current.filename.replace(/\.pdf$/i, "")}`;
  }
  $("tabHome").classList.toggle("on", S.view === "home" || S.view === "course");
  $("tabStudy").classList.toggle("on", S.view === "study");
  $("tabProgress").classList.toggle("on", S.view === "progress");
  $("tabCards").classList.toggle("on", S.view === "cards");
  $("homeScreen").style.display = S.view === "home" ? "block" : "none";
  $("courseScreen").style.display = S.view === "course" ? "block" : "none";
  $("studyScreen").style.display = S.view === "study" ? "flex" : "none";
  $("progressScreen").style.display = S.view === "progress" ? "block" : "none";
  $("cardsScreen").style.display = S.view === "cards" ? "block" : "none";
  // review screen: decks until a session starts, then the chat
  $("reviewHome").style.display = S.reviewView === "decks" ? "flex" : "none";
  $("chatPane").style.display = S.reviewView === "chat" ? "flex" : "none";
  renderHome();
  renderCoursePage();
  renderReviewHome();
  renderConfRow();

  renderProgress();
  if (S.view === "cards") renderCardsScreen();
}

/* ---- actions (referenced from rendered HTML) ---- */
window.setExam = async (courseId, date) => {
  await fetch("/api/exam", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ course_id: courseId, date: date || null }) });
  fetchState();
};
window.toggleNav = () => {
  S.navOpen = !S.navOpen;
  localStorage.setItem("fbNavOpen", S.navOpen ? "1" : "0");
  $("sideNav").classList.toggle("closed", !S.navOpen);
  $("navCollapse").title = S.navOpen ? "Collapse sidebar" : "Expand sidebar";
};
window.pickLen = (m) => { S.sessionLen = m; renderReadSide(); };
window.dismissRecap = () => { S.recap = null; renderProgress(); };

window.setBudget = async (minutes) => {
  await fetch("/api/settings", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ daily_minutes: minutes }) });
  fetchState();
};

window.spreadBacklog = async () => {
  const b = S.state?.budget;
  if (!b?.daily_minutes) return;
  const fit = Math.max(1, Math.floor(b.daily_minutes * 60 / b.sec_per_card));
  if (!confirm(`Keep the ${fit} most overdue cards due today and push the rest onto the coming days (${b.daily_minutes} min/day)?\nScheduling state is untouched — only the due dates move.`)) return;
  const res = await fetch("/api/backlog/spread", { method: "POST" });
  if (res.ok) fetchState();
};
window.openDoc = (pdfId) => { S.pdfId = pdfId; S.view = "study"; fetchState(); };

window.deletePdf = async (pdfId, encName) => {
  const name = decodeURIComponent(encName);
  if (!confirm(`Delete "${name}"?\nIts topics, cards, and scheduled reviews are removed. This cannot be undone.`)) return;
  const res = await fetch(`/api/pdfs/${pdfId}`, { method: "DELETE" });
  if (!res.ok) {
    alert(`Delete failed (${res.status}) — check the server log.`);
    return;
  }
  if (S.pdfId === pdfId) S.pdfId = null;   // let /api/state pick a new current doc
  fetchState();
};
window.startReview = () => {
  const cur = S.state?.current;
  startReviewSession(cur ? { pdf_id: cur.pdf_id } : {});
};

window.toggleFocus = async (kind) => {
  if (S.focusStart) {
    const mins = Math.max(1, Math.round((Date.now() - S.focusStart) / 60000));
    S.focusStart = null;
    clearInterval(S._tick);
    $("focusChip").style.display = "none";
    // reading blocks attribute to the doc open in the reader, not the rail's doc
    const cur = S.state?.current;
    let course_id = cur?.course_id, pdf_id = cur?.pdf_id;
    if (S.focusKind === "reading" && RD.pdfId) {
      pdf_id = RD.pdfId;
      course_id = S.state?.libCourses?.find((c) =>
        c.pdfs.some((p) => p.pdf_id === RD.pdfId))?.id ?? course_id;
    }
    try {
      const res = await fetch("/api/focus", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutes: mins, course_id, pdf_id, kind: S.focusKind }) });
      S.recap = await res.json();
    } catch { S.recap = null; }
    S.blockDone = true;   // reading sidebar: show "logged" state until the next start
    renderReadSide();
    fetchState();
  } else {
    S.focusKind = kind === "reading" ? "reading" : "review";
    S.focusStart = Date.now();
    S.blockDone = false;
    $("focusChip").style.display = "flex";
    S._tick = setInterval(() => {
      // timestamps, not tick counts — throttled background tabs must not drift
      const elapsedSec = Math.floor((Date.now() - S.focusStart) / 1000);
      const elapsed = Math.floor(elapsedSec / 60);
      $("focusElapsedHead").textContent = elapsed;
      const el = $("focusElapsed"), bar = $("focusBar");
      if (el) el.textContent = elapsed;
      if (bar) bar.style.width = `${Math.min(100, elapsed / S.sessionLen * 100)}%`;
      const remain = Math.max(0, S.sessionLen * 60 - elapsedSec);
      const rt = $("readRemain"), rb = $("readBar");
      if (rt) rt.textContent = `${Math.floor(remain / 60)}:${String(remain % 60).padStart(2, "0")}`;
      if (rb) rb.style.width = `${Math.min(100, elapsedSec / (S.sessionLen * 60) * 100)}%`;
      if (elapsed >= S.sessionLen) window.toggleFocus();   // auto-end at target
    }, 1000);

    renderReadSide();
  }
};

/* study-block sidebar inside the reading view — same timer as the rail's
   FOCUS SESSION card (one clock, one log), presented as a countdown */
window.renderReadSide = () => {
  const side = $("viewerSide");
  if (!side || $("viewer").style.display === "none") return;
  AN.pendingText = $("annInput")?.value ?? AN.pendingText;   // survive re-renders
  const running = !!S.focusStart;
  const remain = running ? Math.max(0, S.sessionLen * 60 - Math.floor((Date.now() - S.focusStart) / 1000)) : S.sessionLen * 60;
  const timer = `
    <div class="mono-label">READING BLOCK</div>
    ${running ? `
      <div class="read-timer" id="readRemain">${Math.floor(remain / 60)}:${String(remain % 60).padStart(2, "0")}</div>
      <div style="font-size:11px; color:#8A8F9C">of a ${S.sessionLen}-min block</div>
      <div style="height:6px; border-radius:3px; background:#ECECE8; overflow:hidden">
        <div id="readBar" style="height:100%; width:${Math.min(100, (1 - remain / (S.sessionLen * 60)) * 100)}%; border-radius:3px; background:#1C1E26; transition:width 1s linear"></div>
      </div>
      <button class="btn-block ghost" style="margin-top:2px" onclick="toggleFocus()">End early</button>
    ` : `
      ${S.blockDone ? `<div style="font-size:12px; color:#00794F; font-weight:600">Block logged ✓</div>
        <div style="font-size:11px; color:#8A8F9C; margin-top:-6px">It lands in your Reading hub, separate from flashcard time.</div>` : ""}
      <div class="dur-row">
        ${[15, 25, 45].map((m) => `<button class="dur-btn ${S.sessionLen === m ? "on" : ""}" onclick="pickLen(${m})">${m}m</button>`).join("")}
      </div>
      <button class="btn-block" style="margin-top:2px" onclick="toggleFocus('reading')">Start ${S.sessionLen}-min block</button>
    `}`;

  const pageNotes = AN.items.filter((a) => a.page === RD.page);
  const notes = `
    <div class="mono-label" style="margin-top:12px">NOTES · PAGE ${RD.page ?? "–"}</div>
    ${AN.pending ? `
      <div class="note-item">
        <textarea id="annInput" rows="3" placeholder="Your comment for the boxed area…">${esc(AN.pendingText)}</textarea>
        <div style="display:flex; gap:6px">
          <button class="btn-block" style="margin:0; padding:7px" onclick="saveAnnotation()">Save note</button>
          <button class="btn-block ghost" style="margin:0; padding:7px; flex:none; width:44px" onclick="cancelAnnotation()">✕</button>
        </div>
      </div>` : ""}
    ${pageNotes.map((a, i) => `
      <div class="note-item" id="note-${a.id}" onclick="flashAnnBox(${a.id})" title="Click to locate the box">
        <div style="display:flex; align-items:baseline; gap:7px">
          <span class="note-num">${i + 1}</span>
          <span style="flex:1; font-size:12px; line-height:1.55">${esc(a.comment)}</span>
          <button class="icon-btn" style="font-size:11px; flex:none" title="Delete this note"
            onclick="event.stopPropagation(); deleteAnnotation(${a.id})">✕</button>
        </div>
      </div>`).join("")}
    ${!pageNotes.length && !AN.pending ? `<div style="font-size:11.5px; color:#8A8F9C; line-height:1.6">
      No notes on this page yet. Hit <b>✎ Note</b> and drag a box over anything worth a comment.</div>` : ""}`;

  const exporter = RD.mode ? `
    <div class="mono-label" style="margin-top:12px">TAKE p.${RD.start}–${RD.end} ELSEWHERE</div>
    <div style="display:flex; gap:6px">
      <button class="btn-block ghost" style="margin:0; padding:7px; font-size:11.5px" id="copyTopicBtn" onclick="copyTopicText()">⧉ Copy text</button>
      <a class="btn-block ghost" style="margin:0; padding:7px; font-size:11.5px; text-align:center; text-decoration:none; color:inherit; box-sizing:border-box"
         href="/api/pdf/${RD.pdfId}/slice?start=${RD.start}&end=${RD.end}" download>⬇ PDF pages</a>
    </div>
    <div style="font-size:10.5px; color:#8A8F9C; line-height:1.5">For NotebookLM &amp; friends — and bring its flashcards home via Cards → Import.</div>` : "";

  side.innerHTML = timer + notes + exporter;
};

window.copyTopicText = async () => {
  const pages = await fetch(`/api/pdf/${RD.pdfId}/text?start=${RD.start}&end=${RD.end}`)
    .then((r) => r.json()).catch(() => []);
  if (!pages.length) return;
  const doc = S.state?.libCourses.flatMap((c) => c.pdfs).find((p) => p.pdf_id === RD.pdfId);
  const header = `${doc ? doc.filename : "document"} · p.${RD.start}–${RD.end} · ${RD.title}`;
  const text = `${header}\n\n` + pages.map((p) => `=== page ${p.page} ===\n${p.text}`).join("\n\n");
  try {
    await navigator.clipboard.writeText(text);
    const btn = $("copyTopicBtn");
    if (btn) { btn.textContent = "Copied ✓"; setTimeout(() => { if ($("copyTopicBtn")) $("copyTopicBtn").textContent = "⧉ Copy text"; }, 1600); }
  } catch {
    alert("Clipboard blocked — the text was fetched but couldn't be copied. Try the PDF download instead.");
  }
};

window.flashAnnBox = (annId) => {
  const el = document.querySelector(`.ann-box[data-ann="${annId}"]`);
  if (!el) return;
  el.classList.add("flash");
  setTimeout(() => el.classList.remove("flash"), 1200);
};

/* ---------------------------------------------------------------- topic page viewer */

const pdfDocCache = {};

/* blackout (image occlusion): draw black boxes over key facts, recall, peek.
   Coords stored 0-1 relative to the page box so any render width works. */
const BO = { pdfId: null, boxes: [], edit: false, revealAll: false };
/* annotations: comments anchored to outlined "window boxes" on a page */
const AN = { items: [], mode: false, pending: null, pendingText: "" };
/* reader: one page at a time */
const RD = { pdfId: null, title: "", start: null, end: null, page: null,
             mode: null, textPages: null, seq: 0 };

function syncModes() {
  $("blackoutToggle").classList.toggle("bo-on", BO.edit);
  $("blackoutReveal").classList.toggle("bo-on", BO.revealAll);
  $("annToggle").classList.toggle("bo-on", AN.mode);
  $("viewerBody").classList.toggle("bo-edit", BO.edit);
  $("viewerBody").classList.toggle("ann-edit", AN.mode);
}

function renderBox(wrap, b) {
  const el = document.createElement("div");
  el.className = "blackout-box";
  el.title = "Recall what's under here, then click to peek (blackout mode: click deletes)";
  Object.assign(el.style, { left: `${b.x * 100}%`, top: `${b.y * 100}%`,
    width: `${b.w * 100}%`, height: `${b.h * 100}%` });
  if (BO.revealAll) el.classList.add("peek");
  el.onclick = async (e) => {
    e.stopPropagation();
    if (BO.edit) {
      const res = await fetch(`/api/occlusions/${b.id}`, { method: "DELETE" });
      if (res.ok) { BO.boxes = BO.boxes.filter((x) => x.id !== b.id); el.remove(); }
    } else {
      el.classList.toggle("peek");
    }
  };
  wrap.appendChild(el);
}

function renderAnnBoxes(wrap) {
  wrap.querySelectorAll(".ann-box:not(.pending)").forEach((el) => el.remove());
  AN.items.filter((a) => a.page === RD.page).forEach((a, i) => {
    const el = document.createElement("div");
    el.className = "ann-box";
    el.dataset.ann = a.id;
    el.title = a.comment;
    Object.assign(el.style, { left: `${a.x * 100}%`, top: `${a.y * 100}%`,
      width: `${a.w * 100}%`, height: `${a.h * 100}%` });
    el.innerHTML = `<span class="ann-num">${i + 1}</span>`;
    el.onclick = (e) => {
      e.stopPropagation();
      const item = document.getElementById(`note-${a.id}`);
      if (item) {
        item.scrollIntoView({ block: "nearest" });
        item.classList.add("flash");
        setTimeout(() => item.classList.remove("flash"), 1200);
      }
    };
    wrap.appendChild(el);
  });
}

function wireDrawing(wrap) {
  wrap.addEventListener("mousedown", (e) => {
    const mode = BO.edit ? "blackout" : AN.mode ? "note" : null;
    if (!mode || e.target.closest(".blackout-box") || e.target.closest(".ann-box")) return;
    if (mode === "note" && AN.pending) return;   // finish the open note first
    e.preventDefault();
    const rect = wrap.getBoundingClientRect();
    const norm = (ev) => ({
      x: Math.min(Math.max((ev.clientX - rect.left) / rect.width, 0), 1),
      y: Math.min(Math.max((ev.clientY - rect.top) / rect.height, 0), 1),
    });
    const p0 = norm(e);
    const ghost = document.createElement("div");
    ghost.className = mode === "blackout" ? "blackout-box drawing" : "ann-box drawing";
    wrap.appendChild(ghost);
    let box = null;
    const update = (ev) => {
      const p1 = norm(ev);
      box = { x: Math.min(p0.x, p1.x), y: Math.min(p0.y, p1.y),
              w: Math.abs(p1.x - p0.x), h: Math.abs(p1.y - p0.y) };
      Object.assign(ghost.style, { left: `${box.x * 100}%`, top: `${box.y * 100}%`,
        width: `${box.w * 100}%`, height: `${box.h * 100}%` });
    };
    update(e);
    const up = async () => {
      document.removeEventListener("mousemove", update);
      document.removeEventListener("mouseup", up);
      if (box.w < 0.01 || box.h < 0.01) { ghost.remove(); return; }   // a click, not a drag
      if (mode === "blackout") {
        ghost.remove();
        const res = await fetch("/api/occlusions", { method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ pdf_id: BO.pdfId, page_number: +wrap.dataset.page, ...box }) });
        if (!res.ok) return;
        const { id } = await res.json();
        const saved = { id, page: +wrap.dataset.page, ...box };
        BO.boxes.push(saved);
        renderBox(wrap, saved);
      } else {
        // the box stays as a dashed outline until the comment is saved
        ghost.classList.remove("drawing");
        ghost.classList.add("pending");
        AN.pending = { page: +wrap.dataset.page, box, ghost };
        renderReadSide();
        $("annInput")?.focus();
      }
    };
    document.addEventListener("mousemove", update);
    document.addEventListener("mouseup", up);
  });
}

window.saveAnnotation = async () => {
  if (!AN.pending) return;
  const comment = ($("annInput")?.value || "").trim();
  if (!comment) { $("annInput")?.focus(); return; }
  const { page, box, ghost } = AN.pending;
  const res = await fetch("/api/annotations", { method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ pdf_id: RD.pdfId, page_number: page, comment, ...box }) });
  if (!res.ok) return;
  const { id } = await res.json();
  AN.items.push({ id, page, ...box, comment });
  AN.pending = null;
  AN.pendingText = "";
  ghost.remove();
  const wrap = document.querySelector("#viewerBody .page-wrap");
  if (wrap) renderAnnBoxes(wrap);
  renderReadSide();
};

window.cancelAnnotation = () => {
  AN.pending?.ghost?.remove();
  AN.pending = null;
  AN.pendingText = "";
  renderReadSide();
};

window.deleteAnnotation = async (annId) => {
  const res = await fetch(`/api/annotations/${annId}`, { method: "DELETE" });
  if (!res.ok) return;
  AN.items = AN.items.filter((a) => a.id !== annId);
  const wrap = document.querySelector("#viewerBody .page-wrap");
  if (wrap) renderAnnBoxes(wrap);
  renderReadSide();
};

window.openTopic = async (pdfId, pageStart, pageEnd, encTitle) => {
  RD.pdfId = pdfId;
  RD.title = decodeURIComponent(encTitle);
  RD.start = pageStart;
  RD.end = pageEnd;
  RD.page = pageStart;
  RD.mode = null;
  RD.textPages = null;
  $("viewerTitle").textContent = RD.title;
  $("viewerSub").textContent = `p.${pageStart} of ${pageEnd}`;
  $("viewerBody").innerHTML = `<div style="padding:30px; color:#8A8F9C; font-size:12.5px">Loading pages…</div>`;
  $("viewer").style.display = "flex";
  BO.pdfId = pdfId;
  BO.edit = false;
  BO.revealAll = false;
  AN.mode = false;
  AN.pending = null;
  AN.pendingText = "";
  syncModes();

  const [boxes, anns] = await Promise.all([
    fetch(`/api/occlusions/${pdfId}`).then((r) => r.json()).catch(() => []),
    fetch(`/api/annotations/${pdfId}`).then((r) => r.json()).catch(() => []),
  ]);
  BO.boxes = boxes;
  AN.items = anns;

  try {
    if (!window.pdfjsLib) throw new Error("pdf.js unavailable");
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
    if (!pdfDocCache[pdfId]) {
      pdfDocCache[pdfId] = await pdfjsLib.getDocument(`/api/pdf/${pdfId}`).promise;
    }
    RD.mode = "pdf";
    RD.end = Math.min(pageEnd, pdfDocCache[pdfId].numPages);
  } catch {
    // fallback: extracted text (pasted-text sources, moved files, no pdf.js)
    try {
      const pages = await fetch(`/api/pdf/${pdfId}/text?start=${pageStart}&end=${pageEnd}`)
        .then((r) => r.json());
      if (!pages.length) throw new Error("no pages");
      RD.mode = "text";
      RD.textPages = pages;
    } catch {
      $("viewerBody").innerHTML = `<div style="padding:30px; color:#8A8F9C; font-size:12.5px">
        Couldn't load these pages — the original file may have moved.</div>`;
      renderReadSide();
      return;
    }
  }
  await renderReaderPage();
};

window.renderReaderPage = async () => {
  const seq = ++RD.seq;
  const body = $("viewerBody");
  $("viewerSub").textContent = `p.${RD.page} of ${RD.end}`;
  $("readerPrev").disabled = RD.page <= RD.start;
  $("readerNext").disabled = RD.page >= RD.end;

  const wrap = document.createElement("div");
  wrap.dataset.page = RD.page;
  if (RD.mode === "pdf") {
    wrap.className = "page-wrap";
    const doc = pdfDocCache[RD.pdfId];
    const page = await doc.getPage(RD.page);
    if (seq !== RD.seq) return;   // user paged on before this fetch finished
    const width = Math.min(920, body.clientWidth - 40);
    const base = page.getViewport({ scale: 1 });
    const scale = width / base.width;
    const viewport = page.getViewport({ scale: scale * (window.devicePixelRatio || 1) });
    const canvas = document.createElement("canvas");
    canvas.width = viewport.width;
    canvas.height = viewport.height;
    canvas.style.width = `${width}px`;
    canvas.style.height = `${Math.round(viewport.height / (window.devicePixelRatio || 1))}px`;
    canvas.style.display = "block";
    canvas.className = "viewer-page";
    wrap.appendChild(canvas);
    // paint in the background — the page (and its boxes/notes) is usable
    // immediately, and a throttled tab can't leave the reader blank
    page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise.catch(() => {});
  } else {
    wrap.className = "page-wrap page-wrap-stretch";
    const p = RD.textPages.find((x) => x.page === RD.page);
    const div = document.createElement("div");
    div.className = "viewer-text";
    div.innerHTML = md(p ? p.text : "(no text stored for this page)");
    wrap.appendChild(div);
  }
  body.innerHTML = "";
  body.appendChild(wrap);
  BO.boxes.filter((b) => b.page === RD.page).forEach((b) => renderBox(wrap, b));
  renderAnnBoxes(wrap);
  wireDrawing(wrap);
  renderReadSide();
};

window.readerNav = (delta) => {
  if (RD.mode === null) return;
  const target = Math.min(RD.end, Math.max(RD.start, RD.page + delta));
  if (target === RD.page) return;
  if (AN.pending) cancelAnnotation();   // an unsaved note doesn't survive a page turn
  RD.page = target;
  renderReaderPage();
};

$("readerPrev").onclick = () => readerNav(-1);
$("readerNext").onclick = () => readerNav(1);
$("blackoutToggle").onclick = () => { BO.edit = !BO.edit; if (BO.edit) AN.mode = false; syncModes(); };
$("annToggle").onclick = () => { AN.mode = !AN.mode; if (AN.mode) BO.edit = false; syncModes(); };
$("blackoutReveal").onclick = () => {
  BO.revealAll = !BO.revealAll;
  document.querySelectorAll(".blackout-box").forEach((b) => b.classList.toggle("peek", BO.revealAll));
  syncModes();
};

window.closeViewer = () => { $("viewer").style.display = "none"; };
$("viewer").addEventListener("click", (e) => { if (e.target === $("viewer")) closeViewer(); });
document.addEventListener("keydown", (e) => {
  if ($("viewer").style.display === "none") return;
  const typing = /TEXTAREA|INPUT/.test(e.target.tagName);
  if (e.key === "Escape") { typing ? e.target.blur() : closeViewer(); return; }
  if (typing) return;
  if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); readerNav(1); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); readerNav(-1); }
});

/* ---- static listeners ---- */
$("tabHome").onclick = () => { S.view = S.courseId ? "course" : "home"; render(); };
$("tabStudy").onclick = () => { S.view = "study"; render(); };
$("tabProgress").onclick = () => { S.view = "progress"; render(); };
$("tabCards").onclick = () => { S.view = "cards"; render(); loadCards(); };
$("doNext").onclick = () => {
  const best = S.state?.best;
  if (!best) return;
  S.pdfId = best.pdf_id;
  startReviewSession({ topic_id: best.topic_id });
};
/* ---- button ingest: upload → auto segment+save → fix with Edit split ---- */
function xhrUpload(file, onProgress) {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(Math.round(e.loaded / e.total * 100));
    };
    xhr.onload = () => {
      try {
        const data = JSON.parse(xhr.responseText);
        xhr.status < 300 ? resolve(data) : reject(new Error(data.error || "upload failed"));
      } catch { reject(new Error(`upload failed (${xhr.status})`)); }
    };
    xhr.onerror = () => reject(new Error("network error during upload"));
    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

async function uploadPdfs(files) {
  const pdfs = [...files].filter((f) => f.name.toLowerCase().endsWith(".pdf"));
  if (!pdfs.length || S.ingesting) return;
  // course: taken from the library context when you're inside one, asked otherwise
  let course_id = null, course_name = null;
  const selCourse = S.courseId != null
    ? S.state?.libCourses.find((c) => c.id === S.courseId) : null;
  if (selCourse) course_id = selCourse.id;
  else {
    course_name = (prompt("Which course do these documents belong to? (existing or new name)") || "").trim();
    if (!course_name) { $("fileInput").value = ""; return; }
  }
  if (S.forceVision && !confirm(
      "Read the images on EVERY page?\n\nUse this for slide decks whose content lives in "
      + "diagrams — a vision model reads each page as a picture. Slower, and roughly "
      + "$0.11 per 8 pages (a 40-slide deck ≈ $0.55).")) return;
  S.ingesting = { done: 0, total: pdfs.length, current: "", failed: [] };
  render();
  for (const file of pdfs) {
    S.ingesting.current = file.name;
    render();
    try {
      const up = await xhrUpload(file, () => {});
      const res = await fetch("/api/ingest_auto", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ path: up.path, course_id, course_name,
                               force_vision: S.forceVision }) })
        .then((r) => r.ok ? r.json() : null);
      if (!res) S.ingesting.failed.push(file.name);
      else if (res.course_id) { course_id = res.course_id; course_name = null; }
    } catch { S.ingesting.failed.push(file.name); }
    S.ingesting.done += 1;
  }
  const failed = S.ingesting.failed;
  S.ingesting = null;
  $("fileInput").value = "";
  await fetchState();
  if (failed.length) alert(`These didn't ingest — try them again:\n${failed.join("\n")}`);
}

$("fileInput").addEventListener("change", (e) => uploadPdfs(e.target.files));
window.pickPdfs = () => $("fileInput").click();

$("sendBtn").onclick = () => submitAnswer($("chatInput").value);
$("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") submitAnswer(e.target.value);
});
document.querySelectorAll(".conf-btn[data-conf]").forEach((b) => b.onclick = () => {
  S.pendingConf = S.pendingConf === b.dataset.conf ? null : b.dataset.conf;
  renderConfRow();
});

$("backToDecks").onclick = () => backToDecks();
$("asstBubble").onclick = () => toggleAsst();
$("asstSend").onclick = () => sendAsst($("asstInput").value);
$("asstInput").addEventListener("input", updateAsstSuggest);
$("asstInput").addEventListener("blur", () => setTimeout(dismissAsstSuggest, 120));
$("asstInput").addEventListener("keydown", (e) => {
  const open = S.asstSuggest.length > 0;
  if (open && (e.key === "ArrowDown" || e.key === "ArrowUp")) {
    e.preventDefault();
    const n = S.asstSuggest.length;
    S.asstSuggestIdx = (S.asstSuggestIdx + (e.key === "ArrowDown" ? 1 : n - 1)) % n;
    renderAsstSuggest();
    return;
  }
  if (open && e.key === "Tab") { e.preventDefault(); acceptAsstSuggest(Math.max(0, S.asstSuggestIdx)); return; }
  if (open && e.key === "Escape") { e.preventDefault(); dismissAsstSuggest(); return; }
  if (e.key === "Enter") {
    if (open && S.asstSuggestIdx >= 0) { e.preventDefault(); acceptAsstSuggest(S.asstSuggestIdx); return; }
    sendAsst(e.target.value);
  }
});
$("navCollapse").onclick = toggleNav;
$("sideNav").classList.toggle("closed", !S.navOpen);   // default: icons only
$("navCollapse").title = S.navOpen ? "Collapse sidebar" : "Expand sidebar";

fetchState();
fetchHistory();
