# Pilot records

Per-item records of the pre-declared dev pilots. Dev split only; no test abstract was read. No abstract
text is stored (publisher copyright): fetch the record by its id to check a decision.

## `background_as_result-dev-v1.csv`

- **What:** every dev candidate of the `background_as_result` kind (sieve v2, rule `prior_finding`),
  18 in total, in the public audit order (salt `bio-claim-check/audit/v1`, ADR 0010).
- **Criterion (pre-declared, roadmap §16.9 E3):** a candidate is confirmed when the paper's **own results
  do not establish** the background statement in its cue sentence. Then a claim that presents the
  background as this paper's finding is a fair trap.
- **Rule (pre-declared):** precision below 60 % drops the kind from scoring; the sieve is never
  regex-tweaked to pass.
- **Judge:** one AI agent (the coding agent that built the session), reading the full dev abstracts.
  The author did not review the items. Single judge, no agreement measured.
- **Date:** 2026-10-21.
- **Result:** 12 confirmed, 6 rejected: **12/18 = 67 %, Wilson 95 % CI 0.44–0.84**. Above the
  threshold, so the kind stays; the interval is wide and its lower bound is below 60 %.
- **Supersedes:** an earlier tally from the same session (16/18) that was never recorded per item.
  It is withdrawn; this file is the only pilot result.
- **Rejections:** five are papers whose own cohort, case-control, animal or in vitro results confirm
  the background effect they cite. One (order 13) is a survival study whose own results show the
  protective effect. The real measurement is the test audit after the prompt freeze.
