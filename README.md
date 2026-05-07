# AIManager

Run the platform locally with:

```bash
venv/Scripts/python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload
```

Then open:

- `http://127.0.0.1:8000/` for the platform shell
- `http://127.0.0.1:8000/apps/explorer` for the current Explorer app

Run the active test suite with:

```powershell
venv\Scripts\python -m pytest -q
```

Default pytest collection is intentionally limited to `tests/` so archival
files under `backup/` do not affect normal verification.
