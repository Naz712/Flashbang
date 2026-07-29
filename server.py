"""Flashbang web app — serves the v3 dashboard design (templates/index.html)
and a JSON API over the backend. De-agented 2026-07-29: the app deals review
cards itself and ingestion is a button; the only per-interaction model call
left is the fast-tier grader. Run: python server.py  →  http://localhost:5002
"""

import json
import os
import random
from datetime import datetime, timedelta
from flask import Flask, jsonify, render_template, request, send_file
from werkzeug.utils import secure_filename

import mastery
import stats as stats_module
from database import (
    get_courses, get_pdfs, get_pdf, get_mastery_inputs,
    get_due_forecast, get_time_by_course, get_topic_time_spent,
    log_focus_session, log_answer, attach_card_to_answer,
    get_calibration, get_topic_accuracy, set_session_accuracy, get_study_log,
    get_pdf_pages, get_cards, update_card, delete_card, get_topics, insert_card,
    set_exam_date, delete_pdf,
    save_occlusion, get_occlusions, delete_occlusion,
    save_annotation, get_annotations, update_annotation, delete_annotation,
    get_setting, set_setting, spread_backlog, get_due_cards,
    update_topic, split_topic, delete_topic, get_session_report_data,
    start_session, end_session, review_card, undo_review,
    save_topics, save_concepts, create_course, init_db,
)
from generation import parse_flashcards, extract_topic_concepts, generate_cards_for_topic
from grading import grade_answer
from llm_utils import complete_text
from pdf_ingest import read_pdf, propose_topics

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB upload cap

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
init_db()   # was the orchestrator's job; the orchestrator is gone

chat_history = []       # review-surface display log: {role, text, grade, meta}
grade_log = []          # {at: datetime, quality: int} — feeds focus-session recap
assistant_history = []  # LangChain messages for the corner-bubble assistant

# live review sessions: the app deals, the user types, the grader grades.
# session_id -> {"kind", "queue": [card rows], "i", "relearn": [], "phase",
#                "grades": [], "scope": {...}}
REVIEW = {}


def fmt_min(minutes):
    minutes = int(round(minutes or 0))
    return f"{minutes // 60}h {minutes % 60}m" if minutes >= 60 else f"{minutes}m"


def _pdf_payload(pdf_id, spent_by_topic, now=None):
    """One pdf's report extended with time-spent, weekly delta, and per-topic
    due-card intervals (for the forgetting curve)."""
    pdf = get_pdf(pdf_id)
    topics, cards = get_mastery_inputs(pdf_id)
    report = mastery.build_pdf_report(pdf, topics, cards, now)

    now_dt = now or datetime.now()
    now_iso = now_dt.isoformat(timespec="seconds")
    by_topic = {}
    for c in cards:
        by_topic.setdefault(c["topic_id"], []).append(c)

    # weekly delta: recompute completion as of 7 days ago; cards whose latest
    # review is newer than that are treated as unreviewed then (approximation —
    # only the latest review per card is stored)
    then = now_dt - timedelta(days=7)
    then_iso = then.isoformat(timespec="seconds")
    cards_then = [{"topic_id": c["topic_id"], "interval_days": c["interval_days"],
                   "last_reviewed_at": c["last_reviewed_at"]
                   if c["last_reviewed_at"] and c["last_reviewed_at"] <= then_iso else None,
                   "next_review": c["next_review"], "id": c["id"]}
                  for c in cards]
    report_then = mastery.build_pdf_report(pdf, topics, cards_then, then)
    delta = round(report["completion_pct"] - report_then["completion_pct"])

    total_spent = 0
    for t in report["topics"]:
        topic_cards = by_topic.get(t["id"], [])
        due_cards = [c for c in topic_cards if c["next_review"] <= now_iso]
        t["iv"] = round(sum(c["interval_days"] for c in due_cards) / len(due_cards), 1) if due_cards else 0
        t["spent"] = spent_by_topic.get(t["id"], 0)
        total_spent += t["spent"]

    report["delta"] = delta
    report["due"] = sum(t["cards_due"] for t in report["topics"])
    report["spent_total"] = fmt_min(total_spent)
    report["course_id"] = pdf["course_id"]
    return report


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/architecture")
def architecture():
    """One-page system diagram (docs/architecture.html) — presentation aid."""
    return send_file(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "docs", "architecture.html"))


def _md_lite(md):
    """Tiny markdown→HTML for the reference board (headers, fenced code,
    bold/italic/inline code, hr, list items). Escape first — content is ours
    but the habit is the habit."""
    import html as html_mod
    import re
    out, in_code = [], False
    for line in md.splitlines():
        if line.startswith("```"):
            out.append("</pre>" if in_code else '<pre class="code">')
            in_code = not in_code
            continue
        if in_code:
            out.append(html_mod.escape(line))
            continue
        text = html_mod.escape(line)
        text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*([^*\s][^*]*)\*(?!\*)", r"<em>\1</em>", text)
        if text.startswith("# "):
            out.append(f"<h1>{text[2:]}</h1>")
        elif text.startswith("## "):
            out.append(f"<h2>{text[3:]}</h2>")
        elif text.strip() == "---":
            out.append("<hr>")
        elif text.startswith("- "):
            out.append(f"<div class='li'>• {text[2:]}</div>")
        elif text.strip() == "":
            out.append("<div class='gap'></div>")
        else:
            out.append(f"<p>{text}</p>")
    return "\n".join(out)


