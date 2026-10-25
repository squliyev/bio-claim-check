"""The model-family vocabulary is closed: stored reports and the catalogue validate against these values."""

import pytest

from bio_claim_check.common.model_family import ModelFamily

pytestmark = pytest.mark.unit


def test_the_vocabulary_is_locked() -> None:
    assert [f.value for f in ModelFamily] == ["openai", "anthropic", "moonshot", "google", "xai"]
