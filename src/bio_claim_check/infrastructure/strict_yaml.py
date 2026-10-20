"""[RING:infrastructure] Parse YAML so that every file means exactly one thing.

Why: hand-written, PR-reviewed files (rule packs today) must be unambiguous. Plain `yaml.safe_load`
silently keeps the last of two duplicate keys, expands anchors and aliases (shared or exponential
structure), applies `<<` merge precedence and turns `!!binary` into bytes. This parser rejects all of
those and checks that only plain scalars, lists and string-keyed mappings remain. It replaced the
rule-pack-specific loader of S04 (S05b): what a valid rule pack is now lives in
`features.contracts.rulepack.parse_rulepack`, and the app composes the two.
Must not: know any document schema, read files, or import features or engine (transport only).

No LLM is involved in this module.
"""

from collections.abc import Hashable, Iterator
from typing import Any, cast, override

import yaml
from yaml.constructor import ConstructorError
from yaml.nodes import MappingNode, ScalarNode

_MERGE_TAG = "tag:yaml.org,2002:merge"
_STR_TAG = "tag:yaml.org,2002:str"
_SCALARS = (str, int, float, bool, type(None))


class StrictYamlError(Exception):
    """The text is not unambiguous YAML. `problems` holds one located, human-readable line per problem."""

    def __init__(self, problems: list[str]) -> None:
        super().__init__("\n".join(problems))
        self.problems = tuple(problems)


class _StrictLoader(yaml.SafeLoader):
    @override
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


def load_strict_yaml(text: str, source: str) -> object:
    """Parse `text`; `source` names it in error messages. An empty or comment-only text gives None."""
    try:
        return _load(text, source)
    except RecursionError:  # PyYAML's composer recurses per nesting level; a hostile file can exhaust it
        raise StrictYamlError([f"{source}: nesting is too deep"]) from None


def _load(text: str, source: str) -> object:
    try:
        if lines := _anchor_lines(text):
            raise StrictYamlError([f"{source}:{line}: anchors and aliases are not allowed" for line in lines])
        data: object = yaml.load(text, Loader=_StrictLoader)  # noqa: S506 - _StrictLoader extends SafeLoader
    except yaml.MarkedYAMLError as err:
        mark = err.problem_mark
        where = f"{source}:{mark.line + 1}" if mark else source
        raise StrictYamlError([f"{where}: {err.problem or err}"]) from None
    except yaml.YAMLError as err:
        raise StrictYamlError([f"{source}: {err}"]) from None
    if bad := _non_scalar_paths(data, ""):
        raise StrictYamlError([f"{source}: {problem}" for problem in bad])
    return data
