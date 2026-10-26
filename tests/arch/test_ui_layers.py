"""I82: streamlit is imported by exactly one module, the page, and the page renders only escaped HTML."""

import grimp
import pytest

from tests.support.guards import PACKAGE_NAME
from tests.support.paths import SRC

pytestmark = pytest.mark.arch

PAGE = "bio_claim_check.app.ui.page"


def test_the_page_is_the_only_module_that_imports_streamlit() -> None:
    graph = grimp.build_graph(PACKAGE_NAME, include_external_packages=True, cache_dir=None)
    assert graph.find_modules_that_directly_import("streamlit") == {PAGE}


def test_the_page_never_lets_markdown_or_unescaped_html_through() -> None:
    text = (SRC / "bio_claim_check" / "app" / "ui" / "page.py").read_text(encoding="utf-8")
    assert "unsafe_allow_html" not in text
    assert "st.markdown" not in text
    assert "components.html" not in text
