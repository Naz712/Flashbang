"""Tool schemas for all agents, keyed by name. Each AgentSpec picks its subset
via tools_for(). Calendar CRUD tools are gone — the study log is written
automatically by the session tools and only read by the planner."""

TOOL_SCHEMAS = {
    # ------------------------------------------------------------ courses & library
    "create_course": {
        "name": "create_course",
        "description": "Create a new course (e.g. 'Machine Learning', 'Databases'). Courses are the top level of organization; every pdf, topic, and card belongs to one.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Course name, e.g. 'Machine Learning'"}
            },
            "required": ["name"],
        },
    },
    "get_courses": {
        "name": "get_courses",
        "description": "List all courses with their ids. Call this before any operation that needs a course_id.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    "delete_course": {
        "name": "delete_course",
        "description": "Delete a course AND everything under it (pdfs, topics, notes, cards, insights) via cascade. Destructive — confirm with the user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "integer", "description": "The course to delete."}
            },
            "required": ["course_id"],
        },
    },
    "get_pdfs": {
        "name": "get_pdfs",
        "description": "List ingested documents (pdfs and pasted-text sources), optionally filtered by course. Shows filename, total pages, estimated total minutes, and status.",
        "input_schema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "integer", "description": "Optional course filter."}
            },
            "required": [],
        },
    },
    "delete_pdf": {
        "name": "delete_pdf",
        "description": "Delete an ingested document and everything under it (topics, notes, cards) via cascade. Destructive — confirm with the user first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "integer", "description": "The pdf to delete."}
            },
            "required": ["pdf_id"],
        },
    },

    # ------------------------------------------------------------ ingestion
    "read_pdf": {
        "name": "read_pdf",
        "description": "Ingest a PDF file: extracts every page (locally where possible, Claude vision for scanned/diagram pages) and stores the text per page. First step of ingestion — call propose_topics after this. Requires an existing course_id (call get_courses / create_course first).",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_path": {"type": "string", "description": "Absolute or relative path to the PDF file."},
                "course_id": {"type": "integer", "description": "The course this document belongs to."},
            },
            "required": ["pdf_path", "course_id"],
        },
    },
    "create_text_source": {
        "name": "create_text_source",
        "description": "Ingest pasted text notes (instead of a PDF file). Stores the text as a one-page document; then use propose_topics exactly like a pdf.",
        "input_schema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "integer", "description": "The course this belongs to."},
                "title": {"type": "string", "description": "A short title for these notes."},
                "text": {"type": "string", "description": "The full pasted notes text."},
            },
            "required": ["course_id", "title", "text"],
        },
    },
    "propose_topics": {
        "name": "propose_topics",
        "description": "Analyze an ingested document's pages and propose a split into real content topics, each with a page range, summary, and estimated study minutes (plus the document total). Saves NOTHING — show the proposal to the user for approval/edits before calling save_topics.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "integer", "description": "The ingested document to segment."}
            },
            "required": ["pdf_id"],
        },
    },
    "save_topics": {
        "name": "save_topics",
        "description": "Persist the approved topic list for a document. Call ONCE after the user approves (possibly edited) topics from propose_topics. Sets the document's total time estimate and marks it ready. Returns topic ids in order.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "integer", "description": "The document these topics belong to."},
                "topics": {
                    "type": "array",
                    "description": "The approved topics, each with title, summary, page_start, page_end, est_minutes.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "title": {"type": "string"},
                            "summary": {"type": "string"},
                            "page_start": {"type": "integer"},
                            "page_end": {"type": "integer"},
                            "est_minutes": {"type": "integer"},
                        },
                        "required": ["title", "page_start", "page_end", "est_minutes"],
                    },
                },
            },
            "required": ["pdf_id", "topics"],
        },
    },
    "get_topics": {
        "name": "get_topics",
        "description": "List topics, filtered by pdf and/or course. Shows title, page range, estimated minutes, and position.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "integer", "description": "Optional pdf filter."},
                "course_id": {"type": "integer", "description": "Optional course filter."},
            },
            "required": [],
        },
    },
    "update_topic": {
        "name": "update_topic",
        "description": "Edit a topic's title, summary, or time estimate (the document's total estimate is kept in sync automatically). Only provide fields that change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "The topic to update."},
                "title": {"type": "string", "description": "New title."},
                "summary": {"type": "string", "description": "New summary."},
                "est_minutes": {"type": "integer", "description": "New estimated study minutes."},
            },
            "required": ["topic_id"],
        },
    },
    "extract_topic_concepts": {
        "name": "extract_topic_concepts",
        "description": "Extract key concepts (with verbatim source text) from a topic's pages. First step of making cards for a topic — show the concepts to the user for approval before save_topic_concepts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "The topic to extract concepts from."}
            },
            "required": ["topic_id"],
        },
    },
    "save_topic_concepts": {
        "name": "save_topic_concepts",
        "description": "Save the approved concepts for a topic into the notes corpus (embedded for semantic search). Call ONCE after user approval. Returns note ids in the same order as the concepts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "The topic these concepts belong to."},
                "concepts": {
                    "type": "array",
                    "description": "Approved concepts from extract_topic_concepts, each with 'name' and 'content'.",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "content": {"type": "string"},
                        },
                        "required": ["name", "content"],
                    },
                },
            },
            "required": ["topic_id", "concepts"],
        },
    },
    "generate_cards_for_topic": {
        "name": "generate_cards_for_topic",
        "description": "Generate flashcards for a topic's approved concepts (up to 5 per concept, 80 total). Call after save_topic_concepts, passing its note_ids in the same order as the concepts. Returns the card batch for user review — get approval before bulk_insert_cards.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "The topic the cards belong to."},
                "concepts": {"type": "array", "description": "The approved concepts, same order as note_ids."},
                "note_ids": {"type": "array", "description": "Note ids returned by save_topic_concepts, same order as concepts."},
            },
            "required": ["topic_id", "concepts", "note_ids"],
        },
    },
    "bulk_insert_cards": {
        "name": "bulk_insert_cards",
        "description": "Insert multiple approved flashcards at once, AFTER the user approves the batch from generate_cards_for_topic (drop any rejected cards first). Each card dict carries question, answer, topic_id, note_id — pass them through unchanged.",
        "input_schema": {
            "type": "object",
            "properties": {
                "cards": {
                    "type": "array",
                    "description": "Approved card dicts from generate_cards_for_topic (minus any the user dropped).",
                }
            },
            "required": ["cards"],
        },
    },

    # ------------------------------------------------------------ cards & review
    "insert_card": {
        "name": "insert_card",
        "description": "Create a single flashcard manually under a topic. The card's pdf and course are derived from the topic automatically. For batches from the ingestion flow use bulk_insert_cards instead.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic_id": {"type": "integer", "description": "The topic this card belongs to (get_topics to find it)."},
                "question": {"type": "string", "description": "The question or prompt."},
                "answer": {"type": "string", "description": "The answer or explanation."},
            },
            "required": ["topic_id", "question", "answer"],
        },
    },
    "get_cards": {
        "name": "get_cards",
        "description": "Browse flashcards filtered by course, pdf, and/or topic (all optional; none = all cards). For browsing/cram — use get_due_cards for spaced-repetition review.",
        "input_schema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "integer", "description": "Optional course filter."},
                "pdf_id": {"type": "integer", "description": "Optional pdf filter."},
                "topic_id": {"type": "integer", "description": "Optional topic filter."},
            },
            "required": [],
        },
    },
    "get_due_cards": {
        "name": "get_due_cards",
        "description": "Retrieve flashcards due for review now (next_review has passed), optionally scoped to a course/pdf/topic. Reviewing due cards is what restores topic mastery and completion %.",
        "input_schema": {
            "type": "object",
            "properties": {
                "course_id": {"type": "integer", "description": "Optional course filter."},
                "pdf_id": {"type": "integer", "description": "Optional pdf filter."},
                "topic_id": {"type": "integer", "description": "Optional topic filter."},
            },
            "required": [],
        },
    },
    "review_card": {
        "name": "review_card",
        "description": "Record a review: updates the card's SM-2 schedule from a 0-5 quality score and stamps last_reviewed_at (which resets the card's decay). Call AFTER grade_answer, using its quality value. 0-2 = failure (card resets), 3-5 = pass (interval grows).",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "integer", "description": "The card that was just reviewed."},
                "quality": {"type": "integer", "description": "Recall quality 0-5 from grade_answer."},
            },
            "required": ["card_id", "quality"],
        },
    },
    "update_card": {
        "name": "update_card",
        "description": "Edit a card's question or answer, or move it to a different topic (pdf/course follow the new topic automatically). Does not affect its review schedule. Only provide fields that change.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "integer", "description": "The card to update."},
                "question": {"type": "string", "description": "New question."},
                "answer": {"type": "string", "description": "New answer."},
                "topic_id": {"type": "integer", "description": "New topic to move the card to."},
            },
            "required": ["card_id"],
        },
    },
    "delete_card": {
        "name": "delete_card",
        "description": "Delete a flashcard permanently.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "integer", "description": "The card to delete."}
            },
            "required": ["card_id"],
        },
    },
    "grade_answer": {
        "name": "grade_answer",
        "description": "Grade the user's recalled answer against a card's stored answer. Use AFTER the user types their attempt and BEFORE review_card. Returns {'quality': 0-5, 'feedback': str}; pass the quality to review_card.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "The flashcard question."},
                "correct_answer": {"type": "string", "description": "The card's stored correct answer."},
                "user_answer": {"type": "string", "description": "The user's attempted recall, verbatim."},
            },
            "required": ["question", "correct_answer", "user_answer"],
        },
    },

    # ------------------------------------------------------------ insights
    "insert_insight": {
        "name": "insert_insight",
        "description": "Save an insight (follow-up note, mnemonic, realization) tied to a flashcard. Only on an explicit user cue ('save that', 'note this'), and only after showing a proposed 1-2 sentence summary and getting confirmation.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "integer", "description": "The card (usually the most recently shown one)."},
                "content": {"type": "string", "description": "Concise 1-2 sentence summary of the insight."},
            },
            "required": ["card_id", "content"],
        },
    },
    "get_insights_for_card": {
        "name": "get_insights_for_card",
        "description": "Retrieve saved insights for a card, newest first. Only when the user explicitly asks ('show insights').",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {"type": "integer", "description": "The card whose insights to fetch."}
            },
            "required": ["card_id"],
        },
    },
    "delete_insight": {
        "name": "delete_insight",
        "description": "Delete an insight by id. If the id is ambiguous, ask the user before calling.",
        "input_schema": {
            "type": "object",
            "properties": {
                "insight_id": {"type": "integer", "description": "The insight to delete."}
            },
            "required": ["insight_id"],
        },
    },

    # ------------------------------------------------------------ notes
    "get_note": {
        "name": "get_note",
        "description": "Fetch the source note chunk a flashcard was derived from (for reviewing original wording).",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "The note to fetch."}
            },
            "required": ["note_id"],
        },
    },
    "delete_note": {
        "name": "delete_note",
        "description": "Delete a source note chunk (cards derived from it survive with their link cleared).",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "integer", "description": "The note to delete."}
            },
            "required": ["note_id"],
        },
    },
    "search_notes": {
        "name": "search_notes",
        "description": "Semantic search over saved study notes. Use for conceptual/factual questions about studied material ('what did my notes say about hash collisions'). Returns the most relevant chunks with their course/pdf/topic so you can cite where the answer came from. If nothing relevant returns, say it isn't in the notes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "The concept to search for — phrase as the underlying concept ('hash table collision handling'), not a chatty question."},
                "top_k": {"type": "integer", "description": "Optional. Chunks to retrieve (default 3; 4-5 for broad questions)."},
                "course_id": {"type": "integer", "description": "Optional course filter."},
            },
            "required": ["query"],
        },
    },

    # ------------------------------------------------------------ study sessions & progress
    "start_study_session": {
        "name": "start_study_session",
        "description": "Open a study session log entry. Call at the START of every review or cram session, before showing the first card. kind='review' for spaced-repetition review, 'cram' for quiz-everything mode. The session is auto-logged to the study calendar.",
        "input_schema": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["review", "cram"], "description": "Session type."},
                "course_id": {"type": "integer", "description": "Optional course scope."},
                "pdf_id": {"type": "integer", "description": "Optional pdf scope."},
                "topic_ids": {"type": "array", "description": "Optional topic scope (required for cram so the log knows what was quizzed)."},
            },
            "required": ["kind"],
        },
    },
    "end_study_session": {
        "name": "end_study_session",
        "description": "Close the open study session. Call when every card has been quizzed or the user ends the session. For review sessions the reviewed-card count is derived automatically; for cram sessions pass cards_reviewed explicitly.",
        "input_schema": {
            "type": "object",
            "properties": {
                "session_id": {"type": "integer", "description": "The id returned by start_study_session."},
                "cards_reviewed": {"type": "integer", "description": "Required for cram sessions: how many cards were quizzed."},
                "summary": {"type": "string", "description": "Optional one-line summary of the session."},
            },
            "required": ["session_id"],
        },
    },
    "get_progress_report": {
        "name": "get_progress_report",
        "description": "Full progress report for a document (or every document in a course): completion % with decay applied, per-topic mastery %, status, time estimates, due-card counts, and next due dates. THE tool for 'how am I doing' / 'what % done am I'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pdf_id": {"type": "integer", "description": "Report on one document."},
                "course_id": {"type": "integer", "description": "Report on every document in a course."},
            },
            "required": [],
        },
    },
    "get_upcoming_reviews": {
        "name": "get_upcoming_reviews",
        "description": "Per-topic upcoming review deadlines: earliest due date and number of cards coming due within the window. THE tool for 'what should I study next' / 'what's due this week'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {"type": "integer", "description": "Look-ahead window in days (default 7)."}
            },
            "required": [],
        },
    },
    "get_study_log": {
        "name": "get_study_log",
        "description": "The study calendar: past sessions with date, kind, topics touched, cards reviewed, and minutes. Filter by date range and/or course. THE tool for 'what did I study last week'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {"type": "string", "description": "Optional ISO date lower bound, e.g. '2026-07-01'."},
                "end_date": {"type": "string", "description": "Optional ISO date upper bound."},
                "course_id": {"type": "integer", "description": "Optional course filter."},
            },
            "required": [],
        },
    },
}


def tools_for(names):
    """The Anthropic tools param for an agent's tool subset."""
    return [TOOL_SCHEMAS[name] for name in names]
