import json
from embeddings import embed_text
from database import get_conn


def backfill_embeddings():
    conn = get_conn()
    cursor = conn.cursor()

    cursor.execute("SELECT id, content FROM notes WHERE embedding IS NULL")
    rows = cursor.fetchall()

    print(f"Found {len(rows)} notes to embed")

    for row in rows:
        vector = embed_text(row["content"])
        cursor.execute("UPDATE notes SET embedding = ? WHERE id = ?",
                       (json.dumps(vector), row["id"]))
        print(f"Embedded note {row['id']}")

    conn.commit()
    conn.close()


if __name__ == "__main__":
    backfill_embeddings()
