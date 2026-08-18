"""The Claude layer: a Buffett-voice memo over the quantitative dossier.

This runs last and is entirely optional. If there is no API key, or the call
fails, or the model declines the request, the quantitative report still ships.
The memo adds judgement; it is never the thing that decides a position size.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

from ..config import AgentConfig
from .prompts import MEMO_SCHEMA, SYSTEM_PROMPT, build_user_message

if TYPE_CHECKING:
    from ..analysis.screen import Candidate, ScreenResult

log = logging.getLogger(__name__)

# Claude Opus 5 thinks by default, and `max_tokens` caps thinking plus response
# text together. The floor here leaves room for both.
MIN_MAX_TOKENS = 8000

# Opting into server-side fallbacks means a safety decline is re-run on
# Anthropic's recommended fallback model rather than returned as a dead end.
FALLBACK_BETA = "server-side-fallback-2026-07-01"


@dataclass
class Verdict:
    ticker: str
    verdict: str
    business_in_one_line: str
    moat: str
    why_it_is_cheap: str
    what_would_make_me_wrong: list[str] = field(default_factory=list)
    questions_before_buying: list[str] = field(default_factory=list)
    sizing_comment: str = ""
    conviction: str = "low"


@dataclass
class Memo:
    market_note: str = ""
    discipline_note: str = ""
    verdicts: list[Verdict] = field(default_factory=list)
    model: str = ""
    available: bool = False
    error: str | None = None

    def verdict_for(self, ticker: str) -> Verdict | None:
        for verdict in self.verdicts:
            if verdict.ticker.upper() == ticker.upper():
                return verdict
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "market_note": self.market_note,
            "discipline_note": self.discipline_note,
            "verdicts": [asdict(v) for v in self.verdicts],
            "model": self.model,
            "available": self.available,
            "error": self.error,
        }


def _parse(payload: dict[str, Any], model: str) -> Memo:
    verdicts = []
    for raw in payload.get("verdicts", []):
        verdicts.append(
            Verdict(
                ticker=raw.get("ticker", ""),
                verdict=raw.get("verdict", "pass"),
                business_in_one_line=raw.get("business_in_one_line", ""),
                moat=raw.get("moat", ""),
                why_it_is_cheap=raw.get("why_it_is_cheap", ""),
                what_would_make_me_wrong=list(raw.get("what_would_make_me_wrong", [])),
                questions_before_buying=list(raw.get("questions_before_buying", [])),
                sizing_comment=raw.get("sizing_comment", ""),
                conviction=raw.get("conviction", "low"),
            )
        )
    return Memo(
        market_note=payload.get("market_note", ""),
        discipline_note=payload.get("discipline_note", ""),
        verdicts=verdicts,
        model=model,
        available=True,
    )


def write_memo(
    result: "ScreenResult",
    candidates: list["Candidate"],
    cfg: AgentConfig,
    language: str,
) -> Memo:
    """Ask Claude for the qualitative read. Never raises."""
    if not cfg.enabled:
        return Memo(error="agent disabled (no ANTHROPIC_API_KEY, or switched off)")

    try:
        import anthropic
    except ImportError as exc:
        return Memo(error=f"anthropic SDK not installed: {exc}")

    client = anthropic.Anthropic()
    user_message = build_user_message(result, candidates, language)
    max_tokens = max(cfg.max_tokens, MIN_MAX_TOKENS)

    request: dict[str, Any] = {
        "model": cfg.model,
        "max_tokens": max_tokens,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_message}],
        "output_config": {
            "effort": "high",
            "format": {"type": "json_schema", "schema": MEMO_SCHEMA},
        },
    }

    try:
        message = _send(client, request, with_fallbacks=True)
    except Exception as exc:  # noqa: BLE001 - the report must ship regardless
        log.warning("memo request failed: %s", exc)
        return Memo(error=f"{type(exc).__name__}: {exc}")

    # A safety decline returns HTTP 200 with an empty or partial content list, so
    # this has to be checked before indexing into content.
    if message.stop_reason == "refusal":
        detail = getattr(message, "stop_details", None)
        category = getattr(detail, "category", None) if detail else None
        return Memo(
            error=f"model declined the request (category: {category or 'unspecified'})"
        )
    if message.stop_reason == "max_tokens":
        return Memo(
            error=f"memo truncated at {max_tokens} tokens; raise agent.max_tokens"
        )

    text = next((b.text for b in message.content if b.type == "text"), "")
    if not text.strip():
        return Memo(error="model returned no text content")

    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return Memo(error=f"memo was not valid JSON: {exc}")

    memo = _parse(payload, getattr(message, "model", cfg.model))
    log.info("memo written: %d verdicts", len(memo.verdicts))
    return memo


def _send(client: Any, request: dict[str, Any], *, with_fallbacks: bool) -> Any:
    """Stream the request and return the assembled message.

    Streaming rather than a plain create: the dossier is long, the model thinks
    by default, and a non-streaming request at this `max_tokens` risks an HTTP
    timeout. `get_final_message()` gives back the whole message anyway.
    """
    import anthropic

    kwargs = dict(request)
    if with_fallbacks:
        kwargs["betas"] = [FALLBACK_BETA]
        kwargs["fallbacks"] = "default"

    try:
        with client.beta.messages.stream(**kwargs) as stream:
            return stream.get_final_message()
    except anthropic.BadRequestError as exc:
        # An account or SDK without the fallback beta should still get a memo.
        if with_fallbacks and "fallback" in str(exc).lower():
            log.info("server-side fallbacks unavailable, retrying without them")
            return _send(client, request, with_fallbacks=False)
        raise
