import pytest

from tradelab.core.drawings import Drawing, serialize, deserialize, fib_levels


def test_valid_kinds_construct_without_error():
    for kind in ["trendline", "hline", "vline", "rect", "fib", "text", "channel"]:
        d = Drawing(kind=kind, x1=1, y1=2, x2=3, y2=4)
        assert d.kind == kind
        assert d.id  # auto-generated id present


def test_invalid_kind_raises():
    with pytest.raises(ValueError):
        Drawing(kind="not_a_real_kind")


def test_serialize_deserialize_round_trip():
    drawings = [
        Drawing(kind="trendline", x1=1, y1=2, x2=10, y2=20, color="#ff0000"),
        Drawing(kind="hline", x1=0, y1=55.5),
        Drawing(kind="text", x1=5, y1=6, text="Breakout level"),
    ]
    payload = serialize(drawings)
    restored = deserialize(payload)
    assert len(restored) == 3
    assert restored[0].kind == "trendline"
    assert restored[0].x2 == 10
    assert restored[2].text == "Breakout level"
    # ids preserved across the round trip
    assert [d.id for d in restored] == [d.id for d in drawings]


def test_deserialize_empty_payload_returns_empty_list():
    assert deserialize("") == []
    assert deserialize(None) == []


def test_fib_levels_endpoints_match_anchors():
    levels = fib_levels(100.0, 200.0)
    assert levels[0.0] == 100.0
    assert levels[1.0] == 200.0
    assert levels[0.5] == 150.0


def test_fib_levels_works_downward():
    levels = fib_levels(200.0, 100.0)
    assert levels[0.0] == 200.0
    assert levels[1.0] == 100.0
    assert levels[0.618] < levels[0.0]
