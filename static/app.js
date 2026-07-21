/* Flashbang v3 front-end — renders the design against the live API. */

const GOOD = "#009E73", WARN = "#E69F00", LOW = "#D55E00", MUT = "#8A8F9C";
const SUBJ = ["#0072B2", "#E69F00", "#009E73", "#CC79A7"];
const SHOW_EVIDENCE = true;

const S = {
  view: "study",
  state: null,          // /api/state payload
  pdfId: null,          // current doc
  railOpen: true,
  pendingConf: null,    // "sure" | "unsure" attached to next message
  sessionLen: 25,
  focusStart: null,     // Date when focus timer started
  recap: null,
  busy: false,
  pdfSort: localStorage.getItem("fbPdfSort") || "weakest",  // progress-card order
  cardFilter: { course_id: null, pdf_id: null, topic_id: null },
  cards: [],            // cards screen data
  cardTopics: [],       // topics for the move-to select
};

const $ = (id) => document.getElementById(id);
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
        <button class="undo-btn" onclick="undoGrade(this)" title="Mis-graded? Restore the card's previous schedule">undo</button>
      </div>
      ${body}
      ${m.meta ? `<div class="gcard-meta">${esc(m.meta)}</div>` : ""}
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

window.undoGrade = (btn) => {
  document.querySelectorAll(".undo-btn").forEach((b) => (b.disabled = true));
  sendChat("Undo that last grade — restore the card's previous schedule.");
};

/* ---------------------------------------------------------------- slash commands */
/* Each command maps to a specific agent (skips the router) and expands to an
   unambiguous instruction — the raw /command is what shows in the chat. */
const COMMANDS = [
  { cmd: "/review",   args: "[topic/pdf]",           desc: "Review due cards",                    agent: "review",    expand: (a) => a ? `Start a review session on my due cards in ${a}` : "Start a review session on my due cards" },
  { cmd: "/cram",     args: "<topic/pdf>",           desc: "Quiz everything once, no scheduling", agent: "review",    expand: (a) => `Start a cram session on ${a || "all my cards"}` },
  { cmd: "/end",      args: "",                      desc: "End the current session",             agent: "review",    expand: () => "End the current session and summarize how I did" },
  { cmd: "/undo",     args: "",                      desc: "Undo the last grade",                 agent: "review",    expand: () => "Undo that last grade — restore the card's previous schedule." },
  { cmd: "/ingest",   args: "<file path>",           desc: "Ingest a PDF by path",                agent: "ingestion", expand: (a) => `Ingest ${a}` },
  { cmd: "/cards",    args: "<topic>",               desc: "Generate flashcards for a topic",     agent: "ingestion", expand: (a) => `Make flashcards for the topic ${a}` },
  { cmd: "/pretest",  args: "[document]",            desc: "Unscored pretest before reading",     agent: "ingestion", expand: (a) => `Give me a pretest${a ? ` on ${a}` : " on my newest document"}` },
  { cmd: "/plan",     args: "[minutes per day]",     desc: "Plan the study week",                 agent: "planner",   expand: (a) => `Plan my study week${a ? `, I have ${a} minutes a day` : ""}` },
  { cmd: "/next",     args: "",                      desc: "What should I study next?",           agent: "planner",   expand: () => "What should I study next?" },
  { cmd: "/progress", args: "[course/pdf]",          desc: "Progress report",                     agent: "planner",   expand: (a) => `How is my progress${a ? ` on ${a}` : ""}?` },
  { cmd: "/stats",    args: "",                      desc: "Streak & weekly stats",               agent: "planner",   expand: () => "Show my study stats and streak" },
  { cmd: "/rename",   args: "<topic> to <new name>", desc: "Rename a topic",                      agent: "organizer", expand: (a) => `Rename the topic ${a}` },
  { cmd: "/search",   args: "<query>",               desc: "Ask your notes",                      agent: "organizer", expand: (a) => `What do my notes say about ${a}?` },
  { cmd: "/help",     args: "",                      desc: "List all commands",                   agent: null },
];

function parseCommand(text) {
  if (!text.startsWith("/")) return null;
  const space = text.indexOf(" ");
  const name = (space === -1 ? text : text.slice(0, space)).toLowerCase();
  const arg = space === -1 ? "" : text.slice(space + 1).trim();
  const command = COMMANDS.find((c) => c.cmd === name);
  return command ? { command, arg } : null;
}

