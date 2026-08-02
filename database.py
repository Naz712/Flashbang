import json
import os
import sqlite3
from datetime import datetime, timedelta
import fsrs_adapter   # scheduler: FSRS @ desired_retention=0.95 (see /reference for the eval journey)
import vector_store    # frameworks fork: Chroma replaces JSON embeddings + cosine

# Anchored to THIS FILE, not the working directory. A cwd-relative path means
# a server launched from anywhere else silently creates a fresh empty database
# and studies against it — the worst failure mode is one that doesn't error.
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "flashbang.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")  # per-connection in SQLite
    conn.row_factory = sqlite3.Row
    return conn


def now_iso():
    return datetime.now().isoformat(timespec="seconds")


def init_db():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS courses (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL UNIQUE,
            created_at  TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pdfs (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id         INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            filename          TEXT NOT NULL,
            file_path         TEXT,
            source_type       TEXT NOT NULL DEFAULT 'pdf' CHECK (source_type IN ('pdf','text')),
            total_pages       INTEGER NOT NULL DEFAULT 0,
            est_total_minutes INTEGER,
            status            TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','ready')),
            ingested_at       TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pdf_pages (
            pdf_id      INTEGER NOT NULL REFERENCES pdfs(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            text        TEXT NOT NULL,
            extractor   TEXT NOT NULL CHECK (extractor IN ('pypdf','vision','text')),
            PRIMARY KEY (pdf_id, page_number)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_id      INTEGER NOT NULL REFERENCES pdfs(id)    ON DELETE CASCADE,
            course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title       TEXT NOT NULL,
            summary     TEXT,
            page_start  INTEGER NOT NULL,
            page_end    INTEGER NOT NULL,
            est_minutes INTEGER NOT NULL DEFAULT 0,
            position    INTEGER NOT NULL DEFAULT 0,
            kind        TEXT NOT NULL DEFAULT 'content',
            created_at  TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id    INTEGER NOT NULL REFERENCES topics(id)  ON DELETE CASCADE,
            pdf_id      INTEGER NOT NULL REFERENCES pdfs(id)    ON DELETE CASCADE,
            course_id   INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            name        TEXT NOT NULL,
            content     TEXT NOT NULL,
            page_start  INTEGER,
            page_end    INTEGER,
            embedding   TEXT,
            created_at  TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cards (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id         INTEGER NOT NULL REFERENCES topics(id)  ON DELETE CASCADE,
            pdf_id           INTEGER NOT NULL REFERENCES pdfs(id)    ON DELETE CASCADE,
            course_id        INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            note_id          INTEGER REFERENCES notes(id) ON DELETE SET NULL,
            question         TEXT NOT NULL,
            answer           TEXT NOT NULL,
            ease_factor      REAL    NOT NULL DEFAULT 2.5,
            interval_days    INTEGER NOT NULL DEFAULT 0,
            repetitions      INTEGER NOT NULL DEFAULT 0,
            next_review      TEXT NOT NULL,
            last_reviewed_at TEXT,
            prev_state       TEXT,
            created_at       TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insights (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            card_id    INTEGER NOT NULL REFERENCES cards(id) ON DELETE CASCADE,
            content    TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_sessions (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            kind           TEXT NOT NULL CHECK (kind IN ('review','cram','ingestion','reading')),
            course_id      INTEGER REFERENCES courses(id) ON DELETE SET NULL,
            pdf_id         INTEGER REFERENCES pdfs(id)    ON DELETE SET NULL,
            started_at     TEXT NOT NULL,
            ended_at       TEXT,
            cards_reviewed INTEGER NOT NULL DEFAULT 0,
            minutes        REAL,
            summary        TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS session_topics (
            session_id INTEGER NOT NULL REFERENCES study_sessions(id) ON DELETE CASCADE,
            topic_id   INTEGER NOT NULL REFERENCES topics(id)         ON DELETE CASCADE,
            PRIMARY KEY (session_id, topic_id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS study_plan (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            plan_date  TEXT NOT NULL,
            minutes    INTEGER NOT NULL,
            reason     TEXT,
            created_at TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS course_snapshots (
            course_id    INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            week_start   TEXT NOT NULL,          -- ISO date of that week's Monday
            completion   REAL NOT NULL,
            at           TEXT NOT NULL,
            PRIMARY KEY (course_id, week_start)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS llm_calls (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            at                TEXT NOT NULL,
            purpose           TEXT NOT NULL,
            model             TEXT NOT NULL,
            prompt_tokens     INTEGER NOT NULL DEFAULT 0,
            completion_tokens INTEGER NOT NULL DEFAULT 0,
            cost_usd          REAL NOT NULL DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS annotations (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_id      INTEGER NOT NULL REFERENCES pdfs(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            x           REAL NOT NULL,
            y           REAL NOT NULL,
            w           REAL NOT NULL,
            h           REAL NOT NULL,
            comment     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS occlusions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            pdf_id      INTEGER NOT NULL REFERENCES pdfs(id) ON DELETE CASCADE,
            page_number INTEGER NOT NULL,
            x           REAL NOT NULL,
            y           REAL NOT NULL,
            w           REAL NOT NULL,
            h           REAL NOT NULL,
            created_at  TEXT NOT NULL
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS answer_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            at         TEXT NOT NULL,
            card_id    INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            quality    INTEGER NOT NULL,
            confidence TEXT CHECK (confidence IN ('sure','unsure') OR confidence IS NULL)
        )
    """)

    # TOPIC PRIMER — the "don't go in blind" card: a gist, a concrete analogy
    # with its mapping AND where it breaks, the ideas you'll meet, and what you
    # want to already know. One row per topic, generated once and cached, so
    # opening a topic twice costs nothing.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topic_primers (
            topic_id   INTEGER PRIMARY KEY REFERENCES topics(id) ON DELETE CASCADE,
            gist       TEXT NOT NULL,
            analogy    TEXT NOT NULL,
            mapping    TEXT NOT NULL,   -- JSON [{"this": ..., "is": ...}]
            breaks     TEXT,            -- where the analogy stops being true
            ideas      TEXT NOT NULL,   -- JSON [str]
            prereq     TEXT,
            model      TEXT,
            created_at TEXT NOT NULL
        )
    """)
    # TUTORIALS — practice questions, kept apart from notes. A tutorial is a
    # question paper plus (usually later, when the module releases it) a
    # separate answer paper. Questions never enter the review schedule: this is
    # a pool you pull from when a topic is weak, not another thing falling due.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tutorials (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            course_id     INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
            title         TEXT NOT NULL,
            pdf_id        INTEGER REFERENCES pdfs(id) ON DELETE CASCADE,
            answer_pdf_id INTEGER REFERENCES pdfs(id) ON DELETE SET NULL,
            created_at    TEXT NOT NULL
        )
    """)
    # One row per LEAF question: 3(a) and 3(b) are separate, grouped by `grp`,
    # so a flag can say which part actually confused you.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tutorial_questions (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tutorial_id INTEGER NOT NULL REFERENCES tutorials(id) ON DELETE CASCADE,
            seq         INTEGER NOT NULL,
            label       TEXT NOT NULL,      -- "3(b)"
            grp         TEXT,               -- "3"
            text        TEXT NOT NULL,
            page        INTEGER,            -- where it sits in the question paper
            answer_page INTEGER,            -- where its answer sits in the ANSWER paper
            flagged     INTEGER NOT NULL DEFAULT 0,
            flag_note   TEXT,
            created_at  TEXT NOT NULL
        )
    """)
    # which of the student's OWN note topics each question tests — this is the
    # join that turns "topic X is weak" into "here are questions on X"
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tutorial_question_topics (
            question_id INTEGER NOT NULL REFERENCES tutorial_questions(id) ON DELETE CASCADE,
            topic_id    INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            PRIMARY KEY (question_id, topic_id)
        )
    """)

    # EXTERNAL REVIEWS — retrieval evidence from OUTSIDE the app: a NotebookLM
    # quiz graded there and pasted back. One row per report per topic; the
    # newest wins. Never touches cards or FSRS — it only overlays the topic
    # mastery display, and it decays.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS external_reviews (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id   INTEGER NOT NULL REFERENCES topics(id) ON DELETE CASCADE,
            recall_pct REAL NOT NULL,
            quizzed    INTEGER,
            gaps       TEXT,
            source     TEXT NOT NULL DEFAULT 'notebooklm',
            at         TEXT NOT NULL
        )
    """)

    # migrations for pre-existing databases
    # how a blackout was measured: 'norm' = stored as drawn (0-1 coords);
    # 'text' = snapped to the word rects under the drag at creation. The mode
    # is decided per BOX when it is drawn and never recomputed — recomputing
    # would let a box silently change behaviour when the renderer changes.
    cursor.execute("SELECT COUNT(*) AS n FROM pragma_table_info('occlusions') WHERE name='mode'")
    if cursor.fetchone()["n"] == 0:
        cursor.execute("ALTER TABLE occlusions ADD COLUMN mode TEXT NOT NULL DEFAULT 'norm'")
    # what a pdf IS: lecture notes, a tutorial paper, or its answers. Notes are
    # the default so every existing row keeps behaving exactly as before.
    cursor.execute("SELECT COUNT(*) AS n FROM pragma_table_info('pdfs') WHERE name='kind'")
    if cursor.fetchone()["n"] == 0:
        cursor.execute("ALTER TABLE pdfs ADD COLUMN kind TEXT NOT NULL DEFAULT 'notes'")
    cursor.execute("SELECT COUNT(*) AS n FROM pragma_table_info('cards') WHERE name='prev_state'")
    if cursor.fetchone()["n"] == 0:
        cursor.execute("ALTER TABLE cards ADD COLUMN prev_state TEXT")
    cursor.execute("SELECT COUNT(*) AS n FROM pragma_table_info('study_sessions') WHERE name='accuracy'")
    if cursor.fetchone()["n"] == 0:
        cursor.execute("ALTER TABLE study_sessions ADD COLUMN accuracy REAL")
    cursor.execute("SELECT COUNT(*) AS n FROM pragma_table_info('courses') WHERE name='exam_date'")
    if cursor.fetchone()["n"] == 0:
        cursor.execute("ALTER TABLE courses ADD COLUMN exam_date TEXT")
    # how far along its forgetting curve a card was when answered (t / stability);
    # 1.0 = exactly at the due date. Feeds the personal forgetting-curve fit.
    cursor.execute("SELECT COUNT(*) AS n FROM pragma_table_info('answer_log') WHERE name='elapsed_ratio'")
    if cursor.fetchone()["n"] == 0:
        cursor.execute("ALTER TABLE answer_log ADD COLUMN elapsed_ratio REAL")
    # frameworks fork: FSRS memory-model state per card (py-fsrs). Legacy SM-2
    # cards keep NULL stability until their first FSRS review migrates them.
    for column, decl in (("stability", "REAL"), ("difficulty", "REAL"),
                         ("fsrs_state", "INTEGER")):
        cursor.execute(f"SELECT COUNT(*) AS n FROM pragma_table_info('cards') WHERE name='{column}'")
        if cursor.fetchone()["n"] == 0:
            cursor.execute(f"ALTER TABLE cards ADD COLUMN {column} {decl}")
    # ms from question card shown to answer sent (client-measured); NULL when
    # no question was on screen. Feeds the retrieval-fluency metric.
    cursor.execute("SELECT COUNT(*) AS n FROM pragma_table_info('answer_log') WHERE name='latency_ms'")
    if cursor.fetchone()["n"] == 0:
        cursor.execute("ALTER TABLE answer_log ADD COLUMN latency_ms INTEGER")
    # the grader's one-line gap diagnosis, kept so session reports can say
    # WHAT was missing, not just that the card was missed
    cursor.execute("SELECT COUNT(*) AS n FROM pragma_table_info('answer_log') WHERE name='gap'")
    if cursor.fetchone()["n"] == 0:
        cursor.execute("ALTER TABLE answer_log ADD COLUMN gap TEXT")
    # 'content' = real course material; 'general' = admin/logistics/intro pages
    # (kept for page coverage, excluded from completion math and card-making)
    cursor.execute("SELECT COUNT(*) AS n FROM pragma_table_info('topics') WHERE name='kind'")
    if cursor.fetchone()["n"] == 0:
        cursor.execute("ALTER TABLE topics ADD COLUMN kind TEXT NOT NULL DEFAULT 'content'")
    # widen study_sessions.kind to allow 'reading' (reading-hub blocks).
    # The CHECK is baked into the original CREATE TABLE and SQLite cannot
    # alter a CHECK in place, so pre-'reading' DBs get a one-time rebuild.
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='study_sessions'")
    if "'reading'" not in (cursor.fetchone()["sql"] or ""):
        conn.commit()                              # close any open transaction
        cursor.execute("PRAGMA foreign_keys = OFF")  # session_topics points here
        cursor.execute("""
            CREATE TABLE study_sessions_new (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                kind           TEXT NOT NULL CHECK (kind IN ('review','cram','ingestion','reading')),
                course_id      INTEGER REFERENCES courses(id) ON DELETE SET NULL,
                pdf_id         INTEGER REFERENCES pdfs(id)    ON DELETE SET NULL,
                started_at     TEXT NOT NULL,
                ended_at       TEXT,
                cards_reviewed INTEGER NOT NULL DEFAULT 0,
                minutes        REAL,
                summary        TEXT,
                accuracy       REAL
            )
        """)
        cursor.execute("""
            INSERT INTO study_sessions_new (id, kind, course_id, pdf_id, started_at,
                                            ended_at, cards_reviewed, minutes, summary, accuracy)
            SELECT id, kind, course_id, pdf_id, started_at,
                   ended_at, cards_reviewed, minutes, summary, accuracy
            FROM study_sessions
        """)
        cursor.execute("DROP TABLE study_sessions")
        cursor.execute("ALTER TABLE study_sessions_new RENAME TO study_sessions")
        conn.commit()
        cursor.execute("PRAGMA foreign_keys = ON")

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_topic       ON cards(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_next_review ON cards(next_review)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_topics_pdf        ON topics(pdf_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_topic       ON notes(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_started  ON study_sessions(started_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_occlusions_pdf    ON occlusions(pdf_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_annotations_pdf   ON annotations(pdf_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_llm_calls_at      ON llm_calls(at)")

    conn.commit()
    conn.close()


# ---------------------------------------------------------------- courses

def create_course(name):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO courses (name, created_at) VALUES (?, ?)", (name, now_iso()))
    course_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return course_id


def get_courses():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM courses ORDER BY name")
    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_course(course_id):
    conn = get_conn()
    conn.execute("DELETE FROM courses WHERE id=?", (course_id,))
    conn.commit()
    conn.close()
    vector_store.delete_where(course_id=course_id)  # mirror the SQL cascade


# ---------------------------------------------------------------- pdfs & pages

def create_pdf(course_id, filename, file_path=None, source_type="pdf", total_pages=0,
               kind="notes"):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pdfs (course_id, filename, file_path, source_type, total_pages,
                          ingested_at, kind)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (course_id, filename, file_path, source_type, total_pages, now_iso(), kind))
    pdf_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return pdf_id


def save_pdf_pages(pdf_id, pages):
    """pages: [{'page_number': int, 'text': str, 'extractor': 'pypdf'|'vision'|'text'}]"""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.executemany("""
        INSERT OR REPLACE INTO pdf_pages (pdf_id, page_number, text, extractor)
        VALUES (?, ?, ?, ?)
    """, [(pdf_id, p["page_number"], p["text"], p["extractor"]) for p in pages])
    conn.commit()
    conn.close()


def get_pdf_pages(pdf_id, page_start=None, page_end=None):
    conn = get_conn()
    cursor = conn.cursor()
    query = "SELECT * FROM pdf_pages WHERE pdf_id = ?"
    params = [pdf_id]
    if page_start is not None:
        query += " AND page_number >= ?"
        params.append(page_start)
    if page_end is not None:
        query += " AND page_number <= ?"
        params.append(page_end)
    query += " ORDER BY page_number"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_pdfs(course_id=None, kind="notes"):
    """Notes by default: every existing caller means lecture material, and a
    tutorial paper appearing in the documents list would be a regression."""
    conn = get_conn()
    cursor = conn.cursor()
    where, params = [], []
    if course_id:
        where.append("course_id = ?"); params.append(course_id)
    if kind is not None:
        where.append("kind = ?"); params.append(kind)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    cursor.execute(f"SELECT * FROM pdfs {clause} ORDER BY ingested_at DESC", params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_pdf(pdf_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM pdfs WHERE id = ?", (pdf_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def delete_pdf(pdf_id):
    conn = get_conn()
    conn.execute("DELETE FROM pdfs WHERE id=?", (pdf_id,))
    conn.commit()
    conn.close()
    vector_store.delete_where(pdf_id=pdf_id)  # mirror the SQL cascade


# ---------------------------------------------------------------- course history

def record_course_snapshot(course_id, completion, now=None):
    """Store this week's completion for a course, once per ISO week. Feeds the
    six-week sparkline on the Home course card — a trend can't be recovered
    after the fact (only each card's LATEST review is stored), so it has to be
    written as it happens. Re-recording the same week overwrites."""
    now = now or datetime.now()
    monday = (now.date() - timedelta(days=now.date().weekday())).isoformat()
    conn = get_conn()
    conn.execute("""
        INSERT INTO course_snapshots (course_id, week_start, completion, at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(course_id, week_start) DO UPDATE
        SET completion = excluded.completion, at = excluded.at
    """, (course_id, monday, round(float(completion), 1), now.isoformat(timespec="seconds")))
    conn.commit()
    conn.close()


def get_course_trend(course_id, weeks=6):
    """The last `weeks` weekly readings, oldest first — [] until two exist,
    because a one-point sparkline is a dot pretending to be a trend."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""SELECT completion FROM course_snapshots WHERE course_id = ?
                      ORDER BY week_start DESC LIMIT ?""", (course_id, weeks))
    rows = [r["completion"] for r in cursor.fetchall()][::-1]
    conn.close()
    return rows if len(rows) >= 2 else []


def get_course_week(course_id, now=None):
    """Which of the last 7 days (Monday-first) had a study session for this
    course. Derived from the session log — no new storage needed."""
    now = now or datetime.now()
    today = now.date()
    monday = today - timedelta(days=today.weekday())
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""SELECT started_at FROM study_sessions
                      WHERE course_id = ? AND started_at >= ?""",
                   (course_id, monday.isoformat()))
    days = {datetime.fromisoformat(r["started_at"]).date() for r in cursor.fetchall()}
    conn.close()
    return [(monday + timedelta(days=i)) in days for i in range(7)]


# ---------------------------------------------------------------- llm spend

def log_llm_call(purpose, model, prompt_tokens, completion_tokens, cost_usd):
    """One model call, with what it was for and what it cost. Written from
    llm_utils so every path is covered; failures here must never break the
    call that was actually being made."""
    conn = None
    try:
        conn = get_conn()
        conn.execute("""
            INSERT INTO llm_calls (at, purpose, model, prompt_tokens, completion_tokens, cost_usd)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (now_iso(), purpose, model or "unknown", int(prompt_tokens or 0),
              int(completion_tokens or 0), float(cost_usd or 0)))
        conn.commit()
    except Exception:
        pass                     # accounting must never break the real call
    finally:
        if conn is not None:
            conn.close()         # ...and must never leak a handle either


def get_llm_calls(days=None):
    conn = get_conn()
    cursor = conn.cursor()
    if days:
        since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
        cursor.execute("SELECT * FROM llm_calls WHERE at >= ? ORDER BY at", (since,))
    else:
        cursor.execute("SELECT * FROM llm_calls ORDER BY at")
    rows = cursor.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------- settings

def get_setting(key, default=None):
    conn = get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = get_conn()
    conn.execute("INSERT INTO settings (key, value) VALUES (?, ?) "
                 "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                 (key, str(value)))
    conn.commit()
    conn.close()


def spread_backlog(per_day):
    """Time-budget deferral: keep the first `per_day` due cards due now, push
    the rest onto future days in chunks of `per_day` (most-overdue stay
    earliest). Only next_review moves — interval/ease/FSRS state untouched,
    so the scheduler's lateness math stays honest. Returns cards moved."""
    per_day = max(1, int(per_day))
    due = get_due_cards()          # ordered most-overdue first
    overflow = due[per_day:]
    if not overflow:
        return {"moved": 0, "days_used": 0}
    conn = get_conn()
    cursor = conn.cursor()
    for i, card in enumerate(overflow):
        day_offset = 1 + i // per_day
        new_due = (datetime.now() + timedelta(days=day_offset)).replace(
            hour=4, minute=0, second=0).isoformat(timespec="seconds")
        cursor.execute("UPDATE cards SET next_review = ? WHERE id = ?",
                       (new_due, card["id"]))
    conn.commit()
    conn.close()
    return {"moved": len(overflow), "days_used": (len(overflow) + per_day - 1) // per_day}


# ---------------------------------------------------------------- annotations

def save_annotation(pdf_id, page_number, x, y, w, h, comment):
    """A comment anchored to a boxed area of a page ("window box" note).
    Coords normalized 0-1 like occlusions; the comment is required."""
    comment = (comment or "").strip()
    if not comment:
        raise ValueError("annotation needs a comment")
    x = max(0.0, min(1.0, float(x)))
    y = max(0.0, min(1.0, float(y)))
    w = max(0.0, min(1.0 - x, float(w)))
    h = max(0.0, min(1.0 - y, float(h)))
    if w < 0.005 or h < 0.005:
        raise ValueError("annotation box too small")
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO annotations (pdf_id, page_number, x, y, w, h, comment, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (pdf_id, int(page_number), x, y, w, h, comment, now_iso()))
    ann_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return ann_id


def get_annotations(pdf_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM annotations WHERE pdf_id = ? ORDER BY page_number, id",
                   (pdf_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def update_annotation(annotation_id, comment):
    comment = (comment or "").strip()
    if not comment:
        raise ValueError("annotation needs a comment")
    conn = get_conn()
    conn.execute("UPDATE annotations SET comment = ? WHERE id = ?", (comment, annotation_id))
    conn.commit()
    conn.close()


def delete_annotation(annotation_id):
    conn = get_conn()
    conn.execute("DELETE FROM annotations WHERE id = ?", (annotation_id,))
    conn.commit()
    conn.close()


def get_annotation_counts():
    """{pdf_id: note count} for the reading hub library."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT pdf_id, COUNT(*) AS n FROM annotations GROUP BY pdf_id")
    counts = {r["pdf_id"]: r["n"] for r in cursor.fetchall()}
    conn.close()
    return counts


# ---------------------------------------------------------------- occlusions

def save_occlusion(pdf_id, page_number, x, y, w, h, mode="norm"):
    """One blackout box over a page, coords normalized 0-1 relative to the
    rendered page box (so they survive any render width). Clamped server-side;
    boxes smaller than 0.5% in either dimension are rejected as accidental.
    mode='text' marks a box that was snapped to the words under the drag."""
    if mode not in ("norm", "text"):
        mode = "norm"
    x = max(0.0, min(1.0, float(x)))
    y = max(0.0, min(1.0, float(y)))
    w = max(0.0, min(1.0 - x, float(w)))
    h = max(0.0, min(1.0 - y, float(h)))
    if w < 0.005 or h < 0.005:
        raise ValueError("occlusion box too small")
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO occlusions (pdf_id, page_number, x, y, w, h, created_at, mode)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (pdf_id, int(page_number), x, y, w, h, now_iso(), mode))
    occ_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return occ_id


def get_occlusions(pdf_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM occlusions WHERE pdf_id = ? ORDER BY page_number, id",
                   (pdf_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_occlusion(occlusion_id):
    conn = get_conn()
    conn.execute("DELETE FROM occlusions WHERE id = ?", (occlusion_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- topics

def save_topics(pdf_id, topics):
    """topics: [{'title','summary','page_start','page_end','est_minutes'}].
    Inserts all topics, sets the pdf's est_total_minutes = sum of topic minutes,
    and flips its status to 'ready'. Returns the new topic ids in order."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT course_id FROM pdfs WHERE id = ?", (pdf_id,))
    row = cursor.fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"No pdf with id {pdf_id}")
    course_id = row["course_id"]

    topic_ids = []
    for position, t in enumerate(topics):
        kind = t.get("kind") if t.get("kind") in ("content", "general") else "content"
        cursor.execute("""
            INSERT INTO topics (pdf_id, course_id, title, summary, page_start, page_end,
                                est_minutes, position, kind, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pdf_id, course_id, t["title"], t.get("summary"), t["page_start"],
              t["page_end"], t.get("est_minutes", 0), position, kind, now_iso()))
        topic_ids.append(cursor.lastrowid)

    total_minutes = sum(t.get("est_minutes", 0) for t in topics)
    cursor.execute("UPDATE pdfs SET est_total_minutes = ?, status = 'ready' WHERE id = ?",
                   (total_minutes, pdf_id))
    conn.commit()
    conn.close()
    return topic_ids


def get_topics(pdf_id=None, course_id=None):
    conn = get_conn()
    cursor = conn.cursor()
    query = "SELECT * FROM topics WHERE 1=1"
    params = []
    if pdf_id:
        query += " AND pdf_id = ?"
        params.append(pdf_id)
    if course_id:
        query += " AND course_id = ?"
        params.append(course_id)
    query += " ORDER BY pdf_id, position"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_topic(topic_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM topics WHERE id = ?", (topic_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def add_external_review(topic_id, recall_pct, quizzed=None, gaps=None, source="notebooklm"):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO external_reviews (topic_id, recall_pct, quizzed, gaps, source, at)
                      VALUES (?,?,?,?,?,?)""",
                   (topic_id, max(0.0, min(float(recall_pct), 100.0)), quizzed, gaps, source, now_iso()))
    conn.commit()
    conn.close()


def latest_external_reviews(pdf_id=None, course_id=None):
    """Newest external review per topic, as {topic_id: row}."""
    conn = get_conn()
    cursor = conn.cursor()
    where, params = "", []
    if pdf_id:
        where, params = "WHERE topics.pdf_id = ?", [pdf_id]
    elif course_id:
        where, params = "WHERE topics.course_id = ?", [course_id]
    cursor.execute(f"""
        SELECT er.* FROM external_reviews er
        JOIN topics ON topics.id = er.topic_id
        {where}
        ORDER BY er.at ASC
    """, params)
    out = {}
    for r in cursor.fetchall():
        out[r["topic_id"]] = dict(r)   # later rows overwrite: newest wins
    conn.close()
    return out


""" ---------------------------------------------------------------- tutorials """


def create_tutorial(course_id, title, pdf_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""INSERT INTO tutorials (course_id, title, pdf_id, created_at)
                      VALUES (?,?,?,?)""", (course_id, title, pdf_id, now_iso()))
    tid = cursor.lastrowid
    conn.commit()
    conn.close()
    return tid


def save_tutorial_questions(tutorial_id, questions):
    """Replace a tutorial's questions. Re-splitting starts clean rather than
    accumulating, but FLAGS SURVIVE: a flag is the student's own work, and
    losing it because the split was re-run would be the worst kind of data
    loss. Matched back by label."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""SELECT label, flagged, flag_note FROM tutorial_questions
                      WHERE tutorial_id = ?""", (tutorial_id,))
    kept = {r["label"]: (r["flagged"], r["flag_note"]) for r in cursor.fetchall()}
    cursor.execute("DELETE FROM tutorial_questions WHERE tutorial_id = ?", (tutorial_id,))
    ids = []
    for seq, q in enumerate(questions):
        flagged, note = kept.get(q.get("label"), (0, None))
        cursor.execute("""
            INSERT INTO tutorial_questions
                (tutorial_id, seq, label, grp, text, page, flagged, flag_note, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)
        """, (tutorial_id, seq, q.get("label") or str(seq + 1), q.get("grp"),
              q.get("text", ""), q.get("page"), flagged, note, now_iso()))
        ids.append(cursor.lastrowid)
    conn.commit()
    conn.close()
    return ids


def set_question_topics(question_id, topic_ids):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tutorial_question_topics WHERE question_id = ?", (question_id,))
    for tid in topic_ids:
        cursor.execute("""INSERT OR IGNORE INTO tutorial_question_topics (question_id, topic_id)
                          VALUES (?,?)""", (question_id, tid))
    conn.commit()
    conn.close()


def set_answer_pdf(tutorial_id, answer_pdf_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("UPDATE tutorials SET answer_pdf_id = ? WHERE id = ?",
                   (answer_pdf_id, tutorial_id))
    conn.commit()
    conn.close()


def set_answer_pages(pages_by_label):
    """{question_id: page} — where each answer lives in the answer paper."""
    conn = get_conn()
    cursor = conn.cursor()
    for qid, page in pages_by_label.items():
        cursor.execute("UPDATE tutorial_questions SET answer_page = ? WHERE id = ?", (page, qid))
    conn.commit()
    conn.close()


def flag_question(question_id, flagged, note=None):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""UPDATE tutorial_questions SET flagged = ?, flag_note = ?
                      WHERE id = ?""", (1 if flagged else 0, note, question_id))
    conn.commit()
    conn.close()


def get_tutorials(course_id=None):
    conn = get_conn()
    cursor = conn.cursor()
    clause = "WHERE t.course_id = ?" if course_id else ""
    cursor.execute(f"""
        SELECT t.*, p.filename AS pdf_filename, p.total_pages,
               a.filename AS answer_filename,
               (SELECT COUNT(*) FROM tutorial_questions q WHERE q.tutorial_id = t.id) AS n_questions,
               (SELECT COUNT(*) FROM tutorial_questions q
                 WHERE q.tutorial_id = t.id AND q.flagged = 1) AS n_flagged
        FROM tutorials t
        LEFT JOIN pdfs p ON p.id = t.pdf_id
        LEFT JOIN pdfs a ON a.id = t.answer_pdf_id
        {clause}
        ORDER BY t.id ASC
    """, (course_id,) if course_id else ())
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows


def get_tutorial_questions(tutorial_id=None, topic_id=None, flagged_only=False, course_id=None):
    """Questions with their topic tags. Filterable by tutorial, by topic (the
    'I'm weak on X, show me questions on X' path) or by flag."""
    conn = get_conn()
    cursor = conn.cursor()
    where, params = [], []
    if tutorial_id:
        where.append("q.tutorial_id = ?"); params.append(tutorial_id)
    if course_id:
        where.append("t.course_id = ?"); params.append(course_id)
    if flagged_only:
        where.append("q.flagged = 1")
    if topic_id:
        where.append("""q.id IN (SELECT question_id FROM tutorial_question_topics
                                 WHERE topic_id = ?)""")
        params.append(topic_id)
    clause = f"WHERE {' AND '.join(where)}" if where else ""
    cursor.execute(f"""
        SELECT q.*, t.title AS tutorial_title, t.answer_pdf_id, t.pdf_id
        FROM tutorial_questions q
        JOIN tutorials t ON t.id = q.tutorial_id
        {clause}
        ORDER BY q.tutorial_id ASC, q.seq ASC
    """, params)
    questions = [dict(r) for r in cursor.fetchall()]
    if questions:
        marks = ",".join("?" * len(questions))
        cursor.execute(f"""
            SELECT qt.question_id, topics.id, topics.title
            FROM tutorial_question_topics qt
            JOIN topics ON topics.id = qt.topic_id
            WHERE qt.question_id IN ({marks})
        """, [q["id"] for q in questions])
        by_q = {}
        for r in cursor.fetchall():
            by_q.setdefault(r["question_id"], []).append({"id": r["id"], "title": r["title"]})
        for q in questions:
            q["topics"] = by_q.get(q["id"], [])
    conn.close()
    return questions


def delete_tutorial(tutorial_id):
    """Removes the tutorial, its questions and its tags. The PDFs themselves
    are left alone — deleting uploaded files is delete_pdf's job."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM tutorials WHERE id = ?", (tutorial_id,))
    conn.commit()
    conn.close()


def get_primer(topic_id):
    """The cached primer for a topic, or None. JSON columns come back parsed."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM topic_primers WHERE topic_id = ?", (topic_id,))
    row = cursor.fetchone()
    conn.close()
    if row is None:
        return None
    d = dict(row)
    d["mapping"] = json.loads(d["mapping"] or "[]")
    d["ideas"] = json.loads(d["ideas"] or "[]")
    return d


def save_primer(topic_id, primer, model=None):
    """Write (or replace) a topic's primer. Replacing is how 'regenerate' works,
    so a primer never accumulates duplicates."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO topic_primers (topic_id, gist, analogy, mapping, breaks, ideas,
                                   prereq, model, created_at)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(topic_id) DO UPDATE SET
            gist=excluded.gist, analogy=excluded.analogy, mapping=excluded.mapping,
            breaks=excluded.breaks, ideas=excluded.ideas, prereq=excluded.prereq,
            model=excluded.model, created_at=excluded.created_at
    """, (topic_id, primer.get("gist", ""), primer.get("analogy", ""),
          json.dumps(primer.get("mapping", [])), primer.get("breaks"),
          json.dumps(primer.get("ideas", [])), primer.get("prereq"),
          model, now_iso()))
    conn.commit()
    conn.close()


def delete_primer(topic_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM topic_primers WHERE topic_id = ?", (topic_id,))
    conn.commit()
    conn.close()


def topics_with_primers(topic_ids=None):
    """Which topics already have a primer — so the UI can mark them without
    fetching every primer body."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT topic_id FROM topic_primers")
    ids = {r["topic_id"] for r in cursor.fetchall()}
    conn.close()
    return ids if topic_ids is None else ids & set(topic_ids)


def update_topic(topic_id, title=None, summary=None, est_minutes=None,
                 page_start=None, page_end=None, kind=None):
    """Manual topic edits. Page ranges are validated against each other and
    the document; contiguity with neighbours is deliberately NOT enforced —
    the user owns the split. kind outside content/general is ignored."""
    if kind not in (None, "content", "general"):
        kind = None
    conn = get_conn()
    cursor = conn.cursor()
    if page_start is not None or page_end is not None:
        cursor.execute("""SELECT topics.page_start, topics.page_end, pdfs.total_pages
                          FROM topics JOIN pdfs ON pdfs.id = topics.pdf_id
                          WHERE topics.id = ?""", (topic_id,))
        row = cursor.fetchone()
        if row is None:
            conn.close()
            raise ValueError(f"no topic with id {topic_id}")
        start = page_start if page_start is not None else row["page_start"]
        end = page_end if page_end is not None else row["page_end"]
        if not (1 <= start <= end):
            conn.close()
            raise ValueError(f"invalid page range {start}-{end}")
        if row["total_pages"] and end > row["total_pages"]:
            conn.close()
            raise ValueError(f"page {end} is past the document's {row['total_pages']} pages")
    cursor.execute("""
        UPDATE topics
        SET title       = COALESCE(?, title),
            summary     = COALESCE(?, summary),
            est_minutes = COALESCE(?, est_minutes),
            page_start  = COALESCE(?, page_start),
            page_end    = COALESCE(?, page_end),
            kind        = COALESCE(?, kind)
        WHERE id = ?
    """, (title, summary, est_minutes, page_start, page_end, kind, topic_id))
    # keep the pdf total in sync when a topic estimate changes
    if est_minutes is not None:
        cursor.execute("""
            UPDATE pdfs SET est_total_minutes =
                (SELECT SUM(est_minutes) FROM topics WHERE pdf_id = pdfs.id)
            WHERE id = (SELECT pdf_id FROM topics WHERE id = ?)
        """, (topic_id,))
    conn.commit()
    conn.close()


def split_topic(topic_id, at_page, new_title=None):
    """Split a topic at `at_page`: the original keeps [start..at_page-1], a
    new topic (inheriting kind) takes [at_page..end], inserted right after
    it in reading order. est_minutes divides proportionally by page count.
    Cards and notes stay with the original topic. Returns the new topic id."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM topics WHERE id = ?", (topic_id,))
    topic = cursor.fetchone()
    if topic is None:
        conn.close()
        raise ValueError(f"no topic with id {topic_id}")
    at_page = int(at_page)
    if not (topic["page_start"] < at_page <= topic["page_end"]):
        conn.close()
        raise ValueError(
            f"split page must be inside {topic['page_start'] + 1}-{topic['page_end']}")

    total_pages = topic["page_end"] - topic["page_start"] + 1
    new_pages = topic["page_end"] - at_page + 1
    new_est = round((topic["est_minutes"] or 0) * new_pages / total_pages)
    orig_est = (topic["est_minutes"] or 0) - new_est

    cursor.execute("""UPDATE topics SET position = position + 1
                      WHERE pdf_id = ? AND position > ?""",
                   (topic["pdf_id"], topic["position"]))
    cursor.execute("""
        INSERT INTO topics (pdf_id, course_id, title, summary, page_start, page_end,
                            est_minutes, position, kind, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (topic["pdf_id"], topic["course_id"],
          (new_title or "").strip() or f"{topic['title']} (cont.)",
          None, at_page, topic["page_end"], new_est,
          topic["position"] + 1, topic["kind"] or "content", now_iso()))
    new_id = cursor.lastrowid
    cursor.execute("UPDATE topics SET page_end = ?, est_minutes = ? WHERE id = ?",
                   (at_page - 1, orig_est, topic_id))
    conn.commit()
    conn.close()
    return new_id


def delete_topic(topic_id):
    """Delete one topic and everything under it — cards and notes cascade,
    the notes leave the vector store, review history keeps its rows with the
    card link nulled. The pdf keeps its other topics; its total re-syncs."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT pdf_id FROM topics WHERE id = ?", (topic_id,))
    row = cursor.fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"no topic with id {topic_id}")
    cursor.execute("DELETE FROM topics WHERE id = ?", (topic_id,))
    cursor.execute("""
        UPDATE pdfs SET est_total_minutes =
            (SELECT COALESCE(SUM(est_minutes), 0) FROM topics WHERE pdf_id = pdfs.id)
        WHERE id = ?""", (row["pdf_id"],))
    conn.commit()
    conn.close()
    vector_store.delete_where(topic_id=topic_id)  # mirror the SQL cascade


# ---------------------------------------------------------------- notes

def save_concepts(topic_id, concepts):
    """concepts: [{'name','content', optional 'page_start','page_end'}].
    pdf_id/course_id are resolved from the topic so they can never desync.
    Content is indexed into the Chroma vector store (local embeddings) with
    citation metadata. Returns note ids in order."""
    topic = get_topic(topic_id)
    if topic is None:
        raise ValueError(f"No topic with id {topic_id}")

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT courses.name AS course_name, pdfs.filename AS pdf_filename
        FROM courses, pdfs WHERE courses.id = ? AND pdfs.id = ?
    """, (topic["course_id"], topic["pdf_id"]))
    names = cursor.fetchone()

    note_ids = []
    for c in concepts:
        cursor.execute("""
            INSERT INTO notes (topic_id, pdf_id, course_id, name, content,
                               page_start, page_end, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (topic_id, topic["pdf_id"], topic["course_id"], c["name"], c["content"],
              c.get("page_start"), c.get("page_end"), now_iso()))
        note_ids.append(cursor.lastrowid)
    conn.commit()
    conn.close()

    for note_id, c in zip(note_ids, concepts):
        vector_store.add_note(note_id, c["content"], {
            "name": c["name"],
            "topic_id": topic_id, "pdf_id": topic["pdf_id"],
            "course_id": topic["course_id"],
            "topic_title": topic["title"],
            "course_name": names["course_name"],
            "pdf_filename": names["pdf_filename"],
        })
    return note_ids


def get_note(note_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM notes WHERE id = ?", (note_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def delete_note(note_id):
    conn = get_conn()
    conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
    conn.commit()
    conn.close()
    vector_store.delete_notes([note_id])


def get_notes_with_embeddings(course_id=None, pdf_id=None, topic_id=None):
    """Notes joined with course/pdf/topic names so search results can be cited."""
    conn = get_conn()
    cursor = conn.cursor()
    query = """
        SELECT notes.*, courses.name AS course_name, pdfs.filename AS pdf_filename,
               topics.title AS topic_title
        FROM notes
        JOIN courses ON courses.id = notes.course_id
        JOIN pdfs    ON pdfs.id    = notes.pdf_id
        JOIN topics  ON topics.id  = notes.topic_id
        WHERE notes.embedding IS NOT NULL
    """
    params = []
    if course_id:
        query += " AND notes.course_id = ?"
        params.append(course_id)
    if pdf_id:
        query += " AND notes.pdf_id = ?"
        params.append(pdf_id)
    if topic_id:
        query += " AND notes.topic_id = ?"
        params.append(topic_id)
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------- cards

def insert_card(topic_id, question, answer, note_id=None):
    """pdf_id/course_id come from the topic row, never from the caller."""
    topic = get_topic(topic_id)
    if topic is None:
        raise ValueError(f"No topic with id {topic_id}")
    tomorrow = (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cards (topic_id, pdf_id, course_id, note_id, question, answer,
                           next_review, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (topic_id, topic["pdf_id"], topic["course_id"], note_id, question, answer,
          tomorrow, now_iso()))
    card_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return card_id


def get_cards(course_id=None, pdf_id=None, topic_id=None):
    conn = get_conn()
    cursor = conn.cursor()
    query = """
        SELECT cards.*, topics.title AS topic_title, courses.name AS course_name
        FROM cards
        JOIN topics  ON topics.id  = cards.topic_id
        JOIN courses ON courses.id = cards.course_id
        WHERE 1=1
    """
    params = []
    if course_id:
        query += " AND cards.course_id = ?"
        params.append(course_id)
    if pdf_id:
        query += " AND cards.pdf_id = ?"
        params.append(pdf_id)
    if topic_id:
        query += " AND cards.topic_id = ?"
        params.append(topic_id)
    query += " ORDER BY cards.next_review ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_due_cards(course_id=None, pdf_id=None, topic_id=None):
    conn = get_conn()
    cursor = conn.cursor()
    query = """
        SELECT cards.*, topics.title AS topic_title, courses.name AS course_name
        FROM cards
        JOIN topics  ON topics.id  = cards.topic_id
        JOIN courses ON courses.id = cards.course_id
        WHERE cards.next_review <= ?
    """
    params = [now_iso()]
    if course_id:
        query += " AND cards.course_id = ?"
        params.append(course_id)
    if pdf_id:
        query += " AND cards.pdf_id = ?"
        params.append(pdf_id)
    if topic_id:
        query += " AND cards.topic_id = ?"
        params.append(topic_id)
    query += " ORDER BY cards.next_review ASC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def review_card(card_id, quality):
    """FSRS review at desired_retention=0.95 (settled after the A/B eval:
    0.75 stretched intervals to months → reverted → retuned to 0.95 for an
    Anki-like ladder with per-card adaptation). Quality 0-5 maps to
    Again/Hard/Good/Easy; `repetitions` keeps its successive-relearning
    meaning (consecutive successful recalls, reset on failure)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT ease_factor, interval_days, repetitions, next_review, last_reviewed_at,
               stability, difficulty, fsrs_state
        FROM cards WHERE id=?
    """, (card_id,))
    row = cursor.fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"No card with id {card_id}")
    prev_state = json.dumps(dict(row))  # one-level undo snapshot
    old_interval = row["interval_days"]

    result = fsrs_adapter.review(row, quality)
    new_reps = row["repetitions"] + 1 if quality >= 3 else 0

    cursor.execute("""
        UPDATE cards
        SET interval_days=?, repetitions=?, next_review=?, last_reviewed_at=?,
            stability=?, difficulty=?, fsrs_state=?, prev_state=?
        WHERE id=?
    """, (result["interval_days"], new_reps, result["next_review"], now_iso(),
          result["stability"], result["difficulty"], result["fsrs_state"],
          prev_state, card_id))
    conn.commit()
    conn.close()
    return {"old_interval": old_interval, "new_interval": result["interval_days"],
            "next_review": result["next_review"][:10]}


def undo_review(card_id):
    """Restore the card's scheduling state (incl. FSRS stability/difficulty)
    from before its most recent review. One level deep; snapshot cleared."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT prev_state FROM cards WHERE id=?", (card_id,))
    row = cursor.fetchone()
    if row is None:
        conn.close()
        raise ValueError(f"No card with id {card_id}")
    if not row["prev_state"]:
        conn.close()
        raise ValueError(f"Card {card_id} has no review to undo")
    prev = json.loads(row["prev_state"])
    cursor.execute("""
        UPDATE cards
        SET ease_factor=?, interval_days=?, repetitions=?, next_review=?,
            last_reviewed_at=?, stability=?, difficulty=?, fsrs_state=?,
            prev_state=NULL
        WHERE id=?
    """, (prev["ease_factor"], prev["interval_days"], prev["repetitions"],
          prev["next_review"], prev["last_reviewed_at"], prev.get("stability"),
          prev.get("difficulty"), prev.get("fsrs_state"), card_id))
    conn.commit()
    conn.close()
    return prev


def update_card(card_id, question=None, answer=None, topic_id=None):
    conn = get_conn()
    cursor = conn.cursor()
    if topic_id is not None:
        # moving a card to another topic re-derives pdf/course from the new topic
        topic = get_topic(topic_id)
        if topic is None:
            conn.close()
            raise ValueError(f"No topic with id {topic_id}")
        cursor.execute("""
            UPDATE cards SET topic_id=?, pdf_id=?, course_id=? WHERE id=?
        """, (topic_id, topic["pdf_id"], topic["course_id"], card_id))
    cursor.execute("""
        UPDATE cards
        SET question = COALESCE(?, question),
            answer   = COALESCE(?, answer)
        WHERE id = ?
    """, (question, answer, card_id))
    conn.commit()
    conn.close()


def delete_card(card_id):
    conn = get_conn()
    conn.execute("DELETE FROM cards WHERE id=?", (card_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- insights

def insert_insight(card_id, content):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO insights (card_id, content, created_at) VALUES (?, ?, ?)",
                   (card_id, content, now_iso()))
    insight_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return insight_id


def get_insights_for_card(card_id):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM insights WHERE card_id = ? ORDER BY created_at DESC", (card_id,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def delete_insight(insight_id):
    conn = get_conn()
    conn.execute("DELETE FROM insights WHERE id=?", (insight_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------- study log

def start_session(kind, course_id=None, pdf_id=None, topic_ids=None):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO study_sessions (kind, course_id, pdf_id, started_at)
        VALUES (?, ?, ?, ?)
    """, (kind, course_id, pdf_id, now_iso()))
    session_id = cursor.lastrowid
    if topic_ids:
        cursor.executemany(
            "INSERT OR IGNORE INTO session_topics (session_id, topic_id) VALUES (?, ?)",
            [(session_id, t) for t in topic_ids])
    conn.commit()
    conn.close()
    return session_id


def end_session(session_id, cards_reviewed=None, summary=None):
    """Close a session. For 'review' sessions cards_reviewed and the topic links
    are derived from cards actually reviewed during the window (deterministic —
    immune to model miscounting). Cram sessions pass cards_reviewed explicitly
    since cram never calls review_card."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,))
    session = cursor.fetchone()
    if session is None:
        conn.close()
        raise ValueError(f"No session with id {session_id}")

    ended_at = now_iso()
    if cards_reviewed is None:
        cursor.execute("""
            SELECT COUNT(*) AS n FROM cards
            WHERE last_reviewed_at BETWEEN ? AND ?
        """, (session["started_at"], ended_at))
        cards_reviewed = cursor.fetchone()["n"]
        cursor.execute("""
            INSERT OR IGNORE INTO session_topics (session_id, topic_id)
            SELECT DISTINCT ?, topic_id FROM cards
            WHERE last_reviewed_at BETWEEN ? AND ?
        """, (session_id, session["started_at"], ended_at))

    started = datetime.fromisoformat(session["started_at"])
    minutes = round((datetime.fromisoformat(ended_at) - started).total_seconds() / 60, 1)
    cursor.execute("""
        UPDATE study_sessions
        SET ended_at = ?, cards_reviewed = ?, minutes = ?, summary = COALESCE(?, summary)
        WHERE id = ?
    """, (ended_at, cards_reviewed, minutes, summary, session_id))
    conn.commit()
    conn.close()
    return {"session_id": session_id, "cards_reviewed": cards_reviewed, "minutes": minutes}


def get_study_log(start_date=None, end_date=None, course_id=None, kinds=None):
    """kinds: tuple of session kinds to include; None = all. The flashcard
    hub passes ('review','cram','ingestion'), the reading hub ('reading',)."""
    conn = get_conn()
    cursor = conn.cursor()
    query = """
        SELECT s.*, courses.name AS course_name, pdfs.filename AS pdf_filename,
               GROUP_CONCAT(topics.title, '; ') AS topic_titles
        FROM study_sessions s
        LEFT JOIN courses        ON courses.id = s.course_id
        LEFT JOIN pdfs           ON pdfs.id    = s.pdf_id
        LEFT JOIN session_topics st ON st.session_id = s.id
        LEFT JOIN topics         ON topics.id  = st.topic_id
        WHERE 1=1
    """
    params = []
    if kinds:
        query += f" AND s.kind IN ({','.join('?' * len(kinds))})"
        params.extend(kinds)
    if start_date:
        query += " AND s.started_at >= ?"
        params.append(start_date)
    if end_date:
        query += " AND s.started_at <= ?"
        params.append(end_date)
    if course_id:
        query += " AND s.course_id = ?"
        params.append(course_id)
    query += " GROUP BY s.id ORDER BY s.started_at DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return rows


def get_upcoming_reviews(days=7):
    """Per topic: earliest next_review and how many cards come due within the window."""
    horizon = (datetime.now() + timedelta(days=days)).isoformat(timespec="seconds")
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT topics.id AS topic_id, topics.title, courses.name AS course_name,
               pdfs.filename AS pdf_filename,
               MIN(cards.next_review) AS first_due,
               COUNT(*) AS cards_due
        FROM cards
        JOIN topics  ON topics.id  = cards.topic_id
        JOIN courses ON courses.id = cards.course_id
        JOIN pdfs    ON pdfs.id    = cards.pdf_id
        WHERE cards.next_review <= ?
        GROUP BY topics.id
        ORDER BY first_due ASC
    """, (horizon,))
    rows = cursor.fetchall()
    conn.close()
    return rows


def log_answer(quality, confidence=None, card_id=None, latency_ms=None, gap=None):
    """Record one graded recall attempt (feeds calibration + 85%-rule flags)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO answer_log (at, card_id, quality, confidence, latency_ms, gap) VALUES (?, ?, ?, ?, ?, ?)",
                   (now_iso(), card_id, quality, confidence, latency_ms, gap or None))
    answer_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return answer_id


def attach_card_to_answer(answer_id, card_id):
    """Link an answer to its card and record how far along the forgetting curve
    the card was at answer time (t/S from the pre-review snapshot). Ratio stays
    NULL for a card's first-ever review — there's no decay to measure."""
    from mastery import _STABILITY_SCALE  # standalone module, no import cycle
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT prev_state FROM cards WHERE id = ?", (card_id,))
    card = cursor.fetchone()
    cursor.execute("SELECT at FROM answer_log WHERE id = ?", (answer_id,))
    answer = cursor.fetchone()

    ratio = None
    if card and card["prev_state"] and answer:
        prev = json.loads(card["prev_state"])
        if prev.get("last_reviewed_at"):
            elapsed_days = (datetime.fromisoformat(answer["at"])
                            - datetime.fromisoformat(prev["last_reviewed_at"])
                            ).total_seconds() / 86400
            # FSRS stability when the card has one; legacy interval proxy otherwise
            if prev.get("stability"):
                stability = prev["stability"]
            else:
                stability = _STABILITY_SCALE * max(prev["interval_days"], 1)
            ratio = round(max(0.0, elapsed_days) / stability, 4)

    cursor.execute("UPDATE answer_log SET card_id = ?, elapsed_ratio = ? WHERE id = ?",
                   (card_id, ratio, answer_id))
    conn.commit()
    conn.close()


def get_session_report_data(session_id=None):
    """One ENDED review/cram session (latest by default) plus its graded
    answers joined to cards/topics/pdfs — the raw material for the session
    gap report. Answers are matched by the session's time window, same as
    the accuracy derivation. Page refs prefer the card's source note."""
    conn = get_conn()
    cursor = conn.cursor()
    if session_id:
        cursor.execute("SELECT * FROM study_sessions WHERE id = ?", (session_id,))
    else:
        cursor.execute("""SELECT * FROM study_sessions
                          WHERE ended_at IS NOT NULL AND kind IN ('review', 'cram')
                          ORDER BY id DESC LIMIT 1""")
    session = cursor.fetchone()
    if session is None or not session["ended_at"]:
        conn.close()
        return None, []
    cursor.execute("""
        SELECT answer_log.quality, answer_log.confidence, answer_log.gap,
               cards.id AS card_id, cards.question, cards.answer,
               topics.title AS topic_title, topics.id AS topic_id,
               COALESCE(notes.page_start, topics.page_start) AS page_start,
               COALESCE(notes.page_end, topics.page_end) AS page_end,
               cards.pdf_id, pdfs.filename, courses.name AS course_name
        FROM answer_log
        JOIN cards      ON cards.id   = answer_log.card_id
        JOIN topics     ON topics.id  = cards.topic_id
        LEFT JOIN notes ON notes.id   = cards.note_id
        JOIN pdfs       ON pdfs.id    = cards.pdf_id
        JOIN courses    ON courses.id = cards.course_id
        WHERE answer_log.at BETWEEN ? AND ?
        ORDER BY answer_log.at
    """, (session["started_at"], session["ended_at"]))
    rows = cursor.fetchall()
    conn.close()
    return session, rows


def set_exam_date(course_id, exam_date):
    """exam_date: ISO date string, or None to clear."""
    conn = get_conn()
    conn.execute("UPDATE courses SET exam_date = ? WHERE id = ?", (exam_date, course_id))
    conn.commit()
    conn.close()


def get_calibration(days=28):
    """Recall rate split by stated confidence, weekly buckets (newest last).
    Only answers where a confidence was stated count."""
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT at, quality, confidence FROM answer_log
        WHERE confidence IS NOT NULL AND at >= ?
        ORDER BY at
    """, (since,))
    rows = cursor.fetchall()
    conn.close()

    weeks = {}
    now = datetime.now()
    for row in rows:
        age_days = (now - datetime.fromisoformat(row["at"])).days
        bucket = min(3, age_days // 7)  # 0 = this week ... 3 = 3+ weeks ago
        w = weeks.setdefault(bucket, {"sure": [0, 0], "unsure": [0, 0]})
        counts = w[row["confidence"]]
        counts[0] += 1
        if row["quality"] >= 3:
            counts[1] += 1

    out = []
    for bucket in range(3, -1, -1):
        w = weeks.get(bucket, {"sure": [0, 0], "unsure": [0, 0]})
        out.append({
            "label": "this wk" if bucket == 0 else f"-{bucket}wk",
            "sure_n": w["sure"][0],
            "sure_rate": round(w["sure"][1] / w["sure"][0] * 100) if w["sure"][0] else None,
            "unsure_n": w["unsure"][0],
            "unsure_rate": round(w["unsure"][1] / w["unsure"][0] * 100) if w["unsure"][0] else None,
        })
    return out


def get_topic_accuracy(min_answers=6, days=28):
    """85%-rule input: per-topic recall rate over recent graded answers.
    Topics with fewer than min_answers are omitted (not enough signal)."""
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT cards.topic_id,
               COUNT(*) AS n,
               SUM(CASE WHEN answer_log.quality >= 3 THEN 1 ELSE 0 END) AS passed
        FROM answer_log
        JOIN cards ON cards.id = answer_log.card_id
        WHERE answer_log.at >= ?
        GROUP BY cards.topic_id
        HAVING n >= ?
    """, (since, min_answers))
    rows = cursor.fetchall()
    conn.close()
    return {row["topic_id"]: round(row["passed"] / row["n"] * 100) for row in rows}


def set_session_accuracy(session_id, accuracy):
    conn = get_conn()
    conn.execute("UPDATE study_sessions SET accuracy = ? WHERE id = ?", (accuracy, session_id))
    conn.commit()
    conn.close()


def log_focus_session(minutes, course_id=None, pdf_id=None, kind="review"):
    """Log a UI focus-timer session that just ended (started `minutes` ago).
    kind='reading' for reading-hub blocks (kept separate from flashcard
    analytics). Cards reviewed and topics touched during the window are
    derived from the cards table, same as end_session."""
    if kind not in ("review", "reading"):
        kind = "review"
    ended = datetime.now()
    started = ended - timedelta(minutes=minutes)
    started_iso = started.isoformat(timespec="seconds")
    ended_iso = ended.isoformat(timespec="seconds")

    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT COUNT(*) AS n FROM cards WHERE last_reviewed_at BETWEEN ? AND ?
    """, (started_iso, ended_iso))
    cards_reviewed = cursor.fetchone()["n"]
    cursor.execute("""
        INSERT INTO study_sessions (kind, course_id, pdf_id, started_at, ended_at,
                                    cards_reviewed, minutes, summary)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (kind, course_id, pdf_id, started_iso, ended_iso, cards_reviewed, float(minutes),
          "reading block" if kind == "reading" else "focus session"))
    session_id = cursor.lastrowid
    cursor.execute("""
        INSERT OR IGNORE INTO session_topics (session_id, topic_id)
        SELECT DISTINCT ?, topic_id FROM cards WHERE last_reviewed_at BETWEEN ? AND ?
    """, (session_id, started_iso, ended_iso))
    conn.commit()
    conn.close()
    return {"session_id": session_id, "cards_reviewed": cards_reviewed, "minutes": minutes}


def get_due_forecast(days=7):
    """Cards coming due per day for the next `days` days; overdue cards are
    bucketed into today. Returns [{'day': ISO date, 'count': int}] covering
    every day in the window."""
    today = datetime.now().date()
    horizon = (datetime.now() + timedelta(days=days - 1)).replace(
        hour=23, minute=59, second=59).isoformat(timespec="seconds")
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT next_review FROM cards WHERE next_review <= ?", (horizon,))
    rows = cursor.fetchall()
    conn.close()

    counts = {(today + timedelta(days=i)).isoformat(): 0 for i in range(days)}
    for row in rows:
        due_day = datetime.fromisoformat(row["next_review"]).date()
        key = max(due_day, today).isoformat()
        counts[key] += 1
    return [{"day": day, "count": counts[day]} for day in sorted(counts)]


def get_time_by_course(kinds=None):
    """Total logged study minutes per course, all time. kinds as get_study_log."""
    conn = get_conn()
    cursor = conn.cursor()
    query = """
        SELECT s.course_id, courses.name, SUM(s.minutes) AS minutes
        FROM study_sessions s
        LEFT JOIN courses ON courses.id = s.course_id
        WHERE s.minutes IS NOT NULL
    """
    params = []
    if kinds:
        query += f" AND s.kind IN ({','.join('?' * len(kinds))})"
        params.extend(kinds)
    query += " GROUP BY s.course_id ORDER BY minutes DESC"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()
    return [{"course_id": r["course_id"], "name": r["name"] or "Other",
             "minutes": round(r["minutes"], 1)} for r in rows]


def get_topic_time_spent():
    """Approximate minutes spent per topic: each session's minutes divided
    evenly among the topics it touched. Returns {topic_id: minutes}."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT st.topic_id, s.minutes,
               (SELECT COUNT(*) FROM session_topics st2
                WHERE st2.session_id = s.id) AS topics_in_session
        FROM study_sessions s
        JOIN session_topics st ON st.session_id = s.id
        WHERE s.minutes IS NOT NULL
    """)
    rows = cursor.fetchall()
    conn.close()
    spent = {}
    for row in rows:
        share = row["minutes"] / max(row["topics_in_session"], 1)
        spent[row["topic_id"]] = spent.get(row["topic_id"], 0) + share
    return {tid: round(m, 1) for tid, m in spent.items()}


# ---------------------------------------------------------------- study plan

def save_study_plan(entries, replace_future=True):
    """entries: [{'topic_id','plan_date' (ISO date),'minutes','reason'}].
    By default wipes today-onward entries first so re-planning never stacks
    duplicates; past entries are kept as history."""
    conn = get_conn()
    cursor = conn.cursor()
    if replace_future:
        today = datetime.now().strftime("%Y-%m-%d")
        cursor.execute("DELETE FROM study_plan WHERE plan_date >= ?", (today,))
    cursor.executemany("""
        INSERT INTO study_plan (topic_id, plan_date, minutes, reason, created_at)
        VALUES (?, ?, ?, ?, ?)
    """, [(e["topic_id"], e["plan_date"], e["minutes"], e.get("reason"), now_iso())
          for e in entries])
    conn.commit()
    conn.close()
    return len(entries)


def get_study_plan(start_date=None, end_date=None):
    """Plan entries with topic/course names and a DERIVED status:
    done   — a review/cram session touched the topic on that date
    missed — the date passed with no such session
    planned — upcoming."""
    conn = get_conn()
    cursor = conn.cursor()
    query = """
        SELECT p.*, topics.title AS topic_title, courses.name AS course_name,
               pdfs.filename AS pdf_filename,
               EXISTS (
                   SELECT 1 FROM study_sessions s
                   JOIN session_topics st ON st.session_id = s.id
                   WHERE st.topic_id = p.topic_id
                     AND s.kind IN ('review','cram')
                     AND DATE(s.started_at) = p.plan_date
               ) AS studied
        FROM study_plan p
        JOIN topics  ON topics.id  = p.topic_id
        JOIN courses ON courses.id = topics.course_id
        JOIN pdfs    ON pdfs.id    = topics.pdf_id
        WHERE 1=1
    """
    params = []
    if start_date:
        query += " AND p.plan_date >= ?"
        params.append(start_date)
    if end_date:
        query += " AND p.plan_date <= ?"
        params.append(end_date)
    query += " ORDER BY p.plan_date, p.id"
    cursor.execute(query, params)
    rows = cursor.fetchall()
    conn.close()

    today = datetime.now().strftime("%Y-%m-%d")
    result = []
    for row in rows:
        entry = dict(row)
        if entry.pop("studied"):
            entry["status"] = "done"
        elif entry["plan_date"] < today:
            entry["status"] = "missed"
        else:
            entry["status"] = "planned"
        result.append(entry)
    return result


def get_answer_log(days=90):
    """Graded answers within the window, joined with card/topic context."""
    since = (datetime.now() - timedelta(days=days)).isoformat(timespec="seconds")
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT answer_log.at, answer_log.card_id, answer_log.quality,
               answer_log.confidence, answer_log.elapsed_ratio,
               answer_log.latency_ms,
               cards.question, topics.title AS topic_title
        FROM answer_log
        LEFT JOIN cards  ON cards.id  = answer_log.card_id
        LEFT JOIN topics ON topics.id = cards.topic_id
        WHERE answer_log.at >= ?
        ORDER BY answer_log.at
    """, (since,))
    rows = cursor.fetchall()
    conn.close()
    return rows


# ---------------------------------------------------------------- mastery inputs

def get_mastery_inputs(pdf_id):
    """Everything mastery.py needs for one pdf, in two queries."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM topics WHERE pdf_id = ? ORDER BY position", (pdf_id,))
    topics = cursor.fetchall()
    cursor.execute("""
        SELECT id, topic_id, interval_days, repetitions, last_reviewed_at,
               next_review, stability
        FROM cards WHERE pdf_id = ?
    """, (pdf_id,))
    cards = cursor.fetchall()
    conn.close()
    return topics, cards


if __name__ == "__main__":
    init_db()