@app.route("/reference")
def reference():
    """The hand-rolled ↔ framework reference board, rendered from
    docs/REFERENCE_BOARD.md (single source of truth)."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "docs", "REFERENCE_BOARD.md")
    with open(path, encoding="utf-8") as f:
        body = _md_lite(f.read())
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Flashbang — Reference Board</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
body{{background:#F2F2EF;color:#1C1E26;font-family:'IBM Plex Sans',system-ui,sans-serif;
  max-width:860px;margin:0 auto;padding:34px 28px 60px;line-height:1.65;font-size:14px}}
h1{{font-size:21px;letter-spacing:-.3px;margin:0 0 4px}}
h2{{font-size:15px;margin:30px 0 6px;padding-top:18px;border-top:1px solid #E3E3DE}}
p{{margin:6px 0}} .gap{{height:6px}} .li{{margin:3px 0 3px 10px}}
hr{{border:none;border-top:1px dashed #C9CCD4;margin:22px 0}}
code{{font-family:'IBM Plex Mono',monospace;font-size:12px;background:#ECECE8;
  padding:1px 5px;border-radius:4px}}
.code{{font-family:'IBM Plex Mono',monospace;font-size:12px;line-height:1.55;
  background:#fff;border:1px solid #E3E3DE;border-radius:10px;padding:13px 16px;
  overflow-x:auto;box-shadow:0 1px 2px rgba(16,18,24,.04)}}
</style></head><body>{body}</body></html>"""


@app.get("/api/state")
def state():
    now = datetime.now()
    spent_by_topic = get_topic_time_spent()
    courses = [dict(c) for c in get_courses()]

    lib_courses = []
    all_reports = {}
    for i, course in enumerate(courses):
        pdf_reports = []
        for pdf in get_pdfs(course["id"]):
            payload = _pdf_payload(pdf["id"], spent_by_topic, now)
            all_reports[pdf["id"]] = payload
            pdf_reports.append(payload)
        course_minutes = sum(
            sum(t["spent"] for t in r["topics"]) for r in pdf_reports)
        lib_courses.append({
            "id": course["id"], "name": course["name"], "ci": i,
            "pdfCount": len(pdf_reports),
            "dueCount": sum(r["due"] for r in pdf_reports),
            "timeSpent": fmt_min(course_minutes),
            "pdfs": pdf_reports,
        })

    due_total = sum(c["dueCount"] for c in lib_courses)

    # weakest due topic across the library → "Do next"
    best = None
    for course in lib_courses:
        for pdf_report in course["pdfs"]:
            for t in pdf_report["topics"]:
                if t["cards_due"] > 0 and (best is None or t["mastery_pct"] < best["pct"]):
                    best = {"course_id": course["id"], "pdf_id": pdf_report["pdf_id"],
                            "topic_id": t["id"], "title": t["title"], "pct": t["mastery_pct"]}

    # current doc: requested, else best's pdf, else first
    pdf_id = request.args.get("pdf_id", type=int)
    if pdf_id not in all_reports:
        pdf_id = best["pdf_id"] if best else (next(iter(all_reports), None))
    current = all_reports.get(pdf_id)
    current_course = None
    if current:
        current_course = next(c for c in lib_courses
                              if c["id"] == current["course_id"])

    # forgetting curve for the current doc's weakest due topic
    curve = None
    if current:
        due_topics = [t for t in current["topics"] if t["cards_due"] > 0]
        if due_topics:
            weak = min(due_topics, key=lambda t: t["mastery_pct"])
            curve = {"S": round(mastery._STABILITY_SCALE * max(weak["iv"], 1), 2),
                     "R0": weak["mastery_pct"] / 100, "title": weak["title"]}

    s = stats_module.compute_stats(now)
    today_idx = now.weekday()  # Monday = 0
    week = []
    for i in range(7):
        day = (now - timedelta(days=today_idx - i)).date().isoformat()
        entry = next((d for d in s["daily_last_14"] if d["date"] == day), None)
        week.append({"day": "MTWTFSS"[i], "lit": bool(entry and entry["minutes"] > 0),
                     "future": i > today_idx})

    subject_rows = get_time_by_course(kinds=stats_module.FLASHCARD_KINDS)
    subject_total = sum(r["minutes"] for r in subject_rows) or 1
    course_index = {c["id"]: i for i, c in enumerate(courses)}
    topic_accuracy = get_topic_accuracy()

    return jsonify({
        "courses": courses,
        "dueTotal": due_total,
        "best": best,
        "current": current,
        "currentCourse": {"id": current_course["id"], "name": current_course["name"],
                          "ci": current_course["ci"]} if current_course else None,
        "curve": curve,
        "libCourses": lib_courses,
        "forecast": get_due_forecast(7),
        "subjectTime": [{"name": r["name"], "minutes": r["minutes"],
                         "time": fmt_min(r["minutes"]),
                         "share": round(r["minutes"] / subject_total * 100),
                         "ci": course_index.get(r["course_id"], 3)}
                        for r in subject_rows],
        "metrics": stats_module.compute_metrics(now),
        "calibration": get_calibration(28),
        "topicFlags": {tid: ("easy" if rate > 95 else "hard" if rate < 60 else None)
                       for tid, rate in topic_accuracy.items()},
        "topicAccuracy": topic_accuracy,
        "recentSessions": [
            {"at": r["started_at"], "kind": r["kind"],
             "cards": r["cards_reviewed"], "minutes": r["minutes"],
             "accuracy": r["accuracy"], "topics": r["topic_titles"]}
            for r in get_study_log(kinds=stats_module.FLASHCARD_KINDS)[:8] if r["ended_at"]],
        "stats": {"weekTime": fmt_min(s["week_minutes"]),
                  "sessionCount": s["week_sessions"],
                  "week": week,
                  "litCount": sum(1 for d in week if d["lit"]),
                  "streak": s["current_streak_days"]},
        # reading hub: kind='reading' blocks + annotation counts, fully
        # separate from the flashcard analytics above
        "reading": stats_module.compute_reading_stats(now),
        # daily time budget: minutes/day + measured per-card pace
        "budget": {"daily_minutes": int(get_setting("daily_minutes", 0) or 0),
                   "sec_per_card": stats_module.seconds_per_card()},
        # drives the confidence widget — only review sessions ask for confidence
        "sessionActive": any(s["kind"] == "review" for s in REVIEW.values()),
    })


