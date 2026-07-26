"""Semantic search over saved notes — frameworks fork: a thin wrapper over the
Chroma vector store (see vector_store.py). Same signature and return shape as
the original hand-rolled version (numpy cosine over JSON embeddings), so
agent_core's search handler is unchanged."""

import vector_store


def search_notes(query, top_k=3, min_score=0.0, course_id=None, pdf_id=None, topic_id=None):
    return vector_store.query(query, top_k=top_k, min_score=min_score,
                              course_id=course_id, pdf_id=pdf_id, topic_id=topic_id)
