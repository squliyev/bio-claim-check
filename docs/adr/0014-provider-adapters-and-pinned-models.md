# ADR 0014 — Provider adapters: pure codecs, pinned models, deterministic retries

- **Status:** Accepted
- **Date:** 2026-10-22
- **Supersedes / Extends:** Extends 0012 (LLM engine) and 0007 (ports and backends)
- **Related:** 0002, 0004, 0009, 0013
- **Enforced by:** `tests/unit/engine/test_openai_responses_codec.py` · `tests/unit/engine/test_anthropic_messages_codec.py` · `tests/unit/engine/test_transport_policy.py` · `tests/unit/engine/test_llm_backends.py` · `tests/arch/test_llm_fixtures.py` · `tests/contract/test_llm_client_contract.py` · `tests/unit/app/test_build_llm_clients.py` · `tests/arch/test_dependency_policy.py` · `tests/arch/test_port_guards.py::test_only_backends_import_drivers` (codecs and `transport_policy` are not backends, so they may not import a driver)

## Context

Until S09 every call ran on scripted or cached clients. Real providers bring four risks: usage reported in
shapes that double-count or hide reasoning; finish states (filters, refusals, truncation) that quietly become
"stop"; SDK retries that are random, invisible and may bill twice; and request details (stored responses,
replayed reasoning, a silently dropped parameter) that make a run irreproducible. The answer and verifier
models must also be the exact models the maintainer approved.

## Decision

1. **A pure codec per API, a thin backend per provider.** `openai_responses_codec.py` and
   `anthropic_messages_codec.py` hold all provider knowledge as dict → dict functions (no driver import, no
   network; the I22 driver guard rejects a driver import there): request encoding, response decoding, usage and finish mapping. `openai_llm_client.py` and
   `anthropic_llm_client.py` only post the encoded body and apply the transport policy. Every raw shape is
   unit-tested without the SDK.
2. **Two surfaces, one Foundry resource.** gpt deployments use the Responses API at `<base>/openai/v1/`
   (structured output = strict `json_schema`, `store=false`). Claude deployments use `AnthropicFoundry` at
   `<base>/anthropic` (structured output = **one forced tool**, system prompt in `system`, no thinking).
   Both use the same key (`BCC_FOUNDRY__*`). `app/container.py::build_llm_clients` is the only place SDKs are
   built: `max_retries=0`, timeout 300 s, connect 10 s. Providers without an adapter (Anthropic direct,
   Ollama) fail at wiring with `app.unsupported_provider`.
3. **Nothing is sent that we cannot send faithfully.** Params are whitelisted (`max_output_tokens`,
   `temperature`, `reasoning_effort`); an unknown key, a `seed`, temperature together with reasoning effort,
   reasoning effort on Claude, a Claude call without an output budget, a non-strict schema (named by path)
   or an invalid tool name raise `llm.unsupported_request` before any call.
4. **Reasoning is never sent, stored or replayed.** No `previous_response_id`, item ids or `include`; no
   `thinking` block. Reasoning output items are skipped; a thinking block in a Claude reply fails closed.
5. **Usage normalisation (I52).** Responses: `input_tokens`, `cached_tokens` (missing → 0), `output_tokens`,
   `reasoning_tokens` (missing → `None`); a reported `total_tokens` must equal input + output.
   Messages: input = `input_tokens + cache_read_input_tokens + cache_creation_input_tokens`; cached = cache
   reads; reasoning = the reported `output_tokens_details.thinking_tokens`, else `None`.
6. **Finish mapping is total and fail-closed (I53).** Responses: `completed` → stop; `incomplete` for
   `max_output_tokens` → length, for `content_filter` → content_filter; any refusal part → content_filter.
   Messages: `tool_use`/`end_turn` → stop; `max_tokens` → length; `refusal` → content_filter. Anything else
   raises `llm.unexpected_response`. A Claude reply without the forced tool call decodes to empty text, which
   fails validation and earns the one counted repair; an `{"input": …}` wrapper is not unwrapped.
7. **Prompt filter.** An HTTP 400 with error code `content_filter` raises `llm.prompt_filtered`; the runner
   records an **unmeasured** call (no invented usage) and fails the call as `content_filtered`.
8. **Our own retries (I55).** `transport_policy.py` retries 408, 429, 500, 502, 503, 529 and a refused
   connection (`httpx2.ConnectError`: the request never left), after 1, 2 and 4 s, or the provider's
   `retry-after-ms` / `Retry-After` (capped at 60 s). A failure after the request may have reached the
   provider (a timeout, a connection dropped after sending, a gateway timeout 504) is never retried: the
   provider may have billed it. Errors carry status, attempts and the provider
   error code, never bodies. A 200 whose body is not JSON is `llm.unexpected_response`, with the decoder
   error (which holds the body) dropped. Sleep is injected.
9. **Pinned models.** `app/models.py`: `gpt-6.1-sol` → `model_version="2026-09-29"` (Foundry portal, GA);
   `claude-opus-4-8` → `model_version="claude-opus-4-8"` (the portal shows no separate version; the model id
   is the pin). Claude's `max_output_tokens=8192` is our budget, not a model limit. Prices stay `None`.
   `LlmResponse.served_model` records what the provider reports serving, as provenance outside the cache key.
10. **Fixtures (I56).** `tests/fixtures/llm/<provider>/<case>.json`, labelled `recorded` or `synthetic`.
    Recorded cases (`ok`, `truncated`, `repair_turn`, fictional text only) come from `make record-llm`, which
    scrubs the host, auth headers, request ids and response ids and refuses to write a fixture containing
    the host or key. Filters, refusals and throttling are synthetic: they cannot be provoked honestly with
    fictional text. Replay asserts the codec still sends the recorded body (drift test).

### Structured-output matrix (probed live in S09)

| Deployment | Surface | Structured output | Probed |
|---|---|---|---|
| gpt-6.1-sol | Responses API | strict `json_schema` | ✅ ping, repair turn and truncation recorded |
| claude-opus-4-8 | AnthropicFoundry Messages | one forced tool, no thinking | ✅ ping, repair turn and truncation recorded |
| Kimi-K2.6-1 | — | not probed | deferred (no adapter) |

## Consequences

- **Positive:** every usage and finish shape is a unit test; an unknown provider state is an error, never a
  silent "stop"; retries are reproducible and visible as events; a read-only replay builds no SDK.
- **Negative / costs:** two SDKs, and their HTTP library `httpx2` as a direct (driver) dependency so the
  backends can tell a refused connection from a dropped one. A 504 or dropped connection fails the call
  instead of retrying. Strict schemas forbid optional
  fields, so S10/S12 output models must be strict-compatible. Forced tool use rules out Claude thinking.
- **Open items:** the Anthropic prompt-filter error shape is unknown (only the OpenAI one is handled);
  prompt-filtered calls are assumed unbilled and recorded as unmeasured; OpenAI's new
  `input_tokens_details.cache_write_tokens` is inside input and ignored (prices are `None`); cached input is
  covered by synthetic tests only.
- **Follow-ups:** Kimi adapter and probe (backlog); unify the Europe PMC retry helper with
  `transport_policy` (backlog); S12 maps `llm.*` errors to `FailureKind`.
