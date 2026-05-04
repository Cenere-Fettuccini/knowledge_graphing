import os
import logging
from typing import List
from langchain_community.document_loaders import DirectoryLoader, TextLoader, UnstructuredMarkdownLoader
from langchain_text_splitters import RecursiveCharacterTextSplitter
from src.memory.manager import memory_manager
from src.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class KnowledgeIngestor:
    """
    Processes local files and injects them into the AIManager memory ecosystem.
    """

    def __init__(self):
        self.memory = memory_manager
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=1000,
            chunk_overlap=100
        )

    def ingest_directory(self, path: str):
        """
        Loads all text/markdown files from a directory.
        """
        if not os.path.exists(path):
            logger.error(f"Path does not exist: {path}")
            return

        logger.info(f"Ingesting documents from {path}...")
        
        # 1. Load files
        loader = DirectoryLoader(path, glob="**/*.md", loader_cls=UnstructuredMarkdownLoader)
        docs = loader.load()
        
        if not docs:
            # Try plain text if no markdown
            loader = DirectoryLoader(path, glob="**/*.txt", loader_cls=TextLoader)
            docs = loader.load()

        logger.info(f"Found {len(docs)} documents.")

        # 2. Split into chunks
        chunks = self.splitter.split_documents(docs)
        logger.info(f"Created {len(chunks)} semantic chunks.")

        # 3. Store in ChromaDB
        for i, chunk in enumerate(chunks):
            self.memory.store(
                text=chunk.page_content,
                role="document",
                session_id="bulk_import",
                metadata={
                    "source": chunk.metadata.get("source", "unknown"),
                    "type": "ingested_file"
                }
            )
            if i % 10 == 0:
                logger.info(f"Progress: {i}/{len(chunks)} chunks stored.")

        logger.info("Bulk ingestion complete!")

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python -m src.tools.ingest <directory_path>")
    else:
        ingestor = KnowledgeIngestor()
        ingestor.ingest_directory(sys.argv[1])
