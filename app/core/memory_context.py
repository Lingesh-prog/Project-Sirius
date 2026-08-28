"""Deterministic pre-retrieval of relevant memories for AI requests.

Before a natural-language request is sent to the AI, SIRIUS looks up
memories whose key or value shares a word with the request. Matching is a
plain case-insensitive substring search through the existing memory
service - no embeddings, no semantic search, no automatic saving.

Only the most relevant memories are returned so the memory database is
never dumped into a prompt, and nothing here creates or modifies memory.
"""

import re

from app.tools.memory import service as memory_service


MAX_MEMORY_CONTEXT_MEMORIES = 3
MIN_QUERY_TOKEN_LENGTH = 4

_TOKEN_PATTERN = re.compile(r"[a-z0-9]+")


def collect_relevant_memories(request_text, database_path=None):
    """Return the memories most relevant to *request_text*.

    The request is split into lowercase word tokens; every token of at
    least four characters is searched for, and matches are ranked by how
    many tokens they match, then by key. Requests without usable tokens
    (for example very short inputs) perform no memory search at all.
    """
    tokens = list(dict.fromkeys(_request_tokens(request_text)))
    if not tokens:
        return []

    match_counts = {}
    for token in tokens:
        for memory in memory_service.search_memories(
            token, database_path=database_path
        ):
            match_counts[memory] = match_counts.get(memory, 0) + 1

    ranked = sorted(
        match_counts,
        key=lambda memory: (-match_counts[memory], memory[1], memory[0]),
    )
    return ranked[:MAX_MEMORY_CONTEXT_MEMORIES]


def render_memories(memories):
    """Render memory rows as 'key: value' lines, or None when empty."""
    if not memories:
        return None

    return "\n".join(f"{memory[1]}: {memory[2]}" for memory in memories)


def _request_tokens(request_text):
    if not isinstance(request_text, str):
        return []

    tokens = _TOKEN_PATTERN.findall(request_text.lower())
    return [token for token in tokens if len(token) >= MIN_QUERY_TOKEN_LENGTH]