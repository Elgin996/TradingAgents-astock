"""Shared 5-tier rating vocabulary and a deterministic heuristic parser.

The same five-tier scale (Buy, Overweight, Hold, Underweight, Sell) is used by:
- The Research Manager (investment plan recommendation)
- The Portfolio Manager (final position decision)
- The signal processor (rating extracted for downstream consumers)
- The memory log (rating tag stored alongside each decision entry)

Centralising it here avoids drift between those call sites.

Chinese output: when ``output_language`` is Chinese and a weak model or an
OpenAI-compatible relay falls back from structured output to free-text (see
:func:`tradingagents.agents.utils.structured.invoke_structured_or_freetext`),
the final decision arrives as Chinese prose with **no** English ``Rating:``
header — just a line like ``最终评级：卖出``. The parser therefore also
recognises the Chinese 5-tier vocabulary; without it, every such run silently
defaulted to Hold regardless of the model's actual call (issues #78 / #80).
"""

from __future__ import annotations

import logging
import re
from typing import Tuple

logger = logging.getLogger(__name__)


# Canonical, ordered 5-tier scale (most bullish to most bearish).
RATINGS_5_TIER: Tuple[str, ...] = (
    "Buy", "Overweight", "Hold", "Underweight", "Sell",
)

_RATING_SET = {r.lower() for r in RATINGS_5_TIER}

# Matches "Rating: X" / "rating - X" / "Rating: **X**" — tolerates markdown
# bold wrappers and either a colon or hyphen separator.
_RATING_LABEL_RE = re.compile(r"rating.*?[:\-][\s*]*(\w+)", re.IGNORECASE)

# Chinese 5-tier vocabulary → canonical English rating.
_CN_RATING_MAP = {
    "强烈买入": "Buy", "买入": "Buy", "买进": "Buy",
    "增持": "Overweight",
    "持有": "Hold", "中性": "Hold", "观望": "Hold", "维持": "Hold",
    "减持": "Underweight",
    "强烈卖出": "Sell", "清仓": "Sell", "卖出": "Sell",
}
# Longest-first so "强烈买入" beats "买入" and "强烈卖出" beats "卖出" at the
# same position (regex alternation is leftmost, first-listed among equals).
_CN_ALT = "|".join(sorted(_CN_RATING_MAP, key=len, reverse=True))

# A labelled Chinese rating, e.g. "最终评级：卖出" / "投资建议: **增持**".
_CN_LABEL_RE = re.compile(
    r"(?:最终评级|评级|投资评级|评级结论|最终投资建议|投资建议|操作建议|"
    r"推荐评级|建议|推荐)\s*[:：\-]\s*\*{0,2}\s*(" + _CN_ALT + r")"
)
# Bare Chinese rating term anywhere (last-resort fallback).
_CN_TERM_RE = re.compile(_CN_ALT)

# Cues that invert or disqualify a nearby rating word.
_NEGATION_CUES = (
    "not ", "n't", "avoid", "refrain", "rather than", "instead of",
    "不", "勿", "避免", "无需", "不宜", "而非", "并非", "谈不上",
    "不建议", "不要", "并非",
)

# Rating terms that are also ordinary domain nouns. When the term is preceded by
# one of these, it is describing a market fact, not issuing a recommendation.
_COMPOUND_CONTEXTS = {
    "减持": ("股东", "大股东", "高管", "董监高", "计划", "公告"),
    "卖出": ("席位", "营业部", "前五", "龙虎榜"),
    "买入": ("席位", "营业部", "前五", "龙虎榜", "北向"),
}


def _disqualified(text: str, start: int, term: str) -> bool:
    """True when the match at ``start`` is negated or part of a compound noun."""
    clause = re.split(r"[。；;.!?\n]", text[:start])[-1].lower()
    if any(cue in clause for cue in _NEGATION_CUES):
        return True
    prefix = text[max(0, start - 6):start]
    return any(ctx in prefix for ctx in _COMPOUND_CONTEXTS.get(term, ()))


def parse_rating(text: str, default: str = "Hold") -> str:
    """Heuristically extract a 5-tier rating from English or Chinese prose.

    Pass order (first hit wins; explicit labels always beat bare words):
    1. English ``Rating: X`` label (tolerant of markdown bold).
    2. Chinese rating label, e.g. ``最终评级：卖出`` / ``投资建议: 增持``.
    3. Last non-disqualified bare English 5-tier word (conclusion-first).
    4. Last non-disqualified bare Chinese rating term (conclusion-first).

    Returns a Title-cased canonical rating, or ``default`` if none appears.
    """
    if not text:
        return default

    # 1. English explicit label
    for line in text.splitlines():
        m = _RATING_LABEL_RE.search(line)
        if m and m.group(1).lower() in _RATING_SET:
            return m.group(1).capitalize()

    # 2. Chinese explicit label (最终评级：卖出 …)
    m = _CN_LABEL_RE.search(text)
    if m:
        return _CN_RATING_MAP[m.group(1)]

    # 3. Bare English rating word — scan conclusion-first; skip negated/compound hits.
    for line in reversed(text.splitlines()):
        words = line.lower().split()
        for word in reversed(words):
            clean = word.strip("*:.,")
            if clean not in _RATING_SET:
                continue
            # Locate this occurrence in the original text for disqualification.
            # Prefer the last case-insensitive match of this word on the line.
            line_lower = line.lower()
            idx_in_line = line_lower.rfind(clean)
            if idx_in_line < 0:
                continue
            # Absolute offset approximate: find the line in text.
            abs_start = text.lower().rfind(line_lower)
            if abs_start < 0:
                abs_start = 0
            start = abs_start + idx_in_line
            if _disqualified(text, start, clean):
                continue
            rating = clean.capitalize()
            logger.warning(
                "parse_rating: no explicit rating label found; inferred %r from bare term. "
                "Text begins: %.120s",
                rating, text,
            )
            return rating

    # 4. Bare Chinese rating term — last non-disqualified match wins.
    last_match = None
    for m in _CN_TERM_RE.finditer(text):
        term = m.group(0)
        if _disqualified(text, m.start(), term):
            continue
        last_match = m
    if last_match is not None:
        rating = _CN_RATING_MAP[last_match.group(0)]
        logger.warning(
            "parse_rating: no explicit rating label found; inferred %r from bare term. "
            "Text begins: %.120s",
            rating, text,
        )
        return rating

    return default
