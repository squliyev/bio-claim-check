"""[RING:infrastructure] Read a rule pack from YAML, refusing anything ambiguous.

Why: a rule pack is written by hand and reviewed by pull request, so the loader must make every file
mean exactly one thing. Plain `yaml.safe_load` silently keeps the last of two duplicate keys, expands
anchors and aliases (shared or exponential structure), applies `<<` merge precedence and turns
`!!binary` into bytes. This loader rejects all of those, then checks that only plain scalars remain,
and lets the pydantic models in `features.contracts.rulepack` do the rest.
Must not: decide what a valid rule is (that is the model's job) or read any path it was not given.

No LLM is involved in this module.
"""

from collections.abc import Hashable, Iterator
from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import yaml
from pydantic import ValidationError
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, ScalarNode

from bio_claim_check.features.contracts.rulepack import RulePack

_MERGE_TAG = "tag:yaml.org,2002:merge"
_STR_TAG = "tag:yaml.org,2002:str"
_SCALARS = (str, int, float, bool, type(None))


class RulePackError(Exception):
    """A rule pack could not be loaded. `problems` holds one human-readable line per problem."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


class _StrictLoader(yaml.SafeLoader):
    def construct_mapping(self, node: MappingNode, deep: bool = False) -> dict[Hashable, Any]:
        seen: set[str] = set()
        for key_node, _ in node.value:
            if key_node.tag == _MERGE_TAG:
                raise ConstructorError(None, None, "merge keys (<<) are not allowed", key_node.start_mark)
            if not isinstance(key_node, ScalarNode) or key_node.tag != _STR_TAG:
                raise ConstructorError(None, None, "keys must be plain strings", key_node.start_mark)
            key = str(key_node.value)
            if key in seen:
                raise ConstructorError(None, None, f"duplicate key {key!r}", key_node.start_mark)
            seen.add(key)
        return super().construct_mapping(node, deep=deep)


def _anchor_lines(text: str) -> list[int]:
    """1-based lines of every anchor or alias; checked on events, before anything is constructed."""
    # types-pyyaml leaves parse() untyped; the cast restores the documented event type
    events = cast(Iterator[yaml.Event], yaml.parse(text, Loader=yaml.SafeLoader))  # pyright: ignore[reportUnknownMemberType]
    return [
        event.start_mark.line + 1 if event.start_mark else 0
        for event in events
        if isinstance(event, yaml.AliasEvent) or (isinstance(event, yaml.NodeEvent) and event.anchor)
    ]


def _non_scalar_paths(value: object, path: str) -> list[str]:
    if isinstance(value, dict):
        mapping = cast(dict[str, object], value)
        return [p for key, child in mapping.items() for p in _non_scalar_paths(child, _join(path, key))]
    if isinstance(value, list):
        items = cast(list[object], value)
        return [p for i, child in enumerate(items) for p in _non_scalar_paths(child, _join(path, str(i)))]
    if isinstance(value, _SCALARS):
        return []
    return [f"{path or '(root)'}: {type(value).__name__} values are not allowed"]


def _join(path: str, part: str) -> str:
    return f"{path}.{part}" if path else part


def parse_rulepack(text: str, source: str) -> RulePack:
    """Parse rule-pack YAML text; `source` names the file in error messages."""
    try:
        return _parse(text, source)
    except RecursionError:  # PyYAML's composer recurses per nesting level; a hostile file can exhaust it
        raise RulePackError([f"{source}: nesting is too deep"]) from None


def _parse(text: str, source: str) -> RulePack:
    try:
        if lines := _anchor_lines(text):
            raise RulePackError([f"{source}:{line}: anchors and aliases are not allowed" for line in lines])
        data: object = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - _StrictLoader extends SafeLoader
    except yaml.MarkedYAMLError as err:
        mark = err.problem_mark
        where = f"{source}:{mark.line + 1}" if mark else source
        raise RulePackError([f"{where}: {err.problem or err}"]) from None
    except yaml.YAMLError as err:
        raise RulePackError([f"{source}: {err}"]) from None
    if data is None:
        raise RulePackError([f"{source}: the file is empty"])
    if bad := _non_scalar_paths(data, ""):
        raise RulePackError([f"{source}: {problem}" for problem in bad])
    try:
        return RulePack.model_validate(data)
    except ValidationError as err:
        problems: list[str] = []
        for problem in err.errors(include_input=False, include_url=False):
            location = ".".join(str(part) for part in problem["loc"]) or "(root)"
            problems.append(f"{source}: {location}: {problem['msg']}")
        raise RulePackError(problems) from None


def load_rulepack(path: Path) -> RulePack:
    """Load a rule pack from a file."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as err:
        raise RulePackError([f"{path}: cannot read: {err}"]) from None
    return parse_rulepack(text, str(path))


def load_default_rulepack() -> RulePack:
    """The rule pack shipped with the package (author-written seed rules)."""
    resource = files("bio_claim_check") / "data" / "rulepacks" / "default.yaml"
    return parse_rulepack(resource.read_text(encoding="utf-8"), "default.yaml")
