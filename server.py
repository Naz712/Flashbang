"""Flashbang web app — serves the v3 dashboard design (templates/index.html)
and a small JSON API over the existing backend: orchestrator (chat), mastery
(decay math), and the study log. Run: python server.py  →  http://localhost:5001
"""

import json
import os
import queue
import threading
from datetime import datetime, timedelta
from flask import Flask, Response, jsonify, render_template, request, send_file, stream_with_context
from werkzeug.utils import secure_filename

import mastery
import stats as stats_module
from orchestrator import Orchestrator
from database import (
    get_courses, get_pdfs, get_pdf, get_mastery_inputs,
    get_due_forecast, get_time_by_course, get_topic_time_spent,
    log_focus_session, log_answer, attach_card_to_answer,
    get_calibration, get_topic_accuracy, set_session_accuracy, get_study_log,
    get_pdf_pages,
)

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 100 * 1024 * 1024  # 100 MB upload cap

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

orchestrator = Orchestrator()
chat_history = []       # display log: {role, text, grade, meta}
grade_log = []          # {at: datetime, quality: int} — feeds focus-session recap
session_grades = []     # qualities since the agent's start_study_session — feeds accuracy


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

    subject_rows = get_time_by_course()
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
        "calibration": get_calibration(28),
        "topicFlags": {tid: ("easy" if rate > 95 else "hard" if rate < 60 else None)
                       for tid, rate in topic_accuracy.items()},
        "topicAccuracy": topic_accuracy,
        "recentSessions": [
            {"at": r["started_at"], "kind": r["kind"],
             "cards": r["cards_reviewed"], "minutes": r["minutes"],
             "accuracy": r["accuracy"], "topics": r["topic_titles"]}
            for r in get_study_log()[:8] if r["ended_at"]],
        "stats": {"weekTime": fmt_min(s["week_minutes"]),
                  "sessionCount": s["week_sessions"],
                  "week": week,
                  "litCount": sum(1 for d in week if d["lit"]),
                  "streak": s["current_streak_days"]},
        # drives the confidence widget — only review sessions ask for confidence
        "sessionActive": orchestrator.session_active and orchestrator.pinned == "review",
    })


@app.get("/api/history")
def history():
    return jsonify(chat_history)


@app.post("/api/chat")
def chat():
    body = request.get_json(force=True)
    message = (body.get("message") or "").strip()
    confidence = body.get("confidence")
    if not message:
        return jsonify({"error": "empty message"}), 400

    sent = message + (f" (my confidence before answering: {confidence})" if confidence else "")
    chat_history.append({"role": "user", "text": message, "grade": 0,
                         "meta": f"confidence: {confidence}" if confidence else ""})

    grades_this_turn = []

    def on_tool(name, args, result):
        if name == "grade_answer" and isinstance(result, dict):
            grade_log.append({"at": datetime.now(), "quality": result["quality"]})
            session_grades.append(result["quality"])
            # confidence applies to the attempt that produced the first grade of the turn
            conf = confidence if not grades_this_turn else None
            result["answer_id"] = log_answer(result["quality"], conf)
            grades_this_turn.append(result)
        elif name == "review_card" and grades_this_turn:
            grades_this_turn[-1]["meta"] = str(result)
            if "answer_id" in grades_this_turn[-1] and "card_id" in args:
                attach_card_to_answer(grades_this_turn[-1]["answer_id"], args["card_id"])
        elif name == "start_study_session":
            session_grades.clear()
        elif name == "end_study_session" and isinstance(result, dict):
            if session_grades:
                passed = sum(1 for q in session_grades if q >= 3)
                set_session_accuracy(result["session_id"],
                                     round(passed / len(session_grades) * 100))
            session_grades.clear()

    try:
        reply = orchestrator.handle(sent, on_tool=on_tool)
    except Exception as e:
        reply = f"Something went wrong: {type(e).__name__}: {e}"

    for g in grades_this_turn:
        chat_history.append({"role": "grade", "text": g.get("feedback", ""),
                             "grade": g.get("quality", 0), "meta": g.get("meta", "")})
    chat_history.append({"role": "assistant", "text": reply, "grade": 0, "meta": ""})

    return jsonify({"reply": reply, "grades": grades_this_turn,
                    "sessionActive": orchestrator.session_active,
                    "agent": orchestrator.last_agent})


@app.post("/api/chat/stream")
def chat_stream():
    """SSE version of /api/chat: pushes live status events while the agent
    works (tool starts, results), then the final reply. The front-end renders
    the status line under the thinking indicator and types the reply out."""
    body = request.get_json(force=True)
    message = (body.get("message") or "").strip()
    confidence = body.get("confidence")
    if not message:
        return jsonify({"error": "empty message"}), 400

    sent = message + (f" (my confidence before answering: {confidence})" if confidence else "")
    chat_history.append({"role": "user", "text": message, "grade": 0,
                         "meta": f"confidence: {confidence}" if confidence else ""})

    q = queue.Queue()
    grades_this_turn = []

    def on_event(msg):
        # "[tool: name({...})]" fires BEFORE the tool runs — that's the status signal
        if msg.startswith("[tool: "):
            q.put({"type": "status", "tool": msg[7:].split("(", 1)[0]})
        elif msg.startswith("[router -> "):
            q.put({"type": "agent", "agent": msg[11:-1]})

    def on_tool(name, args, result):
        if name == "grade_answer" and isinstance(result, dict):
            grade_log.append({"at": datetime.now(), "quality": result["quality"]})
            session_grades.append(result["quality"])
            conf = confidence if not grades_this_turn else None
            result["answer_id"] = log_answer(result["quality"], conf)
            grades_this_turn.append(result)
        elif name == "review_card" and grades_this_turn:
            grades_this_turn[-1]["meta"] = str(result)
            if "answer_id" in grades_this_turn[-1] and "card_id" in args:
                attach_card_to_answer(grades_this_turn[-1]["answer_id"], args["card_id"])
        elif name == "start_study_session":
            session_grades.clear()
        elif name == "end_study_session" and isinstance(result, dict):
            if session_grades:
                passed = sum(1 for g in session_grades if g >= 3)
                set_session_accuracy(result["session_id"],
                                     round(passed / len(session_grades) * 100))
            session_grades.clear()

    def worker():
        try:
            reply = orchestrator.handle(sent, on_event=on_event, on_tool=on_tool)
        except Exception as e:
            reply = f"Something went wrong: {type(e).__name__}: {e}"
        for g in grades_this_turn:
            chat_history.append({"role": "grade", "text": g.get("feedback", ""),
                                 "grade": g.get("quality", 0), "meta": g.get("meta", "")})
        chat_history.append({"role": "assistant", "text": reply, "grade": 0, "meta": ""})
        q.put({"type": "done", "reply": reply,
               "grades": [{"quality": g.get("quality", 0), "feedback": g.get("feedback", ""),
                           "meta": g.get("meta", "")} for g in grades_this_turn],
               "sessionActive": orchestrator.session_active,
               "agent": orchestrator.last_agent})

    threading.Thread(target=worker, daemon=True).start()

    def generate():
        while True:
            item = q.get()
            yield f"data: {json.dumps(item)}\n\n"
            if item["type"] == "done":
                break

    return Response(stream_with_context(generate()), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


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


@app.post("/api/focus")
def focus():
    body = request.get_json(force=True)
    minutes = max(1, int(body.get("minutes", 1)))
    result = log_focus_session(minutes,
                               course_id=body.get("course_id"),
                               pdf_id=body.get("pdf_id"))
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
    app.run(port=5001, debug=False)
