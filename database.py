import json
import sqlite3
from datetime import datetime, timedelta
import fsrs_adapter   # scheduler: FSRS @ desired_retention=0.95 (see /reference for the eval journey)
import vector_store    # frameworks fork: Chroma replaces JSON embeddings + cosine

DB_PATH = "flashbang.db"


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
            kind           TEXT NOT NULL CHECK (kind IN ('review','cram','ingestion')),
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
        CREATE TABLE IF NOT EXISTS answer_log (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            at         TEXT NOT NULL,
            card_id    INTEGER REFERENCES cards(id) ON DELETE SET NULL,
            quality    INTEGER NOT NULL,
            confidence TEXT CHECK (confidence IN ('sure','unsure') OR confidence IS NULL)
        )
    """)

    # migrations for pre-existing databases
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

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_topic       ON cards(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cards_next_review ON cards(next_review)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_topics_pdf        ON topics(pdf_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_notes_topic       ON notes(topic_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sessions_started  ON study_sessions(started_at)")

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

def create_pdf(course_id, filename, file_path=None, source_type="pdf", total_pages=0):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO pdfs (course_id, filename, file_path, source_type, total_pages, ingested_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (course_id, filename, file_path, source_type, total_pages, now_iso()))
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


def get_pdfs(course_id=None):
    conn = get_conn()
    cursor = conn.cursor()
    if course_id:
        cursor.execute("SELECT * FROM pdfs WHERE course_id = ? ORDER BY ingested_at DESC", (course_id,))
    else:
        cursor.execute("SELECT * FROM pdfs ORDER BY ingested_at DESC")
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
        cursor.execute("""
            INSERT INTO topics (pdf_id, course_id, title, summary, page_start, page_end,
                                est_minutes, position, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (pdf_id, course_id, t["title"], t.get("summary"), t["page_start"],
              t["page_end"], t.get("est_minutes", 0), position, now_iso()))
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


def update_topic(topic_id, title=None, summary=None, est_minutes=None):
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE topics
        SET title       = COALESCE(?, title),
            summary     = COALESCE(?, summary),
            est_minutes = COALESCE(?, est_minutes)
        WHERE id = ?
    """, (title, summary, est_minutes, topic_id))
    # keep the pdf total in sync when a topic estimate changes
    if est_minutes is not None:
        cursor.execute("""
            UPDATE pdfs SET est_total_minutes =
                (SELECT SUM(est_minutes) FROM topics WHERE pdf_id = pdfs.id)
            WHERE id = (SELECT pdf_id FROM topics WHERE id = ?)
        """, (topic_id,))
    conn.commit()
    conn.close()


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


def get_study_log(start_date=None, end_date=None, course_id=None):
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


def log_answer(quality, confidence=None, card_id=None, latency_ms=None):
    """Record one graded recall attempt (feeds calibration + 85%-rule flags)."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO answer_log (at, card_id, quality, confidence, latency_ms) VALUES (?, ?, ?, ?, ?)",
                   (now_iso(), card_id, quality, confidence, latency_ms))
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


def log_focus_session(minutes, course_id=None, pdf_id=None):
    """Log a UI focus-timer session that just ended (started `minutes` ago).
    Cards reviewed and topics touched during the window are derived from the
    cards table, same as end_session."""
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
        VALUES ('review', ?, ?, ?, ?, ?, ?, 'focus session')
    """, (course_id, pdf_id, started_iso, ended_iso, cards_reviewed, float(minutes)))
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


def get_time_by_course():
    """Total logged study minutes per course, all time."""
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT s.course_id, courses.name, SUM(s.minutes) AS minutes
        FROM study_sessions s
        LEFT JOIN courses ON courses.id = s.course_id
        WHERE s.minutes IS NOT NULL
        GROUP BY s.course_id
        ORDER BY minutes DESC
    """)
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
