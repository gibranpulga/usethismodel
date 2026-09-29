"""Container health probe using Python's standard library."""

import os
import urllib.request

with urllib.request.urlopen(
    f"http://127.0.0.1:{int(os.environ.get('PORT', '8000'))}/health", timeout=5
) as response:
    if response.status != 200:
        raise SystemExit(1)
