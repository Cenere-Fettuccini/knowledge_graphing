"""Root conftest — ensures the project root is on sys.path.

pytest automatically discovers conftest.py files.  By placing one at the
repository root, the ``src`` package becomes importable from every test
without needing ``pip install -e .`` or manual PYTHONPATH hacks.
"""

import sys
from pathlib import Path

# Add the project root so `import src.*` works in every test module.
_PROJECT_ROOT = str(Path(__file__).resolve().parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