@app.get("/api/plan.json")
def plan_json():
    """Read-only feed for external schedulers (the Zo calendar automation):
    cards coming due per day for the next 7 days plus a suggested block
    length, capped at the user's daily budget when one is set. Per-card
    pace is measured from answer latency once enough data exists."""
    budget = int(get_setting("daily_minutes", 0) or 0)
    sec_per_card = stats_module.seconds_per_card()
    forecast = get_due_forecast(7)
    plan = []
    for entry in forecast:
        due = entry["count"]
        raw = due * sec_per_card / 60
        minutes = 0 if due == 0 else min([15, 25, 45, 60], key=lambda b: abs(b - raw))
        if budget:
            minutes = min(minutes, budget)
        plan.append({"date": entry["day"], "cards_due": due, "suggested_minutes": minutes})
    return jsonify({
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "daily_budget_minutes": budget or None,
        "seconds_per_card": sec_per_card,
        "days": plan,
        "note": "cards_due counts overdue cards into today; suggested_minutes "
                "is a focus-block length capped by the daily budget",
    })


@app.get("/api/settings")
def settings_get():
    return jsonify({"daily_minutes": int(get_setting("daily_minutes", 0) or 0)})


@app.post("/api/settings")
def settings_post():
    body = request.get_json(force=True)
    if "daily_minutes" in body:
        minutes = max(0, min(240, int(body["daily_minutes"] or 0)))
        set_setting("daily_minutes", minutes)
    return jsonify({"ok": True})


@app.post("/api/backlog/spread")
def backlog_spread():
    """Push due cards beyond today's time budget onto the coming days."""
    budget = int(get_setting("daily_minutes", 0) or 0)
    if not budget:
        return jsonify({"error": "set a daily budget first"}), 400
    per_day = max(1, int(budget * 60 / stats_module.seconds_per_card()))
    result = spread_backlog(per_day)
    return jsonify({"per_day": per_day, **result})


@app.post("/api/cards/import")
def cards_import():
    """Paste-import (NotebookLM, Anki exports, hand lists) into one topic.
    dry_run=true returns the parsed preview without writing anything."""
    body = request.get_json(force=True)
    topic_id = body.get("topic_id")
    if not isinstance(topic_id, int):
        return jsonify({"error": "topic_id (integer) required"}), 400
    if isinstance(body.get("cards"), list):
        # client sends back the previewed cards — no re-parse, no second LLM call
        cards = [{"question": str(c.get("question", "")).strip(),
                  "answer": str(c.get("answer", "")).strip()}
                 for c in body["cards"] if isinstance(c, dict)]
        cards = [c for c in cards if c["question"] and c["answer"]]
        source = "client"
    else:
        try:
            cards, source = parse_flashcards(body.get("text"))
        except Exception as e:
            return jsonify({"error": f"parse failed: {e}"}), 500
    if body.get("dry_run"):
        return jsonify({"cards": cards, "source": source})
    inserted = 0
    for c in cards:
        insert_card(topic_id, c["question"], c["answer"])
        inserted += 1
    return jsonify({"inserted": inserted, "source": source})


@app.get("/api/history")
def history():
    return jsonify(chat_history)


