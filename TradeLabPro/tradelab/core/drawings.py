"""Drawing object model for the Chart Engine.

These are plain, Qt-free dataclasses so they can be unit tested and
persisted (as JSON) without importing PySide6/pyqtgraph. The chart widget
turns these into pyqtgraph graphics items at render time.

Coordinates are stored in *data space*: x is a pandas.Timestamp (stored as
ISO string) or an integer bar index (we use bar index — simpler, robust to
timezone/weekend gaps, and what most lightweight chart libraries do), y is
price.
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional
import json
import uuid


VALID_KINDS = {"trendline", "hline", "vline", "rect", "fib", "text", "channel", "measure"}


@dataclass
class Drawing:
    kind: str
    # Point 1 (all kinds use this)
    x1: float = 0.0
    y1: float = 0.0
    # Point 2 (trendline / rect / fib / channel)
    x2: Optional[float] = None
    y2: Optional[float] = None
    color: str = "#4aa3ff"
    text: str = ""
    line_width: float = 1.5
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def __post_init__(self):
        if self.kind not in VALID_KINDS:
            raise ValueError(f"Unknown drawing kind: {self.kind!r}. Must be one of {sorted(VALID_KINDS)}")

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Drawing":
        allowed = {f for f in Drawing.__dataclass_fields__.keys()}
        clean = {k: v for k, v in d.items() if k in allowed}
        return Drawing(**clean)


def serialize(drawings: list[Drawing]) -> str:
    return json.dumps([d.to_dict() for d in drawings])


def deserialize(payload: str) -> list[Drawing]:
    if not payload:
        return []
    raw = json.loads(payload)
    return [Drawing.from_dict(item) for item in raw]


def fib_levels(y1: float, y2: float) -> dict:
    """Standard retracement levels between two anchor prices."""
    diff = y2 - y1
    ratios = [0.0, 0.236, 0.382, 0.5, 0.618, 0.786, 1.0]
    return {r: y1 + diff * r for r in ratios}