function renderPalette() {
  const input = $("chatInput");
  const palette = $("cmdPalette");
  const value = input.value;
  if (!value.startsWith("/") || value.includes(" ")) {
    palette.style.display = "none";
    return;
  }
  const matches = COMMANDS.filter((c) => c.cmd.startsWith(value.toLowerCase()));
  if (!matches.length) { palette.style.display = "none"; return; }
  palette.innerHTML = matches.map((c) => `
    <div class="cmd-item" data-cmd="${c.cmd}">
      <span class="mono" style="font-weight:600; font-size:12px">${c.cmd}</span>
      <span class="mono" style="font-size:10.5px; color:#B0B4BE">${c.args}</span>
      <span style="flex:1"></span>
      <span style="font-size:11px; color:#8A8F9C">${c.desc}</span>
    </div>`).join("");
  palette.style.display = "block";
  palette.querySelectorAll(".cmd-item").forEach((el) => {
    el.onmousedown = (e) => {   // mousedown beats input blur
      e.preventDefault();
      input.value = el.dataset.cmd + " ";
      palette.style.display = "none";
      input.focus();
    };
  });
}

function showHelp() {
  const scroll = $("chatScroll");
  const rows = COMMANDS.map((c) =>
    `<div style="display:flex; gap:10px"><code style="flex:none">${c.cmd} ${c.args}</code><span>${c.desc}</span></div>`).join("");
  scroll.insertAdjacentHTML("beforeend",
    `<div class="msg-row-bot"><div class="bubble-bot"><div class="md-head">Commands</div>${rows}
      <div class="md-gap"></div><div>Type <code>/</code> to see this menu inline. Commands go straight to the right specialist — no interpretation needed.</div></div></div>`);
  scroll.scrollTop = scroll.scrollHeight;
}

/* human-readable status lines for tool activity while the agent works */
const STATUS_LABELS = {
  read_pdf: "Reading the PDF page by page…",
  create_text_source: "Saving your notes…",
  propose_topics: "Splitting into topics & estimating study time… (big documents take a minute)",
  save_topics: "Saving the approved topics…",
  generate_pretest: "Writing pretest questions…",
  extract_topic_concepts: "Extracting the key concepts…",
  save_topic_concepts: "Saving concepts to your notes…",
  generate_cards_for_topic: "Writing flashcards…",
  bulk_insert_cards: "Saving your cards…",
  get_due_cards: "Fetching due cards…",
  grade_answer: "Grading your answer…",
  review_card: "Updating the schedule…",
  undo_review: "Undoing that grade…",
  search_notes: "Searching your notes…",
  get_progress_report: "Crunching your progress…",
  propose_study_plan: "Drafting a study plan…",
  get_study_stats: "Adding up your stats…",
};

function typewrite(el, text, onDone) {
  const scroll = $("chatScroll");
  const finish = () => { el.innerHTML = md(text); scroll.scrollTop = scroll.scrollHeight; onDone && onDone(); };
  if (document.hidden) return finish();   // rAF/timers throttle in hidden tabs — don't animate
  let i = 0;
  const started = Date.now();
  const perTick = Math.max(3, Math.round(text.length / 120)); // ~2s at 16ms ticks
  const timer = setInterval(() => {
    if (Date.now() - started > 4000) i = text.length;  // hard cap — never leave chat busy
    i += perTick;
    el.textContent = text.slice(0, i);
    scroll.scrollTop = scroll.scrollHeight;
    if (i >= text.length) { clearInterval(timer); finish(); }
  }, 16);
}