def _ingest_preview(pdf_id):
    """Light course-card payload rendered in chat right after save_topics —
    the same shape the Progress pdf cards show, minus mastery (no cards yet)."""
    pdf = get_pdf(pdf_id)
    if pdf is None:
        return None
    topics = get_topics(pdf_id=pdf_id)
    return {"pdf_id": pdf_id, "filename": pdf["filename"],
            "total_pages": pdf["total_pages"],
            "est": fmt_min(pdf["est_total_minutes"] or 0),
            "topics": [{"title": t["title"],
                        "pages": f"{t['page_start']}-{t['page_end']}",
                        "est_minutes": t["est_minutes"],
                        "kind": t["kind"] or "content"} for t in topics]}


def _build_session_report(session_id=None):
    """The take-it-to-a-tutor gap report for an ended session: what was
    covered, what was missed (with the grader's gap diagnosis and source
    pages), and a coaching prompt — assembled deterministically, zero LLM
    calls. The whole point is spending the user's tokens OUTSIDE the app."""
    session, rows = get_session_report_data(session_id)
    if session is None or not rows:
        return None
    missed = [r for r in rows if r["quality"] <= 3]
    passed = [r for r in rows if r["quality"] > 3]
    courses = sorted({r["course_name"] for r in rows})
    acc = session["accuracy"]

    lines = [f"I just finished a {session['kind']} flashcard session on {', '.join(courses)}: "
             f"{len(rows)} cards" + (f", {round(acc)}% recall." if acc is not None else ".")]
    if missed:
        lines += ["", "Cards I missed or only partly got:"]
        for i, r in enumerate(missed, 1):
            lines.append(f"{i}. [{r['filename']} p.{r['page_start']}-{r['page_end']} · {r['topic_title']}] "
                         f"Q: {r['question']}")
            lines.append(f"   Expected answer: {r['answer']}")
            if r["gap"]:
                lines.append(f"   My gap: {r['gap']}")
            if r["confidence"]:
                lines.append(f"   (I felt {r['confidence']} before answering)")
    if passed:
        lines += ["", "For context, I answered these correctly:"]
        lines += [f"- {r['question']}" for r in passed]
    lines += ["", "Please coach me on the missed items: 1) explain each underlying concept simply and "
                  "connect them to each other, 2) give me one memorable hook per concept, 3) then quiz "
                  "me with three fresh questions that test the same ideas from different angles."]
    return {
        "session_id": session["id"], "kind": session["kind"],
        "cards": len(rows), "accuracy": acc, "passed_count": len(passed),
        "missed": [{"card_id": r["card_id"], "question": r["question"], "answer": r["answer"],
                    "gap": r["gap"], "confidence": r["confidence"],
                    "topic_title": r["topic_title"], "pdf_id": r["pdf_id"],
                    "page_start": r["page_start"], "page_end": r["page_end"]} for r in missed],
        "passed_questions": [r["question"] for r in passed],
        "text": "\n".join(lines),
    }


@app.get("/api/session_report")
def session_report():
    report = _build_session_report(request.args.get("session_id", type=int))
    if report is None:
        return jsonify({"error": "no ended session with graded answers"}), 404
    return jsonify(report)


@app.post("/api/assistant")
def assistant():
    """The corner bubble: one scoped agent turn, only when the user asks for
    one. Reviews/ingest/card-gen stay app-driven — this is for library edits,
    questions against saved notes, stats, and planning. History is capped so
    a long chat can't quietly become expensive."""
    from langchain_core.messages import HumanMessage
    from agents import AGENTS
    from agent_core import run_turn
    body = request.get_json(force=True)
    message = (body.get("message") or "").strip()
    if not message:
        return jsonify({"error": "empty message"}), 400
    assistant_history.append(HumanMessage(content=message))
    del assistant_history[:-12]          # keep the last few turns only
    try:
        reply = run_turn(assistant_history, AGENTS["assistant"])
    except Exception as e:
        return jsonify({"reply": f"Something went wrong: {type(e).__name__}: {e}"})
    return jsonify({"reply": reply})


