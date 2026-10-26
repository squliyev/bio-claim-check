# Exit codes and error codes

This table is curated: `tests/arch/test_error_codes.py` fails if a code below is missing from the code, or
a code in the code is missing below (invariant I49). A published code never changes meaning; a retired one
stays listed as retired.

## Exit codes (`bio-claim-check`)

| Exit | Name | Meaning |
|---|---|---|
| 0 | — | Success |
| 2 | `INPUT` | Bad arguments or configuration |
| 3 | `CACHE_MISS` | `BCC_CACHE_MODE=read-only` and the request is not in the cache |
| 4 | `UPSTREAM` | The literature database (Europe PMC) failed |
| 5 | `LOCAL_CACHE` | The cache file cannot be opened, read or written |
| 6 | `OUTPUT` | An output file exists with different bytes or cannot be written (a run file, the event trace, the ledger); nothing is overwritten |
| 7 | `DATASET` | The dataset folder is not intact (seal, hashes, splits, counts or audits), or `answer dev` found no usable source of the dev pool |
| 8 | `PROVIDER` | An LLM provider call failed or returned an unusable answer, or the live-call budget is spent (`llm ping`, `answer dev`; the error code is printed) |

## Error codes

Every error the package raises on purpose derives from `BccError` (`common/errors.py`) and carries one
stable code. Which exit code a command uses for an error depends on the command (for example a
`StrictYamlError` reaches the CLI wrapped in a `RulePackError` or `CorpusSpecError`); the commands map them.

