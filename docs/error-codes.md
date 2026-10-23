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
| 6 | `OUTPUT` | An output file exists with different bytes or cannot be written; nothing is overwritten |
| 7 | `DATASET` | The dataset folder is not intact (seal, hashes, splits, counts or audits), or `answer dev` found no usable source of the dev pool |
| 8 | `PROVIDER` | An LLM provider call failed or returned an unusable answer (`llm ping`, `answer dev`; the error code is printed) |

## Error codes

Every error the package raises on purpose derives from `BccError` (`common/errors.py`) and carries one
stable code. Which exit code a command uses for an error depends on the command (for example a
`StrictYamlError` reaches the CLI wrapped in a `RulePackError` or `CorpusSpecError`); the commands map them.

| Code | Class | Raised when |
|---|---|---|
| `agent.declaration` | `AgentDeclarationError` | An LLM agent class misdeclares `name`, `prompt` or `output`, or overrides `run` (a bug) |
| `answer.dev_input` | `DevAnswerInputError` | `answer dev` refused: the dataset is not intact and sealed, or the question is unknown or not in the dev split; nothing was fetched (I64) |
| `answer.empty_pool` | `EmptyDevPoolError` | No paper of the question's dev pool came back usable (missing or edited since the build); nothing was answered |
| `answer.invalid_claims` | `AnswerClaimsError` | An LLM answer has a claim with blank text, no cites, a duplicate cite or a malformed source id; refused, never repaired (I61) |
| `app.dataset_read` | `DatasetReadError` | The dataset folder, or a file in it, cannot be read |
| `app.missing_provider` | `MissingProviderError` | A live LLM role has no provider settings |
| `app.output_conflict` | `OutputConflictError` | An output file exists with different bytes, or cannot be written |
| `app.unsupported_provider` | `UnsupportedProviderError` | A deployment whose provider has no adapter yet (Anthropic direct, Ollama) |
| `cache.failed` | `CacheError` | The cache cannot be opened or written |
| `cache.miss` | `CacheMissError` | Read-only cache mode and the key is absent |
| `config.strict_yaml` | `StrictYamlError` | A YAML file is ambiguous (duplicate keys, merges, implicit types) |
| `contracts.corpus_spec` | `CorpusSpecError` | A corpus spec cannot be loaded |
| `contracts.rule_pack` | `RulePackError` | A rule pack cannot be loaded |
| `corpus.audit_input` | `AuditInputError` | The dataset, kind or cache cannot support an audit |
| `corpus.audit_sheet` | `AuditSheetError` | A filled-in audit sheet breaks the audit rules |
| `corpus.pool_conflict` | `PoolConflictError` | One source came back with different metadata under two questions |
| `files.publish` | `PublishError` | A file cannot be published without losing or corrupting data |
| `files.read` | `ReadError` | A file cannot be read as UTF-8 text |
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
| `verdict.negation_rules_mismatch` | `NegationRulesMismatchError` | A stored verdict was made under other negation rules; re-run it rather than re-score it (ADR 0017) |