@app.post("/api/tutor_prompt")
def tutor_prompt():
    """One fast-tier call that reads THIS session's misses and writes the
    coaching request the user should paste into an external tutor chat —
    tailored to the actual confusion pattern instead of a fixed template.
    Runs only when the user clicks copy; the deterministic report text is
    the fallback if the call fails."""
    body = request.get_json(force=True)
    report = _build_session_report(body.get("session_id"))
    if report is None:
        return jsonify({"error": "no report for that session"}), 404
    if not report["missed"]:
        return jsonify({"text": report["text"], "source": "deterministic"})

    misses = "\n".join(
        f"- Topic: {m['topic_title']} (source: {m['pdf_id'] and ''}p.{m['page_start']}-{m['page_end']})\n"
        f"  Question: {m['question']}\n"
        f"  Correct answer: {m['answer']}\n"
        f"  What I got wrong: {m['gap'] or '(not diagnosed)'}"
        + (f"\n  I felt {m['confidence']} before answering" if m["confidence"] else "")
        for m in report["missed"])
    got_right = "\n".join(f"- {q}" for q in report.get("passed_questions", [])) or "(none)"

    prompt = f"""A student just finished a flashcard review and got some cards wrong. Write the message THEY should paste into a separate AI tutor chat to get the most useful help.

What they missed:
{misses}

What they answered correctly (so the tutor doesn't re-explain it):
{got_right}

Write the message in FIRST PERSON as the student. Requirements:
- Open with what they're studying and one sentence naming the REAL pattern in these mistakes if there is one (e.g. confusing two related ideas, missing the mechanism behind a rule, remembering names but not purposes). If the misses are unrelated, say that instead of inventing a pattern.
- Include the specific questions, the right answers, and what they got wrong, so the tutor has the facts.
- Then ask for exactly the help THIS set of gaps needs. Tailor the ask: a conceptual confusion needs a compare-and-contrast; a missing mechanism needs a walk-through; a vocabulary gap needs concrete examples. Don't ask for everything generically.
- End by asking the tutor to check understanding with 2-3 fresh questions aimed at the same weak spots.
- Plain language, no headers, no markdown formatting, under 300 words. Output ONLY the message text — no preamble, no quotes around it."""

    try:
        text, _ = complete_text(prompt, fast=True, max_tokens=800)
        text = (text or "").strip()
        if len(text) < 40:
            raise ValueError("empty tailoring")
        return jsonify({"text": text, "source": "ai"})
    except Exception:
        return jsonify({"text": report["text"], "source": "deterministic"})


def _clean_latency(value):
    """Client-reported ms from question shown to answer sent. Reject anything
    non-numeric, non-positive, or over 30 min (stale tab, walked away)."""
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    return int(value) if 0 < value < 30 * 60 * 1000 else None


# ---------------------------------------------------------------- review driver
# The app deals the cards; the user types; the ONLY model call per answer is
# the fast-tier grader (~$0.0002). No router, no agent loop, no history resend.

def _deal_payload(sess, session_id):
    i, queue = sess["i"], sess["queue"]
    if i >= len(queue):
        return None
    card = queue[i]
    return {"session_id": session_id, "card_id": card["id"],
            "question": card["question"], "topic_title": card["topic_title"],
            "n": i + 1, "total": len(queue),
            "phase": sess["phase"]}


def _q_entry(payload):
    """History entry for a dealt question, in the marker format the UI styles."""
    return {"role": "assistant", "grade": 0, "meta": "",
            "text": f"[CARD {payload['n']}/{payload['total']} · {payload['topic_title']}]\n{payload['question']}"}


@app.post("/api/review/start")
def review_start():
    body = request.get_json(force=True)
    kind = "cram" if body.get("kind") == "cram" else "review"
    scope = {k: body.get(k) for k in ("course_id", "pdf_id", "topic_id") if body.get(k)}
    if kind == "review":
        due = [dict(r) for r in get_due_cards(**scope)]   # most overdue first
        total_due = len(due)
        budget = int(get_setting("daily_minutes", 0) or 0)
        fit = max(1, int(budget * 60 / stats_module.seconds_per_card())) if budget else None
        queue = due[:fit] if fit else due
    else:
        queue = [dict(r) for r in get_cards(**scope)]
        random.shuffle(queue)
        total_due, fit = len(queue), None
    if not queue:
        return jsonify({"empty": True, "kind": kind})
    session_id = start_session(kind, course_id=scope.get("course_id"),
                               pdf_id=scope.get("pdf_id"),
                               topic_ids=[scope["topic_id"]] if kind == "cram" and scope.get("topic_id") else None)
    REVIEW[session_id] = {"kind": kind, "queue": queue, "i": 0, "phase": "main",
                          "relearn": [], "grades": []}
    payload = _deal_payload(REVIEW[session_id], session_id)
    chat_history.append(_q_entry(payload))
    return jsonify({"session_id": session_id, "card": payload,
                    "total_due": total_due,
                    "budget_capped": bool(fit and total_due > len(queue))})


def _advance(sess, session_id):
    """Next card, switching into the relearn phase when the main queue ends."""
    sess["i"] += 1
    if sess["i"] >= len(sess["queue"]):
        if sess["phase"] == "main" and sess["relearn"]:
            # successive relearning: re-ask this session's failures, unscored
            sess["queue"] = sess["relearn"]
            sess["relearn"] = []
            sess["i"] = 0
            sess["phase"] = "relearn"
            return _deal_payload(sess, session_id), True
        return None, False
    return _deal_payload(sess, session_id), False


