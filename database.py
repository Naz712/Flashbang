import json
import sqlite3
from datetime import datetime, timedelta #importing in order to be able to set next review date 
from sm2 import compute_sm2 #importing def compute_sm2 from other folder 
from embeddings import embed_text

def init_db(): #stands for initialise database, creates the db = database if nothing exists curretnly 
    conn = sqlite3.connect("calendar.db") #connect to the database in order to make edits 
    cursor = conn.cursor() #allows the usage of SQL commands through python 
    
    cursor.execute(""" 
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            start_time TEXT NOT NULL,
            end_time TEXT NOT NULL,
            notes TEXT,
            recurrence TEXT
        )
    """) #command being excuted

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                name TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                embedding TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cards (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                subject TEXT NOT NULL,
                topic TEXT NOT NULL,
                question TEXT NOT NULL,
                answer TEXT NOT NULL,
                ease_factor REAL NOT NULL DEFAULT 2.5,
                interval_days INTEGER NOT NULL DEFAULT 0,
                repetitions INTEGER NOT NULL DEFAULT 0,
                next_review TEXT NOT NULL,
                notes_id INTEGER,
                FOREIGN KEY (notes_id) REFERENCES notes(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS insights (
                   id INTEGER PRIMARY KEY AUTOINCREMENT,
                   card_id INTEGER NOT NULL,
                   content TEXT NOT NULL,
                   created_at TEXT NOT NULL,
                   FOREIGN KEY (card_id) REFERENCES cards(id)
        )
    """)    
    conn.commit() #commits the changes to the database and then saves it 
    conn.close() #end connection to database

def insert_event(title, start_time, end_time, notes=None, recurrence=None):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO events (title, start_time, end_time, notes, recurrence)
        VALUES (?, ?, ?, ?, ?)
    """, (title, start_time, end_time, notes, recurrence))
    conn.commit()
    conn.close() 

def get_events(start_date, end_date):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("""
    SELECT * FROM events
    WHERE start_time BETWEEN ? AND ?
    ORDER BY start_time ASC
    """, (start_date, end_date))    
    events = cursor.fetchall()
    conn.close()
    return events

def delete_event(event_id):
    conn = sqlite3.connect("calendar.db")
    cursor=conn.cursor()
    cursor.execute("DELETE FROM events WHERE id=?", (event_id,))
    conn.commit()
    conn.close()

def update_event(event_id, title=None, start_time=None, end_time=None, notes=None, recurrence=None):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE events
    SET title = COALESCE(?, title),
        start_time = COALESCE(?, start_time),
        end_time = COALESCE(?, end_time),
        notes = COALESCE(?, notes),
        recurrence = COALESCE(?, recurrence)
    WHERE id = ?
    """, (title, start_time, end_time, notes, recurrence, event_id))
    conn.commit()
    conn.close()

def insert_card(subject, topic, question, answer, notes_id=None):
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO cards (subject, topic, question, answer, next_review, notes_id)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (subject, topic, question, answer, tomorrow, notes_id))
    card_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return card_id

def delete_card(card_id):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cards WHERE id=?", (card_id,))
    conn.commit()
    conn.close()

def get_due_cards():
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM cards
        WHERE next_review <= ?
        ORDER BY next_review ASC
    """, (today,))
    cards = cursor.fetchall()
    conn.close()
    return cards

def review_card(card_id, quality):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT ease_factor, interval_days, repetitions FROM cards WHERE id=?", (card_id,))
    row = cursor.fetchone()
    ease_factor, interval_days, repetitions = row   
    new_ease_factor, new_interval_days, new_repetitions = compute_sm2(ease_factor, interval_days, repetitions, quality)
    
    next_review_date = (datetime.now() + timedelta(days=new_interval_days)).strftime("%Y-%m-%d")
    
    cursor.execute("""
        UPDATE cards
        SET ease_factor=?, interval_days=?, repetitions=?, next_review=?
        WHERE id=?
    """, (new_ease_factor, new_interval_days, new_repetitions, next_review_date, card_id))
    
    conn.commit()
    conn.close()
    return new_interval_days

def update_card(card_id, subject=None, topic=None, question=None, answer=None):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("""
    UPDATE cards
        SET subject = COALESCE(?, subject),
            topic = COALESCE(?, topic),
            question = COALESCE(?, question),
            answer = COALESCE(?, answer)
    WHERE id = ?
    """, (subject, topic, question, answer, card_id))
    conn.commit()
    conn.close()

def get_cards(subject=None, topic=None):   # plural!
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()

    query = "SELECT * FROM cards WHERE 1=1"
    params = []
    if subject:
        query += " AND subject = ?"
        params.append(subject)
    if topic:
        query += " AND topic = ?"
        params.append(topic)
    query += " ORDER BY next_review ASC"

    cursor.execute(query, params)
    cards = cursor.fetchall()
    conn.close()
    return cards
       
def insert_insight(card_id, content):
    created_at = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO insights (card_id, content, created_at)
        VALUES (?, ?, ?)
    """, (card_id, content, created_at))
    insight_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return insight_id

def get_insights_for_card(card_id):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM insights
        WHERE card_id = ?
        ORDER BY created_at DESC
    """, (card_id,))
    insights = cursor.fetchall()
    conn.close()
    return insights

def delete_insight(insight_id):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute ("DELETE FROM insights WHERE id=?", (insight_id,))
    conn.commit()
    conn.close()

def save_concepts(subject, topic, concepts):
    created_at = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    
    note_ids = []
    for c in concepts:
        vector = embed_text(c["content"])
        vector_as_string = json.dumps(vector)
        cursor.execute("""
            INSERT INTO notes (subject, topic, name, content, created_at, embedding)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (subject, topic, c["name"], c["content"], created_at, vector_as_string))
        note_ids.append(cursor.lastrowid)
    
    conn.commit()
    conn.close()
    return note_ids

def get_note(note_id):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("""
        SELECT * FROM notes
        WHERE id = ?
    """, (note_id,))
    note = cursor.fetchone()
    conn.close()
    return note

def delete_note(note_id):
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notes WHERE id=?", (note_id,))
    conn.commit()
    conn.close()

def get_notes_with_embeddings():
    conn = sqlite3.connect("calendar.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM notes WHERE embedding IS NOT NULL")
    rows = cursor.fetchall()
    conn.close()
    return rows


if __name__ == "__main__":
    init_db()
