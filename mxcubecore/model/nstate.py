"""Pydantic models for N-state hardware option lists."""

from typing import Literal

from pydantic.v1 import BaseModel

Variant = Literal["info", "warning", "danger"]


class NStateOption(BaseModel):
    """A single selectable value from an N-state device.

    Bundles the canonical ``value`` with optional display text and a
    current-state validity flag. An option with ``severity`` unset is
    fully selectable; otherwise ``reason`` explains the flag and the
    consumer decides how to surface it.
    """

    value: str
    label: str | None = None
    description: str | None = None
    variant: Variant | None = None

    class Config:
        extra = "ignore"
