"""Shared helpers for invoking an agent with structured output and a graceful fallback.

The Portfolio Manager, Trader, and Research Manager all follow the same
canonical pattern:

1. At agent creation, wrap the LLM with ``with_structured_output(Schema)``
   so the model returns a typed Pydantic instance. If the provider does
   not support structured output (rare; mostly older Ollama models), the
   wrap is skipped and the agent uses free-text generation instead.
2. At invocation, run the structured call and render the result back to
   markdown. Schema/parse failures fall back to free text with an explicit
   marker; transient provider faults (timeouts, rate limits, auth) propagate.
"""

from __future__ import annotations

import logging
from json import JSONDecodeError
from typing import Any, Callable, Optional, TypeVar, Tuple, Type

from pydantic import BaseModel, ValidationError

logger = logging.getLogger(__name__)

T = TypeVar("T", bound=BaseModel)

try:
    from langchain_core.exceptions import OutputParserException
except ImportError:  # pragma: no cover
    OutputParserException = ()  # type: ignore[misc, assignment]

_SCHEMA_ERRORS: Tuple[Type[BaseException], ...] = (
    ValidationError,
    JSONDecodeError,
    KeyError,
    TypeError,
    AttributeError,  # e.g. structured invoke returned None / wrong shape
    ValueError,
)
if OutputParserException is not ():
    _SCHEMA_ERRORS = _SCHEMA_ERRORS + (OutputParserException,)  # type: ignore[arg-type]

# Survives into the final report so CLI/web/memory can surface the degradation.
FREETEXT_MARKER = "<!-- ta:structured_output=failed -->"


def strip_freetext_marker(text: str) -> str:
    """Remove the structured-output failure marker before LLM prompt injection."""
    if not text:
        return text
    return text.replace(FREETEXT_MARKER, "").lstrip("\n")


def has_freetext_marker(text: str) -> bool:
    return bool(text) and FREETEXT_MARKER in text


def bind_structured(llm: Any, schema: type[T], agent_name: str) -> Optional[Any]:
    """Return ``llm.with_structured_output(schema)`` or ``None`` if unsupported.

    Logs a warning when the binding fails so the user understands the agent
    will use free-text generation for every call instead of one-shot fallback.
    """
    try:
        return llm.with_structured_output(schema)
    except (NotImplementedError, AttributeError) as exc:
        logger.warning(
            "%s: provider does not support with_structured_output (%s); "
            "falling back to free-text generation",
            agent_name, exc,
        )
        return None


def invoke_structured_or_freetext(
    structured_llm: Optional[Any],
    plain_llm: Any,
    prompt: Any,
    render: Callable[[T], str],
    agent_name: str,
) -> str:
    """Run the structured call and render to markdown; fall back on schema errors only.

    Transient provider faults (timeouts, rate limits, auth) are **not** caught —
    they must propagate so the run fails loudly rather than silently degrading.
    """
    if structured_llm is not None:
        try:
            return render(structured_llm.invoke(prompt))
        except _SCHEMA_ERRORS as exc:
            logger.warning(
                "%s: model returned output that does not match the schema (%s); "
                "falling back to free text — the rating for this run will be "
                "recovered heuristically and may be unreliable",
                agent_name, exc,
            )
        # Anything else (timeout, rate limit, auth) propagates.

    response = plain_llm.invoke(prompt)
    content = getattr(response, "content", response)
    return f"{FREETEXT_MARKER}\n{content}"
