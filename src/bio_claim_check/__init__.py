"""[RING:root] bio-claim-check: does this agent's answer hold up?

The package is organised in rings that point inward (ADR 0002):
``common <- engine <- features <- infrastructure <- app``. Only ``app`` wires concrete classes together.
This module only exposes ``__version__``; it must not hold logic or re-export anything.
"""

from importlib.metadata import version

__version__ = version("bio-claim-check")
