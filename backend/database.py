"""Root entrypoint for database management. Forwards to tools.database."""

import sys
from pathlib import Path

_backend = str(Path(__file__).resolve().parent)
if _backend not in sys.path:
    sys.path.insert(0, _backend)

from tools.database import main

if __name__ == "__main__":
    main()