@app.post("/api/review/answer")
def review_answer():
    body = request.get_json(force=True)
    sess = REVIEW.get(body.get("session_id"))
    if sess is None:
        return jsonify({"error": "no such session"}), 404
    session_id = body["session_id"]
    card = sess["queue"][sess["i"]]
    answer = (body.get("answer") or "").strip()
    confidence = body.get("confidence") if body.get("confidence") in ("sure", "unsure") else None
    if not answer:
        return jsonify({"error": "empty answer"}), 400

    grade = grade_answer(card["question"], card["answer"], answer, confidence)
    meta = ""
    if sess["phase"] == "main":
        aid = log_answer(grade["quality"], confidence,
                         latency_ms=_clean_latency(body.get("latency_ms")),
                         gap=grade.get("gap"))
        attach_card_to_answer(aid, card["id"])
        grade_log.append({"at": datetime.now(), "quality": grade["quality"]})
        sess["grades"].append(grade["quality"])
        if sess["kind"] == "review":
            meta = str(review_card(card["id"], grade["quality"]))
        if grade["quality"] < 3:
            sess["relearn"].append(card)
    else:
        meta = "relearning re-ask — not scored"

    grade_entry = {"role": "grade", "grade": grade.get("quality", 0),
                   "text": grade.get("feedback", ""), "meta": meta,
                   "card_id": card["id"],
                   "right": grade.get("right", ""), "gap": grade.get("gap", ""),
                   "why": grade.get("why", ""), "hook": grade.get("hook", ""),
                   "calibration": grade.get("calibration", ""),
                   "answer": grade.get("correct_answer", card["answer"])}
    chat_history.append({"role": "user", "text": answer, "grade": 0,
                         "meta": f"confidence: {confidence}" if confidence else ""})
    chat_history.append(grade_entry)

    nxt, entering_relearn = _advance(sess, session_id)
    if nxt:
        chat_history.append(_q_entry(nxt))
    return jsonify({"grade": grade_entry, "next": nxt,
                    "entering_relearn": entering_relearn,
                    "relearn_count": len(sess["relearn"]) if entering_relearn else None,
                    "done": nxt is None})


@app.post("/api/review/skip")
def review_skip():
    body = request.get_json(force=True)
    sess = REVIEW.get(body.get("session_id"))
    if sess is None:
        return jsonify({"error": "no such session"}), 404
    nxt, entering_relearn = _advance(sess, body["session_id"])
    if nxt:
        chat_history.append(_q_entry(nxt))
    return jsonify({"next": nxt, "entering_relearn": entering_relearn, "done": nxt is None})


@app.post("/api/review/undo")
def review_undo():
    body = request.get_json(force=True)
    undo_review(body.get("card_id"))
    return jsonify({"ok": True})


@app.post("/api/review/end")
def review_end():
    body = request.get_json(force=True)
    session_id = body.get("session_id")
    sess = REVIEW.pop(session_id, None)
    if sess is None:
        return jsonify({"error": "no such session"}), 404
    graded = len(sess["grades"])
    end_session(session_id, cards_reviewed=graded if sess["kind"] == "cram" else None)
    accuracy = None
    if sess["grades"]:
        accuracy = round(sum(1 for q in sess["grades"] if q >= 3) / graded * 100)
        set_session_accuracy(session_id, accuracy)
    report = _build_session_report(session_id)
    summary = {"cards": graded, "accuracy": accuracy, "kind": sess["kind"]}
    chat_history.append({"role": "assistant", "grade": 0, "meta": "",
                         "text": f"Session done — {graded} cards"
                                 + (f", {accuracy}% recall." if accuracy is not None else ".")})
    if report:
        chat_history.append({"role": "report", "report": report, "text": "", "grade": 0, "meta": ""})
    return jsonify({"summary": summary, "report": report})


# ---------------------------------------------------------------- button ingest

@app.post("/api/ingest_auto")
def ingest_auto():
    """The whole ingest pipeline behind one button: read pages → segment →
    save. No conversation, no approval step — the Edit-split editor is the
    correction tool afterwards."""
    body = request.get_json(force=True)
    path = body.get("path")
    if not path or not os.path.exists(path):
        return jsonify({"error": "file not found"}), 400
    course_id = body.get("course_id")
    if not course_id:
        name = (body.get("course_name") or "").strip()
        if not name:
            return jsonify({"error": "course_id or course_name required"}), 400
        existing = next((c for c in get_courses() if c["name"].lower() == name.lower()), None)
        course_id = existing["id"] if existing else create_course(name)
    result = read_pdf(path, course_id)
    pdf_id = result["pdf_id"]
    proposal = propose_topics(pdf_id)
    save_topics(pdf_id, proposal["topics"])
    return jsonify({"preview": _ingest_preview(pdf_id), "course_id": course_id})


@app.post("/api/topics/<int:topic_id>/generate_cards")
def topics_generate_cards(topic_id):
    """Concept extraction → notes (embedded for search) → cards, straight in.
    Unwanted cards get pruned on the Cards screen afterwards."""
    concepts = extract_topic_concepts(topic_id)
    if not concepts:
        return jsonify({"error": "no concepts found in this topic"}), 422
    note_ids = save_concepts(topic_id, concepts)
    cards = generate_cards_for_topic(topic_id, concepts, note_ids)
    ids = [insert_card(topic_id=c["topic_id"], question=c["question"],
                       answer=c["answer"], note_id=c.get("note_id")) for c in cards]
    return jsonify({"inserted": len(ids), "concepts": len(concepts),
                    "cards": [{"question": c["question"], "answer": c["answer"]} for c in cards]})


