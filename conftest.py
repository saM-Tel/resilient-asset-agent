"""
Root-level pytest configuration.

Ensures the repository root is on ``sys.path`` so test modules can import
top-level packages (``agent``, ``stubs``) regardless of the directory pytest
is invoked from.

Without this, running ``pytest tests/`` from a clean checkout (e.g. in GitHub
Actions) fails with ``ModuleNotFoundError: No module named 'agent'`` because
pytest only inserts the ``tests/`` directory (which has no ``__init__.py``)
onto the path. Placing a ``conftest.py`` at the repo root makes pytest prepend
the root directory to ``sys.path`` automatically.
"""

import sys
from pathlib import Path

# Insert the repository root (the directory containing this file) at the front
# of sys.path so that `import agent` / `import stubs` resolve in CI and locally.
_REPO_ROOT = str(Path(__file__).resolve().parent)
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)
