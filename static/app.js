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
  anaTab: 0,            // analytics: which of the six sections is on screen
  reviewView: "decks",  // review screen: "decks" picker | "chat" live | "report"
  report: null,         // the ended session's report, once it replaces the chat
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
  cardSel: null,        // cards screen: which card the editor is showing
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

/* One labelled section of the grade card. Marker geometry is constant — an 18px
   square everywhere — and ONLY the evaluative pair takes a hue: green for what
   was recalled, red for what was not. Marking all four would make the card look
   like a form and would spend colour on sections that judge nothing. */
const GMARK = {
  right: { fill: "var(--fb-green)", border: "var(--fb-green)", glyph: "✓" },
  gap:   { fill: "var(--fb-red)", border: "var(--fb-red)", glyph: "✗" },
  plain: { fill: "transparent", border: "var(--fb-hairline)", glyph: "" },
  hook:  { fill: "var(--fb-ink)", border: "var(--fb-ink)", glyph: "" },
};

function gradeSection(label, text, kind = "plain") {
  if (!text) return "";
  const m = GMARK[kind] || GMARK.plain;
  const hook = kind === "hook";
  return `<div style="display:grid; grid-template-columns:18px 1fr; gap:14px; padding:14px 24px;
      ${hook ? "border-top:1.5px solid var(--fb-hairline)" : ""}">
    <span style="width:18px; height:18px; border-radius:4px; background:${m.fill};
      border:1.5px solid ${m.border}; display:flex; align-items:center; justify-content:center;
      font-size:11px; font-weight:700; color:var(--fb-ink); margin-top:2px">${m.glyph}</span>
    <div style="min-width:0">
      <div class="fb-label" style="margin-bottom:6px">${label}</div>
      <div style="font-size:13.5px; line-height:1.6; color:${hook ? "var(--fb-ink)" : "var(--fb-slate)"};
        font-weight:${hook ? 600 : 400}">${esc(text)}</div>
    </div>
  </div>`;
}

/* The schedule footer answers exactly one question — when do I see this card
   again — and puts the OLD interval on the same track as a ghost tick, so the
   consequence of the grade is one alignment rather than two bars to compare.
   A shortened interval is information, not a telling-off: nothing here is red. */
function gradeSchedule(sc) {
  const from = Math.max(0, sc.old_interval || 0), to = Math.max(0, sc.new_interval || 0);
  const max = Math.max(from, to, 1);
  const nowPct = to / max * 100, wasPct = from / max * 100;
  const tick = (pct, text, strong) => `<span style="position:absolute; ${pct > 92
      ? "right:0" : `left:${pct}%; transform:translateX(-50%)`}; white-space:nowrap;
    color:var(--fb-${strong ? "ink" : "muted"}); font-weight:${strong ? 600 : 400}">${text}</span>`;
  const note = to === from ? `Same interval as before — the grade held it where it was.`
    : to > from ? `${to} days instead of ${from}. Recalling it cleanly pushes the card further out — that is the whole consequence of this grade.`
    : `${to} day${to === 1 ? "" : "s"} instead of ${from}. A partial answer pulls the card back in — that is the whole consequence of this grade.`;
  return `<div style="margin:0 24px; padding:16px 0 20px; border-top:1.5px solid var(--fb-hairline)">
    <div class="fb-label" style="margin-bottom:10px">Next review</div>
    <div style="display:flex; align-items:baseline; gap:9px; margin-bottom:16px">
      <span style="font-family:var(--fb-mono); font-size:26px; font-weight:700; letter-spacing:-1px; line-height:1">in ${to} day${to === 1 ? "" : "s"}</span>
      ${sc.next_review ? `<span class="fb-data" style="font-size:13px; color:var(--fb-muted)">· ${esc(sc.next_review)}</span>` : ""}
    </div>
    <div style="position:relative; height:22px; margin-bottom:8px">
      <span style="position:absolute; left:0; right:0; top:9px; height:3px; background:var(--fb-hairline); border-radius:2px"></span>
      <span style="position:absolute; left:0; width:${nowPct}%; top:9px; height:3px; background:var(--fb-ink); border-radius:2px"></span>
      <span style="position:absolute; left:0; top:4px; width:3px; height:13px; background:var(--fb-ink)"></span>
      <span style="position:absolute; left:calc(${wasPct}% - 1.5px); top:4px; width:3px; height:13px; background:var(--fb-hairline)"></span>
      <span style="position:absolute; left:calc(${nowPct}% - 1.5px); top:0; width:3px; height:21px; background:var(--fb-ink)"></span>
    </div>
    <div style="position:relative; height:14px; font-family:var(--fb-mono); font-size:10px; letter-spacing:.6px; text-transform:uppercase">
      <span style="position:absolute; left:0; color:var(--fb-muted)">today</span>
      ${tick(wasPct, `${from}d · was`, false)}
      ${tick(nowPct, `${to}d · now`, true)}
    </div>
    <div class="fb-body-sm" style="margin-top:14px">${note}</div>
  </div>`;
}

