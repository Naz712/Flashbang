tools = [
    {
        "name": "insert_event",
        "description": "Create a new calendar event. Use this when the user wants to schedule, add, or book something.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title of the event, e.g. 'Lunch with Sarah'"
                },
                "start_time": {
                    "type": "string",
                    "description": "ISO 8601 format, e.g. '2026-05-13T14:00'"
                },
                "end_time": {
                    "type": "string",
                    "description": "ISO 8601 format, e.g. '2026-05-13T15:00'"
                },
                "notes": {
                    "type": "string",
                    "description": "Optional extra info about the event"
                },
                "recurrence": {
                    "type": "string",
                    "description": "Optional. 'daily', 'weekly', 'monthly', or null for one-time."
                }
            },
            "required": ["title", "start_time", "end_time"]
        }
    },
    
    {
        "name": "get_events",
        "description": "Retrieve calendar events within a date range. Use this when the user asks what's on their schedule, what's coming up, or about specific days/weeks.",
        "input_schema": {
            "type": "object",
            "properties": {
                "start_date": {
                    "type": "string",
                    "description": "The start date for the range (inclusive), in ISO 8601 format."
                },
                "end_date": {
                    "type": "string",
                    "description": "The end date for the range (inclusive), in ISO 8601 format."
                }
            },
            "required": ["start_date", "end_date"]
        }
    },
    {
        "name": "delete_event",
        "description": "Delete a calendar event by its ID. Use this when the user wants to cancel, remove, or delete an event. You may need to call get_events first to find the right event_id.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "integer",
                    "description": "The unique identifier of the event to delete."
                }
            },
            "required": ["event_id"]
        }
    },
    {  
        "name": "update_event",
        "description": "Update an existing calendar event by its ID. Use this when the user wants to change the details of an event. You may need to call get_events first to find the right event_id. Only provide the fields that need to be updated.",
        "input_schema": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "integer",
                    "description": "The unique identifier of the event to update."
                },
                "title": {
                    "type": "string",
                    "description": "Updated title of the event, e.g. 'Lunch with Sarah'"
                },
                "start_time": {
                    "type": "string",
                    "description": "Updated start time in ISO 8601 format, e.g. '2026-05-13T14:00'"
                },
                "end_time": {
                    "type": "string",
                    "description": "Updated end time in ISO 8601 format, e.g. '2026-05-13T15:00'"
                },
                "notes": {
                    "type": "string",
                    "description": "Updated extra info about the event"
                },
                "recurrence": {
                    "type": "string",
                    "description": "Updated recurrence pattern: 'daily', 'weekly', 'monthly', 'bi-weekly', or one-time."
                }
            },
            "required": ["event_id"]
        }
    },

    {
    "name": "insert_card",
    "description": "Create a new flashcard for spaced repetition learning. Use this when the user wants to add a new fact or concept to their study deck. For cards generated from notes, pass the notes_id from the card dict to link it to its source chunk.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The subject of the flashcard, e.g. 'Java', 'Python'"
                },
                "topic": {
                    "type": "string",
                    "description": "The topic within the subject, e.g. 'basics', 'advanced'"
                },
                "question": {
                    "type": "string",
                    "description": "The question or prompt for the flashcard"
                },
                "answer": {
                    "type": "string",
                    "description": "The answer or explanation for the flashcard"
                },
                "notes_id": {
                    "type": "integer",
                    "description": "Optional. The id of the source note chunk this card was derived from. Only used for cards generated via the notes-to-cards flow; omit for manually created cards."
                }
            },
            "required": ["subject", "topic", "question", "answer"]
        }
    },

    {
        "name": "review_card",
        "description": "Review a flashcard and update its spaced repetition parameters using the SM-2 algorithm. Use this when the user has just attempted to recall a card and tells you how well they did. Quality is a 0–5 score: 0=blackout, 1=wrong but recognized answer, 2=wrong but easy to remember once seen, 3=correct with serious effort, 4=correct with hesitation, 5=perfect instant recall. Scores 0–2 are failures (card resets). Scores 3–5 are passes (interval grows).",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "integer",
                    "description": "The unique identifier of the flashcard to review."
                },
                "quality": {
                    "type": "integer",
                    "description": "Recall quality score from 0 to 5 (5 = perfect recall, 0 = complete blackout)."
                }
            },
            "required": ["card_id", "quality"]
        }
    },

    {
        "name": "get_due_cards",
        "description": "Retrieve all flashcards that are due for review today. Use this when the user wants to see which cards they need to review. This will return a list of cards where next_review is today or earlier.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },

    {
        "name": "delete_card",
        "description": "Delete a flashcard by its ID. Use this when the user wants to remove a card permanently from their study deck.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "integer",
                    "description": "The unique identifier of the flashcard to delete."
                }
            },
            "required": ["card_id"]
        }
    },

    {
        "name": "grade_answer",
        "description": "Grade a user's recalled answer to a flashcard. Use this AFTER the user has typed their attempt at recalling the answer, and BEFORE calling review_card. Returns a dict with 'quality' (0-5 SM-2 score) and 'feedback' (explanation of what was right/missed). Use the returned quality value when calling review_card.",
        "input_schema": {
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "The flashcard question."
                },
                "correct_answer": {
                    "type": "string",
                    "description": "The flashcard's stored correct answer."
                },
                "user_answer": {
                    "type": "string",
                    "description": "The user's attempted recall, in their own words."
                }
            },
            "required": ["question", "correct_answer", "user_answer"]
        }
    },

    {
        "name": "update_card",
        "description": "Update the content of an existing flashcard by its ID. Use this when the user wants to edit the subject, topic, question, or answer of a card they already have — for example, fixing a typo or rewording an answer. Only provide the fields that need to change. This does not affect the card's spaced repetition schedule.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "integer",
                    "description": "The unique identifier of the flashcard to update."
                },
                "subject": {
                    "type": "string",
                    "description": "Updated subject of the flashcard, e.g. 'Java', 'Python'"
                },
                "topic": {
                    "type": "string",
                    "description": "Updated topic within the subject, e.g. 'basics', 'advanced'"
                },
                "question": {
                    "type": "string",
                    "description": "Updated question or prompt for the flashcard"
                },
                "answer": {
                    "type": "string",
                    "description": "Updated answer or explanation for the flashcard"
                }
            },
            "required": ["card_id"]
        }
    },

    {
        "name": "get_cards",
        "description": "Retrieve flashcards filtered by subject and/or topic. Use this when the user wants to browse, list, or look up cards by content — e.g. 'show me my Python cards' or 'list all my recursion cards'. Both filters are optional — if neither is provided, returns all cards. This is for browsing, not for reviewing due cards (use get_due_cards for that).",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "Optional filter by subject, e.g. 'Java', 'Python'"
                },
                "topic": {
                    "type": "string",
                    "description": "Optional filter by topic within the subject, e.g. 'basics', 'advanced'"
                }
            },
            "required": []
        }
    },

    {
        "name": "insert_insight",
        "description": "Save an insight tied to a specific flashcard. An insight is a follow-up note, realization, mnemonic, or connection the user wants to remember next time they review this card. Use when the user says 'save this insight', 'remember this thought', 'note that', or similar phrases while reviewing or discussing a card.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "integer",
                    "description": "The unique identifier of the flashcard for which to insert an insight."
                },
                "content": {
                     "type": "string",
                     "description": "The text of the insight — a concise summary (1-2 sentences) of the realization, follow-up fact, or mnemonic. Synthesize from the conversation rather than copying long passages verbatim."
                }
            },
            "required": ["card_id", "content"]
        }
    },

    {
        "name": "get_insights_for_card",
        "description": "Retrieve all insights tied to the card_id of a specific flashcard. Use this when the user wants to review all the insights they have saved for a card. The user might say 'what are the insights' or 'show insights'. Returns a list of insights, each with id, content, and creation date, ordered newest first.",
        "input_schema": {
            "type": "object",
            "properties": {
                "card_id": {
                    "type": "integer",
                    "description": "The unique identifier of the flashcard for which to retrieve insights."
                }
            },
            "required": ["card_id"]
        }
    },

    {
        "name": "delete_insight",
        "description": "Delete a specific insight by its ID. Use this when the user wants to remove an insight they have previously saved.",
        "input_schema": {
            "type": "object",
            "properties": {
                "insight_id": {
                    "type": "integer",
                    "description": "The unique identifier of the insight to delete."
                }
            },
            "required": ["insight_id"]
        }
    },

    {
    "name": "extract_concepts",
    "description": "Extract key concepts from study notes, with verbatim source text for each. Use this when the user wants to turn a block of notes into flashcards. This is the first step of the notes-to-cards flow — always call this before save_concepts or generate_cards_for_session.",
    "input_schema": {
        "type": "object",
        "properties": {
            "notes": {
                "type": "string",
                "description": "The raw study notes text from which to extract concepts."
            }
        },
        "required": ["notes"]
    }
    },

    {
        "name": "save_concepts",
        "description": "Save all approved concept chunks into the notes corpus in one batch. Call this ONCE after the user approves the output of extract_concepts. Returns a list of note ids, one per concept, in the same order as the input.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The subject for these notes, e.g. 'Java'. Comes from extract_concepts's output."
                },
                "topic": {
                    "type": "string",
                    "description": "The topic for these notes, e.g. 'Inheritance'. Comes from extract_concepts's output."
                },
                "concepts": {
                    "type": "array",
                    "description": "The full list of approved concepts as returned by extract_concepts. Each item has 'name' and 'content' fields."
                }
            },
            "required": ["subject", "topic", "concepts"]
        }
    },
    {
        "name": "generate_cards_for_session",
        "description": "Generate flashcards for all approved concepts in a notes session. Call this ONCE after save_concepts returns note_ids. Internally loops over each concept (up to 3 cards each), tags each card with its source note_id, and caps total at 15. Returns the full batch for user review before insert_card is called per card.",
        "input_schema": {
            "type": "object",
            "properties": {
                "subject": {
                    "type": "string",
                    "description": "The subject for the flashcards, as approved from extract_concepts."
                },
                "topic": {
                    "type": "string",
                    "description": "The topic for the flashcards, as approved from extract_concepts."
                },
                "concepts": {
                    "type": "array",
                    "description": "The approved list of concepts from extract_concepts. Each item has 'name' and 'content'."
                },
                "note_ids": {
                    "type": "array",
                    "description": "The list of note ids returned by save_concepts, in the same order as concepts."
                }
            },
            "required": ["subject", "topic", "concepts", "note_ids"]
        }
    },

    {
    "name": "bulk_insert_cards",
    "description": "Insert multiple flashcards at once. Use this for the notes-to-cards flow AFTER the user approves the cards from generate_cards_for_session. Pass the approved list of card dicts (each containing subject, topic, question, answer, and notes_id). Each card is saved with its notes_id intact, preserving the link to its source chunk.",
    "input_schema": {
        "type": "object",
        "properties": {
            "cards": {
                "type": "array",
                "description": "The full list of approved card dicts. Each card has subject, topic, question, answer, and notes_id fields — pass them through exactly as returned by generate_cards_for_session (minus any the user dropped)."
            }
        },
        "required": ["cards"]
        }
    },

    {
    "name": "extract_text_from_pdf_vision",
    "description": """Extract text content from a PDF file. Use this when the user provides a PDF file path and wants to ingest its content for any purpose — making flashcards, summarizing, or pulling out specific information. 
                    This is typically the first step of the notes-to-cards flow when the source is a PDF; call this BEFORE extract_concepts so the extracted text can be fed in.
                    The user might say read this or something similar. Generally use this when the user provides a PDF path.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "pdf_path": {
                "type": "string",
                "description": "The absolute or relative file system path to the PDF file."
            }
        },
        "required": ["pdf_path"]
        }
    },

    {
        "name": "delete_note",
        "description": "Delete a specific note by its ID. Use this when the user wants to remove a note chunk they have previously saved. This is for deleting source notes, not flashcards or insights.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "integer",
                    "description": "The unique identifier of the note to delete."
                }
            },
            "required": ["note_id"]
        }
    },

    {
        "name": "get_note",
        "description": "Retrieve a specific note by its ID. Use this when the user wants to review or reference the original note chunk that a flashcard was derived from. This is for fetching source notes, not flashcards or insights.",
        "input_schema": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "integer",
                    "description": "The unique identifier of the note to retrieve."
                }
            },
            "required": ["note_id"]
        }
        
    },

    {
    "name": "search_notes",
    "description": "Semantic search over the user's saved study notes. Use this when the user asks a conceptual question about material they've studied — e.g. 'what did my notes say about hash collisions', 'explain transformers', 'how does open addressing work'. Returns the most relevant note chunks by meaning. Answer using the returned chunks and name the subject/topic they came from; if nothing relevant is returned, tell the user it isn't in their notes.",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The concept or question to search for, in natural language. Phrasing it as the underlying concept (e.g. 'hash table collision handling') usually retrieves better than a chatty question."
            },
            "top_k": {
                "type": "integer",
                "description": "Optional. How many chunks to retrieve (default 3). Use 4-5 for broad questions spanning several ideas."
            }
        },
        "required": ["query"]
    }
    }


]