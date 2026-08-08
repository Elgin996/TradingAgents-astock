"""F1.2 — structured-output fallback: schema errors mark, transients propagate."""

from json import JSONDecodeError
from unittest.mock import MagicMock

import pytest
from pydantic import BaseModel, ValidationError

from tradingagents.agents.utils.structured import (
    FREETEXT_MARKER,
    has_freetext_marker,
    invoke_structured_or_freetext,
    strip_freetext_marker,
)


class _Plan(BaseModel):
    decision: str
    confidence: int


def _render(plan: _Plan) -> str:
    return f"Rating: {plan.decision}\nconfidence={plan.confidence}"


def test_schema_error_falls_back_with_marker():
    structured = MagicMock()
    structured.invoke.side_effect = ValidationError.from_exception_data(
        "Plan", [{"type": "missing", "loc": ("decision",), "input": {}}]
    )
    plain = MagicMock()
    plain.invoke.return_value = MagicMock(content="Rating: Hold\nfree text")

    out = invoke_structured_or_freetext(structured, plain, "p", _render, "PM")
    assert has_freetext_marker(out)
    assert out.startswith(FREETEXT_MARKER)
    assert "free text" in out
    plain.invoke.assert_called_once()


def test_json_decode_error_falls_back_with_marker():
    structured = MagicMock()
    structured.invoke.side_effect = JSONDecodeError("Expecting value", "doc", 0)
    plain = MagicMock()
    plain.invoke.return_value = MagicMock(content="fallback body")

    out = invoke_structured_or_freetext(structured, plain, "p", _render, "Trader")
    assert FREETEXT_MARKER in out
    assert "fallback body" in strip_freetext_marker(out)


def test_transient_error_propagates():
    structured = MagicMock()
    structured.invoke.side_effect = TimeoutError("provider timed out")
    plain = MagicMock()

    with pytest.raises(TimeoutError, match="timed out"):
        invoke_structured_or_freetext(structured, plain, "p", _render, "PM")
    plain.invoke.assert_not_called()


def test_structured_success_bypasses_marker():
    structured = MagicMock()
    structured.invoke.return_value = _Plan(decision="Buy", confidence=4)
    plain = MagicMock()

    out = invoke_structured_or_freetext(structured, plain, "p", _render, "PM")
    assert out == "Rating: Buy\nconfidence=4"
    assert not has_freetext_marker(out)
    plain.invoke.assert_not_called()


def test_strip_and_has_freetext_marker():
    raw = f"{FREETEXT_MARKER}\nRating: Hold"
    assert has_freetext_marker(raw)
    assert strip_freetext_marker(raw) == "Rating: Hold"
    assert not has_freetext_marker(strip_freetext_marker(raw))
