"""Compatibility wrapper for the project decision engine module."""

__all__ = ["should_reply"]


def should_reply(*args, **kwargs):
    from decision_engine import should_reply as _should_reply

    return _should_reply(*args, **kwargs)
