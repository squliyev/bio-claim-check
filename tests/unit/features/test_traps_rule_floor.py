"""Rule-floor traps: one site, one edit; zero or several sites means no trap."""

import pytest

from bio_claim_check.features.traps.rule_floor import FloorTrap, mutate


@pytest.mark.parametrize(
    ("parent", "expected"),
    [
        (
            "Drug X increased survival in mice.",
            (FloorTrap(rule="direction", claim="Drug X decreased survival in mice."),),
        ),
        (
            "Higher intake went with fewer events.",
            (FloorTrap(rule="direction", claim="Lower intake went with fewer events."),),
        ),
        (
            "Mortality was < 5% with drug X.",
            (FloorTrap(rule="operator", claim="Mortality was > 5% with drug X."),),
        ),
        ("Uptake was ≥ 2 per week.", (FloorTrap(rule="operator", claim="Uptake was ≤ 2 per week."),)),
        ("Mice got 0.5 mg/kg of drug X.", (FloorTrap(rule="dose", claim="Mice got 5 mg/kg of drug X."),)),
        ("Patients took 100 mg daily.", (FloorTrap(rule="dose", claim="Patients took 1000 mg daily."),)),
        ("Patients took 2.5µg daily.", (FloorTrap(rule="dose", claim="Patients took 25µg daily."),)),
    ],
)
def test_one_site_gives_one_edit(parent: str, expected: tuple[FloorTrap, ...]) -> None:
    assert mutate(parent) == expected


@pytest.mark.parametrize(
    "parent",
    [
        "Drug X helped mice.",
        "Drug X increased A and decreased B.",
        "Values ranged 1 < x < 3.",
        "Doses of 1 mg and 10 mg were tried.",
        "The increasedness of X was noted.",
    ],
)
def test_zero_or_several_sites_give_no_trap(parent: str) -> None:
    assert mutate(parent) == ()


def test_several_rules_can_apply_to_one_parent() -> None:
    rules = [t.rule for t in mutate("10 mg increased levels, p < 0.05.")]
    assert rules == ["direction", "operator", "dose"]


def test_all_caps_case_is_kept() -> None:
    assert mutate("LEVELS INCREASED.")[0].claim == "LEVELS DECREASED."
