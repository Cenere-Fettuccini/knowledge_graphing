"""Text chunking helpers for ingestion pipelines."""


def chunk_text(text: str, chunk_size: int = 1000, chunk_overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks using paragraph and line boundaries when possible."""
    normalized = text.replace("\r\n", "\n").strip()
    if not normalized:
        return []

    chunks: list[str] = []
    cursor = 0
    length = len(normalized)

    while cursor < length:
        window_end = min(cursor + chunk_size, length)
        if window_end < length:
            split_at = normalized.rfind("\n\n", cursor, window_end)
            if split_at == -1:
                split_at = normalized.rfind("\n", cursor, window_end)
            if split_at == -1 or split_at <= cursor:
                split_at = window_end
        else:
            split_at = length

        chunk = normalized[cursor:split_at].strip()
        if chunk:
            chunks.append(chunk)

        if split_at >= length:
            break

        cursor = max(split_at - chunk_overlap, cursor + 1)

    return chunks
