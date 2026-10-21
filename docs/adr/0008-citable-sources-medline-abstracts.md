# ADR 0008 — Citable sources: MEDLINE abstracts, identity `MED:<pmid>`

- **Status:** Accepted
- **Date:** 2026-10-20
- **Supersedes / Extends:** —
- **Related:** 0006, 0007, 0009
- **Enforced by:** `tests/unit/features/test_europe_pmc_literature_source.py::test_a_hostile_query_cannot_admit_an_uncitable_record` · `tests/unit/features/test_citable.py` · `tests/contract/test_literature_source_contract.py::test_real_ids_are_medline_ids` · `tests/live/test_europe_pmc_live.py` (`make live`, opt-in)

## Context

Every verdict compares a claim with the abstract of the paper it cites. If retrieval can return a
notice, an editorial, a record without an abstract or a non-English record, the verifier is asked to
judge a claim against text that was never a finding. If the same paper can appear under two ids, a claim
can be "not retrieved" while the paper sits in the list. The source and the identity have to be fixed
before any number is produced.

Europe PMC's REST search returns MEDLINE records alongside preprints, patents, agricultural records and
full-text-only PMC records. The search filters are convenient but are part of the query string the user
also writes, so they cannot be the guarantee.

## Decision

- **Source:** Europe PMC REST search (`resultType=core`), MEDLINE records only (`source == "MED"`).
  We describe them as **MEDLINE/PubMed-indexed abstracts**, never as "peer-reviewed".
- **Identity:** `MED:<pmid>`, with the PMID ASCII digits only. Results are de-duplicated on it; the first
  (highest-ranked) record wins.
- **The rule is `is_citable`, applied to every record after the response arrives:** `source == "MED"`,
  a numeric PMID, a non-blank title and abstract, `language == "eng"`, and no excluded publication type.
  Rejections are counted per reason (`RejectReason`) and logged. The same conditions are also sent as
  search filters (`SRC:MED AND HAS_ABSTRACT:y AND LANG:eng NOT PUB_TYPE:"…"`) to save bandwidth, but
  only the post-filter is trusted: a query such as `x) OR (SRC:PPR` cannot admit a preprint.
- **Excluded publication types** (notices and opinion, not findings): Retraction of Publication,
  Published Erratum, Comment, Editorial, Letter, News. Compared case-insensitively. **Reviews are kept**:
  they are legitimate background, and a claim citing a review is still checked against what it says.
  Every spelling matches real MEDLINE records (`make live`, 2026-10-20: from 21,178 hits for Retraction of
  Publication to 1,457,376 for Letter); a misspelt filter would silently exclude nothing.
- **Retracted papers are kept and marked** (`Paper.retracted`). A retraction is detected from the
  `Retracted Publication` publication type or a `Retraction in` comment/correction. Dropping them would
  turn "cites a retracted paper" into "cites a paper that was not retrieved", which hides the problem.
- **The query is Europe PMC search syntax by design** and is sent verbatim inside `(<query>) AND
  <filters>`. Control characters, blank queries and limits outside 1–100 are rejected with `ValueError`
  before any request.
- **Etiquette:** the REST API only (never the website), one sequential client, a `User-Agent` naming the
  tool and the user's contact address (`BCC_CONTACT_EMAIL`, never logged), timeouts (30 s, 10 s
  connect), deterministic back-off of 1, 2 and 4 s on 429/5xx and transport errors, `Retry-After`
  honoured up to 60 s, and a local cache (ADR 0009) so repeated runs make no requests.
- **Terms of use** (Europe PMC, read 2026-10-20): material is "protected by U.K. and/or foreign copyright
  laws", and users "are directly and solely responsible for compliance with copyright restrictions".
  "Crawlers and other automated processes may NOT be used to systematically retrieve batches of articles
  from the Europe PMC web site"; the RESTful web service is among "the only services that may be used for
  automated downloading". No rate limit is published. Consequences here: **no publisher text is
  committed** (fixtures are fictional; the cache lives in the git-ignored `var/`), and bulk use goes
  through the API with a throttle (S07).
- **NLM terms** (read 2026-10-21; amended in S07a, which closes the S06 open item). NLM data "include works
  of the United States Government that are not protected by U.S. copyright law [...] as well as abstracts
  originating from publications that may be protected by U.S. or non-US copyright law", and NLM "assumes
  no responsibility or liability associated with use of copyrighted material, including transmitting,
  reproducing, redistributing" (*Copyright Information & Downloading National Library of Medicine Data*).
  Users of the data agree to "acknowledge NLM as the source of the data [...] in a clear and conspicuous
  manner" and to "not indicate or imply that NLM has endorsed its products/services/applications"; those
  who redistribute agree to "maintain the most current version of all distributed data, or make known in
  a clear and conspicuous manner that the products/services/applications do not reflect the most
  current/accurate data available from NLM" (*NLM Terms and Conditions*). Consequences here: **abstract
  text is never committed or shipped**, only identifiers, NLM metadata (MeSH, publication types),
  character offsets and hashes; every shipped dataset carries "Courtesy of the U.S. National Library of
  Medicine", says NLM does not endorse it, and states that it is a dated snapshot that does not reflect
  the most current NLM data. This is a reading of published terms, not legal advice.
- **Credit:** abstracts and metadata come from Europe PMC (EMBL-EBI), which redistributes MEDLINE/PubMed
  data from the U.S. National Library of Medicine. Courtesy of the U.S. National Library of Medicine.

## Consequences

- **Positive:** every retrieved paper is a citable MEDLINE abstract with one stable id, whatever the
  query. The policy is one function with one test per reason.
- **Negative (accepted):** English-only biases the evidence base; non-MEDLINE literature (preprints,
  full-text-only PMC articles) is invisible. Both are stated in the report and the docs. Preprints are a
  possible opt-in tier after 1.0.
- **Negative (accepted):** the filter is applied after paging, so a page can hold fewer than `limit`
  citable papers. No `cursorMark` paging in S06.
- **Follow-ups:** throttle for bulk callers (S07); retraction re-check for cited papers on every live
  run, because the cache freezes retraction status (ADR 0009, S12).
