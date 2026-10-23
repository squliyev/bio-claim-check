"""[RING:engine/events] The one fold from a run's events to LLM usage per model.

Why: the CLI's usage line and the run ledger must agree, so both use this fold (moved here from the S10
`answer dev` use case in S11). Fields are named by unit so no count is mistaken for another:
- `finished_attempts`: logical attempts that returned a response (cache hits included);
- `cache_hits`: of those, replayed from the cache; they cost nothing now, so their tokens are not summed;
- `failed_calls`: runner calls that failed (one `LlmCallFailed` each);
- `unmeasured_attempts`: logical attempts that may have reached the provider without reported usage: a
  failure marked `unmeasured`, or a start with no terminal event (the process stopped, or the trace write
  failed); never summed as 0 tokens;
- `transport_retries`: earlier transport tries inside a logical attempt (`LlmRetryScheduled`), whose
  usage is unknown too. Potentially billed but unmeasured = `unmeasured_attempts + transport_retries`;
- `measured_*_tokens`: summed over finished live attempts only; `reasoning_unreported` counts live
  attempts whose provider did not report reasoning tokens, never as 0.
Starts are paired with their terminal events per (agent, model); the runner is sequential, so each start
is followed by its own terminal event. The fold never raises (it runs while a run is being recorded, even
after a failure): a start that is followed by another start of the same (agent, model) is counted as never
ended (unmeasured), and a finish without a start still counts as finished.
No deployment has a price yet, so there is no money here (backlog A13).
Must not: read anything but events, or guess usage it was not given.

No LLM is involved in this module.
"""

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, fields, replace

from bio_claim_check.engine.events.llm_events import (
    LlmCallFailed,
    LlmCallFinished,
    LlmCallStarted,
    LlmRetryScheduled,
)
from bio_claim_check.engine.events.pipeline_event import ModelRef, PipelineEvent


@dataclass(frozen=True, slots=True)
class CallTally:
    finished_attempts: int = 0
    cache_hits: int = 0
    failed_calls: int = 0
    unmeasured_attempts: int = 0
    transport_retries: int = 0
    measured_input_tokens: int = 0
    measured_output_tokens: int = 0
    measured_reasoning_tokens: int = 0
    reasoning_unreported: int = 0

    @property
    def finished_live_attempts(self) -> int:
        """Finished attempts that were not cache hits."""
        return self.finished_attempts - self.cache_hits


type Terminal = LlmCallFinished | LlmCallFailed


def paired_attempts(events: Iterable[PipelineEvent]) -> Iterator[tuple[LlmCallStarted, Terminal | None]]:
    """Each `LlmCallStarted` with its terminal event, or None if it never ended. A failure with no open
    start (it came after the attempt finished, or before any attempt started) is not paired."""
    open_starts: dict[tuple[str | None, ModelRef], LlmCallStarted] = {}
    for event in events:
        if isinstance(event, LlmCallStarted):
            if (earlier := open_starts.pop((event.agent, event.model), None)) is not None:
                yield earlier, None
            open_starts[(event.agent, event.model)] = event
        elif isinstance(event, LlmCallFinished | LlmCallFailed):
            if (start := open_starts.pop((event.agent, event.model), None)) is not None:
                yield start, event
    for start in open_starts.values():
        yield start, None


def tally_calls(events: Iterable[PipelineEvent]) -> Mapping[ModelRef, CallTally]:
    """Usage per model, in first-seen order."""
    events = tuple(events)
    tallies: dict[ModelRef, CallTally] = {}

    def add(model: ModelRef, **counts: int) -> None:
        tally = tallies.get(model, CallTally())
        tallies[model] = replace(tally, **{k: getattr(tally, k) + v for k, v in counts.items()})

    for event in events:
        if isinstance(event, LlmRetryScheduled):
            add(event.model, transport_retries=1)
        elif isinstance(event, LlmCallFailed):
            add(event.model, failed_calls=1)
        elif isinstance(event, LlmCallFinished) and event.cache_hit:
            add(event.model, finished_attempts=1, cache_hits=1)
        elif isinstance(event, LlmCallFinished):
            add(
                event.model,
                finished_attempts=1,
                measured_input_tokens=event.input_tokens,
                measured_output_tokens=event.output_tokens,
                measured_reasoning_tokens=event.reasoning_tokens or 0,
                reasoning_unreported=int(event.reasoning_tokens is None),
            )
    for start, end in paired_attempts(events):
        if end is None or (isinstance(end, LlmCallFailed) and end.unmeasured):
            add(start.model, unmeasured_attempts=1)
    return tallies


def summed(tallies: Iterable[CallTally]) -> CallTally:
    """All models together, for a one-line summary."""
    tallies = tuple(tallies)
    return CallTally(**{f.name: sum(getattr(t, f.name) for t in tallies) for f in fields(CallTally)})
