"""[RING:engine/prompts] Versioned, hashed prompt templates and strict rendering (S08).

Does: define `PromptTemplate` (name, version, system and user text; a sha256 derived from that text) and
`render`, which fills a template's `$placeholders` into a system + user message pair.
Does not: hold any prompt text. Prompts are code constants in the slice that owns them (answer in S10,
verify in S12), so the slice's rules and tests apply to its prompt.
Must not: import features (contract `engine-is-feature-agnostic`) or call a provider.
"""
