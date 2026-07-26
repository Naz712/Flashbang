"""One-shot migration (frameworks fork): index every existing SQLite note into
the Chroma vector store with citation metadata. Safe to re-run — upserts."""

import vector_store
from database import get_conn


def backfill_into_chroma():
    conn = get_conn()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT notes.id, notes.name, notes.content,
               notes.topic_id, notes.pdf_id, notes.course_id,
               topics.title AS topic_title, courses.name AS course_name,
               pdfs.filename AS pdf_filename
        FROM notes
        JOIN topics  ON topics.id  = notes.topic_id
        JOIN courses ON courses.id = notes.course_id
        JOIN pdfs    ON pdfs.id    = notes.pdf_id
    """)
    rows = cursor.fetchall()
    conn.close()

    print(f"Indexing {len(rows)} notes into Chroma...")
    for row in rows:
        vector_store.add_note(row["id"], row["content"], {
            "name": row["name"],
            "topic_id": row["topic_id"], "pdf_id": row["pdf_id"],
            "course_id": row["course_id"],
            "topic_title": row["topic_title"],
            "course_name": row["course_name"],
            "pdf_filename": row["pdf_filename"],
        })
    print("Done.")


if __name__ == "__main__":
    backfill_into_chroma()
