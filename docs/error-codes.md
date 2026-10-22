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
| 7 | `DATASET` | The dataset folder is not intact (seal, hashes, splits, counts or audits) |

## Error codes

Every error the package raises on purpose derives from `BccError` (`common/errors.py`) and carries one
stable code. Which exit code a command uses for an error depends on the command (for example a
`StrictYamlError` reaches the CLI wrapped in a `RulePackError` or `CorpusSpecError`); the commands map them.

| Code | Class | Raised when |
|---|---|---|
| `app.dataset_read` | `DatasetReadError` | The dataset folder, or a file in it, cannot be read |
| `app.missing_provider` | `MissingProviderError` | A live LLM role has no provider settings |
| `app.output_conflict` | `OutputConflictError` | An output file exists with different bytes, or cannot be written |
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
| `llm.unknown_deployment` | `UnknownDeploymentError` | A deployment name is not in the model catalogue |
| `prompts.render` | `PromptRenderError` | Template placeholders and variables differ |
| `retrieval.failed` | `RetrievalError` | The literature database failed or sent a malformed response |
| `retrieval.malformed_record` | `MalformedRecordError` | A record field has a type the API was not seen to return |
