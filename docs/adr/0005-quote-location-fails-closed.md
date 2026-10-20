# ADR 0005 — Quote location fails closed; no fuzzy pass

- **Status:** Accepted
- **Date:** 2026-10-21
- **Supersedes / Extends:** —
- **Related:** 0003
- **Enforced by:** `tests/unit/common/test_locate_quote.py::test_behaviour_table` (rules L1–L31; L15 has its own test), the oracle properties in `tests/unit/common/test_text_properties.py`, and the `make cov-core` gate (100% branch coverage of `common` and `features.contracts`, also a CI step; renamed from `cov-common` in S04).

## Context

A verdict of *supported* is only as good as the proof that the quoted evidence is in the cited abstract.
A wrong match turns a misreading into a *supported* label, which is the failure this project exists to
catch. Two shortcuts look attractive and both are wrong:

- **One regex that joins words with "any punctuation".** It lets `1.5` match `15`, `0.05` match inside
  `0.005`, `= 0.05` match `<= 0.05`, and `0.5` match `-0.5`.
- **A fuzzy score as a pass.** A partial-ratio score passes flipped meanings: "reduced" → "increased"
  and an inserted "not" both score above 90.

The cleaner also matters: if `10<sup>5</sup>` becomes `105`, cleaning itself has changed a number.

## Decision

- **`clean_abstract`** produces the one text the model reads, the checks match against and the UI
  highlights:
  - Only **known** tags are stripped (an allow-list of local names, with an optional namespace prefix
    such as `jats:`, and attributes that carry values). Block tags become a space; inline tags are
    removed; `<sup>x</sup>` (also `<jats:sup>`) becomes `^x`. Anything else that looks like a tag
    (`x<y>z`, `a <b and c> d`) stays literal text, so cleaning never deletes prose.
  - Entities are unescaped only after tag stripping, so an escaped `&lt;i&gt;` stays literal.
  - Unicode superscript runs become one `^` plus the plain run.
  - Format characters: soft hyphen removed, others become a space. This happens **before** NFKC, so
    cleaning is idempotent (except for double-escaped entities).
  - NFKC, dash normalisation (hyphens, en dash, minus → `-`; em dash → space; `∼` → `~`), whitespace
    collapse.
- **`locate_quote`** cuts quote and text into the same tokens and requires the quote's tokens to be a
  contiguous run of the text's tokens, compared **exactly, case included**:
  - Number: one token, with its sign (when not after a word character), verbatim separators
    (`1,000` ≠ `1.000` ≠ `1000`) and its exponent (`1e-5`).
  - Symbol: `<= >= != ==` as one token each, and **every other non-space symbol** as its own token
    (`< > ≤ ≥ = ± × ^ % + - / ~ ≈ ° & …`). Charges (`Na+`), ratios (`Na/K`), units (`°C`) are evidence;
    an unknown symbol fails closed instead of being ignored.
  - Word: `\w+`. Identifier hyphens are kept, so `IL 6` does not match `IL-6`.
  - Only prose punctuation is ignored: `. , ; : ! ?`, brackets and quote marks.
  - **Whole expressions only:** no text token may touch either end of the match. `5 mg` is not found
    in `5 mg/kg`, `5 cells` not in `10^5 cells`, `1 receptor` not in `GLP-1 receptor`, `ER+` not in
    `ER+/-`. Brackets and spaces separate, so `p < 0.05` is found in `(p < 0.05).`.
  - Offsets are Python code points. The first occurrence wins.
- **`near_match`** (rapidfuzz `partial_ratio_alignment`, score ≥ 90, quotes of ≥ 3 tokens) only routes
  a claim to *needs review*. It can never make evidence located.
- **rapidfuzz is a core-allowed dependency:** a pure, typed function with no I/O.

## Consequences

- **Positive:** a located span is exact, so the highlight is the proof. The rules are one readable
  table.
- **Negative (accepted, fail closed):** a case-only difference, a dropped identifier hyphen or a
  transliteration (`β2` vs `beta2`) is not located. It goes to near → *needs review*, not *supported*.
- **Known limit:** location is provenance, not meaning. `significant reduction` is located inside
  `no significant reduction` (row L18). This is handled downstream: S10 adds a negation-context check,
  and the S04 disposition maps *supported* with a negated span to *needs review*.
- **Known cost:** the tag regexes are quadratic on pathological input (tens of thousands of unclosed
  `<sup>` tags in one string). Real abstracts are a few thousand characters, so this is accepted.
- **Follow-ups:** tune the near threshold on dev data only (S12). Run the cleaner over 100 real
  abstracts once retrieval exists (S06).