@app.get("/api/pdf/<int:pdf_id>")
def serve_pdf(pdf_id):
    """The original PDF file, for the in-app page viewer."""
    pdf = get_pdf(pdf_id)
    if pdf is None or not pdf["file_path"] or not os.path.exists(pdf["file_path"]):
        return jsonify({"error": "file not available"}), 404
    return send_file(pdf["file_path"], mimetype="application/pdf")


@app.get("/api/pdf/<int:pdf_id>/text")
def serve_pdf_text(pdf_id):
    """Extracted page text for a range — fallback viewer for pasted-text
    sources or PDFs whose file moved."""
    start = request.args.get("start", type=int)
    end = request.args.get("end", type=int)
    pages = get_pdf_pages(pdf_id, start, end)
    return jsonify([{"page": p["page_number"], "text": p["text"]} for p in pages])


@app.get("/api/pdf/<int:pdf_id>/slice")
def serve_pdf_slice(pdf_id):
    """A new PDF containing just pages start..end — for taking one topic's
    pages into NotebookLM or anywhere else."""
    from io import BytesIO
    from pypdf import PdfReader, PdfWriter
    pdf = get_pdf(pdf_id)
    if pdf is None or not pdf["file_path"] or not os.path.exists(pdf["file_path"]):
        return jsonify({"error": "source pdf not available"}), 404
    reader = PdfReader(pdf["file_path"])
    ranges_arg = request.args.get("ranges")
    if ranges_arg:
        # several topics in ONE file, e.g. ranges=1-4,9-12,20-20
        try:
            spans = []
            for part in ranges_arg.split(","):
                a, _, b = part.partition("-")
                s, e = int(a), int(b or a)
                if not (1 <= s <= e <= len(reader.pages)):
                    raise ValueError
                spans.append((s, e))
            if not spans:
                raise ValueError
        except ValueError:
            return jsonify({"error": "bad ranges"}), 400
        name_bit = "selection"
    else:
        start = max(1, request.args.get("start", 1, type=int))
        end = min(request.args.get("end", start, type=int), len(reader.pages))
        if start > end:
            return jsonify({"error": "invalid range"}), 400
        spans = [(start, end)]
        name_bit = f"p{start}-{end}"
    writer = PdfWriter()
    for s, e in spans:
        for n in range(s - 1, e):          # pypdf is 0-based; ours is 1-based
            writer.add_page(reader.pages[n])
    buf = BytesIO()
    writer.write(buf)
    buf.seek(0)
    base = os.path.splitext(pdf["filename"])[0]
    return send_file(buf, mimetype="application/pdf", as_attachment=True,
                     download_name=f"{base}-{name_bit}.pdf")


@app.patch("/api/topics/<int:topic_id>")
def topics_update(topic_id):
    body = request.get_json(force=True)
    try:
        update_topic(topic_id,
                     title=(body.get("title") or "").strip() or None,
                     page_start=body.get("page_start"),
                     page_end=body.get("page_end"),
                     est_minutes=body.get("est_minutes"),
                     kind=body.get("kind"))
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.delete("/api/topics/<int:topic_id>")
def topics_delete(topic_id):
    try:
        delete_topic(topic_id)
    except ValueError as e:
        return jsonify({"error": str(e)}), 404
    return jsonify({"ok": True})


@app.post("/api/topics/<int:topic_id>/split")
def topics_split(topic_id):
    body = request.get_json(force=True)
    try:
        new_id = split_topic(topic_id, body.get("at_page"), body.get("new_title"))
    except (ValueError, TypeError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"new_topic_id": new_id})


@app.post("/api/exam")
def api_set_exam():
    body = request.get_json(force=True)
    set_exam_date(body["course_id"], body.get("date") or None)
    return jsonify({"ok": True})


@app.get("/api/cards")
def api_cards():
    rows = get_cards(course_id=request.args.get("course_id", type=int),
                     pdf_id=request.args.get("pdf_id", type=int),
                     topic_id=request.args.get("topic_id", type=int))
    return jsonify([dict(r) for r in rows])


@app.get("/api/topics")
def api_topics():
    rows = get_topics(pdf_id=request.args.get("pdf_id", type=int),
                      course_id=request.args.get("course_id", type=int))
    return jsonify([dict(r) for r in rows])


@app.post("/api/cards")
def api_create_card():
    """Create a card under a topic; pdf_id/course_id derive from the topic
    server-side so the linkage can never be wrong."""
    body = request.get_json(force=True)
    topic_id = body.get("topic_id")
    question = (body.get("question") or "").strip()
    answer = (body.get("answer") or "").strip()
    if not (topic_id and question and answer):
        return jsonify({"error": "topic_id, question, and answer are required"}), 400
    card_id = insert_card(topic_id, question, answer)
    return jsonify({"id": card_id})


@app.post("/api/cards/<int:card_id>")
def api_update_card(card_id):
    body = request.get_json(force=True)
    update_card(card_id, question=body.get("question"),
                answer=body.get("answer"), topic_id=body.get("topic_id"))
    return jsonify({"ok": True})


