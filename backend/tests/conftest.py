from __future__ import annotations

import os

# Tests never talk to real services unless an integration fixture says so.
os.environ.setdefault("CORTEX_ENV", "test")
os.environ.setdefault("CORTEX_LOG_LEVEL", "WARNING")
