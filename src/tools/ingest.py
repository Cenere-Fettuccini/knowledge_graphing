import logging
from pathlib import Path

from src.core.logging_config import setup_logging
from src.ingestion.chunker import chunk_text
from src.memory.manager import memory_manager

setup_logging()
logger = logging.getLogger(__name__)


class KnowledgeIngestor:
    """Processes local files and injects them into the AIManager memory ecosystem."""

    def __init__(self):
        self.memory = memory_manager

    def ingest_directory(self, path: str):
        """Load text and markdown files from a directory and store them as chunks."""
        root = Path(path)
        if not root.exists():
            logger.error("Path does not exist: %s", path)
            return

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

        logger.info("Bulk ingestion complete. Stored %d chunks from %d files.", chunk_total, len(files))


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        logger.error("Usage: python -m src.tools.ingest <directory_path>")
    else:
        ingestor = KnowledgeIngestor()
        ingestor.ingest_directory(sys.argv[1])
