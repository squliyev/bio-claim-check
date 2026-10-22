"""[RING:engine/agent] The agent package's typed failure.

Why: a misdeclared agent is a programming error that must fail loudly at construction, before any
provider call, with a stable code (I49).
Must not: carry payloads or prompt text.
"""

from bio_claim_check.common.errors import BccError


class AgentDeclarationError(BccError, TypeError):
    """An agent class misdeclares `name`, `prompt` or `output`, or overrides `run` (a bug, not input)."""

    code = "agent.declaration"
