# Ingestion — Bulk Data Import Pipeline

Imports external data files (JSONL, plaintext, Telegram exports) into ChromaDB
so the analyzer pipeline can process them. Not involved in real-time conversation
storage — that path goes directly through `MemoryManager.store()`.

## Files
| File | Role |
|------|------|
| `bulk_importer.py` | `BulkImporter` — orchestrates directory/file imports, calls `MemoryManager.store()` in bulk |
| `chunker.py` | `chunk_text()` — splits large documents into overlapping segments |
| `formats/plaintext.py` | Parser for `.txt` files |
| `formats/telegram.py` | Parser for Telegram JSON export format |

---

## Called By
| Caller | What it uses |
|--------|-------------|
| `src.apps.explorer.services` | `BulkImporter` — instantiated in `run_bulk_import()`, called from `POST /api/explorer/ingest/bulk` |

---

## Calls Into
| Dependency | What is imported |
|------------|-----------------|
| `src.memory.manager` | `MemoryManager` — calls `memory.store()` for each chunk |
| `src.ingestion.chunker` | `chunk_text()` — used by `BulkImporter` to split documents |
| `src.core.config` | `settings` — chunk size defaults |

---

## Public API

### `bulk_importer.py`
```python
@dataclass
class BulkImportResult:
    imported: int
    skipped: int
    errors: list[str]
    source_path: str

class BulkImporter:
    def __init__(memory: MemoryManager)

    async def import_jsonl(path: str, **metadata) -> BulkImportResult
    # Each line must be {"text": str, ...optional metadata fields}

    async def import_directory(
        path: str,
        chunk_size: int = 1000,
        overlap: int = 100,
        **metadata,
    ) -> BulkImportResult
    # Recursively imports all supported files in a directory.
    # After import, the caller (explorer services) triggers run_extraction_pass()
    # to drain the newly queued rows.
```

### `chunker.py`
```python
def chunk_text(text: str, chunk_size: int = 1000, overlap: int = 100) -> list[str]:
    """Split text into overlapping chunks for embedding storage."""
```

---

## Coupling Notes
- `BulkImporter` only calls `memory.store()` — it writes to Chroma but never
  writes to Neo4j directly. The Neo4j graph is populated later by the analyzer
  pipeline (`graph_ingest_trigger.run_extraction_pass`).
- After `import_directory` completes, `explorer/services.py` loops
  `run_extraction_pass()` until the queue is empty (50-batch safety cap).
- Format parsers in `formats/` are pure functions — they take a file path and
  return `list[dict]` records. Add new formats by creating a new file there and
  importing it in `BulkImporter._detect_format()`.
- `BulkImporter` does **not** deduplicate — if you import the same file twice,
  you get double entries in Chroma. Dedup is handled at the canonicalization
  stage in the analyzer.
