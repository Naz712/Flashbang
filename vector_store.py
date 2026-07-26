"""Chroma vector store — replaces the hand-rolled embedding pipeline
(embeddings.py + JSON vectors in SQLite + cosine loop in search.py, all kept
on disk for the reference board).

Uses Chroma's default LOCAL embedding function (all-MiniLM-L6-v2 via ONNX):
no API calls, no per-embedding cost, works offline. First use downloads the
model (~80 MB) into Chroma's cache. Cosine space so scores read like the old
similarity numbers. SQLite stays the source of truth for note content; Chroma
holds vectors + citation metadata and is rebuildable any time via
backfill_embedding.py."""

import os
import chromadb

CHROMA_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma")

_collection = None


def _notes():
    global _collection
    if _collection is None:
        client = chromadb.PersistentClient(path=CHROMA_PATH)
        _collection = client.get_or_create_collection(
            "notes", metadata={"hnsw:space": "cosine"})
    return _collection


def reset(path=None):
    """Point at a different store (tests) or force re-open."""
    global _collection, CHROMA_PATH
    if path:
        CHROMA_PATH = path
    _collection = None


def add_note(note_id, content, metadata):
    """metadata: ids + display names for citations. Chroma rejects None values,
    so they're dropped."""
    clean = {k: v for k, v in metadata.items() if v is not None}
    _notes().upsert(ids=[str(note_id)], documents=[content], metadatas=[clean])


def delete_notes(note_ids):
    if note_ids:
        _notes().delete(ids=[str(n) for n in note_ids])


def delete_where(**filters):
    """Delete by metadata equality, e.g. delete_where(course_id=3)."""
    clean = {k: v for k, v in filters.items() if v is not None}
    if clean:
        _notes().delete(where=_where(clean))


def _where(filters):
    clauses = [{k: {"$eq": v}} for k, v in filters.items()]
    return clauses[0] if len(clauses) == 1 else {"$and": clauses}


def query(text, top_k=3, min_score=0.0, **filters):
    """Semantic search. Returns [(score, note_dict)] best-first, where
    note_dict carries id/content plus the citation metadata."""
    collection = _notes()
    if collection.count() == 0:
        return []
    clean = {k: v for k, v in filters.items() if v is not None}
    result = collection.query(
        query_texts=[text],
        n_results=min(top_k, collection.count()),
        where=_where(clean) if clean else None,
    )
    hits = []
    for note_id, document, meta, distance in zip(
            result["ids"][0], result["documents"][0],
            result["metadatas"][0], result["distances"][0]):
        score = 1 - distance  # cosine distance -> similarity
        if score < min_score:
            continue
        hits.append((score, {"id": int(note_id), "content": document, **meta}))
    return hits
