from abc import ABC, abstractmethod
from typing import Any, Optional
import logging
import warnings

logger = logging.getLogger(__name__)

# 各 provider 表示"因为撞到 max_tokens 才停下"的字段值。
_TRUNCATION_MARKERS = {
    "stop_reason": "max_tokens",   # Anthropic
    "finish_reason": "length",     # OpenAI 兼容
}


def warn_if_truncated(response, model: str):
    """回复因为撞到输出上限被截断时，明确说出来。

    截断的表现是报告写到一半戛然而止，而返回值本身完全合法——不喊出来就是静默
    失败，用户只会以为"模型没写完"，根本想不到去调 max_tokens（#91）。
    """
    metadata = getattr(response, "response_metadata", None) or {}
    for field, truncated_value in _TRUNCATION_MARKERS.items():
        if metadata.get(field) == truncated_value:
            logger.warning(
                "模型 %s 的这次回复因为达到输出上限被截断（%s=%s），报告会缺一截。"
                "请在 config 里调大 `max_tokens`（或设环境变量 "
                "TRADINGAGENTS_MAX_TOKENS），例如 max_tokens=16000。",
                model, field, truncated_value,
            )
            break
    return response


def normalize_content(response):
    """Normalize LLM response content to a plain string.

    Multiple providers (OpenAI Responses API, Google Gemini 3) return content
    as a list of typed blocks, e.g. [{'type': 'reasoning', ...}, {'type': 'text', 'text': '...'}].
    Downstream agents expect response.content to be a string. This extracts
    and joins the text blocks, discarding reasoning/metadata blocks.
    """
    content = response.content
    if isinstance(content, list):
        texts = [
            item.get("text", "") if isinstance(item, dict) and item.get("type") == "text"
            else item if isinstance(item, str) else ""
            for item in content
        ]
        response.content = "\n".join(t for t in texts if t)
    return response


class BaseLLMClient(ABC):
    """Abstract base class for LLM clients."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        self.model = model
        self.base_url = base_url
        self.kwargs = kwargs

    def get_provider_name(self) -> str:
        """Return the provider name used in warning messages."""
        provider = getattr(self, "provider", None)
        if provider:
            return str(provider)
        return self.__class__.__name__.removesuffix("Client").lower()

    def warn_if_unknown_model(self) -> None:
        """Warn when the model is outside the known list for the provider."""
        if self.validate_model():
            return

        warnings.warn(
            (
                f"Model '{self.model}' is not in the known model list for "
                f"provider '{self.get_provider_name()}'. Continuing anyway."
            ),
            RuntimeWarning,
            stacklevel=2,
        )

    @abstractmethod
    def get_llm(self) -> Any:
        """Return the configured LLM instance."""
        pass

    @abstractmethod
    def validate_model(self) -> bool:
        """Validate that the model is supported by this client."""
        pass
