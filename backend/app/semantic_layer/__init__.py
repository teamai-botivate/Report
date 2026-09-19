"""Semantic layer: hand-authored dictionary (`dictionary.py`), an in-process
metadata cache combining structural facts from `Base.metadata` with that
dictionary (`metadata_cache.py`), and deterministic, no-LLM retrieval of the
relevant slice of metadata for a given question (`retrieval.py`).

Entry points are exposed lazily via `__getattr__` so that
`app.semantic_layer.dictionary` (pure Python, no SQLAlchemy/DB dependency)
can be imported on its own, e.g. from unit tests, without pulling in the
rest of the app.
"""
__all__ = [
    "refresh_metadata_cache",
    "get_cached_metadata",
    "retrieve_relevant_metadata",
    "retrieve_relevant_schema",
]


def __getattr__(name: str):
    if name in ("refresh_metadata_cache", "get_cached_metadata"):
        from app.semantic_layer import metadata_cache

        return getattr(metadata_cache, name)
    if name in ("retrieve_relevant_metadata", "retrieve_relevant_schema"):
        from app.semantic_layer import retrieval

        return getattr(retrieval, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