async function sendChat(text) {
  if (S.busy || !text.trim()) return;
  $("cmdPalette").style.display = "none";

  // slash command? translate to an explicit instruction + forced agent
  let display = text, message = text, agent = null;
  const parsed = parseCommand(text.trim());
  if (parsed) {
    if (parsed.command.cmd === "/help") { $("chatInput").value = ""; showHelp(); return; }
    message = parsed.command.expand(parsed.arg);
    agent = parsed.command.agent;
  }

  S.busy = true;
  const scroll = $("chatScroll");
  scroll.insertAdjacentHTML("beforeend", renderMsg({ role: "user", text: display,
    meta: S.pendingConf ? `confidence: ${S.pendingConf}` : "" }));
  scroll.insertAdjacentHTML("beforeend",
    `<div id="thinking" class="msg-row-bot"><div class="bubble-bot">
       <div style="display:flex; align-items:baseline; gap:8px">
         <span id="statusLine" class="status-line working">Thinking…</span>
         <span id="statusElapsed" class="status-elapsed"></span>
       </div></div></div>`);
  scroll.scrollTop = scroll.scrollHeight;
  $("chatInput").value = "";
  const confidence = S.pendingConf;
  S.pendingConf = null;
  renderConfRow();

  const startedAt = Date.now();
  const elapsedTimer = setInterval(() => {
    const el = document.getElementById("statusElapsed");
    if (el) el.textContent = `${Math.round((Date.now() - startedAt) / 1000)}s`;
  }, 1000);

  const finish = (data) => {
    clearInterval(elapsedTimer);
    document.getElementById("thinking")?.remove();
    (data.grades || []).forEach((g) => scroll.insertAdjacentHTML("beforeend", renderMsg(g)));
    if (data.agent) $("agentName").textContent = `${data.agent[0].toUpperCase()}${data.agent.slice(1)} specialist`;
    scroll.insertAdjacentHTML("beforeend",
      `<div class="msg-row-bot" id="typingRow"><div class="bubble-bot" id="typing"></div></div>`);
    const el = document.getElementById("typing");
    el.removeAttribute("id");
    typewrite(el, data.reply || "", () => {
      // final render through renderMsg so question-card markers become styled cards
      const row = document.getElementById("typingRow");
      if (row) row.outerHTML = renderMsg({ role: "assistant", text: data.reply || "" });
      scroll.scrollTop = scroll.scrollHeight;
      S.busy = false;
      fetchState();
    });
  };

  try {
    const res = await fetch("/api/chat/stream", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, display, agent, confidence }) });
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";
    let finished = false;
    while (!finished) {
      const { done, value } = await reader.read();
      if (done) break;
      buf += decoder.decode(value, { stream: true });
      let sep;
      while ((sep = buf.indexOf("\n\n")) >= 0) {
        const chunk = buf.slice(0, sep).trim();
        buf = buf.slice(sep + 2);
        if (!chunk.startsWith("data: ")) continue;
        const evt = JSON.parse(chunk.slice(6));
        if (evt.type === "status") {
          const line = document.getElementById("statusLine");
          if (line) line.textContent = STATUS_LABELS[evt.tool] || `${evt.tool}…`;
          scroll.scrollTop = scroll.scrollHeight;
        } else if (evt.type === "agent") {
          $("agentName").textContent = `${evt.agent[0].toUpperCase()}${evt.agent.slice(1)} specialist`;
        } else if (evt.type === "done") {
          finished = true;
          finish(evt);
        }
      }
    }
    if (!finished) throw new Error("stream ended unexpectedly");
  } catch (e) {
    clearInterval(elapsedTimer);
    document.getElementById("thinking")?.remove();
    scroll.insertAdjacentHTML("beforeend", renderMsg({ role: "assistant", text: `Connection error: ${e.message}` }));
    scroll.scrollTop = scroll.scrollHeight;
    S.busy = false;
    fetchState();
  }
}

