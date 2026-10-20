"""[RING:app/ui] Streamlit interface (S17): a driving adapter, like the CLI.

Why: the boundary exists now so `driving-adapters-use-the-container` covers it before any page exists.
Must not: hold logic or import infrastructure; it calls `app.container` and `app.usecases` only.
"""
