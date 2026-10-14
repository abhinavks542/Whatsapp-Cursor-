"""Compatibility wrapper for the project generator module."""

__all__ = ["generate_reply"]


def generate_reply(*args, **kwargs):
    from generator import generate_reply as _generate_reply

    return _generate_reply(*args, **kwargs)
