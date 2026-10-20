"""[RING:features/bench] Score verifiers on a frozen benchmark split (S16).

Does: join outcomes to items by id, count missing outcomes as failures and compute the
pre-registered endpoints.
Does not: drop rows, pool repeats into one confidence interval or look at the sealed test split
before the protocol is tagged.
"""
