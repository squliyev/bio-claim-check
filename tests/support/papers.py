"""[TEST SUPPORT] Build fictional `Paper`s with just the metadata a test cares about.

Defaults describe an eligible human journal article with MeSH indexed and no trap cues, so each test
states only the field it is about. Ids use the real `MED:` namespace with made-up numbers.
"""

from bio_claim_check.features.contracts.paper import Paper


def paper(
    pmid: int = 1,
    *,
    title: str | None = None,
    abstract: str = "Background sentence here. We report a result in patients.",
    mesh: tuple[str, ...] | None = ("Humans",),
    types: tuple[str, ...] = ("Journal Article",),
    retracted: bool = False,
    year: int | None = 2020,
) -> Paper:
    return Paper(
        source_id=f"MED:{pmid}",
        title=title if title is not None else f"Fictional study number {pmid}",
        year=year,
        raw_abstract=abstract,
        mesh_headings=mesh,
        publication_types=types,
        retracted=retracted,
    )