function renderConfRow() {
  const st = S.state;
  const show = !!(st && st.sessionActive);
  $("confRow").style.display = show ? "flex" : "none";
  document.querySelectorAll(".conf-btn").forEach((b) =>
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

function renderRail() {
  const st = S.state, rail = $("rail");
  $("railReopen").style.display = S.railOpen ? "none" : "block";
  rail.style.display = S.railOpen ? "flex" : "none";
  if (!S.railOpen) return;

  if (!st || !st.current) {
    rail.innerHTML = `<div class="card"><div class="mono-label" style="margin-bottom:10px">NOW STUDYING</div>
      <div style="font-size:12.5px; color:#5C616E; line-height:1.6">Nothing ingested yet. Drop a PDF path or paste notes into the chat to get started.</div></div>`;
    return;
  }

  const cur = st.current, cc = st.currentCourse;
  const color = SUBJ[cc.ci % 4];
  const d = deltaBits(cur.delta);
  const hours = ((cur.est_total_minutes || 0) / 60).toFixed(1);

  // NOW STUDYING
  let html = `<div class="card">
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:10px">
      <span style="display:flex; align-items:center; gap:7px">
        <span class="mono-label">NOW STUDYING</span>
        <span class="course-chip" style="border-left:3px solid ${color}">${esc(cc.name)}</span>
      </span>
      <button class="icon-btn" title="Hide panel" onclick="toggleRail()">⇥</button>
    </div>
    <div class="doc-name">${esc(cur.filename)}</div>
    <div class="doc-meta">${cur.total_pages} pages · ~${hours}h est · ${cur.spent_total} studied</div>
    <div style="display:flex; align-items:baseline; justify-content:space-between; margin-top:14px; margin-bottom:6px">
      <span style="font-size:11.5px; color:#5C616E; white-space:nowrap">Completion</span>
      <span style="display:flex; align-items:baseline; gap:7px">
        <span class="mono" style="font-size:13px; font-weight:600">${cur.completion_pct.toFixed(0)}%</span>
        <span class="delta" style="color:${d.color}">${d.label}</span>
      </span>
    </div>
    <div class="bar-track"><div class="bar-fill" style="width:${cur.completion_pct}%; background:${retColor(cur.completion_pct)}"></div></div>
    ${cur.due > 0 ? `<button class="btn-block" onclick="startReview()">Review ${cur.due} due cards</button>` : ""}
    ${evidence("Retrieval practice: testing yourself strengthens memory more than re-reading (Roediger &amp; Karpicke, 2006).")}
  </div>`;

  // TOPICS · WEAKEST FIRST
  const sorted = [...cur.topics].sort((a, b) => {
    const ra = a.cards_due > 0 ? 0 : a.mastery_pct > 0 ? 1 : 2;
    const rb = b.cards_due > 0 ? 0 : b.mastery_pct > 0 ? 1 : 2;
    return ra !== rb ? ra - rb : a.mastery_pct - b.mastery_pct;
  });
  html += `<div class="card">
    <div class="mono-label" style="margin-bottom:11px">TOPICS · WEAKEST FIRST</div>
    <div style="display:flex; flex-direction:column; gap:4px">
      ${sorted.map((t) => `
      <div class="topic-row" style="cursor:pointer" title="Open pages ${t.pages}"
           onclick="openTopic(${cur.pdf_id}, ${t.pages.split("-")[0]}, ${t.pages.split("-")[1]}, '${encodeURIComponent(t.title)}')">
        <span class="ret-dot" style="background:${retColor(t.mastery_pct)}"></span>
        <div style="flex:1; min-width:0">
          <div class="topic-title">${esc(t.title)}</div>
          <div class="mini-track"><div class="mini-fill" style="width:${t.mastery_pct}%; background:${retColor(t.mastery_pct)}"></div></div>
        </div>
        <span class="topic-pct">${t.mastery_pct.toFixed(0)}%</span>
        ${flagTag(t.id)}
        ${t.cards_due > 0 ? `<span class="due-tag">${t.cards_due} due</span>` : ""}
      </div>`).join("")}
    </div>
    ${evidence("Ordered by retention — the items closest to being forgotten come first.")}
  </div>`;

  // FORGETTING CURVE
  if (st.curve) html += renderCurve(st.curve, sorted);

  // SESSION RECAP
  if (S.recap) {
    const r = S.recap;
    html += `<div class="card" style="border-color:#9BD4BE">
      <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:12px">
        <span class="mono-label" style="color:#00794F; font-weight:600">SESSION RECAP</span>
        <button class="icon-btn" title="Dismiss" onclick="dismissRecap()">✕</button>
      </div>
      <div class="recap-grid">
        <div><div class="recap-num">${r.mins}m</div><div class="recap-lbl">focused</div></div>
        <div><div class="recap-num">${r.cards}</div><div class="recap-lbl">cards</div></div>
        <div><div class="recap-num" style="color:#00794F">${r.acc == null ? "—" : r.acc + "%"}</div><div class="recap-lbl">recall</div></div>
      </div>
      <div style="font-size:11.5px; color:#5C616E">${r.ext} intervals extended · <span style="color:${LOW}">${r.reset} reset to 1d</span></div>
      ${evidence("Immediate post-practice feedback sharpens metacognitive calibration and next-session planning.")}
    </div>`;
  }

  // FOCUS SESSION
  const active = !!S.focusStart;
  const elapsed = active ? Math.floor((Date.now() - S.focusStart) / 60000) : 0;
  html += `<div class="card">
    <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:11px">
      <span class="mono-label">FOCUS SESSION</span>
    </div>
    ${!active ? `<div class="dur-row">
      ${[15, 25, 45].map((m) => `<button class="dur-btn ${S.sessionLen === m ? "on" : ""}" onclick="pickLen(${m})">${m}m</button>`).join("")}
    </div>` : `
    <div style="display:flex; align-items:baseline; gap:6px; margin-bottom:8px">
      <span class="mono" style="font-size:22px; font-weight:600" id="focusElapsed">${elapsed}</span>
      <span class="mono" style="font-size:11px; color:#8A8F9C">/ ${S.sessionLen} min</span>
    </div>
    <div style="height:6px; border-radius:3px; background:#ECECE8; overflow:hidden; margin-bottom:12px">
      <div id="focusBar" style="height:100%; width:${Math.min(100, elapsed / S.sessionLen * 100)}%; border-radius:3px; background:#1C1E26; transition:width 1s linear"></div>
    </div>`}
    <button class="btn-block ${active ? "ghost" : ""}" style="margin-top:0" onclick="toggleFocus()">
      ${active ? "End session" : `Start ${S.sessionLen}-min focus`}</button>
  </div>`;

  // evening nudge: reviewing shortly before sleep aids consolidation
  if (new Date().getHours() >= 18 && st.dueTotal > 0 && !active) {
    html += `<div class="nudge">🌙 ${st.dueTotal} cards due — a short review before
      sleep helps consolidation. Even 10 minutes counts.</div>`;
  }

  rail.innerHTML = html;
}

function renderCurve(curve, sortedTopics) {
  const { S: stab, R0, title } = curve;
  const tNow = -stab * Math.log(Math.max(0.05, R0));
  const tMax = Math.max(14, Math.ceil(tNow + 3));
  const pts = [];
  for (let i = 0; i <= 40; i++) {
    const t = tMax * i / 40;
    pts.push(`${(16 + t / tMax * 232).toFixed(1)},${(14 + (1 - Math.exp(-t / stab)) * 82).toFixed(1)}`);
  }
  const nowX = +(16 + tNow / tMax * 232).toFixed(1);
  const nowY = +(14 + (1 - R0) * 82).toFixed(1);
  const t75 = stab * 0.2877;
  const pct = Math.round(R0 * 100);
  const note = R0 < 0.75
    ? `“${esc(title)}” has decayed to ${pct}% — past its review point. Reviewing now resets the curve.`
    : `“${esc(title)}” reaches the 75% threshold in ${Math.max(1, Math.ceil(t75 - tNow))} days.`;
  return `<div class="card">
    <div class="mono-label" style="margin-bottom:8px">FORGETTING CURVE</div>
    <svg width="264" height="112" viewBox="0 0 264 112">
      <line x1="16" y1="96" x2="248" y2="96" stroke="#ECECE8" stroke-width="1"></line>
      <line x1="16" y1="34.5" x2="248" y2="34.5" stroke="#D9D9D4" stroke-width="1" stroke-dasharray="4 3"></line>
      <text x="248" y="30" text-anchor="end" font-family="IBM Plex Mono" font-size="8.5" fill="#8A8F9C">75% · review threshold</text>
      <text x="16" y="11" font-family="IBM Plex Mono" font-size="8.5" fill="#8A8F9C">100%</text>
      <text x="16" y="108" font-family="IBM Plex Mono" font-size="8.5" fill="#B0B4BE">day 0</text>
      <text x="248" y="108" text-anchor="end" font-family="IBM Plex Mono" font-size="8.5" fill="#B0B4BE">day ${tMax}</text>
      <polyline points="${pts.join(" ")}" fill="none" stroke="#0072B2" stroke-width="2" stroke-linejoin="round"></polyline>
      <circle cx="${nowX}" cy="${nowY}" r="4" fill="#D55E00" stroke="#fff" stroke-width="1.5"></circle>
      <text x="${nowX}" y="${nowY - 9}" text-anchor="middle" font-family="IBM Plex Mono" font-size="8.5" font-weight="600" fill="#D55E00">now</text>
    </svg>
    <div style="font-size:11.5px; line-height:1.5; color:#5C616E; margin-top:6px">${note}</div>
    ${evidence("Ebbinghaus decay, R = e^(−t/S). A card at its SM-2 due date sits at 75% retention; reviewing resets the curve.")}
  </div>`;
}

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

  const PDF_SORTS = {
    weakest:  { label: "Weakest first",   fn: (a, b) => a.completion_pct - b.completion_pct },
    strongest:{ label: "Strongest first", fn: (a, b) => b.completion_pct - a.completion_pct },
    due:      { label: "Most due first",  fn: (a, b) => b.due - a.due },
    name:     { label: "By name",         fn: (a, b) => a.filename.localeCompare(b.filename) },
    newest:   { label: "Newest first",    fn: (a, b) => b.pdf_id - a.pdf_id },
  };
  const sortFn = (PDF_SORTS[S.pdfSort] || PDF_SORTS.weakest).fn;
  const sortSelect = `<select id="pdfSort" class="sort-select">
      ${Object.entries(PDF_SORTS).map(([key, s]) =>
        `<option value="${key}" ${key === S.pdfSort ? "selected" : ""}>${s.label}</option>`).join("")}
    </select>`;

  const courseCards = st.libCourses.map((c) => {
    const pdfCards = [...c.pdfs].sort(sortFn).map((p) => {
      const started = p.topics.some((t) => t.status !== "not_started");
      const [badge, bg, fg] = p.completion_pct >= 70 ? ["On track", "rgba(0,158,115,.10)", "#00794F"]
        : started ? ["In progress", "rgba(230,159,0,.13)", "#8A6100"] : ["Not started", "#F0F0EC", "#8A8F9C"];
      const d = deltaBits(p.delta);
      const topicRows = p.topics.map((t) => `
        <div class="trow" style="cursor:pointer" title="Open pages ${t.pages}"
             onclick="event.stopPropagation(); openTopic(${p.pdf_id}, ${t.pages.split("-")[0]}, ${t.pages.split("-")[1]}, '${encodeURIComponent(t.title)}')">
          <span class="dot" style="background:${retColor(t.mastery_pct)}"></span>
          <span class="name">${esc(t.title)}</span>
          <div class="track"><div class="fill" style="width:${Math.min(100, t.spent / Math.max(t.est_minutes, 1) * 100)}%"></div></div>
          <span class="time">${fmtMin(t.spent)} / ${fmtMin(t.est_minutes)}</span>
        </div>`).join("");
      return `
      <div class="pdf-card" onclick="openDoc(${p.pdf_id})">
        <div style="display:flex; align-items:flex-start; gap:12px; margin-bottom:11px">
          <div style="flex:1; min-width:0">
            <div style="font-size:13px; font-weight:600; line-height:1.4">${esc(p.filename)}</div>
            <div class="doc-meta">${p.total_pages} pages · ${p.spent_total} studied ·
              <span style="${p.due > 0 ? `color:${LOW}; font-weight:600` : "color:#8A8F9C"}">${p.due} due</span></div>
          </div>
          <span class="badge" style="background:${bg}; color:${fg}">${badge}</span>
        </div>
        <div style="display:flex; align-items:center; gap:10px; margin-bottom:14px">
          <div class="bar-track" style="flex:1"><div class="bar-fill" style="width:${p.completion_pct}%; background:${retColor(p.completion_pct)}"></div></div>
          <span class="mono" style="font-size:12px; font-weight:600; width:36px; text-align:right">${p.completion_pct.toFixed(0)}%</span>
          <span class="delta" style="color:${d.color}">${d.label}</span>
        </div>
        <div style="display:flex; flex-direction:column; gap:7px">${topicRows}</div>
      </div>`;
    }).join("");
    return `
    <div class="course-card">
      <div class="course-head">
        <span class="course-tile" style="background:${SUBJ[c.ci % 4]}"></span>
        <span class="course-name">${esc(c.name)}</span>
        <span class="course-meta">${c.pdfCount} PDFs · ${c.timeSpent} invested ·
          <span style="color:${LOW}">${c.dueCount} due</span></span>
      </div>
      <div class="pdf-grid">${pdfCards}</div>
    </div>`;
  }).join("");

  inner.innerHTML = `
    <div class="section-head"><span class="mono-label">OVERVIEW</span><div class="rule"></div></div>
    <div class="grid3">
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:9px">TIME THIS WEEK</div>
        <div class="stat-num">${stats.weekTime}</div>
        <div class="stat-sub">${stats.sessionCount} focus sessions</div>
      </div>
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:9px">CARDS DUE NOW</div>
        <div class="stat-num" style="color:${LOW}">${st.dueTotal}</div>
        <div class="stat-sub">across ${st.courses.length} courses</div>
      </div>
      <div class="card" style="padding:16px 20px">
        <div class="mono-label" style="margin-bottom:9px">CONSISTENCY</div>
        <div class="week-dots">${weekDots}</div>
        <div style="font-size:11.5px; color:#5C616E"><span style="font-weight:600; color:#1C1E26">${stats.litCount} of last 7 days</span> · streak ${stats.streak}d</div>
      </div>
    </div>
    <div class="grid2">
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div style="display:flex; align-items:center; justify-content:space-between; margin-bottom:14px">
          <span class="mono-label">REVIEW FORECAST · NEXT 7 DAYS</span>
          <span class="mono" style="font-size:10.5px; color:#8A8F9C">${forecastTotal} scheduled</span>
        </div>
        <div class="forecast-row">${forecastCols}</div>
        ${evidence("Spacing effect: SM-2 pushes each successful recall further out, so daily load stays small (Cepeda et al., 2006).")}
      </div>
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:14px">TIME BY COURSE · ALL TIME</div>
        <div class="seg-track">${segs}</div>
        <div style="display:flex; flex-direction:column; gap:10px">${legend}</div>
        ${evidence("Interleaving courses within a week beats blocking one at a time (Rohrer &amp; Taylor, 2007).")}
      </div>
    </div>
    <div class="grid2">
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:14px">CALIBRATION · CONFIDENCE VS RECALL</div>
        ${renderCalibration(st.calibration)}
        ${evidence("Calibration training: comparing predicted vs actual recall improves self-regulated study.")}
      </div>
      <div class="card" style="padding:16px 20px; display:flex; flex-direction:column">
        <div class="mono-label" style="margin-bottom:14px">RECENT SESSIONS</div>
        ${renderRecentSessions(st.recentSessions)}
        ${evidence("Self-monitoring: seeing your own accuracy trend supports habit formation.")}
      </div>
    </div>
    <div class="section-head" style="margin-top:10px"><span class="mono-label">COURSES</span><div class="rule"></div>${sortSelect}</div>
    ${courseCards || '<div class="card" style="color:#8A8F9C; font-size:12.5px">No courses yet — ingest something from the Study tab.</div>'}`;

  const sortEl = document.getElementById("pdfSort");
  if (sortEl) sortEl.onchange = (e) => {
    S.pdfSort = e.target.value;
    localStorage.setItem("fbPdfSort", S.pdfSort);
    renderProgress();
  };
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

  inner.innerHTML = `
    <div class="section-head"><span class="mono-label">CARDS</span><div class="rule"></div>
      <span class="mono" style="font-size:10.5px; color:#8A8F9C">${S.cards.length} shown</span>
      <button id="newCardBtn" class="conf-btn">+ New card</button></div>
    <div style="display:flex; gap:10px; flex-wrap:wrap">
      <select id="cfCourse" class="sort-select">${courseOpts.join("")}</select>
      <select id="cfPdf" class="sort-select">${pdfOpts.join("")}</select>
      <select id="cfTopic" class="sort-select">${topicOpts.join("")}</select>
    </div>
    ${newCardBox}
    ${rows || `<div class="card" style="color:#8A8F9C; font-size:12.5px">No cards match this filter — generate some from the Study chat ("make cards for &lt;topic&gt;"), or use + New card.</div>`}`;

  $("newCardBtn").onclick = () => { S.showNewCard = !S.showNewCard; renderCardsScreen(); };
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
  $("tabStudy").classList.toggle("on", S.view === "study");
  $("tabProgress").classList.toggle("on", S.view === "progress");
  $("tabCards").classList.toggle("on", S.view === "cards");
  $("studyScreen").style.display = S.view === "study" ? "flex" : "none";
  $("progressScreen").style.display = S.view === "progress" ? "block" : "none";
  $("cardsScreen").style.display = S.view === "cards" ? "block" : "none";
  renderConfRow();
  renderRail();
  renderProgress();
  if (S.view === "cards") renderCardsScreen();
}

/* ---- actions (referenced from rendered HTML) ---- */
window.toggleRail = () => { S.railOpen = !S.railOpen; renderRail(); };
window.pickLen = (m) => { S.sessionLen = m; renderRail(); };
window.dismissRecap = () => { S.recap = null; renderRail(); };
window.openDoc = (pdfId) => { S.pdfId = pdfId; S.view = "study"; fetchState(); };
window.startReview = () => {
  const cur = S.state?.current;
  sendChat(cur ? `Review my due cards in "${cur.filename}" (pdf_id ${cur.pdf_id})`
               : "Review my due cards");
};

window.toggleFocus = async () => {
  if (S.focusStart) {
    const mins = Math.max(1, Math.round((Date.now() - S.focusStart) / 60000));
    S.focusStart = null;
    clearInterval(S._tick);
    $("focusChip").style.display = "none";
    const cur = S.state?.current;
    try {
      const res = await fetch("/api/focus", { method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ minutes: mins, course_id: cur?.course_id, pdf_id: cur?.pdf_id }) });
      S.recap = await res.json();
    } catch { S.recap = null; }
    fetchState();
  } else {
    S.focusStart = Date.now();
    $("focusChip").style.display = "flex";
    S._tick = setInterval(() => {
      const elapsed = Math.floor((Date.now() - S.focusStart) / 60000);
      $("focusElapsedHead").textContent = elapsed;
      const el = $("focusElapsed"), bar = $("focusBar");
      if (el) el.textContent = elapsed;
      if (bar) bar.style.width = `${Math.min(100, elapsed / S.sessionLen * 100)}%`;
      if (elapsed >= S.sessionLen) window.toggleFocus();   // auto-end at target
    }, 1000);
    renderRail();
  }
};

