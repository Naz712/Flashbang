import sqlite3
import json
from embeddings import embed_text

def backfill_embeddings():
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, content FROM notes WHERE embedding IS NULL")
    rows = cursor.fetchall()
    
    print(f"Found {len(rows)} notes to embed")
    
    for row in rows:
        note_id = row[0]
        content = row[1]
        
        vector = embed_text(content)
        vector_as_string = json.dumps(vector)
        
        cursor.execute("UPDATE notes SET embedding = ? WHERE id = ?", (vector_as_string, note_id))
        print(f"Embedded note {note_id}")
    
    conn.commit()
    conn.close()

if __name__ == "__main__":
    backfill_embeddings()