@app.delete("/api/cards/<int:card_id>")
def api_delete_card(card_id):
    delete_card(card_id)
    return jsonify({"ok": True})


@app.post("/api/upload")
def upload():
    """Save an uploaded PDF into uploads/ and return its path; the front-end
    then asks the ingestion agent to ingest that path."""
    f = request.files.get("file")
    if f is None or not f.filename:
        return jsonify({"error": "no file provided"}), 400
    if not f.filename.lower().endswith(".pdf"):
        return jsonify({"error": "only .pdf files are supported"}), 400
    name = secure_filename(f.filename) or "upload.pdf"
    base, ext = os.path.splitext(name)
    path = os.path.join(UPLOAD_DIR, name)
    suffix = 1
    while os.path.exists(path):   # never overwrite an earlier upload
        path = os.path.join(UPLOAD_DIR, f"{base}_{suffix}{ext}")
        suffix += 1
    f.save(path)
    return jsonify({"path": path, "filename": os.path.basename(path)})


@app.delete("/api/pdfs/<int:pdf_id>")
def delete_pdf_route(pdf_id):
    """Manual delete from the Progress screen — same cascade the organizer
    agent's delete_pdf tool runs, plus removal of the uploaded file copy."""
    pdf = get_pdf(pdf_id)
    if pdf is None:
        return jsonify({"error": f"no pdf with id {pdf_id}"}), 404
    delete_pdf(pdf_id)
    if pdf["file_path"]:
        file_path = os.path.abspath(pdf["file_path"])
        if os.path.normcase(os.path.dirname(file_path)) == os.path.normcase(UPLOAD_DIR):
            try:
                os.remove(file_path)
            except OSError:
                pass   # already gone or locked — the DB row is what matters
    return jsonify({"ok": True, "deleted": pdf["filename"]})


@app.get("/api/annotations/<int:pdf_id>")
def annotations_list(pdf_id):
    return jsonify([{"id": r["id"], "page": r["page_number"],
                     "x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"],
                     "comment": r["comment"], "at": r["created_at"]}
                    for r in get_annotations(pdf_id)])


@app.post("/api/annotations")
def annotations_create():
    body = request.get_json(force=True)
    pdf_id = body.get("pdf_id")
    if get_pdf(pdf_id) is None:
        return jsonify({"error": f"no pdf with id {pdf_id}"}), 404
    try:
        ann_id = save_annotation(pdf_id, body.get("page_number"),
                                 body.get("x"), body.get("y"),
                                 body.get("w"), body.get("h"),
                                 body.get("comment"))
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": ann_id})


@app.patch("/api/annotations/<int:ann_id>")
def annotations_update(ann_id):
    body = request.get_json(force=True)
    try:
        update_annotation(ann_id, body.get("comment"))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"ok": True})


@app.delete("/api/annotations/<int:ann_id>")
def annotations_delete(ann_id):
    delete_annotation(ann_id)
    return jsonify({"ok": True})


@app.get("/api/occlusions/<int:pdf_id>")
def occlusions_list(pdf_id):
    return jsonify([{"id": r["id"], "page": r["page_number"],
                     "x": r["x"], "y": r["y"], "w": r["w"], "h": r["h"]}
                    for r in get_occlusions(pdf_id)])


@app.post("/api/occlusions")
def occlusions_create():
    body = request.get_json(force=True)
    pdf_id = body.get("pdf_id")
    if get_pdf(pdf_id) is None:
        return jsonify({"error": f"no pdf with id {pdf_id}"}), 404
    try:
        occ_id = save_occlusion(pdf_id, body.get("page_number"),
                                body.get("x"), body.get("y"),
                                body.get("w"), body.get("h"))
    except (TypeError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    return jsonify({"id": occ_id})


@app.delete("/api/occlusions/<int:occ_id>")
def occlusions_delete(occ_id):
    delete_occlusion(occ_id)
    return jsonify({"ok": True})


@app.post("/api/focus")
def focus():
    body = request.get_json(force=True)
    minutes = max(1, int(body.get("minutes", 1)))
    result = log_focus_session(minutes,
                               course_id=body.get("course_id"),
                               pdf_id=body.get("pdf_id"),
                               kind="reading" if body.get("kind") == "reading" else "review")
    window_start = datetime.now() - timedelta(minutes=minutes)
    grades = [g["quality"] for g in grade_log if g["at"] >= window_start]
    passed = sum(1 for q in grades if q >= 3)
    accuracy = round(passed / len(grades) * 100) if grades else None
    if accuracy is not None:
        set_session_accuracy(result["session_id"], accuracy)
    return jsonify({
        "mins": minutes,
        "cards": result["cards_reviewed"],
        "acc": accuracy,
        "ext": passed,
        "reset": len(grades) - passed,
    })


if __name__ == "__main__":
    # frameworks fork: 5002 by default so it can run beside the original (5001);
    # 0.0.0.0 + PORT env make it deployable (e.g. on a Zo Computer machine)
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5002)), debug=False)
