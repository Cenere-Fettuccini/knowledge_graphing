import logging
from pathlib import Path

from src.agent_platform.analyzers.knowledge import KnowledgeAnalyzer
from src.core.config import settings
from src.core.logging_config import setup_logging
from src.ingestion.chunker import chunk_text
from src.memory.manager import get_memory_manager

setup_logging()
logger = logging.getLogger(__name__)


class KnowledgeIngestor:
    """Processes local files and injects them into the AIManager memory ecosystem."""

    def __init__(self):
        self.memory = get_memory_manager()

    def ingest_directory(self, path: str, *, analyze: bool = True) -> dict:
        """Load text/markdown files from a directory, store them as chunks, and
        optionally drain the knowledge analyzer over the freshly queued rows.

        Set ``analyze=False`` for tests, or when you'd rather let the next
        scheduler tick pick up the queue instead.
        """
        root = Path(path)
        if not root.exists():
            logger.error("Path does not exist: %s", path)
            return {"files": 0, "chunks": 0, "analyzer": None}

        files = sorted(
            candidate
            for candidate in root.rglob("*")
            if candidate.is_file() and candidate.suffix.lower() in {".md", ".txt"}
        )
        logger.info("Found %d candidate documents in %s.", len(files), path)

        chunk_total = 0
        for file_path in files:
            try:
                text = file_path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                text = file_path.read_text(encoding="utf-8", errors="ignore")

            chunks = chunk_text(text, chunk_size=1000, chunk_overlap=100)
            chunk_total += len(chunks)

            for chunk in chunks:
                self.memory.store(
                    text=chunk,
                    role="document",
                    session_id="bulk_import",
                    source=str(file_path),
                    type="ingested_file",
                )

        logger.info(
            "Bulk ingestion complete. Stored %d chunks from %d files.",
            chunk_total,
            len(files),
        )

        analyzer_summary = None
        if analyze and chunk_total:
            analyzer_summary = self._drain_analyzer_queue()

        return {"files": len(files), "chunks": chunk_total, "analyzer": analyzer_summary}

    def _drain_analyzer_queue(self) -> dict:
        """Loop ``analyze_pending`` until the queue is empty, the LLM bails,
        or we hit the safety cap. Yields back to the caller after each batch
        so a giant ingest can't block on a single oversized LLM call.
        """
        analyzer = KnowledgeAnalyzer(memory=self.memory)
        batch_size = settings.analyzer_batch_size
        max_batches = 50  # hard ceiling so a misbehaving model can't loop forever
        passes: list[dict] = []

        for attempt in range(max_batches):
            result = analyzer.analyze_pending(batch_size=batch_size)
            passes.append(result.as_dict())
            if result.skipped:
                logger.info(
                    "Bulk-ingest analyzer drain stopping after %d batches: %s",
                    attempt,
                    result.reason or "skipped",
                )
                break
            if result.processed_messages == 0:
                # Defensive: an unskipped result that processed nothing means
                # the queue is empty.
                break
        else:
            logger.warning(
                "Bulk-ingest analyzer hit the %d-batch safety cap; "
                "remaining rows will be picked up on the next scheduler tick.",
                max_batches,
            )

        return {
            "batches": len(passes),
            "total_processed": sum(p.get("processed_messages", 0) for p in passes),
            "total_entities": sum(p.get("entities_written", 0) for p in passes),
            "total_relationships": sum(p.get("relationships_written", 0) for p in passes),
            "stopped_reason": passes[-1].get("reason") if passes else None,
        }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        logger.error("Usage: python -m src.tools.ingest <directory_path>")
    else:
        ingestor = KnowledgeIngestor()
        ingestor.ingest_directory(sys.argv[1])
