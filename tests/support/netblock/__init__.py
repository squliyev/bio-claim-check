"""[TEST SUPPORT] Offline tests open no internet sockets (invariant I31).

`sitecustomize.py` in this directory does the blocking. The root conftest applies it to every test that is
not marked `live`, and puts this directory on `PYTHONPATH`, so Python subprocesses block too: Python
imports `sitecustomize` at startup. A subprocess given an explicit `env` must pass `NETBLOCK_DIR` itself.
"""

from pathlib import Path

NETBLOCK_DIR = Path(__file__).resolve().parent
