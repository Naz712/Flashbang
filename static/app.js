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
};

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
  (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
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

function renderMsg(m) {
  if (m.role === "user") {
    const meta = m.meta ? `<div class="grade-head"><span class="grade-meta">${esc(m.meta)}</span></div>` : "";
    return `<div class="msg-row-user"><div class="bubble-user">${meta}${esc(m.text)}</div></div>`;
  }
  if (m.role === "grade") {
    const cls = m.grade >= 4 ? "good" : "warn";
    const meta = m.meta ? `<span class="grade-meta">${esc(m.meta)}</span>` : "";
    return `<div class="msg-row-bot"><div class="bubble-bot">
      <div class="grade-head"><span class="grade-chip ${cls}">Grade ${m.grade}/5</span>${meta}</div>${esc(m.text)}</div></div>`;
  }
  return `<div class="msg-row-bot"><div class="bubble-bot">${esc(m.text)}</div></div>`;
}

async function sendChat(text) {
  if (S.busy || !text.trim()) return;
  S.busy = true;
  const scroll = $("chatScroll");
  scroll.insertAdjacentHTML("beforeend", renderMsg({ role: "user", text,
    meta: S.pendingConf ? `confidence: ${S.pendingConf}` : "" }));
  scroll.insertAdjacentHTML("beforeend",
    `<div id="thinking" class="msg-row-bot"><div class="bubble-bot thinking"><span></span><span></span><span></span></div></div>`);
  scroll.scrollTop = scroll.scrollHeight;
  $("chatInput").value = "";
  const confidence = S.pendingConf;
  S.pendingConf = null;
  renderConfRow();

  try {
    const res = await fetch("/api/chat", { method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: text, confidence }) });
    const data = await res.json();
    document.getElementById("thinking")?.remove();
    (data.grades || []).forEach((g) => scroll.insertAdjacentHTML("beforeend",
      renderMsg({ role: "grade", text: g.feedback, grade: g.quality, meta: g.meta || "" })));
    scroll.insertAdjacentHTML("beforeend", renderMsg({ role: "assistant", text: data.reply }));
    if (data.agent) $("agentName").textContent = `${data.agent[0].toUpperCase()}${data.agent.slice(1)} specialist`;
  } catch (e) {
    document.getElementById("thinking")?.remove();
    scroll.insertAdjacentHTML("beforeend", renderMsg({ role: "assistant", text: `Connection error: ${e}` }));
  }
  scroll.scrollTop = scroll.scrollHeight;
  S.busy = false;
  fetchState();
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
      <div class="topic-row">
        <span class="ret-dot" style="background:${retColor(t.mastery_pct)}"></span>
        <div style="flex:1; min-width:0">
          <div class="topic-title">${esc(t.title)}</div>
          <div class="mini-track"><div class="mini-fill" style="width:${t.mastery_pct}%; background:${retColor(t.mastery_pct)}"></div></div>
        </div>
        <span class="topic-pct">${t.mastery_pct.toFixed(0)}%</span>
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

  const courseCards = st.libCourses.map((c) => {
    const pdfCards = c.pdfs.map((p) => {
      const started = p.topics.some((t) => t.status !== "not_started");
      const [badge, bg, fg] = p.completion_pct >= 70 ? ["On track", "rgba(0,158,115,.10)", "#00794F"]
        : started ? ["In progress", "rgba(230,159,0,.13)", "#8A6100"] : ["Not started", "#F0F0EC", "#8A8F9C"];
      const d = deltaBits(p.delta);
      const topicRows = p.topics.map((t) => `
        <div class="trow">
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
    <div class="section-head" style="margin-top:10px"><span class="mono-label">COURSES</span><div class="rule"></div></div>
    ${courseCards || '<div class="card" style="color:#8A8F9C; font-size:12.5px">No courses yet — ingest something from the Study tab.</div>'}`;
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
  $("studyScreen").style.display = S.view === "study" ? "flex" : "none";
  $("progressScreen").style.display = S.view === "progress" ? "block" : "none";
  renderConfRow();
  renderRail();
  renderProgress();
}

/* ---- actions (referenced from rendered HTML) ---- */
window.toggleRail = () => { S.railOpen = !S.railOpen; renderRail(); };
window.pickLen = (m) => { S.sessionLen = m; renderRail(); };
window.dismissRecap = () => { S.recap = null; renderRail(); };
window.openDoc = (pdfId) => { S.pdfId = pdfId; S.view = "study"; fetchState(); };
window.startReview = () => {
  const cur = S.state?.current;
  sendChat(cur ? `Review my due cards in ${cur.filename}` : "Review my due cards");
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

/* ---- static listeners ---- */
$("tabStudy").onclick = () => { S.view = "study"; render(); };
$("tabProgress").onclick = () => { S.view = "progress"; render(); };
$("doNext").onclick = () => {
  const best = S.state?.best;
  if (!best) return;
  S.pdfId = best.pdf_id;
  S.view = "study";
  fetchState().then(() => sendChat(`Review my due cards in the topic "${best.title}"`));
};
$("sendBtn").onclick = () => sendChat($("chatInput").value);
$("chatInput").addEventListener("keydown", (e) => { if (e.key === "Enter") sendChat(e.target.value); });
document.querySelectorAll(".conf-btn").forEach((b) => b.onclick = () => {
  S.pendingConf = S.pendingConf === b.dataset.conf ? null : b.dataset.conf;
  renderConfRow();
});

fetchState();
fetchHistory();
