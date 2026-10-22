"""[TEST SUPPORT] The one way tests build a `Settings` object without reading the environment.

`Settings.model_validate` validates the given values only: no `.env` file and no `BCC_*` variables are
read, so a developer's shell can never change a test (the autouse `_isolate_env` fixture in
`tests/conftest.py` already scrubs both for code paths that do read them, such as the CLI).
Overrides replace defaults key by key, so `make_settings(contact_email=...)` is allowed.
"""

from bio_claim_check.app.settings import Settings

TEST_CONTACT_EMAIL = "someone@example.org"


def make_settings(**overrides: object) -> Settings:
    """Valid settings with a fake contact address; any field can be overridden."""
    values: dict[str, object] = {"contact_email": TEST_CONTACT_EMAIL}
    values.update(overrides)
    return Settings.model_validate(values)
