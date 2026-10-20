"""[RING:root] bio-claim-check: does this agent's answer hold up?

The package is organised in rings that point inward (ADR 0002):
``common <- engine <- features <- infrastructure <- app``. Only ``app`` wires concrete classes together.
"""

from importlib.metadata import version

__version__ = version("bio-claim-check")
