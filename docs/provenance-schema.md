# Provenance Schema

First-pass provenance uses Neo4j as the durable graph and Chroma as retrieval storage.

Nodes:
- `Conversation`: one per `session_id`
- `Note`: a user-authored conversation turn
- `Thought`: an assistant-authored conversation turn
- `Belief`: durable interpreted claims with evidence and evolution
- `Task`, `Project`, and entity nodes: existing graph objects

Relationships:
- `HAS_TURN`: `Conversation -> Note|Thought`
- `FOLLOWS`: links each turn to the immediately previous turn in the same conversation
- `REFERENCES`: links a turn to its current anchor node or context node
- `EXTRACTED_FROM`, `SUPPORTED_BY`, `WEAKENED_BY`, `EVOLVED_FROM`: belief provenance

Rules:
- Every stored chat turn should still be embedded into Chroma for search.
- Every stored chat turn should also be written into Neo4j when available.
- Explorer should read generic provenance for any node, then layer belief-specific evidence on top when present.
