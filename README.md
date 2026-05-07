# AIManager

Run the Explorer API locally with:

```powershell
venv\Scripts\python -m uvicorn src.main:app --host 127.0.0.1 --port 8000 --reload
```

Run the active test suite with:

```powershell
venv\Scripts\python -m pytest -q
```

Default pytest collection is intentionally limited to `tests/` so archival
files under `backup/` do not affect normal verification.
