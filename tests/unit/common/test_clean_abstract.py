"""`clean_abstract`: Europe PMC markup -> the one text every stage uses.

Cases come from the S03 tag inventory of 300 real Europe PMC abstracts (tag names, entities and
characters only; see docs/dev-log/S03.md) plus the pipeline steps in ADR 0005.
"""

import pytest

from bio_claim_check.common.text import clean_abstract

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        pytest.param(None, "", id="none"),
        pytest.param("", "", id="empty"),
        pytest.param("   \n\t ", "", id="only-whitespace"),
        # block tags -> space (never glue a heading to the next word)
        pytest.param("<h4>Background</h4>Metformin is", "Background Metformin is", id="glued-h4"),
        pytest.param("<H4 class='x'>Methods</H4>We", "Methods We", id="upper-case-tag-with-attrs"),
        pytest.param("<p>one</p><p>two</p>", "one two", id="paragraphs"),
        pytest.param("a<br/>b<br />c", "a b c", id="self-closing-br"),
        pytest.param("<title>T</title>x", "T x", id="title"),
        pytest.param("<jats:p>a</jats:p>b", "a b", id="namespaced-block"),
        pytest.param("<abstract><sec>a</sec><sec>b</sec></abstract>", "a b", id="sec-abstract"),
        # inline tags -> removed
        pytest.param("<i>in vivo</i> data", "in vivo data", id="italic"),
        pytest.param("<b>Results:</b> fell", "Results: fell", id="bold-b"),
        pytest.param("<bold>Results</bold>: fell", "Results: fell", id="bold-jats"),
        pytest.param("IC<sub>50</sub> of", "IC50 of", id="sub-inline"),
        pytest.param("<span lang='en'>x</span>y", "xy", id="inline-with-attrs"),
        pytest.param("a<!-- hidden <p> -->b", "ab", id="comment"),
        # superscripts keep their meaning as ^
        pytest.param("10<sup>5</sup> cells", "10^5 cells", id="sup-digits"),
        pytest.param("10<sup>&minus;6</sup> M", "10^-6 M", id="sup-entity-minus"),
        pytest.param("10<sup>\u22126</sup> M", "10^-6 M", id="sup-unicode-minus"),
        pytest.param("Ink4a<sup>-/-</sup> mice", "Ink4a^-/- mice", id="sup-genotype"),
        pytest.param("Na<SUP>+</SUP>", "Na^+", id="sup-charge-uppercase-tag"),
        pytest.param("x<sup>-<i>9</i></sup>", "x^-9", id="sup-with-inner-tag"),
        pytest.param("10<jats:sup>5</jats:sup> cells", "10^5 cells", id="sup-namespaced"),
        pytest.param("10<jats:sup>&#8722;6</jats:sup>", "10^-6", id="sup-namespaced-negative"),
        pytest.param("Ink4a<mml:sup>-/-</mml:sup>", "Ink4a^-/-", id="sup-namespaced-genotype"),
        pytest.param("<sup class=\"x\" id='y'>2</sup>", "^2", id="sup-valued-attrs"),
        pytest.param("x<y>z", "x<y>z", id="unknown-tag-stays-literal"),
        pytest.param("a <b and c> d", "a <b and c> d", id="tag-like-prose-stays-literal"),
        pytest.param("p<q and r>0", "p<q and r>0", id="comparison-prose-stays-literal"),
        pytest.param("<i>a</i><foo:bar>b", "a<foo:bar>b", id="unknown-namespaced-stays-literal"),
        pytest.param("<span lang>x</span>", "<span lang>x", id="valueless-attr-is-not-a-tag"),
        pytest.param("10\u207b\u2076 M", "10^-6 M", id="unicode-superscript-run"),
        pytest.param("Na\u207a and cm\u00b2", "Na^+ and cm^2", id="unicode-superscript-charge-square"),
        pytest.param("x\u00b9\u00b2", "x^12", id="superscript-run-is-one-caret"),
        pytest.param("C\u2085\u2080", "C50", id="unicode-subscript-digits"),
        # entities are unescaped AFTER tags are stripped
        pytest.param("p &lt; 0.05", "p < 0.05", id="lt-entity"),
        pytest.param("&lt;i&gt;x&lt;/i&gt;", "<i>x</i>", id="escaped-tag-stays-literal"),
        pytest.param("Alzheimer&#x2019;s and &rsquo;", "Alzheimer\u2019s and \u2019", id="apostrophes"),
        pytest.param("&beta;-amyloid &#x03B2;", "\u03b2-amyloid \u03b2", id="beta-entities"),
        pytest.param("&copy; 2024", "\u00a9 2024", id="copyright"),
        # characters
        pytest.param("inhi\u00adbition", "inhibition", id="soft-hyphen-removed"),
        pytest.param("cafe\u00ad\u0301", "caf\u00e9", id="soft-hyphen-removed-before-nfkc-composes"),
        pytest.param("drug\u200bresponse", "drug response", id="zwsp-is-space"),
        pytest.param("a\ufeffb\u200ec", "a b c", id="bom-and-bidi-are-space"),
        pytest.param("10\u00a0mg", "10 mg", id="nbsp"),
        pytest.param("10\u2009mg and 5\u202fmg and 3\u2005mg", "10 mg and 5 mg and 3 mg", id="thin-spaces"),
        pytest.param("GLP\u20111 and GLP\u20101", "GLP-1 and GLP-1", id="unicode-hyphens"),
        pytest.param("1\u20135 mg", "1-5 mg", id="en-dash"),
        pytest.param("\u221212.5%", "-12.5%", id="minus-sign"),
        pytest.param("a\uff0db\ufe63c", "a-b-c", id="fullwidth-and-small-hyphen"),
        pytest.param("reduced\u2014growth", "reduced growth", id="em-dash-is-prose"),
        pytest.param("a\u2015b", "a b", id="horizontal-bar"),
        pytest.param("\u223c50%", "~50%", id="tilde-operator"),
        pytest.param("\u00b5M", "\u03bcM", id="micro-sign-to-mu"),
        pytest.param("\ufb01brosis", "fibrosis", id="ligature"),
        pytest.param("a \n\n  b", "a b", id="whitespace-collapse"),
        pytest.param(
            "\u2265 2 and \u00b1 1 and \u00d7 3", "\u2265 2 and \u00b1 1 and \u00d7 3", id="operators-kept"
        ),
    ],
)
def test_clean_abstract(raw: str | None, expected: str) -> None:
    assert clean_abstract(raw) == expected


def test_lone_less_than_is_not_a_tag() -> None:
    assert clean_abstract("p<0.05 and a <b") == "p<0.05 and a <b"


def test_double_escaped_entities_are_the_documented_idempotence_exception() -> None:
    once = clean_abstract("&amp;lt;b&amp;gt;x")
    assert once == "&lt;b&gt;x"
    assert clean_abstract(once) == "<b>x"
