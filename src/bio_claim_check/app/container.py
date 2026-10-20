"""[RING:app] Composition root: the one place concrete implementations are chosen and wired.

Why: features depend on base classes, never on backends; something has to pick the backends, and
only `app` may (ADR 0002). It is also the only app module that imports infrastructure: driving
adapters (CLI, UI) call the composers below instead (contract `driving-adapters-use-the-container`).
Today only the fake wiring exists (S05); live wiring arrives with real backends (S12).
Must not: hold logic. It builds objects, composes infrastructure with pure parsers, and normalises
infrastructure errors into the domain's error types.
"""

from pathlib import Path

from bio_claim_check.app.usecases.run import RunPorts
from bio_claim_check.features.answer.scripted_answerer import ScriptedAnswerer
from bio_claim_check.features.contracts.rulepack import RulePack, RulePackError, parse_rulepack
from bio_claim_check.features.report.canonical import REPORT_FILE, canonical_bytes, run_id
from bio_claim_check.features.report.models import Report
from bio_claim_check.features.retrieval.in_memory_literature_source import InMemoryLiteratureSource
from bio_claim_check.features.verify.scripted_verifier import ScriptedVerifier
from bio_claim_check.infrastructure.publish import publish_once
from bio_claim_check.infrastructure.strict_yaml import StrictYamlError, load_strict_yaml
from bio_claim_check.infrastructure.text_files import ReadError, read_package_text, read_text_file

DEFAULT_RULEPACK = ("data", "rulepacks", "default.yaml")


def _rulepack_from_text(text: str, source: str) -> RulePack:
    try:
        data = load_strict_yaml(text, source)
    except StrictYamlError as err:
        raise RulePackError(list(err.problems)) from None
    return parse_rulepack(data, source)


def load_rulepack(path: Path) -> RulePack:
    """A rule pack from a YAML file; every problem is a `RulePackError` line naming the file."""
    try:
        text = read_text_file(path)
    except ReadError as err:
        raise RulePackError([str(err)]) from None
    return _rulepack_from_text(text, str(path))


def default_rulepack() -> RulePack:
    """The rule pack shipped with the package (author-written seed rules)."""
    try:
        text = read_package_text(*DEFAULT_RULEPACK)
    except ReadError as err:
        raise RulePackError([str(err)]) from None
    return _rulepack_from_text(text, DEFAULT_RULEPACK[-1])


def publish_report(out: Path, report: Report) -> Path:
    """Write `<out>/<run_id>/report.json` once, as canonical bytes, and return its path."""
    data = canonical_bytes(report)
    return publish_once(out / run_id(data), REPORT_FILE, data)


def build_fake_run_ports() -> RunPorts:
    """Fictional papers, scripted answers and verdicts. Needs no settings, network or `.env`."""
    return RunPorts(
        literature=InMemoryLiteratureSource(),
        answerer=ScriptedAnswerer(),
        verifier=ScriptedVerifier(),
        rules=default_rulepack(),
        provenance="fake",
    )