/* ---------------------------------------------------------------- topic page viewer */

const pdfDocCache = {};

window.openTopic = async (pdfId, pageStart, pageEnd, encTitle) => {
  const title = decodeURIComponent(encTitle);
  $("viewerTitle").textContent = title;
  $("viewerSub").textContent = `pages ${pageStart}–${pageEnd}`;
  const body = $("viewerBody");
  body.innerHTML = `<div style="padding:30px; color:#8A8F9C; font-size:12.5px">Loading pages…</div>`;
  $("viewer").style.display = "flex";

  try {
    if (!window.pdfjsLib) throw new Error("pdf.js unavailable");
    pdfjsLib.GlobalWorkerOptions.workerSrc =
      "https://cdnjs.cloudflare.com/ajax/libs/pdf.js/3.11.174/pdf.worker.min.js";
    if (!pdfDocCache[pdfId]) {
      pdfDocCache[pdfId] = await pdfjsLib.getDocument(`/api/pdf/${pdfId}`).promise;
    }
    const doc = pdfDocCache[pdfId];
    body.innerHTML = "";
    const width = Math.min(860, body.clientWidth - 40);
    const last = Math.min(pageEnd, doc.numPages);
    for (let n = pageStart; n <= last; n++) {
      const page = await doc.getPage(n);
      const base = page.getViewport({ scale: 1 });
      const scale = width / base.width;
      const viewport = page.getViewport({ scale: scale * (window.devicePixelRatio || 1) });
      const canvas = document.createElement("canvas");
      canvas.width = viewport.width;
      canvas.height = viewport.height;
      canvas.style.width = `${width}px`;
      canvas.className = "viewer-page";
      const label = document.createElement("div");
      label.className = "viewer-page-label";
      label.textContent = `page ${n}`;
      body.appendChild(label);
      body.appendChild(canvas);
      await page.render({ canvasContext: canvas.getContext("2d"), viewport }).promise;
    }
  } catch {
    // fallback: extracted text (pasted-text sources, moved files, no pdf.js)
    try {
      const res = await fetch(`/api/pdf/${pdfId}/text?start=${pageStart}&end=${pageEnd}`);
      const pages = await res.json();
      if (!pages.length) throw new Error("no pages");
      body.innerHTML = pages.map((p) => `
        <div class="viewer-page-label">page ${p.page}</div>
        <div class="viewer-text">${md(p.text)}</div>`).join("");
    } catch {
      body.innerHTML = `<div style="padding:30px; color:#8A8F9C; font-size:12.5px">
        Couldn't load these pages — the original file may have moved.</div>`;
    }
  }
};

