"""Compatibility package exposing project modules under the expected agent namespace."""

__all__ = ["resolve_relationship", "should_reply", "generate_reply"]


def __getattr__(name):
    if name == "resolve_relationship":
        from .router import resolve_relationship

        return resolve_relationship
    if name == "should_reply":
        from .decision_engine import should_reply

        return should_reply
    if name == "generate_reply":
        from .generator import generate_reply

        return generate_reply
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
