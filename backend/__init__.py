"""RollCall AI Backend Package.

Provides core FastAPI backend API, AI Agent pipeline, database layer, and tools.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Automatically ensure backend directory is prepended to sys.path
_BACKEND_DIR = str(Path(__file__).resolve().parent)
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