window.closeViewer = () => { $("viewer").style.display = "none"; };
$("viewer").addEventListener("click", (e) => { if (e.target === $("viewer")) closeViewer(); });
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeViewer(); });

/* ---- static listeners ---- */
$("tabStudy").onclick = () => { S.view = "study"; render(); };
$("tabProgress").onclick = () => { S.view = "progress"; render(); };
$("tabCards").onclick = () => { S.view = "cards"; render(); loadCards(); };
$("doNext").onclick = () => {
  const best = S.state?.best;
  if (!best) return;
  S.pdfId = best.pdf_id;
  S.view = "study";
  fetchState().then(() => sendChat(`Review my due cards in the topic "${best.title}" (topic_id ${best.topic_id})`));
};
/* ---- pdf upload (button + drag-and-drop onto the chat) ---- */
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
  if (!pdfs.length || S.busy) return;
  const btn = $("uploadBtn");
  btn.disabled = true;
  const scroll = $("chatScroll");
  const paths = [];
  try {
    for (const file of pdfs) {
      const id = `up-${Date.now()}`;
      scroll.insertAdjacentHTML("beforeend", `
        <div class="msg-row-user"><div class="bubble-user" style="min-width:240px">
          <div style="font-size:12px; margin-bottom:7px">📎 ${esc(file.name)}
            <span class="mono" style="font-size:10px; opacity:.7">(${(file.size / 1048576).toFixed(1)} MB)</span></div>
          <div class="up-track"><div class="up-fill" id="${id}"></div></div>
        </div></div>`);
      scroll.scrollTop = scroll.scrollHeight;
      const data = await xhrUpload(file, (pct) => {
        const fill = document.getElementById(id);
        if (fill) fill.style.width = `${pct}%`;
      });
      const fill = document.getElementById(id);
      if (fill) fill.style.width = "100%";
      paths.push(data.path);
    }
    const list = paths.map((p) => `"${p}"`).join(", ");
    sendChat(paths.length === 1
      ? `I've uploaded a PDF — ingest ${list}. Ask me which course it belongs to if you can't tell.`
      : `I've uploaded ${paths.length} PDFs — ingest them one at a time, starting with the first: ${list}. Ask me which course they belong to.`);
  } catch (e) {
    const scroll = $("chatScroll");
    scroll.insertAdjacentHTML("beforeend",
      renderMsg({ role: "assistant", text: `Upload failed: ${e.message}` }));
    scroll.scrollTop = scroll.scrollHeight;
  }
  btn.disabled = false;
  $("fileInput").value = "";
}