function renderMsg(m) {
  if (m.role === "user") {
    const meta = m.meta ? `<div class="fb-data" style="font-size:10px; color:rgba(255,255,255,.6); margin-bottom:6px">${esc(m.meta)}</div>` : "";
    return `<div class="fb-row-user"><div class="fb-bubble-user">${meta}${esc(m.text)}</div></div>`;
  }
  if (m.role === "grade") {
    /* No red verdict rule: a missed card is scheduling information, not a
       failure, so the left rule is green at 4+ and yellow below. */
    const good = m.grade >= 4;
    const verdict = good ? "Correct" : m.grade === 3 ? "Partially correct" : "Not quite";
    const pill = `${good ? "Correct" : m.grade === 3 ? "Partial" : "Missed"} · ${m.grade}/5`;
    // structured feedback, with a plain-text fallback for pre-upgrade history
    const structured = m.right || m.gap || m.answer;
    const body = structured
      ? gradeSection("You had", m.right, "right")
        + gradeSection("The gap", m.gap, "gap")
        + gradeSection("Model answer", m.answer)
        + gradeSection("Why", m.why)
        + gradeSection("Remember", m.hook, "hook")
        + (m.calibration ? `<div class="fb-gcard-meta">${esc(m.calibration)}</div>` : "")
      : `<div class="fb-gcard-body">${md(m.text)}</div>`;
    return `<div class="fb-row-bot"><div class="fb-gcard ${good ? "fb-gcard--correct" : "fb-gcard--partial"}${m.grade === 5 ? " fb-anim-grade5" : ""}">
      <div style="display:flex; align-items:center; gap:12px; padding:18px 24px 4px">
        <span class="fb-pill">${pill}</span>
        <span class="fb-body-sm" style="color:var(--fb-ink); font-weight:600; font-size:14px">${verdict}</span>
        <span style="flex:1"></span>
        <button class="fb-undo" data-card="${m.card_id || ""}" onclick="undoGrade(this)" title="Mis-graded? Restore the card's previous schedule">undo</button>
      </div>
      ${body}
      ${m.schedule ? gradeSchedule(m.schedule)
        : m.meta ? `<div class="fb-gcard-meta">${esc(m.meta)}</div>` : ""}
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
    return `<div class="fb-row-bot"><div class="chat-pdfcard" onclick="openDoc(${p.pdf_id})" title="Open in Study">
      <div style="font-size:13px; font-weight:600; line-height:1.4">📄 ${esc(p.filename)}</div>
      <div class="doc-meta" style="margin-bottom:10px">${p.total_pages} pages · ${esc(p.est)} est · ${p.topics.length} topics</div>
      <div style="display:flex; flex-direction:column; gap:6px">${rows}</div>
    </div></div>`;
  }
  // the session report is no longer a chat message — it REPLACES the
  // transcript (renderSessionReport), because once the last card is graded the
  // scroll is not what you need in front of you
  if (m.role === "report") return "";
  // assistant: question marker → styled card (plain bubble for any lead-in text)
  const match = m.text.match(CARD_RE);
  if (match) {
    const at = m.text.search(CARD_RE);
    const pre = m.text.slice(0, at).trim();
    const question = m.text.slice(at + match[0].length).trim();
    /* the 4px sky left rule is the card-type signal — no head tint, no wash.
       Blue means exactly one thing here: answer this. */
    return (pre ? `<div class="fb-row-bot"><div class="fb-bubble-bot">${md(pre)}</div></div>` : "") + `
      <div class="fb-row-bot"><div class="fb-qcard">
        <div class="fb-qcard-head">
          <span class="fb-label">Question ${match[1]} of ${match[2]}</span>
          <span class="fb-data" style="font-size:11px; color:var(--fb-muted)">· ${esc(match[3].trim())}</span>
        </div>
        <div class="fb-qcard-body">${md(question)}</div>
        <div class="fb-qcard-hint">Type your answer below</div>
      </div></div>`;
  }
  return `<div class="fb-row-bot"><div class="fb-bubble-bot">${md(m.text)}</div></div>`;
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

  /* One deck row per course, expanding to its documents. The ▶ is DISABLED at
     zero rather than hidden: a course you owe nothing on is information, and a
     row that changes shape between states is harder to scan. No course colour —
     in this system colour means mastery and nothing else. */
  const deckRow = (lead, name, due, title, onclick, indented) => `
    <div style="display:flex; align-items:center; gap:10px; ${indented
      ? "padding:8px 0 8px 22px; border-top:1.5px solid var(--fb-hairline)" : "cursor:pointer"}"
      ${indented ? "" : `onclick="toggleDeck(${lead.id})"`}>
      ${indented ? "" : `<span style="flex:none; width:12px; color:var(--fb-muted); font-family:var(--fb-mono); font-size:11px">${lead.caret}</span>`}
      <span style="flex:1; min-width:0; ${indented
        ? "font-size:12.5px; color:var(--fb-slate)" : "font-size:13.5px; font-weight:600"};
        overflow:hidden; text-overflow:ellipsis; white-space:nowrap" title="${esc(name)}">${esc(name)}</span>
      <span class="fb-chip${due ? " fb-chip--due" : ""}"${due ? "" : ` style="color:var(--fb-muted)"`}>${due} due</span>
      <button class="fb-btn" style="padding:4px 9px; font-size:11px; flex:none" ${due ? "" : "disabled"}
        title="${title}" onclick="event.stopPropagation(); ${onclick}">▶</button>
    </div>`;

  const decks = st.libCourses.map((c) => {
    const open = S.deckOpen.has(c.id);
    return `<div class="fb-card fb-card--sm" style="padding:12px 14px">
      ${deckRow({ id: c.id, caret: open ? "▾" : "▸" }, c.name, c.dueCount,
        "Review this course's due cards", `startReviewSession({ course_id: ${c.id} })`, false)}
      ${open && c.pdfs.length ? `<div style="margin-top:10px; display:flex; flex-direction:column">
        ${c.pdfs.map((p) => deckRow(null, p.filename.replace(/\.pdf$/i, ""), p.due,
          "Review this document's due cards", `startReviewSession({ pdf_id: ${p.pdf_id} })`, true)).join("")}
      </div>` : ""}
      ${open && !c.pdfs.length ? `<div class="fb-body-sm" style="margin-top:10px; padding-left:22px">No documents in this course yet.</div>` : ""}
    </div>`;
  }).join("");

  /* The budget sentence is derived from the DEAL, not written: a screen that
     promises 17 cards and hands you 6 is the kind of small lie that makes the
     whole thing untrustworthy. */
  const b = st.budget || { daily_minutes: 0, sec_per_card: 84 };
  const fit = b.daily_minutes ? Math.max(1, Math.floor(b.daily_minutes * 60 / b.sec_per_card)) : null;
  const dealing = fit ? Math.min(fit, st.dueTotal) : st.dueTotal;
  const mins = Math.max(1, Math.round(dealing * b.sec_per_card / 60));

  home.innerHTML = `
    <div style="flex:none; width:var(--fb-rail); display:flex; flex-direction:column; gap:10px">
      <span class="fb-label">Decks</span>
      ${decks || `<div class="fb-card fb-card--sm"><div class="fb-body-sm">No decks yet — add PDFs from Home.</div></div>`}
    </div>
    <div style="flex:1; min-width:0; display:flex; flex-direction:column; gap:var(--fb-gap-grid)">
      <div class="fb-card fb-card--key">
        <div class="fb-label" style="margin-bottom:16px">Today's review</div>
        <div class="fb-numeral">${st.dueTotal}<small> cards due</small></div>
        <div class="fb-body-sm" style="margin-top:14px">${st.dueTotal === 0
          ? "All caught up — nothing owed today."
          : dealing < st.dueTotal
          ? `Dealing ${dealing} of them — about ${mins} minute${mins === 1 ? "" : "s"} at ${b.sec_per_card}s a card. The rest wait.`
          : `Dealing all ${dealing} — about ${mins} minute${mins === 1 ? "" : "s"} at ${b.sec_per_card}s a card.${
              fit ? "" : " No daily budget set, so nothing is held back."}`}</div>
        <button class="fb-btn fb-btn--block" style="margin-top:20px" ${st.dueTotal ? "" : "disabled"}
          onclick="startReviewSession({})">▶ Start today's review</button>
        <div class="fb-evidence">Due order is most-at-risk first, and courses interleave naturally — which
          beats blocking one subject at a time (Rohrer &amp; Taylor, 2007).</div>
      </div>
      ${st.best ? `<div class="fb-card">
        <div class="fb-label" style="margin-bottom:16px">Weakest due topic</div>
        <div style="font-size:15px; font-weight:600">${esc(st.best.title)}</div>
        <div class="fb-bar" style="margin:16px 0 12px">
          <div class="fb-bar-track"><div class="fb-bar-fill" style="width:${st.best.pct}%; background:${MASTERY_HUE(st.best.pct)}"></div></div>
          <span class="fb-bar-pct">${st.best.pct.toFixed(0)}%</span>
        </div>
        <div class="fb-body-sm">The lowest retention you own among cards that are due. Most in need of a rep.</div>
        <button class="fb-btn fb-btn--ghost fb-btn--block" style="margin-top:18px"
          onclick="startReviewSession({ topic_id: ${st.best.topic_id} })">Review just this topic</button>
      </div>` : ""}
    </div>`;
}

window.toggleDeck = (courseId) => {
  S.deckOpen.has(courseId) ? S.deckOpen.delete(courseId) : S.deckOpen.add(courseId);
  renderReviewHome();
};

window.backToDecks = () => {
  if (RV.sid) {
    // endSession lands on the report itself — let it, rather than dropping
    // the student straight back to the rail with the gaps unseen
    if (!confirm("End the session and go back to your decks?")) return;
    return endSession();
  }
  S.report = null;
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
  $("sessionLabel").textContent = `· card ${card.n} of ${card.total}`;
  S.qShownAt = Date.now();
  $("chatInput").placeholder = card.phase === "relearn"
    ? "Re-ask (not scored) — type what you remember…"
    : "Type your answer…";
  renderConfRow();
  $("chatInput").focus();
}

function reviewIdle() {
  RV.sid = RV.kind = RV.card = null;
  S.qShownAt = null;
  $("chatInput").placeholder = "Start a review to begin — cards get dealt here.";
  $("agentName").textContent = "Review";
  $("sessionLabel").textContent = "";
  renderConfRow();
  fetchState();   // ends in render(), which paints whichever state is now set
}

window.startReviewSession = async (scope = {}, kind = "review") => {
  if (RV.sid || S.busy) return;
  S.view = "study";
  S.report = null;         // last session's sheet doesn't outlive this one
  S.reviewView = "chat";   // the chat only appears once a review starts
  $("chatScroll").innerHTML = "";
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
  chatLine(`<div id="thinking" class="fb-row-bot"><div class="fb-bubble-bot"><span class="status-line working">Grading…</span></div></div>`);
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
  /* The report REPLACES the transcript. Once the last card is graded the
     scroll is not what you need in front of you — and a session with no
     graded answers has no report to show, so that one falls back to the
     decks rather than to an empty sheet. */
  if (res?.report) {
    S.report = res.report;
    S.reviewView = "report";
    $("chatScroll").innerHTML = "";
  } else {
    S.report = null;
    S.reviewView = "decks";
  }
  reviewIdle();
}


/* ------------------------------------------------------- the session report */

/* One gap. The left rule is the only colour on the card — red at 2/5 and below,
   yellow above — and its own corner radius drops to 3px so it reads as a rule
   rather than a curve. The gap carries the EXPECTED ANSWER, not just the mark:
   a card you missed and cannot see the right answer to is one you will miss
   again. */
function reportGap(it) {
  const hue = it.quality <= 2 ? "var(--fb-red)" : "var(--fb-yellow)";
  return `<div style="background:var(--fb-page); border-radius:var(--fb-r-card);
      border-left:var(--fb-rule-w) solid ${hue}; border-top-left-radius:3px;
      border-bottom-left-radius:3px; padding:16px 18px">
    <div style="display:flex; align-items:baseline; gap:10px">
      <span class="fb-data" style="font-size:10px; letter-spacing:1.2px; text-transform:uppercase; color:var(--fb-muted)">${esc(it.topic_title)}</span>
      <span style="flex:1"></span>
      <span class="fb-data" style="font-size:11px; color:var(--fb-muted)">${it.quality}/5</span>
    </div>
    <div style="font-size:13.5px; font-weight:600; line-height:1.5; margin-top:9px">${esc(it.question)}</div>
    <div style="font-size:12.5px; color:var(--fb-slate); line-height:1.6; margin-top:8px">
      ${it.gap ? `${esc(it.gap)} ` : ""}Expected: ${esc(it.answer)}</div>
    <div style="display:flex; align-items:center; gap:10px; margin-top:14px; flex-wrap:wrap">
      <button class="fb-btn fb-btn--ghost" style="padding:6px 11px; font-size:11.5px"
        title="Open ${esc(it.topic_title)} at these pages in the reader"
        onclick="openTopic(${it.pdf_id}, ${it.page_start}, ${it.page_end}, '${encT(it.topic_title)}', ${it.topic_id ?? "null"})">Re-read p.${it.page_start}–${it.page_end}</button>
      ${it.quality < 3 ? `<span class="fb-data" style="font-size:11px; color:var(--fb-muted)">reset to 1d</span>` : ""}
    </div>
  </div>`;
}

/* The recall count-up — the second of the four earned moments, and the only
   value on the sheet that animates. Driven by ELAPSED TIME, not tick count: a
   per-tick increment takes unbounded wall-clock time whenever timers are
   throttled, and every frame it crawls it is displaying a number that is not
   the student's score. */
function countUp(el, target) {
  if (!el) return;
  /* The true value goes in FIRST and the animation only ever overwrites it.
     requestAnimationFrame does not fire in a page that isn't compositing — a
     background tab, a hidden pane — and an animation that never starts would
     otherwise leave 0% on screen forever, which is not the student's score. */
  el.textContent = target;
  if (!target || document.visibilityState !== "visible"
      || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  const t0 = performance.now();
  const step = (now) => {
    const k = Math.min(1, (now - t0) / 420);
    el.textContent = Math.round(target * (1 - Math.pow(1 - k, 3)));
    if (k < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function renderSessionReport() {
  const rep = S.report;
  const box = $("reviewReport");
  if (!rep || S.view !== "study" || S.reviewView !== "report") return;
  const st = S.state || {};
  const missed = rep.missed || [];
  /* Two different thresholds live on this sheet and they must not be conflated:
     the GAP list is quality <= 3, because a partial answer is still worth
     re-reading, while SCHEDULING extends at quality >= 3. Counting extended
     intervals off the gap list would under-report them — and reading "1 passed"
     beside "75% by cards passed" is how a sheet stops being believed. */
  const reset = missed.filter((m) => m.quality < 3).length;
  const kept = rep.cards - reset;
  const spelled = ["no", "one", "two", "three", "four", "five", "six"][missed.length] ?? missed.length;
  const at = rep.ended_at ? new Date(rep.ended_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }) : "";

  /* Both the headline and the where-to-next line are composed from the
     session's own numbers — nothing here is a model call, and nothing claims
     more than the deal contained. */
  const headline = missed.length === 0
    ? `Clean sweep — all ${rep.cards} recalled. Every interval moved out.`
    : missed.length === rep.cards
    ? `All ${rep.cards} need another pass. Re-read the pages below before tomorrow.`
    : `${kept} held, ${missed.length} slipped. The ${spelled} below ${missed.length === 1 ? "is" : "are"} worth re-reading before tomorrow.`;
  const topics = [...new Set(missed.map((m) => m.topic_title))];
  const next = missed.length
    ? `${topics.slice(0, 2).map(esc).join(" and ")}${topics.length > 2 ? ` and ${topics.length - 2} more` : ""} — open the pages, then let a tutor chat do the explaining.`
    : `Nothing owed from this session. The next cards come back on their own schedule.`;

  const week = st.stats?.week || [];
  const pace = rep.sec_per_card;
  const delta = pace != null && rep.baseline_measured ? rep.baseline_sec - pace : null;

  box.innerHTML = `
    <div class="fb-card fb-anim-report" style="max-width:var(--fb-content); margin:0 auto">
      <div style="display:flex; align-items:baseline; gap:12px; flex-wrap:wrap">
        <span class="fb-label">Session complete</span>
        <span class="fb-data" style="color:var(--fb-muted); white-space:nowrap">${at}${rep.minutes != null ? ` · ${rep.minutes} min` : ""}${rep.courses?.length ? ` · ${esc(rep.courses.join(", "))}` : ""}</span>
        <span style="flex:1"></span>
        <button class="fb-btn fb-btn--ghost" style="padding:6px 12px; font-size:11.5px"
          onclick="backToDecks()" title="Back to your decks">‹ Decks</button>
      </div>
      <div style="font-size:var(--fb-title); font-weight:700; letter-spacing:-.6px; line-height:1.35; margin-top:12px; max-width:44ch">${headline}</div>

      <div class="fb-band" style="padding-bottom:6px">
        ${bandMetric("Recall", `<span id="repRecall">${rep.recall_marks || 0}</span>`, "%",
          `<div class="fb-body-sm" style="margin-top:8px">${rep.marks} of ${rep.marks_of} marks</div>`)}
        ${bandMetric("Cards", rep.cards, "",
          `<div class="fb-body-sm" style="margin-top:8px">${missed.length
            ? `${missed.length} left a gap to re-read` : "no gaps left behind"}</div>`)}
        ${bandMetric("Per card", pace != null ? pace : "—", pace != null ? "s" : "",
          `<div class="fb-body-sm" style="margin-top:8px">${pace == null ? "session too short to time"
            : delta == null ? "no personal baseline yet"
            : delta > 0 ? `${delta}s faster than your usual`
            : delta < 0 ? `${-delta}s slower than your usual`
            : "exactly your usual pace"}</div>`)}
        ${bandMetric("Streak", st.stats?.streak ?? 0, st.stats?.streak === 1 ? " day" : " days",
          `<div style="display:flex; gap:5px; margin-top:12px">
            ${week.map((d) => `<span title="${d.day}" style="width:14px; height:14px; border-radius:3px;
              background:${d.lit ? "var(--fb-ink)" : "transparent"};
              border:${d.lit ? "none" : "1.5px solid var(--fb-hairline)"}"></span>`).join("")}
          </div>`)}
      </div>

      <div style="display:flex; align-items:baseline; gap:12px; margin-top:24px">
        <span class="fb-label">The ${spelled} gap${missed.length === 1 ? "" : "s"}</span>
        ${missed.length ? `<span class="fb-data" style="color:var(--fb-muted)">re-read before tomorrow</span>` : ""}
      </div>
      <div style="display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:16px; margin-top:14px">
        ${missed.map(reportGap).join("")}
        <div style="border-radius:var(--fb-r-card); border:var(--fb-border); padding:16px 18px; display:flex; flex-direction:column">
          <div class="fb-label">Where to next</div>
          <div class="fb-body-sm" style="margin-top:9px">${next}</div>
          <div style="flex:1; min-height:14px"></div>
          <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
            ${missed.length ? `<button class="fb-btn" title="Open ${esc(missed[0].topic_title)} at its pages"
              onclick="openTopic(${missed[0].pdf_id}, ${missed[0].page_start}, ${missed[0].page_end}, '${encT(missed[0].topic_title)}', ${missed[0].topic_id ?? "null"})">Open the reader</button>` : ""}
            <button class="fb-btn fb-btn--ghost" style="padding:6px 12px; font-size:11.5px"
              onclick="copyReport(${rep.session_id}, this)"
              title="Copy a ready-made coaching prompt — paste it into a tutor chat and let THEM burn the tokens explaining">Copy tutor prompt</button>
          </div>
        </div>
      </div>

      <div class="fb-evidence">Recall here is retrieval-weighted across marks, not cards — a 3/5 counts as three,
        so a session of near-misses reads lower than its hit rate. ${rep.accuracy != null
          ? `By cards passed it was ${rep.accuracy}%.` : ""}
        Intervals updated: ${kept} extended, ${reset} reset to 1d.</div>
    </div>`;
  countUp($("repRecall"), rep.recall_marks || 0);
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

/* ------------------------------------------------------- analytics: charts
   Hand-written SVG, no chart library. viewBox + width:100% so they scale, and
   vector-effect keeps strokes at 1.5px however far they stretch. Every chart
   ships with its number beside it — a shape alone is not a measurement. */

/* A line with an optional filled area. The domain fits the SERIES, not 0–100:
   on a full axis a 62→74 rise compresses to three pixels and reads as flat. */
function lineChart(points, labels, { height = 132, target = null, hue = "var(--fb-ink)", unit = "%" } = {}) {
  if (!points || points.length < 2) return "";
  const W = 300, H = 100, pad = 3;
  const all = target == null ? points : points.concat([target]);
  const lo = Math.min(...all) - 6, hi = Math.max(...all) + 6;
  const x = (i) => pad + (i / (points.length - 1)) * (W - pad * 2);
  const y = (v) => H - pad - ((v - lo) / (hi - lo)) * (H - pad * 2);
  const line = points.map((p, i) => `${x(i).toFixed(1)},${y(p).toFixed(1)}`).join(" ");
  const last = points[points.length - 1];
  return `<div>
    <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="width:100%; height:${height}px; display:block"
      role="img" aria-label="trend, ${points[0]}${unit} to ${last}${unit}">
      ${target != null ? `<line x1="${pad}" y1="${y(target)}" x2="${W - pad}" y2="${y(target)}"
        stroke="var(--fb-muted)" stroke-width="1" stroke-dasharray="4 3" vector-effect="non-scaling-stroke"></line>` : ""}
      <polygon points="${line} ${W - pad},${H} ${pad},${H}" fill="${hue}" opacity=".08"></polygon>
      <polyline points="${line}" fill="none" stroke="${hue}" stroke-width="1.5" stroke-linecap="round"
        stroke-linejoin="round" vector-effect="non-scaling-stroke"></polyline>
      ${points.map((p, i) => `<circle cx="${x(i)}" cy="${y(p)}" r="${i === points.length - 1 ? 3 : 1.8}"
        fill="${hue}" vector-effect="non-scaling-stroke"></circle>`).join("")}
    </svg>
    <div style="display:flex; justify-content:space-between; margin-top:10px">
      ${labels.map((l, i) => `<span class="fb-data" style="font-size:9.5px; letter-spacing:.8px;
        text-transform:uppercase; color:${i === labels.length - 1 ? "var(--fb-ink)" : "var(--fb-muted)"}">${esc(l)}</span>`).join("")}
    </div>
    <div class="fb-data" style="margin-top:12px; color:var(--fb-muted)">
      now <b style="color:var(--fb-ink)">${last}${unit}</b>${target != null ? ` · target ${target}${unit}` : ""}</div>
  </div>`;
}

/* An arc gauge for a projection. The arc is ink; the shortfall is hairline. */
function gauge(value, sub) {
  const W = 200, H = 108, cx = 100, cy = 96, r = 78;
  const a = (t) => [cx - r * Math.cos(Math.PI * t), cy - r * Math.sin(Math.PI * t)];
  const arc = (from, to) => {
    const [x1, y1] = a(from), [x2, y2] = a(to);
    return `M${x1.toFixed(1)},${y1.toFixed(1)} A${r},${r} 0 0 1 ${x2.toFixed(1)},${y2.toFixed(1)}`;
  };
  return `<div>
    <svg viewBox="0 0 ${W} ${H}" style="width:100%; max-width:240px; height:132px; display:block"
      role="img" aria-label="${value} percent projected">
      <path d="${arc(0, 1)}" fill="none" stroke="var(--fb-hairline)" stroke-width="12"></path>
      <path d="${arc(0, Math.max(0.004, value / 100))}" fill="none" stroke="var(--fb-ink)" stroke-width="12"></path>
    </svg>
    <div style="margin-top:-6px">
      <div class="fb-numeral">${value}<small>%</small></div>
      ${sub ? `<div class="fb-body-sm" style="margin-top:10px">${sub}</div>` : ""}
    </div>
  </div>`;
}

/* Horizontal bars with the value at the end — "where the time went". */
function barRows(rows, { unit = "", hue = "var(--fb-ink)" } = {}) {
  if (!rows.length) return "";
  const peak = Math.max(...rows.map((r) => r.value), 1);
  return `<div style="display:flex; flex-direction:column; gap:12px">
    ${rows.map((r) => `<div class="fb-fn-row" title="${esc(r.title || r.label)}">
      <span class="fb-fn-label" style="overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${esc(r.label)}</span>
      <span class="fb-fn-track"><span style="display:block; height:100%;
        width:${Math.max(2, r.value / peak * 100)}%; background:${r.hue || hue}"></span></span>
      <span class="fb-fn-n">${r.display != null ? r.display : r.value + unit}</span>
    </div>`).join("")}
  </div>`;
}

/* A card in the bento. `span` is columns of six. */
function panel(span, label, note, body, { key = false, tall = false } = {}) {
  return `<div class="fb-card${key ? " fb-card--key" : ""} s${span}${tall ? " tall" : ""}"
      ${tall ? `style="display:flex; flex-direction:column"` : ""}>
    <div style="display:flex; align-items:baseline; justify-content:space-between; gap:12px; margin-bottom:18px">
      <span class="fb-label">${label}</span>
      ${note ? `<span class="fb-data" style="color:var(--fb-muted); font-size:11px">${note}</span>` : ""}
    </div>
    ${body}
  </div>`;
}

function fbEvidence(text) {
  return SHOW_EVIDENCE ? `<div class="fb-evidence">${text}</div>` : "";
}

const ANA_TABS = ["Where you stand", "Pacing", "Trends", "Diagnostics", "Reading", "Spend"];
window.setAnaTab = (i) => { S.anaTab = i; renderProgress(); };

/* ---------------------------------------------------------------- progress */

function renderProgress() {
  const st = S.state;
  if (!st) return;
  const inner = $("progressInner");
  const stats = st.stats;

  /* Study consistency, not mastery — so the dots take ink and hairline, never a
     mastery hue. A future day is an outline: nothing is known about it yet. */
  const weekDots = stats.week.map((d) => `
    <div class="fb-week-day">
      <span class="fb-wdot" style="${d.lit ? "background:var(--fb-ink)"
        : d.future ? "background:transparent; border:1.5px dashed var(--fb-hairline)"
        : "background:var(--fb-hairline)"}"></span>
      <span class="fb-wlbl">${d.day}</span>
    </div>`).join("");

  const fMax = Math.max(1, ...st.forecast.map((f) => f.count));
  const forecastTotal = st.forecast.reduce((a, f) => a + f.count, 0);
  const forecastCols = st.forecast.map((f, i) => `
    <div class="fb-forecast-col">
      <span class="fb-forecast-n">${f.count}</span>
      <div class="fb-forecast-bar" style="height:${Math.max(4, f.count / fMax * 64)}px;
        background:${i === 0 ? "var(--fb-ink)" : "var(--fb-hairline)"}"></div>
      <span class="fb-forecast-day">${i === 0 ? "today" : `+${i}d`}</span>
    </div>`).join("");

  // ---- ordering follows the learning-analytics evidence: a few north-star
  // numbers with reference frames and an action first, then pacing (spacing
  // made visible), then outcome trends, then drill-down diagnostics.
  // Cognitive-load research caps a useful view around 5-9 items per layer.
  const mx = renderMetrics(st.metrics);
  if (!mx) return;   // no metrics payload yet — nothing honest to draw
  const b = st.budget || { daily_minutes: 0, sec_per_card: 84 };
  const fit = b.daily_minutes ? Math.max(1, Math.floor(b.daily_minutes * 60 / b.sec_per_card)) : 0;
  const exams = Object.entries(st.metrics?.exams || {})
    .map(([cid, e]) => ({ ...e, course: st.courses.find((c) => c.id === +cid)?.name || "course" }))
    .filter((e) => e.today != null)
    .sort((a, b2) => a.days_left - b2.days_left);
  const nextExam = exams[0];
  const latest = mx.latestRetention;

  /* Retention as a line, but only where it is actually a line: weeks with no
     graded answers have no rate, and interpolating across them would draw a
     trend that never happened. Below two real points the panel says so. */
  const retPts = mx.retention.filter((r) => r.rate != null);
  const tab = S.anaTab;

  const sections = [];

  // ---------------- 1 · where you stand
  sections[0] = `<div class="fb-bento">
    ${panel(2, "Due now", null, `
      <div class="fb-numeral">${st.dueTotal}</div>
      <div class="fb-body-sm" style="margin-top:12px">across ${st.courses.length} course${st.courses.length === 1 ? "" : "s"}${fit ? ` · a ${b.daily_minutes}m budget has room for about ${fit}` : ""}</div>
      <div style="margin-top:18px">
        <div class="fb-label" style="margin-bottom:10px">Daily budget</div>
        <div class="fb-dur-row">
          ${[15, 25, 45, 60].map((m) => `<button class="fb-dur-btn${b.daily_minutes === m ? " fb-dur-btn--on" : ""}"
            onclick="setBudget(${b.daily_minutes === m ? 0 : m})">${m}m</button>`).join("")}
        </div>
        <div class="fb-data" style="color:var(--fb-muted); font-size:11px; margin-top:8px">${b.sec_per_card}s per card ${b.sec_per_card === 84 ? "(assumed — needs 6 timed answers)" : "(measured)"}</div>
      </div>
      ${fit && st.dueTotal > fit ? `<button class="fb-btn fb-btn--ghost fb-btn--block" style="margin-top:16px" onclick="spreadBacklog()"
          title="Keep the ${fit} most overdue due today; push the other ${st.dueTotal - fit} onto the coming days">Spread ${st.dueTotal - fit} onto later days</button>`
        : st.dueTotal ? `<button class="fb-btn fb-btn--block" style="margin-top:16px" onclick="startReviewSession({})">▶ Start today's review</button>` : ""}`,
      { key: true })}

    ${panel(2, "Exam readiness", nextExam ? esc(nextExam.course) : null, nextExam
      ? gauge(nextExam.onPlan, `Projected recall on exam day if you keep to the schedule.
          ${nextExam.days_left} days left, <b style="color:var(--fb-ink)">${nextExam.today}%</b> if you stop today.`)
        + (exams.length > 1 ? `<div class="fb-data" style="color:var(--fb-muted); font-size:11px; margin-top:10px">${exams.slice(1).map((e) => `${esc(e.course)}: ${e.onPlan}% in ${e.days_left}d`).join(" · ")}</div>` : "")
        + fbEvidence("A goal with a deadline and a projection beats a raw score: it turns 'how am I doing' into 'is this pace enough' (Kluger &amp; DeNisi, 1996).")
      : `<div class="fb-body-sm">No exam dates set. Add one on a course page and this becomes the number that tells you whether the current pace is enough.</div>`)}

    ${panel(2, "Retention right now", "aim 85%", latest
      ? `<div class="fb-numeral">${latest.rate}<small>%</small></div>
         <div class="fb-body-sm" style="margin-top:12px">of cards recalled at review time this week</div>
         ${fbEvidence("True retention is the outcome measure: everything else here is a means to it.")}`
      : `<div class="fb-body-sm">No graded answers yet — review a deck and this fills in.</div>`)}

    ${panel(3, "Knowledge in memory", "decay-weighted", `
      <div class="fb-numeral">${mx.kn.held}<small> / ${mx.kn.total} facts</small></div>
      <div class="fb-body-sm" style="margin-top:12px">${mx.kn.pct}% of your cards, held right now</div>
      ${fbEvidence("Retrievability-weighted total (the FSRS 'knowledge' metric): each card counts as its current recall probability.")}`)}

    ${panel(3, "Card maturity", "all cards", mx.funnelRows
      + fbEvidence("Stability, not just coverage: mature cards (21d+ intervals) are knowledge that survives exams."))}
  </div>`;

  // ---------------- 2 · pacing
  sections[1] = `<div class="fb-bento">
    ${panel(4, "Review forecast · next 7 days", `${forecastTotal} scheduled`, `
      <div class="fb-forecast-row">${forecastCols}</div>
      ${fbEvidence("Spacing effect: each successful recall pushes the next one further out, so daily load stays small (Cepeda et al., 2006).")}`)}

    ${panel(2, "This week", null, `
      <div class="fb-week-dots">${weekDots}</div>
      <div class="fb-body-sm" style="margin-top:16px">
        <b style="color:var(--fb-ink)">${stats.litCount} of the last 7 days</b> · streak ${stats.streak}d</div>
      <div class="fb-numeral fb-numeral--sm" style="margin-top:18px">${esc(stats.weekTime)}</div>
      <div class="fb-body-sm" style="margin-top:10px">in ${stats.sessionCount} session${stats.sessionCount === 1 ? "" : "s"}</div>`,
      { tall: true })}

    ${panel(6, `Study consistency · last ${mx.weeks} weeks`, "volume, not mastery — so it takes no hue", `
      <div class="fb-hm-grid">${mx.heatCols}</div>
      <div class="fb-data" style="color:var(--fb-muted); font-size:11px; margin-top:12px">${mx.activeDays} active days</div>
      ${fbEvidence("Distributed practice: many short sessions beat few long ones (Cepeda et al., 2006).")}`)}

    ${panel(3, "Time by course", "all time", barRows(st.subjectTime.map((r) => ({
      label: r.name, value: r.minutes ?? 0, display: `${r.share}%`, title: `${r.name} · ${r.time}` }))))}

    ${panel(3, "Session length", st.recentSessions.length ? `last ${Math.min(6, st.recentSessions.length)}` : null,
      st.recentSessions.length
        ? barRows(st.recentSessions.slice(0, 6).map((s) => ({
            label: new Date(s.at).toLocaleDateString(undefined, { day: "numeric", month: "short" }),
            value: Math.round(s.minutes || 0), unit: "m", display: fmtMin(s.minutes) })), { unit: "m" })
          + fbEvidence("Short and frequent beats long and rare — the schedule assumes you come back tomorrow.")
        : `<div class="fb-body-sm">No sessions logged yet.</div>`)}
  </div>`;

  // ---------------- 3 · trends
  sections[2] = `<div class="fb-bento">
    ${panel(4, "True retention · by week", "graded answers only", retPts.length >= 2
      ? lineChart(retPts.map((r) => r.rate), retPts.map((r) => r.label), { target: 85, height: 168 })
        + fbEvidence("The trend matters more than any single week — one bad session is noise.")
      : `<div class="fb-body-sm">${retPts.length === 1
          ? `One week has graded answers so far (${retPts[0].rate}% in ${retPts[0].label}). A trend needs at least two.`
          : "No graded answers yet, so there is no trend to draw."}</div>`)}

    ${panel(2, "Card maturity", null, mx.funnelRows
      + fbEvidence("Cards that were never carded are not scheduled at all — coverage is not the same as retention."),
      { tall: true })}
  </div>`;

  // ---------------- 4 · diagnostics
  sections[3] = `<div class="fb-bento">
    ${panel(3, "Hardest cards", "by failures", mx.hardRows
      + fbEvidence("Leeches: a handful of cards eat most of your failures. Blackout them in the reader or rewrite them — don't just keep failing them."))}

    ${panel(3, "Difficulty · the 85% rule", null, mx.sweetBody
      + fbEvidence("~85% success is the optimal difficulty for learning (Wilson et al., 2019; Bjork's desirable difficulties)."))}

    ${panel(4, "Calibration · confidence vs recall", null, renderCalibration(st.calibration)
      + fbEvidence("Comparing predicted vs actual recall improves self-regulated study — and confident errors are the most correctable."))}

    ${panel(2, "Retrieval fluency", "28 days", mx.fluencyBody, { tall: true })}

    ${panel(6, "Recent sessions", "recall per session", renderRecentSessions(st.recentSessions)
      + fbEvidence("Recall per session, not cards per session — volume without recall is time spent, not learning."))}
  </div>`;

  // ---------------- 5 · reading
  sections[4] = `<div class="fb-bento">${readingBandHTML(st)}</div>`;

  // ---------------- 6 · spend (no design counterpart — this app's own)
  sections[5] = `<div class="fb-bento">${spendBandHTML(st)}</div>`;

  inner.innerHTML = `
    <div style="display:flex; align-items:baseline; gap:16px; flex-wrap:wrap">
      <span class="fb-title">Analytics</span>
      <span style="flex:1"></span>
      <span class="fb-data" style="color:var(--fb-muted)">${mx.weeks} weeks of data</span>
    </div>
    <div class="fb-seg" role="tablist" style="align-self:flex-start">
      ${ANA_TABS.map((t, i) => `<button role="tab" aria-selected="${i === tab}"
        onclick="setAnaTab(${i})">${t}</button>`).join("")}
    </div>
    ${sections[tab] || sections[0]}`;
}

/* spend: estimated from logged token usage × list prices. Every number here
   is the app's own accounting, not a bill — labelled as such. */
function spendBandHTML(st) {
  const sp = st.spend;
  if (!sp) return "";
  const usd = (n) => n == null ? "–" : n >= 1 ? `$${n.toFixed(2)}` : `$${n.toFixed(n < 0.01 ? 4 : 3)}`;
  if (!sp.calls) {
    return panel(6, "Spend", null, `<div class="fb-body-sm">No model calls logged yet. Grading, card
      generation, ingestion and the assistant all record their tokens here from now on.</div>`);
  }
  const maxDay = Math.max(0.0001, ...sp.days.map((d) => d.usd));
  const dayCols = sp.days.map((d) => `
    <div class="fb-forecast-col" title="${d.date} · ${usd(d.usd)}">
      <div class="fb-forecast-bar" style="height:${Math.max(3, d.usd / maxDay * 54)}px;
        background:${d.usd ? "var(--fb-ink)" : "var(--fb-hairline)"}"></div>
    </div>`).join("");

  return `
    ${panel(2, "All time", null, `
      <div class="fb-numeral fb-numeral--sm">${usd(sp.total)}</div>
      <div class="fb-body-sm" style="margin-top:10px">${sp.calls} model call${sp.calls === 1 ? "" : "s"}${sp.biggest ? ` · mostly ${esc(sp.biggest)}` : ""}</div>`)}
    ${panel(2, "Last 7 days", null, `
      <div class="fb-numeral fb-numeral--sm">${usd(sp.week)}</div>
      <div class="fb-body-sm" style="margin-top:10px">${usd(sp.today)} today</div>`)}
    ${panel(2, "Unit cost", null, `
      <div style="display:flex; gap:24px">
        <div><div class="fb-numeral fb-numeral--sm" style="font-size:22px">${usd(sp.per_answer)}</div>
          <div class="fb-body-sm" style="margin-top:8px">per graded answer</div></div>
        <div><div class="fb-numeral fb-numeral--sm" style="font-size:22px">${usd(sp.per_card)}</div>
          <div class="fb-body-sm" style="margin-top:8px">per card made</div></div>
      </div>`)}
    ${panel(3, "Where it went", "by purpose", barRows(sp.by_purpose.map((p) => ({
      label: p.purpose, value: p.usd, display: usd(p.usd),
      title: `${p.calls} call${p.calls === 1 ? "" : "s"} · ${p.tokens.toLocaleString()} tokens` }))))}
    ${panel(3, "Last 14 days", null, `<div class="fb-forecast-row">${dayCols}</div>
      ${fbEvidence("Estimated from each call's token counts at published list prices — your provider dashboard is the actual bill. Embeddings and search cost $0 here: they run locally.")}`)}`;
}

function renderCalibration(weeks) {
  const hasData = (weeks || []).some((w) => w.sure_n + w.unsure_n > 0);
  if (!hasData) {
    return `<div class="fb-body-sm">No confidence-tagged answers yet. Pick <em>Sure</em> or
      <em>Unsure</em> before answering during reviews and this chart fills in.</div>`;
  }
  const cols = weeks.map((w) => {
    const bar = (rate, color, n, label) => rate == null
      ? `<div class="fb-cal-bar" style="height:4px; background:var(--fb-hairline)" title="${label}: no data"></div>`
      : `<div class="fb-cal-bar" style="height:${Math.max(4, rate * 0.56)}px; background:${color}"
           title="${label}: ${rate}% recall over ${n} answers"></div>`;
    return `<div class="fb-cal-col">
      <div class="fb-cal-bars">
        ${bar(w.sure_rate, "var(--fb-ink)", w.sure_n, "Sure")}
        ${bar(w.unsure_rate, "var(--fb-hairline)", w.unsure_n, "Unsure")}
      </div>
      <span class="fb-forecast-day">${w.label}</span>
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
  return `<div class="fb-cal-row">${cols}</div>
    <div class="fb-key">
      <span class="fb-key-item"><span class="fb-key-swatch" style="background:var(--fb-ink)"></span>said sure</span>
      <span class="fb-key-item"><span class="fb-key-swatch" style="background:var(--fb-hairline)"></span>said unsure</span>
    </div>
    ${verdict ? `<div class="fb-body-sm" style="margin-top:16px">${verdict}</div>` : ""}`;
}

function renderRecentSessions(sessions) {
  if (!sessions || !sessions.length) {
    return `<div class="fb-body-sm">No sessions yet.</div>`;
  }
  return `<div style="display:flex; flex-direction:column; gap:14px">` + sessions.map((s) => {
    const day = new Date(s.at).toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short" });
    // the bar is the recall rate, so it takes the mastery hue and never ships
    // without the number beside it
    return `<div class="fb-sess-row">
      <span class="fb-data" style="font-size:11px; color:var(--fb-muted); width:78px; flex:none">${day}</span>
      <span class="fb-data" style="font-size:11px; color:var(--fb-muted); width:126px; flex:none">${s.cards} card${s.cards === 1 ? "" : "s"} · ${fmtMin(s.minutes)}</span>
      <span class="fb-sess-track">${s.accuracy == null ? ""
        : `<span style="display:block; height:100%; width:${s.accuracy}%; background:${MASTERY_HUE(s.accuracy)}"></span>`}</span>
      <span class="fb-data" style="font-size:11px; font-weight:600; width:42px; text-align:right; flex:none">${s.accuracy == null ? "—" : s.accuracy + "%"}</span>
    </div>`;
  }).join("") + "</div>";
}

/* ---------------------------------------------------------------- study metrics */

function renderMetrics(mx) {
  if (!mx) return null;

  /* heatmap: one column per week, Monday-first rows. This is VOLUME, not
     mastery, so it takes ink density rather than a hue — a green cell here
     would read as "recalled well", which it does not mean. */
  const shade = (mins) => mins <= 0 ? "var(--fb-hairline)"
    : mins < 10 ? "rgba(10,10,10,.22)" : mins < 25 ? "rgba(10,10,10,.45)"
    : mins < 45 ? "rgba(10,10,10,.7)" : "var(--fb-ink)";
  const cols = [];
  for (let w = 0; w < mx.weeks; w++) {
    const cells = mx.heatmap.slice(w * 7, w * 7 + 7).map((c) => `
      <div class="fb-hm-cell" title="${c.date} · ${c.minutes} min"
        style="${c.future ? "background:transparent" : `background:${shade(c.minutes)}`}"></div>`).join("");
    cols.push(`<div class="fb-hm-col">${cells}</div>`);
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
  const funnelRows = barRows(stages.map(([label, n, color, hint]) => ({
    label, value: n, display: String(n), hue: color, title: `${label} — ${hint}` })));

  const latest = [...mx.retention].reverse().find((r) => r.rate != null);

  // hardest cards
  const hardRows = mx.hardest.length ? `<div style="display:flex; flex-direction:column">
    ${mx.hardest.map((h) => `
    <div style="display:flex; align-items:center; gap:12px; padding:11px 0; border-bottom:1.5px solid var(--fb-hairline)"
         title="${esc(h.topic || "")}">
      <span style="flex:1; font-size:12.5px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${esc(h.question || "(deleted card)")}</span>
      <span class="fb-chip">${h.fails} fail${h.fails === 1 ? "" : "s"}</span>
    </div>`).join("")}</div>`
    : `<div class="fb-body-sm">No repeat-failed cards — nothing is beating you yet.</div>`;

  // knowledge in memory (retrievability-weighted, FSRS-style)
  const kn = mx.knowledge;
  // retrieval fluency: 2×2 of fast/slow (vs personal median) × right/wrong
  const fl = mx.fluency || { n: 0, needed: 6, fluent_pct: null };
  const sec = (ms) => ms == null ? "–" : `${(ms / 1000).toFixed(1)}s`;
  let fluencyBody;
  if (fl.fluent_pct == null) {
    fluencyBody = `<div class="fb-body-sm">Collecting timing data — <b style="color:var(--fb-ink)">${fl.n} of ${fl.needed}</b>
      timed answers. Each question card you answer in a review adds one.</div>`
      + fbEvidence("How fast a correct answer comes predicts retention beyond accuracy alone (Benjamin &amp; Bjork, 1996).");
  } else {
    const q = fl.quads;
    fluencyBody = `
      <div class="fb-numeral fb-numeral--sm">${fl.fluent_pct}<small>%</small></div>
      <div class="fb-body-sm" style="margin-top:10px">fast and correct · right answers take ${sec(fl.pass_ms)}${fl.fail_ms != null ? ` · wrong ${sec(fl.fail_ms)}` : ""}</div>
      <div style="margin-top:14px">${barRows([
        { label: "Fluent", value: q.fluent, display: String(q.fluent), hue: "var(--fb-green)", title: "faster than your median AND correct — strong memories" },
        { label: "Effortful", value: q.effortful, display: String(q.effortful), hue: "var(--fb-yellow)", title: "correct but slower than your median — still fragile, keep spacing" },
        { label: "Hasty miss", value: q.fast_wrong, display: String(q.fast_wrong), hue: "var(--fb-red)", title: "fast but wrong — check for a misconception" },
        { label: "Slow miss", value: q.slow_wrong, display: String(q.slow_wrong), hue: "var(--fb-hairline)", title: "slow and wrong — not there yet" },
      ])}</div>
      ${fbEvidence("How fast a correct answer comes predicts retention beyond accuracy alone (Benjamin &amp; Bjork, 1996) — slow rights are the ones to keep spacing.")}`;
  }

  // sweet spot
  const sw = mx.sweet;
  const sweetBody = sw.rate == null
    ? `<div class="fb-body-sm">Needs 5+ recent answers.</div>`
    : `<div class="fb-numeral">${sw.rate}<small>%</small></div>
       <div class="fb-body-sm" style="margin-top:12px">${
         sw.rate > 95 ? "Right of the band, so your cards are too easy. Harden them or stretch the intervals." :
         sw.rate < 70 ? "Left of the band — overloaded. Smaller sessions, or re-read before reviewing." :
         "Inside the band: the productive-struggle zone."}</div>
       <div class="fb-sweet-track"><div class="fb-sweet-band"></div>
         <div class="fb-sweet-pin" style="left:${Math.min(98, Math.max(2, sw.rate))}%"></div></div>
       <div style="display:flex; justify-content:space-between; margin-top:10px">
         <span class="fb-data" style="font-size:10px; color:var(--fb-muted)">too hard</span>
         <span class="fb-data" style="font-size:10px; color:var(--fb-muted)">too easy</span>
       </div>`;

  /* Raw fragments, not finished cards: the Analytics screen owns the bento
     spans and the panel chrome, so a metric can move between tabs without
     being rewritten. */
  return {
    latestRetention: latest,
    retention: mx.retention,
    weeks: mx.weeks,
    kn, funnelRows, hardRows, sweetBody, fluencyBody,
    heatCols: cols.join(""),
    activeDays,
  };
}

/* ---------------------------------------------------------------- reading hub */

function readingBandHTML(st) {
  const rd = st.reading;
  const notes = Object.values(rd.notes_by_pdf || {}).reduce((a, n) => a + n, 0);
  // documents by minutes read, so "where the reading went" is one bar chart
  const docs = (rd.by_pdf || []).slice().sort((a, b) => b.minutes - a.minutes).slice(0, 8);
  const docName = (e) => {
    for (const c of st.libCourses) {
      const p = c.pdfs.find((x) => x.pdf_id === e.pdf_id);
      if (p) return p.filename.replace(/\.pdf$/i, "");
    }
    return `document ${e.pdf_id}`;
  };

  return `
    ${panel(2, "Time in the reader", "all time", `
      <div class="fb-numeral fb-numeral--sm">${fmtMin(rd.total_minutes)}</div>
      <div class="fb-body-sm" style="margin-top:10px">${fmtMin(rd.week_minutes)} in the last 7 days ·
        ${rd.block_count} block${rd.block_count === 1 ? "" : "s"}${notes ? ` · ${notes} annotation${notes === 1 ? "" : "s"}` : ""}</div>
      ${fbEvidence("Logged from the reader's sidebar timer, attributed to whichever document is open.")}`)}

    ${panel(2, "Reading streak", null, `
      <div class="fb-numeral fb-numeral--sm">${rd.streak_days}<small> day${rd.streak_days === 1 ? "" : "s"}</small></div>
      <div class="fb-body-sm" style="margin-top:10px">${rd.week_blocks} block${rd.week_blocks === 1 ? "" : "s"} this week</div>`)}

    ${panel(2, "By course", "minutes", rd.by_course.length
      ? barRows(rd.by_course.map((r) => ({ label: r.name, value: r.minutes, display: fmtMin(r.minutes) })))
      : `<div class="fb-body-sm">Nothing logged yet.</div>`)}

    ${panel(6, "Where the reading went", "minutes per document", docs.length
      ? barRows(docs.map((e) => ({ label: docName(e), value: e.minutes, display: fmtMin(e.minutes) })))
        + fbEvidence("Flashcard analytics exclude reading on purpose. This tab answers \"am I putting in the hours\"; the others answer \"is retrieval working\". Mastery only ever moves through review.")
      : `<div class="fb-body-sm">No reading blocks logged yet. Open a topic and start a block in the reader's sidebar.</div>`)}`;
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

/* mastery band → hue. Fills only, never type: against white, yellow is 1.8:1
   and green 2.6:1, so a coloured numeral would be illegible. Every bar that
   uses these ships with its percentage beside it. */
const MASTERY_HUE = (pct) => pct >= 75 ? "var(--fb-green)"
  : pct >= 40 ? "var(--fb-yellow)" : "var(--fb-red)";

/* six-week completion sparkline. The domain fits the SERIES, not 0–100 — on a
   0–100 axis a 48→61 rise compresses to three pixels and reads as flat. */
function sparkSVG(points, w = 96, h = 26) {
  if (!points || points.length < 2) return "";
  const lo = Math.min(...points) - 4, hi = Math.max(...points) + 4;
  const y = (p) => (h - ((p - lo) / (hi - lo || 1)) * h).toFixed(1);
  const d = points.map((p, i) => `${((i / (points.length - 1)) * w).toFixed(1)},${y(p)}`).join(" ");
  const last = points[points.length - 1];
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}" style="overflow:visible; flex:none"
      aria-label="six-week trend, ${points[0]}% to ${last}%">
    <polyline points="${d}" fill="none" stroke="var(--fb-ink)" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></polyline>
    <circle cx="${w}" cy="${y(last)}" r="2.5" fill="${last >= points[0] ? "var(--fb-ink)" : "var(--fb-red)"}"></circle>
  </svg>`;
}

/* this week's study dots — CONSISTENCY, not mastery. Green is safe here
   because nothing on the row is a retention value. */
function weekStrip(week) {
  if (!week || !week.length) return "";
  const lit = week.filter(Boolean).length;
  return `<div style="display:flex; align-items:center; gap:6px">
    ${week.map((on, i) => `<span class="${on ? "fb-anim-dot" : ""}" style="width:15px; height:15px; border-radius:4px; --i:${i};
      background:${on ? "var(--fb-green)" : "var(--fb-hairline)"}"></span>`).join("")}
    <span class="fb-data" style="color:var(--fb-muted); margin-left:6px; font-size:11px">${lit} of ${week.length} days</span>
  </div>`;
}

function renderHome() {
  const st = S.state;
  if (!st || S.view !== "home") return;

  /* the course canvas card — the densest card in the system, fixed order: ink
     band names the course, then the one number with its trend, the bar with its
     percentage, this week, what exists, and the consequence. */
  const cards = st.libCourses.map((c) => {
    const s = courseStats(c, st);
    const pct = c.completion != null ? c.completion : s.completion;
    const untouched = !s.cards;
    return `<div class="fb-card" style="padding:0; overflow:hidden; cursor:pointer" role="button" tabindex="0"
        onclick="openCourse(${c.id})" onkeydown="if(event.key==='Enter')openCourse(${c.id})">
      <div style="background:var(--fb-ink); padding:16px 22px; display:flex; align-items:center; gap:12px">
        <span style="flex:1; min-width:0; font-size:16px; font-weight:600; color:#fff">${esc(c.name)}</span>
        ${s.due ? `<span class="fb-chip" style="color:#fff; border-color:rgba(255,255,255,.5); font-weight:600">${s.due} due</span>` : ""}
      </div>
      <div style="padding:22px 24px 24px">
        ${untouched ? `
          <div class="fb-numeral" style="margin-bottom:14px; color:var(--fb-muted)">—</div>
          <div class="fb-bar" style="margin-bottom:18px">
            <div class="fb-bar-track"></div>
            <span class="fb-bar-pct" style="color:var(--fb-muted)">—</span>
          </div>`
        : `
          <div style="display:flex; align-items:flex-end; justify-content:space-between; gap:16px; margin-bottom:14px">
            <div class="fb-numeral">${pct.toFixed(0)}<small>% complete</small></div>
            ${c.trend && c.trend.length > 1 ? `<div style="display:flex; flex-direction:column; align-items:flex-end; gap:6px">
              ${sparkSVG(c.trend)}<span class="fb-label">6 weeks</span></div>` : ""}
          </div>
          <div class="fb-bar" style="margin-bottom:18px">
            <div class="fb-bar-track"><div class="fb-bar-fill" style="width:${pct}%; background:${MASTERY_HUE(pct)}"></div></div>
            <span class="fb-bar-pct">${pct.toFixed(0)}%</span>
          </div>`}
        ${c.week ? `<div style="margin-bottom:18px">${weekStrip(c.week)}</div>` : ""}
        <div class="fb-data" style="color:var(--fb-muted); line-height:1.8">
          ${c.pdfCount} document${c.pdfCount === 1 ? "" : "s"} · ${s.topicsTotal} topics · ${s.cards} cards<br>
          ${untouched ? "no cards generated yet"
            : `${s.covered} covered · ${s.started} in progress · ${fmtMin(s.readMin)} read`}
        </div>
        ${s.exam ? `<div style="margin-top:18px"><span class="fb-chip">Exam in ${s.exam.days_left}d${s.exam.today != null ? ` · ${s.exam.today}% if you stop now` : ""}</span></div>` : ""}
      </div>
    </div>`;
  }).join("");

  const r = S.recap;
  const recap = r ? `<div class="fb-card fb-card--key">
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:14px">
      <span class="fb-label">Last focus block</span>
      <button class="fb-icon-btn" title="Dismiss" onclick="dismissRecap()">✕</button>
    </div>
    <div class="fb-recap-grid">
      <div><div class="fb-recap-num">${r.mins}m</div><div class="fb-recap-lbl">focused</div></div>
      <div><div class="fb-recap-num">${r.cards}</div><div class="fb-recap-lbl">cards</div></div>
      <div><div class="fb-recap-num">${r.acc == null ? "—" : r.acc + "%"}</div><div class="fb-recap-lbl">recall</div></div>
    </div>
    <div class="fb-data" style="color:var(--fb-muted); margin-top:14px">${r.ext} intervals extended · ${r.reset} reset to 1d</div>
  </div>` : "";

  const hour = new Date().getHours();
  const nudge = hour >= 18 && st.dueTotal > 0
    ? `<div class="fb-nudge">It's ${String(hour).padStart(2, "0")}:${String(new Date().getMinutes()).padStart(2, "0")}
       and you've got ${st.dueTotal} cards due. A short review before sleep helps consolidation — even ten minutes counts.</div>` : "";

  $("homeInner").innerHTML = `
    <div class="fb-section-head">
      <span class="fb-label">Courses</span><span class="fb-rule"></span>
      ${visionToggle()}
      ${st.dueTotal ? `<button class="fb-btn" style="padding:8px 14px; font-size:12px"
        onclick="startReviewSession({})" title="Review everything due, capped at your daily budget">▶ Review ${st.dueTotal} due</button>` : ""}
      <button class="fb-btn fb-btn--ghost" style="padding:8px 14px; font-size:12px"
        onclick="pickPdfs()" title="Upload PDFs — they segment into topics and save automatically">＋ Add PDFs</button>
    </div>
    ${S.ingesting ? ingestBanner() : ""}
    ${recap}
    <div class="fb-course-grid">${cards || `<div class="fb-card"><div class="fb-body">No courses yet. Add a PDF and Flashbang will read it, split it into topics with time estimates, and file them here.</div></div>`}</div>
    ${nudge}`;
}

/* opt-in for diagram-heavy decks: read every page as an image instead of
   only the pages whose text came back sparse */
function visionToggle() {
  return `<label class="fb-vision-toggle" title="Default reads only pages with almost no text. Turn this on for slide decks whose content is in the diagrams — a vision model reads every page (~$0.11 per 8 pages).">
    <input type="checkbox" ${S.forceVision ? "checked" : ""} onchange="setForceVision(this.checked)">
    read images on every page</label>`;
}

window.setForceVision = (on) => { S.forceVision = !!on; render(); };

function ingestBanner() {
  return `<div class="fb-card fb-card--sm fb-card--key" style="display:flex; align-items:center; gap:14px">
    <span class="fb-label">Ingesting</span>
    <span class="fb-body-sm" style="flex:1; color:var(--fb-ink)">${esc(S.ingesting.current)} —
      reading, splitting into topics, saving.</span>
    <span class="fb-data" style="color:var(--fb-muted)">${S.ingesting.done + 1} of ${S.ingesting.total}</span>
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

/* one column of the metrics band: mono label, one numeral, then whatever
   qualifies it — a bar, a button, a date input. */
function bandMetric(label, value, unit, body) {
  return `<div>
    <div class="fb-label">${label}</div>
    <div class="fb-band-num">${value}${unit ? `<small>${unit}</small>` : ""}</div>
    ${body}
  </div>`;
}

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

  /* ---- the band: four numbers across the top, so the documents below get the
     full width. The evidence line sits under a hairline INSIDE the card — the
     band doesn't get an exemption from the rule that a derived number carries
     its reasoning. */
  const untouched = !s.cards;
  const band = `<div class="fb-card fb-card--key" style="padding:0">
    <div class="fb-band">
      ${bandMetric("Completion", untouched ? "—" : s.completion.toFixed(0), untouched ? "" : "%", `
        <div class="fb-bar" style="margin-top:14px">
          <div class="fb-bar-track">${untouched ? "" : `<div class="fb-bar-fill" style="width:${s.completion}%; background:${MASTERY_HUE(s.completion)}"></div>`}</div>
          <span class="fb-bar-pct"${untouched ? ` style="color:var(--fb-muted)"` : ""}>${untouched ? "—" : `${s.completion.toFixed(0)}%`}</span>
        </div>
        <div class="fb-body-sm" style="margin-top:10px">${untouched ? "no cards generated yet"
          : `${s.covered} of ${s.topicsTotal} covered · ${s.started} in progress`}</div>`)}

      ${bandMetric("Due now", s.due, "", `
        <div class="fb-body-sm" style="margin-top:10px">of ${s.cards} card${s.cards === 1 ? "" : "s"} in this course</div>
        <button class="fb-btn fb-btn--block" style="margin-top:14px" ${s.due ? "" : "disabled"}
          onclick="startReviewSession({ course_id: ${c.id} })">▶ Review this course</button>`)}

      ${bandMetric("Time invested", c.timeSpent, "", `
        <div class="fb-body-sm" style="margin-top:10px">on flashcards</div>
        <div class="fb-data" style="margin-top:12px; color:var(--fb-muted); line-height:1.7">
          ${fmtMin(s.readMin)} reading<br>${s.notes} note${s.notes === 1 ? "" : "s"}</div>`)}

      ${bandMetric("Exam readiness",
        s.exam && s.exam.onPlan != null ? s.exam.onPlan : "—",
        s.exam && s.exam.onPlan != null ? "%" : "", `
        ${s.exam && s.exam.today != null
          ? `<div class="fb-body-sm" style="margin-top:10px">${s.exam.days_left} days left ·
              <b style="color:var(--fb-ink)">${s.exam.today}%</b> if you stop today</div>`
          : s.exam
          ? `<div class="fb-body-sm" style="margin-top:10px">${s.exam.days_left} days left — generate some cards to get a projection.</div>`
          : `<div class="fb-body-sm" style="margin-top:12px">Set a date and you'll get a projected exam-day recall.</div>`}
        <input type="date" class="fb-select" value="${courseInfo?.exam_date || ""}"
          style="font-family:var(--fb-mono); font-size:11px; margin-top:12px; width:100%"
          title="Exam date — drives the readiness projection" onchange="setExam(${c.id}, this.value)">`)}
    </div>
    <div style="padding:0 26px 20px">
      <div class="fb-evidence" style="margin-top:0">Completion is retrieval-weighted, so a topic only counts
        once its cards are actually recalled, not once it has been read — which is also why the reading
        time below is kept apart from it.</div>
    </div>
  </div>`;

  /* ---- documents: a disclosure each, two up. Closed it's a filename and its
     counts; open it's the topic list, or the split editor over the same rows. */
  const docBlocks = docs.map((p) => {
    const open = S.docOpen.has(p.pdf_id);
    const readMin = rd.by_pdf?.find((e) => e.pdf_id === p.pdf_id)?.minutes || 0;
    const notes = rd.notes_by_pdf?.[p.pdf_id] || 0;
    const editing = S.editSplit === p.pdf_id;
    const sel = [...S.readSel].map((id) => p.topics.find((t) => t.id === id)).filter(Boolean);

    let body = "";
    if (open && editing) {
      const inp = `border:var(--fb-border); border-radius:var(--fb-r-button); padding:6px 8px;
        font-family:var(--fb-sans); font-size:12.5px; color:var(--fb-ink)`;
      body = `<div class="fb-body-sm" style="padding:12px 0 4px">Your split, your rules — ranges may overlap
          or leave gaps. Splitting keeps existing cards with the original topic.</div>`
        + p.topics.map((t) => {
          const [ps, pe] = t.pages.split("-").map(Number);
          return `<div class="fb-split-row ts-row" data-id="${t.id}">
            <input class="ts-title" style="${inp}; flex:1; min-width:140px" value="${esc(t.title)}" aria-label="Topic title">
            <input class="ts-start" type="number" min="1" value="${ps}" aria-label="First page" style="${inp}; width:58px; font-family:var(--fb-mono)">
            <span style="color:var(--fb-muted)">–</span>
            <input class="ts-end" type="number" min="1" value="${pe}" aria-label="Last page" style="${inp}; width:58px; font-family:var(--fb-mono)">
            <select class="ts-kind fb-select" aria-label="Topic kind">
              <option value="content" ${t.kind !== "general" ? "selected" : ""}>content</option>
              <option value="general" ${t.kind === "general" ? "selected" : ""}>general</option>
            </select>
            <button class="fb-btn" style="padding:6px 12px; font-size:11.5px" onclick="saveTopicEdit(${t.id}, this)">Save</button>
            <button class="fb-btn fb-btn--ghost" style="padding:6px 12px; font-size:11.5px"
              title="Split into two at a page" onclick="splitTopicAsk(${t.id}, ${ps}, ${pe})">Split…</button>
            <button class="fb-icon-btn" title="Delete this topic and its ${t.cards_total} card${t.cards_total === 1 ? "" : "s"}"
              onclick="deleteTopicAsk(${t.id}, '${encT(t.title)}', ${t.cards_total})">✕</button>
          </div>`;
        }).join("");
    } else if (open && p.topics.length) {
      body = `<div style="margin-top:12px">`
        + (sel.length ? `<a class="fb-btn fb-btn--block" style="margin-bottom:10px; text-align:center; text-decoration:none"
            href="/api/pdf/${p.pdf_id}/slice?ranges=${sel.map((t) => t.pages).join(",")}" download>
            ⬇ ${sel.length} topic${sel.length === 1 ? "" : "s"} as one PDF</a>` : "")
        + p.topics.map((t) => {
          const general = t.kind === "general";
          return `<div class="fb-topic-row" style="cursor:pointer" title="Open p.${t.pages} in the reader"
              onclick="openTopic(${p.pdf_id}, ${t.pages.split("-")[0]}, ${t.pages.split("-")[1]}, '${encT(t.title)}', ${t.id})">
            <input type="checkbox" class="fb-topic-check" title="Tick topics, then download them together as one PDF"
              onclick="event.stopPropagation(); toggleReadSel(${t.id})" ${S.readSel.has(t.id) ? "checked" : ""}>
            <span class="fb-dot" style="background:${general ? "var(--fb-hairline)" : MASTERY_HUE(t.mastery_pct)}"></span>
            <span style="flex:1; min-width:0">
              <span class="fb-topic-title" style="display:block; font-weight:500">${esc(t.title)}</span>
              <span class="fb-doc-meta">p.${t.pages} · ~${fmtMin(t.est_minutes)}${general ? "" : ` · ${t.mastery_pct.toFixed(0)}%`}</span>
            </span>
            ${t.cards_due ? `<span class="fb-chip fb-chip--due">${t.cards_due} due</span>` : ""}
            ${general ? `<span class="fb-chip" style="color:var(--fb-muted); font-size:10px; letter-spacing:.8px; text-transform:uppercase">info</span>`
              : t.cards_total ? `<span class="fb-data" style="color:var(--fb-muted); flex:none">${t.cards_total} cards</span>`
              : `<button class="fb-btn fb-btn--ghost" style="padding:5px 10px; font-size:11px; flex:none"
                  title="Generate flashcards for this topic (~$0.05, ~30s)"
                  onclick="event.stopPropagation(); generateCards(${t.id}, this)">Make cards</button>`}
          </div>`;
        }).join("")
        + `</div>`;
    } else if (open) {
      body = `<div class="fb-body-sm" style="margin-top:12px">Ingest didn't finish for this document, so it has
        no topics yet. Delete it and add it again, and Flashbang will read, split and file it.</div>`;
    }

    return `<div class="fb-card fb-card--sm">
      <div style="display:flex; align-items:flex-start; gap:12px; cursor:pointer" onclick="toggleDoc(${p.pdf_id})">
        <span style="flex:none; width:14px; color:var(--fb-muted); font-family:var(--fb-mono); font-size:11px; line-height:20px">${open ? "▾" : "▸"}</span>
        <span style="flex:1; min-width:0">
          <span class="fb-doc-name" style="display:block; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${esc(p.filename)}</span>
          <span class="fb-doc-meta" style="display:block">${p.total_pages}p · ${p.topics.length} topics · ${fmtMin(readMin)} read${notes ? ` · ${notes} note${notes === 1 ? "" : "s"}` : ""}</span>
        </span>
        ${p.status === "pending" ? `<span class="fb-chip" style="color:var(--fb-red); border-color:var(--fb-red)">Ingest incomplete</span>` : ""}
        ${p.due ? `<span class="fb-chip fb-chip--due">${p.due} due</span>` : ""}
        ${open && p.topics.length ? `<button class="fb-btn${editing ? "" : " fb-btn--ghost"}" style="padding:5px 10px; font-size:11px; flex:none"
          title="Rename topics, fix page ranges, split or delete"
          onclick="event.stopPropagation(); toggleEditSplit(${p.pdf_id})">✎ Split</button>` : ""}
        <button class="fb-icon-btn" title="Delete this document and everything under it"
          onclick="event.stopPropagation(); deletePdf(${p.pdf_id}, '${encT(p.filename)}')">✕</button>
      </div>
      ${body}
    </div>`;
  }).join("");

  /* ---- reading: where the hours went, kept below the documents because the
     band had no room for it and dropping a metric is the worse trade. */
  const perDoc = docs.map((p) => ({
    name: p.filename.replace(/\.pdf$/i, ""),
    min: rd.by_pdf?.find((e) => e.pdf_id === p.pdf_id)?.minutes || 0,
    notes: rd.notes_by_pdf?.[p.pdf_id] || 0,
    last: rd.by_pdf?.find((e) => e.pdf_id === p.pdf_id)?.last_read,
  })).sort((a, b) => b.min - a.min);
  const read = perDoc.filter((d) => d.min > 0);
  const maxMin = Math.max(1, ...perDoc.map((d) => d.min));
  const lastRead = read.map((d) => d.last).filter(Boolean).sort().pop();

  const reading = `<div class="fb-card">
    <div class="fb-label" style="margin-bottom:18px">Reading · this course</div>
    ${read.length ? `
      <div class="fb-read-split">
        <div style="display:flex; flex-direction:column; gap:12px">
          ${read.slice(0, 6).map((d) => `
            <div class="fb-fn-row" title="${esc(d.name)}${d.notes ? ` · ${d.notes} notes` : ""}">
              <span class="fb-fn-label" style="width:112px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap">${esc(d.name)}</span>
              <span class="fb-fn-track"><span style="display:block; height:100%; width:${Math.max(3, d.min / maxMin * 100)}%; background:var(--fb-ink)"></span></span>
              <span class="fb-fn-n">${fmtMin(d.min)}</span>
            </div>`).join("")}
        </div>
        <div>
          <div class="fb-body-sm">${read.length} of ${docs.length} documents opened${lastRead
            ? ` · last read ${new Date(lastRead).toLocaleDateString(undefined, { day: "numeric", month: "short" })}` : ""}</div>
          <div class="fb-evidence">Reading time is tracked apart from recall on purpose: hours in the PDF
            never move mastery — only retrieval does.</div>
        </div>
      </div>`
    : `<div class="fb-body-sm">No reading blocks logged for this course yet. Open a topic and start a block
        in the reader's sidebar.</div>`}
  </div>`;

  $("courseInner").innerHTML = `
    <div style="display:flex; align-items:center; gap:16px">
      <div class="fb-crumbs">
        <button class="fb-crumb" onclick="goHome()">Courses</button>
        <span class="fb-crumb-sep">›</span>
        <span class="fb-crumb fb-crumb--on">${esc(c.name)}</span>
      </div>
      <span style="flex:1"></span>
      ${visionToggle()}
      <button class="fb-btn fb-btn--ghost" style="padding:8px 14px; font-size:12px"
        onclick="pickPdfs()" title="Upload PDFs straight into ${esc(c.name)}">＋ Add PDFs</button>
    </div>
    ${S.ingesting ? ingestBanner() : ""}
    ${band}
    <div>
      <div class="fb-section-head" style="margin-bottom:18px">
        <span class="fb-label">Documents &amp; topics · click a topic to read</span>
        <span class="fb-rule"></span>
      </div>
      ${docs.length ? `<div class="fb-doc-grid">${docBlocks}</div>`
        : `<div class="fb-card"><div class="fb-body-sm">Nothing in this course yet. Hit ＋ Add PDFs and
            Flashbang will read, split and file them for you.</div></div>`}
    </div>
    ${reading}`;
}

/* ---- assistant bubble: a scoped agent, only when you open it ---- */
window.toggleAsst = () => {
  const open = $("asstPanel").style.display === "none";
  $("asstPanel").style.display = open ? "flex" : "none";
  $("asstBubble").classList.toggle("fb-asst-bubble--on", open);
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
  // keep the editor on the same card across a reload where that card survives;
  // otherwise open the first, so the right pane is never pointlessly empty
  if (!cards.some((c) => c.id === S.cardSel)) S.cardSel = cards.length ? cards[0].id : null;
  renderCardsScreen();
}

/* topics grouped under a bold header per source pdf (optgroup renders bold).
   Module scope, not inside renderCardsScreen: the editor pane re-renders on
   its own and needs to build the same select. */
function groupedTopicOptions(topics, selectedId) {
  const pdfName = {};
  (S.state?.libCourses || []).forEach((c) => c.pdfs.forEach((p) => { pdfName[p.pdf_id] = p.filename; }));
  const groups = new Map();
  topics.forEach((t) => {
    if (!groups.has(t.pdf_id)) groups.set(t.pdf_id, []);
    groups.get(t.pdf_id).push(t);
  });
  return [...groups.entries()].map(([pid, list]) => `
    <optgroup label="${esc(pdfName[pid] || `document ${pid}`)}">
      ${list.map((t) => `<option value="${t.id}" ${selectedId === t.id ? "selected" : ""}>${esc(t.title)}</option>`).join("")}
    </optgroup>`).join("");
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
  const pdfTopics = S.cardTopics.filter((t) => !f.pdf_id || t.pdf_id === f.pdf_id);
  const topicOpts = [`<option value="">All topics</option>`,
    groupedTopicOptions(pdfTopics, f.topic_id)];

  // new-card form: topic select (grouped by pdf, defaults to the active filter)
  const newCardBox = S.showNewCard ? `
    <div class="fb-card fb-card--key fb-editor" id="newCard">
      <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
        <span class="fb-label">New card</span>
        <select class="fb-select" id="ncTopic">${groupedTopicOptions(S.cardTopics, f.topic_id)}</select>
        <span style="flex:1"></span>
        <button class="fb-btn" style="padding:6px 12px; font-size:11.5px" id="ncCreate">Create</button>
        <button class="fb-icon-btn" id="ncCancel" title="Cancel">✕</button>
      </div>
      <textarea id="ncQ" rows="2" placeholder="Question…"></textarea>
      <textarea id="ncA" rows="3" placeholder="Answer…"></textarea>
      <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
        <span class="fb-body-sm">Files under the chosen topic — its PDF and course link automatically. First review: tomorrow.</span>
        <span id="ncMsg" class="fb-data" style="font-size:11px; color:var(--fb-red)"></span>
      </div>
    </div>` : "";

  // paste-import panel (NotebookLM output, Anki exports, hand lists)
  const ip = S.importPreview;
  const previewRows = ip && ip.cards.length ? `<div style="margin-top:4px">` + ip.cards.slice(0, 8).map((c, i) => `
    <div style="display:flex; gap:10px; font-size:12px; line-height:1.55; padding:9px 0; border-top:1.5px solid var(--fb-hairline)">
      <span class="fb-data" style="color:var(--fb-muted); flex:none">${i + 1}.</span>
      <span style="flex:1"><b>${esc(c.question)}</b><br><span style="color:var(--fb-slate)">${esc(c.answer)}</span></span>
    </div>`).join("") + (ip.cards.length > 8
      ? `<div class="fb-data" style="font-size:11px; color:var(--fb-muted); padding-top:8px">…and ${ip.cards.length - 8} more</div>` : "") + `</div>` : "";
  const importBox = S.showImport ? `
    <div class="fb-card fb-card--key fb-editor" id="importCard">
      <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
        <span class="fb-label">Import cards</span>
        <select class="fb-select" id="imTopic">${groupedTopicOptions(S.cardTopics, f.topic_id)}</select>
        <span style="flex:1"></span>
        <button class="fb-btn fb-btn--ghost" style="padding:6px 12px; font-size:11.5px" id="imPreview">Preview</button>
        <button class="fb-btn" style="padding:6px 12px; font-size:11.5px" id="imInsert" ${ip && ip.cards.length ? "" : "disabled"}>Add ${ip ? ip.cards.length : 0} cards</button>
        <button class="fb-icon-btn" id="imCancel" title="Close">✕</button>
      </div>
      <textarea id="imText" rows="6" placeholder="Paste flashcards here — NotebookLM output, Q:/A: pairs, or one card per line with a TAB, ' :: ', ';;' or '|' between question and answer.">${esc(S.importText)}</textarea>
      <div class="fb-body-sm" id="imMsg">${
        ip ? (ip.cards.length
          ? `${ip.cards.length} card${ip.cards.length === 1 ? "" : "s"} ${ip.source === "ai" ? "AI-parsed — read them before adding" : "parsed"} · they file under the chosen topic, first review tomorrow`
          : "Nothing parsed — check the format or add Q:/A: markers.")
        : "Preview parses without saving. Clean formats parse instantly; free-form text falls back to one cheap AI call."}</div>
      ${previewRows}
    </div>` : "";

  inner.innerHTML = `
    <div class="fb-section-head">
      <span class="fb-label">Cards</span><span class="fb-rule"></span>
      <span class="fb-data" style="color:var(--fb-muted); font-size:11px">${S.cards.length} shown</span>
      <button id="importBtn" class="fb-btn fb-btn--ghost" style="padding:8px 14px; font-size:12px">⇪ Import</button>
      <button id="newCardBtn" class="fb-btn fb-btn--ghost" style="padding:8px 14px; font-size:12px">＋ New card</button>
    </div>
    <div style="display:flex; gap:10px; flex-wrap:wrap">
      <select id="cfCourse" class="fb-select">${courseOpts.join("")}</select>
      <select id="cfPdf" class="fb-select">${pdfOpts.join("")}</select>
      <select id="cfTopic" class="fb-select">${topicOpts.join("")}</select>
    </div>
    ${importBox}
    ${newCardBox}
    <div class="fb-cards-split">
      <div id="cardList" style="display:flex; flex-direction:column"></div>
      <div id="cardEditor"></div>
    </div>`;

  renderCardList();
  renderCardEditor();

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

}

/* The list. Colour here is INTERVAL MATURITY, not retention — there is no
   per-card recall probability to show, and the interval sits in the same row
   so the square never travels without its number. */
const CARD_MATURITY = (days, reps) => !reps ? { hue: "var(--fb-hairline)", label: "new" }
  : days < 7 ? { hue: "var(--fb-red)", label: "learning" }
  : days < 21 ? { hue: "var(--fb-yellow)", label: "young" }
  : { hue: "var(--fb-green)", label: "mature" };

function renderCardList() {
  const list = $("cardList");
  if (!list) return;
  if (!S.cards.length) {
    list.innerHTML = `<div class="fb-card fb-card--sm"><div class="fb-body-sm">No cards match this filter —
      make some from a topic's ⚡ Cards button on a course page, or use ＋ New card.</div></div>`;
    return;
  }
  list.innerHTML = S.cards.map((c) => {
    const m = CARD_MATURITY(c.interval_days, c.repetitions);
    const due = c.next_review
      ? new Date(c.next_review).toLocaleDateString(undefined, { day: "numeric", month: "short" }) : "—";
    const on = S.cardSel === c.id;
    return `<div class="fb-card-row${on ? " fb-card-row--on" : ""}" data-id="${c.id}" role="button" tabindex="0"
        onclick="selectCard(${c.id})" onkeydown="if(event.key==='Enter')selectCard(${c.id})">
      <span class="fb-card-dot" style="background:${m.hue}" title="${m.label} · interval ${c.interval_days}d"></span>
      <span style="flex:1; min-width:0">
        <span class="fb-card-q">${esc(c.question)}</span>
        <span class="fb-doc-meta" style="display:block">${esc(c.topic_title)} · ${c.interval_days}d · due ${due}</span>
      </span>
    </div>`;
  }).join("");
}

/* The editor. It never moves when you pick another card — that steadiness is
   the whole reason for the two-pane split, so selecting re-renders THIS pane
   and the list's selected class, never the screen. */
function renderCardEditor() {
  const box = $("cardEditor");
  if (!box) return;
  const c = S.cards.find((x) => x.id === S.cardSel);
  if (!c) {
    box.innerHTML = `<div class="fb-card"><div class="fb-body-sm">Pick a card on the left to edit it.
      The editor stays put as you move between cards.</div></div>`;
    return;
  }
  const due = (c.next_review || "").slice(0, 10);
  box.innerHTML = `<div class="fb-card fb-editor">
    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
      <span class="fb-data" style="color:var(--fb-muted); font-size:11px">#${c.id} · ${esc(c.course_name)}</span>
      <span style="flex:1"></span>
      <span class="fb-chip">interval ${c.interval_days}d</span>
      <span class="fb-chip">due ${due}</span>
    </div>
    <div>
      <div class="fb-label" style="margin-bottom:8px">Question</div>
      <textarea class="ce-q" rows="3">${esc(c.question)}</textarea>
    </div>
    <div>
      <div class="fb-label" style="margin-bottom:8px">Answer</div>
      <textarea class="ce-a" rows="5">${esc(c.answer)}</textarea>
    </div>
    <div style="display:flex; align-items:center; gap:10px; flex-wrap:wrap">
      <select class="fb-select ce-topic" title="Move to topic">${groupedTopicOptions(S.cardTopics, c.topic_id)}</select>
      <span style="flex:1"></span>
      <button class="fb-btn ce-save" style="padding:8px 16px" disabled>Save</button>
      <button class="fb-icon-btn ce-del" title="Delete card permanently">Delete</button>
    </div>
    ${fbEvidence("Editing the wording never resets the schedule — interval, due date and FSRS state are left exactly as they were, because a typo fix is not a failed recall.")}
  </div>`;

  const saveBtn = box.querySelector(".ce-save");
  const changed = () =>
    box.querySelector(".ce-q").value !== c.question ||
    box.querySelector(".ce-a").value !== c.answer ||
    +box.querySelector(".ce-topic").value !== c.topic_id;
  box.addEventListener("input", () => { saveBtn.disabled = !changed(); });
  box.querySelector(".ce-topic").addEventListener("change", () => { saveBtn.disabled = !changed(); });

  saveBtn.onclick = async () => {
    saveBtn.textContent = "Saving…";
    const body = {
      question: box.querySelector(".ce-q").value,
      answer: box.querySelector(".ce-a").value,
      topic_id: +box.querySelector(".ce-topic").value,
    };
    const res = await fetch(`/api/cards/${c.id}`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    if (!res.ok) { saveBtn.textContent = "Failed — retry"; return; }
    Object.assign(c, body);          // keep the row and the dirty check in step
    saveBtn.textContent = "Saved ✓";
    saveBtn.disabled = true;
    renderCardList();                // the question may have changed in the list
    setTimeout(() => { if (saveBtn.isConnected) saveBtn.textContent = "Save"; }, 1600);
  };
  box.querySelector(".ce-del").onclick = async () => {
    if (!confirm("Delete this card permanently?")) return;
    await fetch(`/api/cards/${c.id}`, { method: "DELETE" });
    S.cardSel = null;
    loadCards();
  };
}

window.selectCard = (id) => {
  S.cardSel = id;
  // only the row classes and the editor change — the screen does not re-render
  document.querySelectorAll("#cardList .fb-card-row").forEach((r) =>
    r.classList.toggle("fb-card-row--on", +r.dataset.id === id));
  renderCardEditor();
};

/* ---------------------------------------------------------------- shell */

function render() {
  const st = S.state;
  if (!st) return;
  $("dueTotal").textContent = st.dueTotal;
  $("doNext").title = st.best
    ? `Weakest due topic: ${st.best.title} (${st.best.pct.toFixed(0)}% retention)` : "All caught up";
  // the session label belongs to the review driver — it counts the deal
  // (`· card 3 of 6`), which a render pass has no business overwriting
  $("tabHome").classList.toggle("fb-nav-item--on", S.view === "home" || S.view === "course");
  $("tabStudy").classList.toggle("fb-nav-item--on", S.view === "study");
  $("tabProgress").classList.toggle("fb-nav-item--on", S.view === "progress");
  $("tabCards").classList.toggle("fb-nav-item--on", S.view === "cards");
  $("navDue").textContent = st.dueTotal;
  $("navDue").style.display = st.dueTotal ? "" : "none";
  $("homeScreen").style.display = S.view === "home" ? "block" : "none";
  $("courseScreen").style.display = S.view === "course" ? "block" : "none";
  $("studyScreen").style.display = S.view === "study" ? "flex" : "none";
  $("progressScreen").style.display = S.view === "progress" ? "block" : "none";
  $("cardsScreen").style.display = S.view === "cards" ? "block" : "none";
  $("readerScreen").style.display = S.view === "reader" ? "flex" : "none";
  // review screen: decks until a session starts, the chat while it runs, then
  // the report — three states, one on screen at a time
  $("reviewHome").style.display = S.reviewView === "decks" ? "flex" : "none";
  $("chatPane").style.display = S.reviewView === "chat" ? "flex" : "none";
  $("reviewReport").style.display = S.reviewView === "report" ? "block" : "none";
  renderHome();
  renderCoursePage();
  renderReviewHome();
  renderSessionReport();
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
  $("sideNav").classList.toggle("fb-nav--closed", !S.navOpen);
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
    S._tick = setInterval(() => {
      // timestamps, not tick counts — throttled background tabs must not drift
      const elapsedSec = Math.floor((Date.now() - S.focusStart) / 1000);
      const elapsed = Math.floor(elapsedSec / 60);
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
  if (!side || S.view !== "reader") return;
  AN.pendingText = $("annInput")?.value ?? AN.pendingText;   // survive re-renders
  const running = !!S.focusStart;
  const remain = running ? Math.max(0, S.sessionLen * 60 - Math.floor((Date.now() - S.focusStart) / 1000)) : S.sessionLen * 60;
  const timer = `
    <div class="fb-label">Reading block</div>
    ${running ? `
      <div class="fb-read-timer" id="readRemain">${Math.floor(remain / 60)}:${String(remain % 60).padStart(2, "0")}</div>
      <div class="fb-body-sm">of a ${S.sessionLen}-min block</div>
      <div class="fb-bar-track">
        <div id="readBar" class="fb-bar-fill" style="width:${Math.min(100, (1 - remain / (S.sessionLen * 60)) * 100)}%; background:var(--fb-ink); transition:width 1s linear"></div>
      </div>
      <button class="fb-btn fb-btn--ghost fb-btn--block" onclick="toggleFocus()">End early</button>
    ` : `
      ${S.blockDone ? `<div class="fb-body-sm" style="color:var(--fb-ink); font-weight:600">Block logged ✓</div>
        <div class="fb-body-sm">It lands in your Reading hub, separate from flashcard time.</div>` : ""}
      <div class="fb-dur-row">
        ${[15, 25, 45].map((m) => `<button class="fb-dur-btn${S.sessionLen === m ? " fb-dur-btn--on" : ""}" onclick="pickLen(${m})">${m}m</button>`).join("")}
      </div>
      <button class="fb-btn fb-btn--block" onclick="toggleFocus('reading')">Start ${S.sessionLen}-min block</button>
    `}`;

  const pageNotes = AN.items.filter((a) => a.page === RD.page);
  const notes = `
    <div class="fb-label" style="margin-top:8px">Notes · page ${RD.page ?? "–"}</div>
    ${AN.pending ? `
      <div class="fb-note-item">
        <textarea id="annInput" rows="3" placeholder="Your comment for the boxed area…"
          style="width:100%; border:var(--fb-border); border-radius:var(--fb-r-button); padding:8px 10px;
          font-family:var(--fb-sans); font-size:12.5px; line-height:1.6; resize:vertical">${esc(AN.pendingText)}</textarea>
        <div style="display:flex; gap:6px; margin-top:8px">
          <button class="fb-btn" style="flex:1; padding:7px; font-size:11.5px" onclick="saveAnnotation()">Save note</button>
          <button class="fb-btn fb-btn--ghost" style="padding:7px 12px; font-size:11.5px" onclick="cancelAnnotation()">✕</button>
        </div>
      </div>` : ""}
    ${pageNotes.map((a, i) => `
      <div class="fb-note-item" id="note-${a.id}" onclick="flashAnnBox(${a.id})" title="Click to locate the box">
        <div style="display:flex; align-items:baseline; gap:8px">
          <span class="fb-note-num">${i + 1}</span>
          <span style="flex:1; font-size:12px; line-height:1.55">${esc(a.comment)}</span>
          <button class="fb-icon-btn" style="font-size:11px; flex:none" title="Delete this note"
            onclick="event.stopPropagation(); deleteAnnotation(${a.id})">✕</button>
        </div>
      </div>`).join("")}
    ${!pageNotes.length && !AN.pending ? `<div class="fb-body-sm">
      No notes on this page yet. Hit <b>✎ Note</b> and drag a box over anything worth a comment.</div>` : ""}`;

  const exporter = RD.mode ? `
    <div class="fb-label" style="margin-top:8px">Take p.${RD.start}–${RD.end} elsewhere</div>
    <div style="display:flex; gap:6px">
      <button class="fb-btn fb-btn--ghost" style="flex:1; padding:7px; font-size:11.5px" id="copyTopicBtn" onclick="copyTopicText()">⧉ Copy text</button>
      <a class="fb-btn fb-btn--ghost" style="flex:1; padding:7px; font-size:11.5px; text-align:center; text-decoration:none"
         href="/api/pdf/${RD.pdfId}/slice?start=${RD.start}&end=${RD.end}" download>⬇ PDF pages</a>
    </div>
    <div class="fb-body-sm" style="font-size:11px">For NotebookLM &amp; friends — and bring its flashcards home via Cards → Import.</div>` : "";

  side.innerHTML = timer + notes + exporter;

  // the header chip mirrors the block timer, so the rail can collapse without
  // hiding the fact that a block is running
  const chip = $("rdTimer");
  if (chip) {
    chip.style.display = running ? "inline-flex" : "none";
    if (running) chip.textContent = `${Math.floor(remain / 60)}:${String(remain % 60).padStart(2, "0")}`;
  }
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
  const el = document.querySelector(`.fb-ann[data-ann="${annId}"]`);
  if (!el) return;
  el.scrollIntoView({ block: "center", behavior: "smooth" });
  el.classList.add("fb-ann--flash");
  setTimeout(() => el.classList.remove("fb-ann--flash"), 1200);
};

/* ---------------------------------------------------------------- topic page viewer */

const pdfDocCache = {};

/* blackout (image occlusion): draw black boxes over key facts, recall, peek.
   Coords stored 0-1 relative to the page box so any render width works. */
const BO = { pdfId: null, boxes: [], edit: false, revealAll: false };
/* annotations: comments anchored to outlined "window boxes" on a page */
const AN = { items: [], mode: false, pending: null, pendingText: "" };
/* reader: one page at a time */
/* reader: continuous scroll, two independently collapsible rails */
const RD = { pdfId: null, title: "", start: null, end: null, page: null,
             mode: null, textPages: null, seq: 0,
             railL: true, railR: true, full: false, backView: "course",
             io: null, spy: null, tio: null };

function syncModes() {
  $("blackoutToggle").classList.toggle("fb-icon-btn--on", BO.edit);
  $("blackoutReveal").classList.toggle("fb-icon-btn--on", BO.revealAll);
  $("annToggle").classList.toggle("fb-icon-btn--on", AN.mode);
  document.querySelectorAll("#rdPages .fb-page-wrap").forEach((w) => {
    w.dataset.mode = BO.edit ? "blackout" : AN.mode ? "note" : "";
  });
}

function renderBox(wrap, b) {
  const el = document.createElement("div");
  el.className = "fb-blackout";
  el.title = "Recall what's under here, then click to peek (blackout mode: click deletes)";
  Object.assign(el.style, { left: `${b.x * 100}%`, top: `${b.y * 100}%`,
    width: `${b.w * 100}%`, height: `${b.h * 100}%` });
  if (BO.revealAll) el.classList.add("fb-blackout--peek");
  el.onclick = async (e) => {
    e.stopPropagation();
    if (BO.edit) {
      const res = await fetch(`/api/occlusions/${b.id}`, { method: "DELETE" });
      if (res.ok) { BO.boxes = BO.boxes.filter((x) => x.id !== b.id); el.remove(); }
    } else {
      el.classList.toggle("fb-blackout--peek");
    }
  };
  wrap.appendChild(el);
}

function renderAnnBoxes(wrap, page) {
  const n = page ?? +wrap.dataset.page;
  wrap.querySelectorAll(".fb-ann:not(.fb-ann--pending)").forEach((el) => el.remove());
  AN.items.filter((a) => a.page === n).forEach((a, i) => {
    const el = document.createElement("div");
    el.className = "fb-ann";
    el.dataset.ann = a.id;
    el.title = a.comment;
    Object.assign(el.style, { left: `${a.x * 100}%`, top: `${a.y * 100}%`,
      width: `${a.w * 100}%`, height: `${a.h * 100}%` });
    el.innerHTML = `<span class="fb-ann-num">${i + 1}</span>`;
    el.onclick = (e) => {
      e.stopPropagation();
      const item = document.getElementById(`note-${a.id}`);
      if (item) {
        item.scrollIntoView({ block: "nearest" });
        item.classList.add("fb-note-item--flash");
        setTimeout(() => item.classList.remove("fb-note-item--flash"), 1200);
      }
    };
    wrap.appendChild(el);
  });
}

function wireDrawing(wrap) {
  if (wrap.dataset.wired) return;
  wrap.dataset.wired = "1";
  wrap.addEventListener("mousedown", (e) => {
    const mode = BO.edit ? "blackout" : AN.mode ? "note" : null;
    if (!mode || e.target.closest(".fb-blackout") || e.target.closest(".fb-ann")) return;
    if (mode === "note" && AN.pending) return;   // finish the open note first
    e.preventDefault();
    const rect = wrap.getBoundingClientRect();
    const norm = (ev) => ({
      x: Math.min(Math.max((ev.clientX - rect.left) / rect.width, 0), 1),
      y: Math.min(Math.max((ev.clientY - rect.top) / rect.height, 0), 1),
    });
    const p0 = norm(e);
    const ghost = document.createElement("div");
    ghost.className = mode === "blackout" ? "fb-blackout fb-blackout--drawing" : "fb-ann fb-ann--pending";
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
  const wrap = document.querySelector(`#rdPages .fb-page-wrap[data-page="${page}"]`);
  if (wrap) renderAnnBoxes(wrap, page);
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
  document.querySelectorAll("#rdPages .fb-page-wrap").forEach((w) => renderAnnBoxes(w));
  renderReadSide();
};

window.openTopic = async (pdfId, pageStart, pageEnd, encTitle, topicId = null) => {
  RD.pdfId = pdfId;
  RD.title = decodeURIComponent(encTitle);
  RD.start = pageStart;
  RD.end = pageEnd;
  RD.page = pageStart;
  RD.mode = null;
  RD.textPages = null;
  RD.backView = S.view === "reader" ? RD.backView : S.view;   // where ‹ returns to
  S.view = "reader";
  render();

  const doc = S.state?.libCourses.flatMap((c) => c.pdfs.map((p) => ({ ...p, course: c.name })))
    .find((p) => p.pdf_id === pdfId);
  $("rdFile").textContent = doc ? doc.filename : RD.title;
  $("rdFile").title = RD.title;
  $("rdCourse").textContent = doc ? doc.course : "Course";
  $("rdPages").innerHTML = `<div class="fb-body-sm" style="padding:40px">Loading pages…</div>`;
  $("rdThumbs").innerHTML = "";
  loadPrimer(topicId);   // cached only — generating stays a button
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
      $("rdPages").innerHTML = `<div class="fb-body-sm" style="padding:40px">
        Couldn't load these pages — the original file may have moved.</div>`;
      renderReadSide();
      return;
    }
  }
  await buildReaderPages();
};

/* ---------------------------------------------------------------- the primer
   The "don't go in blind" card, pinned above page 1 — the moment before you
   read is the only moment it helps. Comprehension needs somewhere to PUT new
   information (Ausubel's advance organizers, Mayer's pre-training principle);
   reading cold is decoding sentence by sentence with nothing to attach them to.

   Generated once per topic and cached, so re-opening costs nothing. */
const PR = { topicId: null, data: null, busy: false, open: true };

function primerHTML() {
  if (!PR.topicId) return "";
  const p = PR.data;
  if (!p) {
    return `<div class="fb-card fb-card--key fb-primer" id="rdPrimer">
      <div class="fb-primer-head">
        <span class="fb-label">Before you read</span>
        <span style="flex:1"></span>
        <button class="fb-btn" style="padding:7px 14px; font-size:12px" ${PR.busy ? "disabled" : ""}
          onclick="makePrimer()" title="One fast-model call over this topic's pages. Measured at $0.0003 — cached after that, so re-opening is free.">
          ${PR.busy ? "Painting the picture…" : "◎ Paint me a picture"}</button>
      </div>
      <div class="fb-body-sm" style="margin-top:12px">Going in cold means every new fact arrives with
        nowhere to attach. This writes you the gist, one concrete analogy with its limits, and the ideas
        you're about to meet — one measured $0.0003 of model call, then free forever.</div>
    </div>`;
  }
  return `<div class="fb-card fb-card--key fb-primer" id="rdPrimer">
    <div class="fb-primer-head">
      <span class="fb-label">Before you read</span>
      <span style="flex:1"></span>
      <button class="fb-icon-btn" onclick="regenPrimer()" ${PR.busy ? "disabled" : ""}
        title="Write a different primer — replaces this one (~$0.0003)">${PR.busy ? "…" : "↻ Redo"}</button>
      <button class="fb-icon-btn" onclick="togglePrimer()" title="Collapse">${PR.open ? "▾" : "▸"}</button>
    </div>
    ${PR.open ? `
      <div class="fb-primer-gist">${md(p.gist)}</div>

      <div class="fb-primer-analogy">
        <div class="fb-label" style="margin-bottom:8px">Picture it like this</div>
        <div style="font-size:14px; line-height:1.65">${esc(p.analogy)}</div>

        ${p.mapping?.length ? `<div class="fb-primer-map">
          ${p.mapping.map((m) => `<div class="fb-primer-map-row">
            <span class="fb-primer-map-this">${esc(m.this)}</span>
            <span class="fb-primer-map-arrow">→</span>
            <span class="fb-primer-map-is">${esc(m.is)}</span>
          </div>`).join("")}
        </div>` : ""}
        ${p.breaks ? `<div class="fb-primer-breaks"><b>Where it breaks:</b> ${esc(p.breaks)}</div>` : ""}
      </div>

      ${p.ideas?.length ? `<div style="margin-top:18px">
        <div class="fb-label" style="margin-bottom:10px">What you'll meet</div>
        <div style="display:flex; flex-wrap:wrap; gap:8px">
          ${p.ideas.map((i) => `<span class="fb-chip">${esc(i)}</span>`).join("")}
        </div>
      </div>` : ""}

      ${p.prereq ? `<div class="fb-body-sm" style="margin-top:16px"><b>Assumed going in:</b> ${esc(p.prereq)}</div>` : ""}

      ${p.links?.length ? `<div style="margin-top:18px">
        <div class="fb-label" style="margin-bottom:10px">If this isn't enough</div>
        <div style="display:flex; flex-wrap:wrap; gap:10px">
          ${p.links.map((l) => `<a class="fb-btn fb-btn--ghost" style="padding:6px 12px; font-size:11.5px; text-decoration:none"
            href="${l.url}" target="_blank" rel="noopener noreferrer">${esc(l.label)} <span style="color:var(--fb-muted)">· ${esc(l.note)}</span></a>`).join("")}
        </div>
      </div>` : ""}

      <div class="fb-evidence">A rough model first is what makes reading comprehension rather than decoding
        (Ausubel's advance organizers; Mayer's pre-training principle). The analogy carries its own limits
        on purpose — an unbounded analogy is how a misconception gets installed. The links are SEARCHES
        built from the topic title, not addresses the model invented, so none of them can be dead.</div>
    ` : `<div class="fb-body-sm" style="margin-top:10px">${esc(p.gist.split("\n")[0])}</div>`}
  </div>`;
}

function paintPrimer() {
  const slot = $("rdPrimerSlot");
  if (slot) slot.innerHTML = primerHTML();
}

window.togglePrimer = () => { PR.open = !PR.open; paintPrimer(); };

window.makePrimer = async (force) => {
  if (PR.busy || !PR.topicId) return;
  PR.busy = true;
  paintPrimer();
  const res = await fetch(`/api/topics/${PR.topicId}/primer${force ? "?force=1" : ""}`, { method: "POST" })
    .then((r) => r.ok ? r.json() : null).catch(() => null);
  PR.busy = false;
  if (res) { PR.data = res; PR.open = true; }
  paintPrimer();
  if (!res) alert("Couldn't write the primer — the topic may have no stored page text.");
};

window.regenPrimer = () => {
  if (!confirm("Replace this primer with a fresh one? (~$0.0003)")) return;
  makePrimer(true);
};

/* Cached primers load with the topic; generating is always a button, so
   opening a document can never quietly spend money. */
async function loadPrimer(topicId) {
  PR.topicId = topicId;
  PR.data = null;
  PR.busy = false;
  PR.open = true;
  if (!topicId) return;
  PR.data = await fetch(`/api/topics/${topicId}/primer`)
    .then((r) => r.ok ? r.json() : null).catch(() => null);
  paintPrimer();
}

/* Continuous vertical scroll. Every page in the range gets its wrapper up
   front so scroll height is correct and the boxes have somewhere to live, but
   canvases PAINT LAZILY through an IntersectionObserver — a 100-page document
   would otherwise render a hundred canvases before showing anything. */
async function buildReaderPages() {
  const host = $("rdPages");
  const seq = ++RD.seq;
  host.innerHTML = "";
  host.onscroll = null;
  RD.io?.disconnect();

  // the primer sits above page 1 — before you read is the only place it helps
  const slot = document.createElement("div");
  slot.id = "rdPrimerSlot";
  slot.className = "fb-primer-slot";
  host.appendChild(slot);
  paintPrimer();

  const nums = [];
  for (let p = RD.start; p <= RD.end; p++) nums.push(p);
  $("rdOf").textContent = ` of ${RD.end}`;
  $("rdJump").min = RD.start;
  $("rdJump").max = RD.end;
  $("rdJump").value = RD.page;

  /* Reserve each page's height BEFORE anything paints, from the first page's
     aspect ratio. Without it an unpainted page is 0px tall: the scrollbar lies,
     the position jumps as pages arrive, and a jump target computed now lands
     somewhere else a second later. Corrected per page when its canvas lands. */
  RD.pageW = Math.min(920, host.clientWidth - 48);
  let reserve = 0;
  if (RD.mode === "pdf") {
    try {
      const first = await pdfDocCache[RD.pdfId].getPage(RD.start);
      const v = first.getViewport({ scale: 1 });
      reserve = Math.round(RD.pageW * (v.height / v.width));
    } catch { reserve = 0; }
  }
  if (seq !== RD.seq) return;

  for (const n of nums) {
    const wrap = document.createElement("div");
    wrap.className = "fb-page-wrap";
    wrap.dataset.page = n;
    if (reserve) { wrap.style.minHeight = `${reserve}px`; wrap.style.width = `${RD.pageW}px`; }
    const label = document.createElement("div");
    label.className = "fb-page-label";
    label.textContent = `page ${n}`;
    host.appendChild(label);
    host.appendChild(wrap);
    if (RD.mode === "text") {
      wrap.classList.add("fb-page-wrap--stretch");
      const p = RD.textPages.find((x) => x.page === n);
      const div = document.createElement("div");
      div.className = "fb-viewer-text";
      div.innerHTML = md(p ? p.text : "(no text stored for this page)");
      wrap.appendChild(div);
      decorate(wrap, n);
    }
  }
  if (seq !== RD.seq) return;

  if (RD.mode === "pdf") {
    // paint on approach, one page at a time, and only once
    RD.io = new IntersectionObserver((entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting && !e.target.dataset.painted) paintPage(e.target);
      });
    }, { root: host, rootMargin: "600px 0px" });
    host.querySelectorAll(".fb-page-wrap").forEach((w) => RD.io.observe(w));
    /* the first page paints EAGERLY. An observer only fires once the page is
       laid out and compositing; in a background tab that can be never, and a
       reader that opens blank looks broken rather than lazy. */
    const first = host.querySelector(".fb-page-wrap");
    if (first && !first.dataset.painted) await paintPage(first);
  }

  /* The header follows the page in view: whichever wrapper's top is nearest
     the top of the scroller. A scroll listener rather than an observer —
     thresholds only fire at page boundaries, so scrolling inside a page taller
     than the viewport would leave the header, the thumbnail and the notes rail
     all pointing at the wrong page. */
  host.onscroll = () => {
    const top = host.getBoundingClientRect().top;
    let best = null, bestD = Infinity;
    host.querySelectorAll(".fb-page-wrap").forEach((w) => {
      const d = Math.abs(w.getBoundingClientRect().top - top);
      if (d < bestD) { bestD = d; best = w; }
    });
    const n = best ? +best.dataset.page : RD.page;
    if (n === RD.page) return;
    RD.page = n;
    if (document.activeElement !== $("rdJump")) $("rdJump").value = n;
    markThumb();
    renderReadSide();
  };

  buildThumbs();
  renderReadSide();
}

async function paintPage(wrap) {
  wrap.dataset.painted = "1";
  const n = +wrap.dataset.page;
  const doc = pdfDocCache[RD.pdfId];
  if (!doc) return;
  const page = await doc.getPage(n);
  const width = RD.pageW || Math.min(920, $("rdPages").clientWidth - 48);
  const base = page.getViewport({ scale: 1 });
  const scale = width / base.width;
  const dpr = window.devicePixelRatio || 1;
  const viewport = page.getViewport({ scale: scale * dpr });
  const canvas = document.createElement("canvas");
  canvas.width = viewport.width;
  canvas.height = viewport.height;
  canvas.style.width = `${width}px`;
  canvas.style.height = `${Math.round(viewport.height / dpr)}px`;
  canvas.style.display = "block";
  canvas.className = "fb-viewer-page";
  wrap.prepend(canvas);
  wrap.style.minHeight = "";   // the canvas is the real height now
  page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise.catch(() => {});
  decorate(wrap, n);
}

/* boxes and notes for one page */
function decorate(wrap, n) {
  BO.boxes.filter((b) => b.page === n).forEach((b) => renderBox(wrap, b));
  renderAnnBoxes(wrap, n);
  wireDrawing(wrap);
}

/* the left rail: one thumbnail per page, painted lazily like the pages */
function buildThumbs() {
  const rail = $("rdThumbs");
  rail.innerHTML = "";
  RD.tio?.disconnect();
  for (let n = RD.start; n <= RD.end; n++) {
    const b = document.createElement("button");
    b.className = "fb-thumb";
    b.dataset.page = n;
    b.title = `Go to page ${n}`;
    b.innerHTML = `<span class="fb-thumb-box"></span><span class="fb-thumb-n">${n}</span>`;
    b.onclick = () => scrollToPage(n);
    rail.appendChild(b);
  }
  markThumb();
  if (RD.mode !== "pdf") return;
  RD.tio = new IntersectionObserver((entries) => {
    entries.forEach(async (e) => {
      if (!e.isIntersecting || e.target.dataset.painted) return;
      e.target.dataset.painted = "1";
      const doc = pdfDocCache[RD.pdfId];
      if (!doc) return;
      const page = await doc.getPage(+e.target.dataset.page);
      const base = page.getViewport({ scale: 1 });
      const w = 108, scale = w / base.width;
      const vp = page.getViewport({ scale });
      const c = document.createElement("canvas");
      c.width = vp.width; c.height = vp.height;
      c.style.width = `${w}px`; c.style.height = `${Math.round(vp.height)}px`;
      e.target.querySelector(".fb-thumb-box").replaceWith(c);
      page.render({ canvasContext: c.getContext("2d"), viewport: vp }).promise.catch(() => {});
    });
  }, { root: rail, rootMargin: "300px 0px" });
  rail.querySelectorAll(".fb-thumb").forEach((t) => RD.tio.observe(t));
}

function markThumb() {
  document.querySelectorAll("#rdThumbs .fb-thumb").forEach((t) =>
    t.classList.toggle("fb-thumb--on", +t.dataset.page === RD.page));
}

window.scrollToPage = (n) => {
  const wrap = document.querySelector(`#rdPages .fb-page-wrap[data-page="${n}"]`);
  if (!wrap) return;
  const host = $("rdPages");
  // the page LABEL sits above the wrapper, so scroll to it and not past it
  const label = wrap.previousElementSibling;
  host.scrollTo({ top: (label || wrap).offsetTop - 12, behavior: "smooth" });
};

/* Fullscreen is ONE control: it collapses the nav and both rails, and restores
   whatever was open before. That is what actually buys reading width. */
window.toggleReaderFull = () => {
  RD.full = !RD.full;
  if (RD.full) {
    RD.wasNav = S.navOpen;
    RD.wasL = RD.railL;
    RD.wasR = RD.railR;
    if (S.navOpen) toggleNav();
    setRail("L", false);
    setRail("R", false);
  } else {
    if (RD.wasNav && !S.navOpen) toggleNav();
    setRail("L", RD.wasL);
    setRail("R", RD.wasR);
  }
  $("rdFull").textContent = RD.full ? "⤡ Exit fullscreen" : "⤢ Fullscreen";
  $("rdFull").classList.toggle("fb-icon-btn--on", RD.full);
};

function setRail(side, open) {
  const key = side === "L" ? "railL" : "railR";
  RD[key] = open;
  $(side === "L" ? "rdRailL" : "rdRailR").style.display = open ? "flex" : "none";
  $(side === "L" ? "rdSpineL" : "rdSpineR").style.display = open ? "none" : "flex";
}

window.toggleRail = (side) => {
  setRail(side, !(side === "L" ? RD.railL : RD.railR));
};

$("blackoutToggle").onclick = () => { BO.edit = !BO.edit; if (BO.edit) AN.mode = false; syncModes(); };
$("annToggle").onclick = () => { AN.mode = !AN.mode; if (AN.mode) BO.edit = false; syncModes(); };
$("blackoutReveal").onclick = () => {
  BO.revealAll = !BO.revealAll;
  document.querySelectorAll(".fb-blackout").forEach((b) => b.classList.toggle("fb-blackout--peek", BO.revealAll));
  syncModes();
};
$("rdFull").onclick = () => toggleReaderFull();
$("rdBack").onclick = () => closeViewer();
$("rdJump").onchange = (e) => {
  const n = Math.min(RD.end, Math.max(RD.start, +e.target.value || RD.start));
  e.target.value = n;
  scrollToPage(n);
};

window.closeViewer = () => {
  if (RD.full) toggleReaderFull();      // never strand the nav collapsed
  RD.io?.disconnect(); RD.tio?.disconnect();
  $("rdPages").onscroll = null;
  S.view = RD.backView === "reader" ? "course" : (RD.backView || "course");
  render();
};

document.addEventListener("keydown", (e) => {
  if (S.view !== "reader") return;
  const typing = /TEXTAREA|INPUT/.test(e.target.tagName);
  if (e.key === "Escape") { typing ? e.target.blur() : closeViewer(); return; }
  if (typing) return;
  if (e.key === "ArrowRight" || e.key === " ") { e.preventDefault(); scrollToPage(Math.min(RD.end, RD.page + 1)); }
  else if (e.key === "ArrowLeft") { e.preventDefault(); scrollToPage(Math.max(RD.start, RD.page - 1)); }
  else if (e.key === "f") { e.preventDefault(); toggleReaderFull(); }
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
$("sideNav").classList.toggle("fb-nav--closed", !S.navOpen);   // default: icons only
$("navCollapse").title = S.navOpen ? "Collapse sidebar" : "Expand sidebar";

fetchState();
fetchHistory();
