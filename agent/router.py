"""Compatibility wrapper for the project router module."""

__all__ = ["resolve_relationship"]


def resolve_relationship(*args, **kwargs):
    from router import resolve_relationship as _resolve_relationship

    return _resolve_relationship(*args, **kwargs)
