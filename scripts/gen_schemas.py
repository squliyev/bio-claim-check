"""Write the committed JSON Schemas from the contracts, so reviewers can diff them.

`tests/arch/test_schemas.py` fails when a file here is stale; run `make schemas` after changing a contract.
"""

import json
from collections.abc import Callable
from pathlib import Path

from pydantic import JsonValue

from bio_claim_check.features.contracts.rulepack import rulepack_json_schema
from bio_claim_check.features.contracts.verdict import verifier_output_json_schema

SCHEMAS: dict[str, Callable[[], dict[str, JsonValue]]] = {
    "verifier_output.schema.json": verifier_output_json_schema,
    "rulepack.schema.json": rulepack_json_schema,
}


def render(build: Callable[[], dict[str, JsonValue]]) -> str:
    return json.dumps(build(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    out = Path(__file__).resolve().parents[1] / "schemas"
    out.mkdir(exist_ok=True)
    for name, build in SCHEMAS.items():
        (out / name).write_text(render(build), encoding="utf-8")


if __name__ == "__main__":
    main()
