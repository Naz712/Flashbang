"""Flashbang — Streamlit chat + dashboard.

Left: chat with the agent (router picks the right specialist per message).
Right: live dashboard — decay-aware completion bars, per-topic mastery,
upcoming reviews, and the study log. Everything on the dashboard is computed
at read time from mastery.py, so decay shows without any background process."""

import streamlit as st
from datetime import datetime

from orchestrator import Orchestrator
from database import get_courses, get_pdfs, get_pdf, get_mastery_inputs, \
    get_upcoming_reviews, get_study_log
import mastery

st.set_page_config(page_title="Flashbang", page_icon="⚡", layout="wide")

if "orchestrator" not in st.session_state:
    st.session_state.orchestrator = Orchestrator()   # module state is unsafe across reruns
if "chat" not in st.session_state:
    st.session_state.chat = []       # [(role, text)] for display
if "events" not in st.session_state:
    st.session_state.events = []

chat_col, dash_col = st.columns([3, 2], gap="large")


# ---------------------------------------------------------------- chat pane

with chat_col:
    st.subheader("⚡ Flashbang")

    for role, content in st.session_state.chat:
        with st.chat_message(role):
            if isinstance(content, dict) and "quality" in content:
                # formatted grade card from grade_answer's structured result
                quality = content["quality"]
                color = "green" if quality >= 4 else ("orange" if quality == 3 else "red")
                st.markdown(f":{color}[**Grade: {quality}/5**]")
                st.markdown(content["feedback"])
            else:
                st.markdown(content)

    if prompt := st.chat_input("Ingest notes, review cards, check progress..."):
        st.session_state.chat.append(("user", prompt))
        with st.chat_message("user"):
            st.markdown(prompt)

        events = []

        def on_event(msg):
            events.append(msg)

        def on_tool(name, args, result):
            if name == "grade_answer" and isinstance(result, dict):
                st.session_state.chat.append(("assistant", result))

        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                text = st.session_state.orchestrator.handle(
                    prompt, on_event=on_event, on_tool=on_tool)
            if text:
                st.markdown(text)

        st.session_state.chat.append(("assistant", text))
        st.session_state.events = events
        st.rerun()   # refresh the dashboard so finished reviews move the bars

    if st.session_state.events:
        with st.expander("Agent log (last turn)"):
            for line in st.session_state.events:
                st.text(line)


# ---------------------------------------------------------------- dashboard pane

with dash_col:
    st.subheader("Dashboard")

    courses = get_courses()
    if not courses:
        st.info("No courses yet — tell the agent to ingest your first notes.")
    else:
        course_names = {c["id"]: c["name"] for c in courses}
        selected = st.selectbox("Course", options=list(course_names),
                                format_func=course_names.get)

        pdfs = get_pdfs(selected)
        if not pdfs:
            st.caption("No documents in this course yet.")
        for pdf in pdfs:
            topics, cards = get_mastery_inputs(pdf["id"])
            report = mastery.build_pdf_report(get_pdf(pdf["id"]), topics, cards)

            hours = (report["est_total_minutes"] or 0) / 60
            st.markdown(f"**{report['filename']}**  ·  {report['total_pages']} pages"
                        f"  ·  ~{hours:.1f} h")
            st.progress(min(report["completion_pct"] / 100, 1.0),
                        text=f"{report['completion_pct']:.0f}% complete (decay-aware)")

            with st.expander(f"{len(report['topics'])} topics"):
                for t in report["topics"]:
                    status_icon = {"not_started": "⚪", "in_progress": "🟡", "covered": "🟢"}[t["status"]]
                    due_note = f" · **{t['cards_due']} due**" if t["cards_due"] else ""
                    st.markdown(
                        f"{status_icon} **{t['title']}** (p.{t['pages']}, ~{t['est_minutes']} min)  \n"
                        f"mastery {t['mastery_pct']:.0f}% · {t['cards_total']} cards{due_note}"
                    )

        st.divider()
        st.markdown("**Upcoming reviews (7 days)**")
        upcoming = get_upcoming_reviews(7)
        if not upcoming:
            st.caption("Nothing due — you're ahead.")
        for row in upcoming[:8]:
            due = datetime.fromisoformat(row["first_due"]).strftime("%a %d %b")
            st.markdown(f"- **{row['title']}** ({row['course_name']}) — "
                        f"{row['cards_due']} cards, first due {due}")

        st.divider()
        st.markdown("**Study log**")
        log = get_study_log()
        if not log:
            st.caption("No sessions logged yet.")
        for row in log[:8]:
            day = datetime.fromisoformat(row["started_at"]).strftime("%a %d %b")
            topics_str = row["topic_titles"] or "—"
            minutes = f"{row['minutes']:.0f} min" if row["minutes"] else "open"
            st.markdown(f"- {day} · {row['kind']} · {topics_str} · "
                        f"{row['cards_reviewed']} cards · {minutes}")
