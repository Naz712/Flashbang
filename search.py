import json
import numpy as np
from embeddings import embed_text
from database import get_notes_with_embeddings

def cosine_similarity(a, b):
    a = np.array(a)
    b = np.array(b)
    return np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))

def search_notes(query, top_k=3, min_score=0.0, course_id=None, pdf_id=None, topic_id=None): #adjust min score for eval
    query_vec = embed_text(query)
    notes = get_notes_with_embeddings(course_id=course_id, pdf_id=pdf_id, topic_id=topic_id)

    scored = []
    for note in notes:
        stored_vec = json.loads(note["embedding"])
        score = cosine_similarity(query_vec, stored_vec)
        scored.append((score, note))

    scored.sort(key=lambda pair: pair[0], reverse=True)
    filtered = [pair for pair in scored if pair[0] >= min_score]
    return filtered[:top_k]