| Code | Class | Raised when |
|---|---|---|
| `agent.declaration` | `AgentDeclarationError` | An LLM agent class misdeclares `name`, `prompt` or `output`, or overrides `run` (a bug) |
| `answer.dataset` | `DevDatasetError` | `answer dev` refused: the dataset is not intact and sealed; nothing was fetched |
| `answer.dev_input` | `DevAnswerInputError` | `answer dev` refused: the question is unknown or not in the dev split; nothing was fetched (I64) |
| `answer.empty_pool` | `EmptyDevPoolError` | No paper of the question's dev pool came back usable (missing or edited since the build); nothing was answered |
| `answer.invalid_claims` | `AnswerClaimsError` | An LLM answer has a claim with blank text, no cites, a duplicate cite or a malformed source id; refused, never repaired (I61) |
| `app.dataset_read` | `DatasetReadError` | The dataset folder, or a file in it, cannot be read |
| `app.freeze` | `FreezeError` | This code is not the active frozen judge (ADR 0020), so a test-split audit is refused |
| `app.judge_read` | `JudgeReadError` | A judge file (ADR 0020) is missing from the installed package |
| `app.missing_provider` | `MissingProviderError` | A live LLM role has no provider settings |
| `app.output_conflict` | `OutputConflictError` | An output file exists with different bytes, or cannot be written |
| `app.unsupported_provider` | `UnsupportedProviderError` | A deployment whose provider has no adapter yet (Anthropic direct, Ollama) |
| `cache.failed` | `CacheError` | The cache cannot be opened or written |
| `cache.miss` | `CacheMissError` | Read-only cache mode and the key is absent |
| `cache.write_failed` | `CacheWriteError` | A live response could not be stored in the cache; the attempt is recorded as unmeasured (ADR 0018) |
| `check.input` | `CheckInputError` | `check`: the claim is blank, too long or has control characters, or the PMID is not 1 to 9 digits; refused before any request |
| `challenge.input` | `ChallengeInputError` | The challenge set is malformed, or an item is not a sealed dev pair; nothing was fetched (I72) |
| `challenge.pool` | `ChallengePoolError` | An item's source did not come back, with its sealed hash, in its dev pool |
| `config.strict_yaml` | `StrictYamlError` | A YAML file is ambiguous (duplicate keys, merges, implicit types) |
| `contracts.corpus_spec` | `CorpusSpecError` | A corpus spec cannot be loaded |
| `contracts.rule_pack` | `RulePackError` | A rule pack cannot be loaded |
| `corpus.audit_input` | `AuditInputError` | The dataset, kind or cache cannot support an audit |
| `corpus.audit_sheet` | `AuditSheetError` | A filled-in audit sheet breaks the audit rules |
| `corpus.pool_conflict` | `PoolConflictError` | One source came back with different metadata under two questions |
| `events.write` | `EventWriteError` | A run's event trace cannot be created, written or closed (ADR 0018) |
| `files.append` | `AppendError` | A line cannot be appended to the run ledger; the file is truncated back to its previous length |
| `files.publish` | `PublishError` | A file cannot be published without losing or corrupting data |
| `files.read` | `ReadError` | A file cannot be read as UTF-8 text |
| `llm.budget_exceeded` | `LlmBudgetExceededError` | The command already made `BCC_MAX_LIVE_LLM_CALLS` live LLM calls; the next one was refused before it was sent (I68) |
| `llm.call_failed` | `LlmCallError` | A structured LLM call produced no usable output |
| `llm.processor_contract` | `ProcessorContractError` | A pipeline processor changed a field the runner owns (a bug) |
| `llm.prompt_filtered` | `LlmPromptFilteredError` | The provider's content filter rejected the prompt (HTTP 400); recorded as an unmeasured, content-filtered call |
| `llm.provider_rejected` | `LlmProviderError` | The provider refused the request permanently (auth, not found, bad request); never retried |
| `llm.transport` | `LlmTransportError` | The provider could not be reached, or kept failing transiently, after the bounded retries |
| `llm.unexpected_response` | `LlmUnexpectedResponseError` | A provider response in a shape the codec does not know (fail closed) |
| `llm.unknown_deployment` | `UnknownDeploymentError` | A deployment name is not in the model catalogue |
| `llm.unsupported_request` | `LlmRequestError` | A request the backend cannot send faithfully (unknown param, a seed, a non-strict schema, an invalid tool name) |
| `prompts.render` | `PromptRenderError` | Template placeholders and variables differ |
| `retrieval.failed` | `RetrievalError` | The literature database failed or sent a malformed response |
| `retrieval.malformed_record` | `MalformedRecordError` | A record field has a type the API was not seen to return |
| `retrieval.not_citable` | `NotCitableError` | `fetch`: the record exists but is not a citable paper (no abstract, a letter, …); the reason is named |
| `retrieval.not_found` | `PaperNotFoundError` | `fetch`: the literature database holds no record for the id |
| `run.input` | `RunInputError` | `run`: the question is blank or `k` is not a positive int |
| `runs.busy` | `RecordBusyError` | Another recorded `run` or `check` is in progress in this process (the UI); nothing was recorded |
| `runs.published` | `PublishedRunError` | A published run's id is malformed, or the run is missing, altered (hash chain), or not a `run`/`check` this build can show |
| `retractions.input` | `RetractionInputError` | `retractions`: the run id is malformed, or the run is missing, altered, not a live `run`, or not a report (checked before any request) |
| `traps.audit_sheet` | `TrapAuditError` | A filled-in trap audit sheet was made from another draft, or has an added, missing, duplicated, edited or undecided row, or a rejection without a reason |
| `traps.budget` | `TrapBudgetError` | `BCC_MAX_LIVE_LLM_CALLS` cannot cover a call and a repair per trap draft or trap item; refused before any call |
| `traps.checkpoint` | `CheckpointError` | The ADR 0024 go/adjust rule was asked of a result that is not dev-v1 with its predeclared denominators (15 model traps, 16 parents, 38 items); it fails closed |
| `traps.infeasible` | `TrapSamplingError` | A scored kind has no eligible dev source at all; nothing was drafted (a kind with fewer sources than `--per-kind` gets all it has, and the run reports the shortfall) |
| `traps.input` | `TrapInputError` | The dataset is not sealed, a trap draft is edited or empty, or a trap set breaks I76/I77/I79 (non-dev question or source, changed hash, missing parent, contamination, not canonical; a panel without two registered raters of separate families, one sheet each, or a set its ledger does not attest) |
| `traps.pool` | `TrapPoolError` | A sampled or committed trap source did not come back, with its sealed hash, in its dev pool |
| `verdict.negation_rules_mismatch` | `NegationRulesMismatchError` | A stored verdict was made under other negation rules; re-run it rather than re-score it (ADR 0017) |