$("uploadBtn").onclick = () => $("fileInput").click();
$("fileInput").addEventListener("change", (e) => uploadPdfs(e.target.files));

const chatPane = document.querySelector(".chat");
["dragenter", "dragover"].forEach((ev) => chatPane.addEventListener(ev, (e) => {
  e.preventDefault();
  chatPane.classList.add("dragging");
}));
["dragleave", "drop"].forEach((ev) => chatPane.addEventListener(ev, (e) => {
  e.preventDefault();
  chatPane.classList.remove("dragging");
}));
chatPane.addEventListener("drop", (e) => uploadPdfs(e.dataTransfer.files));

$("sendBtn").onclick = () => sendChat($("chatInput").value);
$("chatInput").addEventListener("keydown", (e) => {
  if (e.key === "Enter") sendChat(e.target.value);
  if (e.key === "Escape") $("cmdPalette").style.display = "none";
  if (e.key === "Tab" && $("cmdPalette").style.display === "block") {
    e.preventDefault();
    const first = $("cmdPalette").querySelector(".cmd-item");
    if (first) { e.target.value = first.dataset.cmd + " "; renderPalette(); }
  }
});
$("chatInput").addEventListener("input", renderPalette);
$("chatInput").addEventListener("blur", () => setTimeout(() => { $("cmdPalette").style.display = "none"; }, 150));
document.querySelectorAll(".conf-btn").forEach((b) => b.onclick = () => {
  S.pendingConf = S.pendingConf === b.dataset.conf ? null : b.dataset.conf;
  renderConfRow();
});

fetchState();
fetchHistory();
