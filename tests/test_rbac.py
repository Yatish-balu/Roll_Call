"""Forwarding test runner to backend/tests/test_rbac.py (Ticket RC-RBAC-002)."""
import sys
from pathlib import Path

_backend_dir = str(Path(__file__).resolve().parent.parent / "backend")
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from tests.test_rbac import *

