"""The memo layer: schema validity, graceful degradation, dossier completeness.

The API call itself is not exercised here (that needs a key and a network), so
these tests pin the things that would otherwise fail at 21:00 in production: a
schema the structured-outputs endpoint would reject, a request built with
parameters the SDK does not accept, and a dossier that crashes on a filer with
missing data.
"""

from __future__ import annotations

import inspect
from datetime import date

import pytest

from buffett.agent.memo import Memo, Verdict, _parse, write_memo
from buffett.agent.prompts import (
    MEMO_SCHEMA,
    SYSTEM_PROMPT,
    build_user_message,
    dossier_for,
)
from buffett.analysis.kelly import size_position
from buffett.analysis.quality import assess_quality
from buffett.analysis.screen import Candidate, apply_gates, compute_price_stats
from buffett.analysis.valuation import value_company
from buffett.config import AgentConfig, Config
from buffett.fixtures import make_company, steady_compounder, value_trap
from buffett.models import Company, FiscalYear

TODAY = date(2026, 8, 17)


def _candidate(company: Company, cfg: Config) -> Candidate:
    quality = assess_quality(company, 6, cfg.valuation.fallback_tax_rate)
    stats = compute_price_stats(company)
    valuation = value_company(
        company, quality, cfg.valuation, 6, stats.volatility, {}
    )
    return Candidate(
        company=company,
        quality=quality,
        valuation=valuation,
        sizing=size_position(
            valuation, quality, cfg.kelly, cfg.portfolio, cfg.tranches, TODAY
        ),
        gate=apply_gates(company, quality, valuation, cfg),
        price_stats=stats,
    )


# ---- schema validity ---------------------------------------------------


def _walk_objects(node: dict):
    """Yield every object-typed subschema, including inside array items."""
    if node.get("type") == "object":
        yield node
        for child in node.get("properties", {}).values():
            yield from _walk_objects(child)
    elif node.get("type") == "array":
        yield from _walk_objects(node.get("items", {}))


def test_memo_schema_satisfies_structured_output_rules():
    """Every object needs additionalProperties false and all keys required."""
    objects = list(_walk_objects(MEMO_SCHEMA))
    assert objects, "schema has no object nodes"

    for node in objects:
        assert node.get("additionalProperties") is False, node.get("properties", {}).keys()
        declared = set(node.get("properties", {}))
        required = set(node.get("required", []))
        assert declared == required, (
            f"structured outputs need every property required; "
            f"missing: {sorted(declared - required)}"
        )


def test_memo_schema_avoids_unsupported_json_schema_keywords():
    """Numeric and string constraints are not supported and would 400."""
    unsupported = {
        "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
        "multipleOf", "minLength", "maxLength", "pattern",
        "minItems", "maxItems", "uniqueItems",
    }

    def scan(node) -> None:
        if isinstance(node, dict):
            offending = unsupported & set(node)
            assert not offending, f"unsupported keywords: {sorted(offending)}"
            for value in node.values():
                scan(value)
        elif isinstance(node, list):
            for item in node:
                scan(item)

    scan(MEMO_SCHEMA)


def test_memo_schema_carries_the_fields_the_report_renders():
    verdict_props = MEMO_SCHEMA["properties"]["verdicts"]["items"]["properties"]
    # The report renderers read exactly these attribute names off Verdict.
    for name in Verdict.__dataclass_fields__:
        assert name in verdict_props, name


def test_request_parameters_are_accepted_by_the_installed_sdk():
    """Catches a parameter rename in the SDK before it fails at 21:00."""
    anthropic = pytest.importorskip("anthropic")
    client = anthropic.Anthropic(api_key="not-a-real-key")
    accepted = set(inspect.signature(client.beta.messages.stream).parameters)

    for name in ("model", "max_tokens", "system", "messages", "output_config",
                 "betas", "fallbacks"):
        assert name in accepted, f"SDK no longer accepts {name!r}"

    # Sampling parameters are rejected on Claude Opus 5, so the request must not
    # carry them.
    import buffett.agent.memo as memo_module

    source = inspect.getsource(memo_module)
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in source, f"{banned} would be rejected by the model"


# ---- graceful degradation ----------------------------------------------


def test_disabled_agent_returns_an_unavailable_memo_without_calling_out():
    memo = write_memo(
        result=None, candidates=[], cfg=AgentConfig(enabled=False), language="id"
    )
    assert not memo.available
    assert memo.error and "disabled" in memo.error
    assert memo.verdicts == []


def test_unavailable_memo_is_safe_for_the_renderers_to_consume():
    memo = Memo(error="no key")
    assert memo.verdict_for("AAPL") is None
    payload = memo.to_dict()
    assert payload["available"] is False
    assert payload["verdicts"] == []


def test_parse_builds_verdicts_and_tolerates_missing_optional_lists():
    memo = _parse(
        {
            "market_note": "Pasar mahal.",
            "discipline_note": "Jangan memaksa beli.",
            "verdicts": [
                {
                    "ticker": "cmpd",
                    "verdict": "buy",
                    "business_in_one_line": "Menjual perangkat.",
                    "moat": "ROIC tinggi konsisten.",
                    "why_it_is_cheap": "Sentimen sektor.",
                    "sizing_comment": "Ukuran wajar.",
                    "conviction": "high",
                }
            ],
        },
        model="claude-opus-5",
    )

    assert memo.available
    assert memo.model == "claude-opus-5"
    assert len(memo.verdicts) == 1
    # Ticker lookup is case-insensitive so renderer and model need not agree.
    found = memo.verdict_for("CMPD")
    assert found is not None and found.verdict == "buy"
    assert found.what_would_make_me_wrong == []


# ---- dossier -----------------------------------------------------------


def test_dossier_covers_every_section_for_a_full_filer():
    cfg = Config()
    candidate = _candidate(
        make_company("CMPD", years=steady_compounder(), last_close=69.0,
                     shares_outstanding=1_344e6),
        cfg,
    )
    text = dossier_for(candidate)

    for heading in (
        "-- Valuation", "-- Multiples", "-- Business quality",
        "-- Balance sheet", "-- Dividend", "-- Price behaviour",
        "-- Sizing already computed",
    ):
        assert heading in text, heading
    assert "MARGIN OF SAFETY" in text
    assert "CMPD" in text


def test_dossier_marks_gaps_as_unavailable_rather_than_zero():
    """A thinly tagged filer must produce 'unavailable', never a fabricated 0."""
    cfg = Config()
    sparse = [
        FiscalYear(
            period_end=date(2020 + offset, 12, 31),
            label=2020 + offset,
            revenue=1_000e6,
            net_income=90e6,
            assets=2_000e6,
            equity=1_200e6,
            diluted_shares=100e6,
        )
        for offset in range(6)
    ]
    candidate = _candidate(
        make_company("THIN", years=sparse, last_close=12.0, shares_outstanding=100e6),
        cfg,
    )
    text = dossier_for(candidate)

    assert "unavailable" in text
    # Gross margin was never tagged, so it must not appear as a real figure.
    assert "Gross margin latest: unavailable" in text


def test_dossier_never_raises_on_a_value_trap():
    cfg = Config()
    candidate = _candidate(
        make_company("TRAP", years=value_trap(), last_close=3.8,
                     shares_outstanding=623e6),
        cfg,
    )
    text = dossier_for(candidate)
    assert "TRAP" in text
    assert "-- Flags raised by the screen" in text


# ---- prompt assembly ---------------------------------------------------


def test_system_prompt_forbids_inventing_figures():
    lowered = SYSTEM_PROMPT.lower()
    assert "only the figures in the dossier" in lowered
    assert "never state a number that is not there" in lowered
    # It must not be allowed to propose its own position size.
    assert "do not recommend a position size" in lowered


def test_user_message_handles_an_empty_screen():
    from buffett.analysis.screen import ScreenResult

    result = ScreenResult(run_date=TODAY, universe_size=503, analysed=498)
    message = build_user_message(result, [], language="id")

    assert "No candidate cleared the gates" in message
    assert "Return an empty verdict list" in message
    assert "Bahasa Indonesia" in message


def test_user_message_language_switches_to_english():
    from buffett.analysis.screen import ScreenResult

    result = ScreenResult(run_date=TODAY, universe_size=10, analysed=10)
    message = build_user_message(result, [], language="en")
    assert "plain English" in message


def test_user_message_includes_a_dossier_per_candidate():
    from buffett.analysis.screen import ScreenResult

    cfg = Config()
    candidates = [
        _candidate(
            make_company(ticker, years=steady_compounder(), last_close=69.0,
                         shares_outstanding=1_344e6),
            cfg,
        )
        for ticker in ("AAA", "BBB")
    ]
    result = ScreenResult(run_date=TODAY, universe_size=2, analysed=2)
    result.candidates = candidates

    message = build_user_message(result, candidates, language="id")
    assert message.count("=== ") >= 2
    assert "AAA" in message and "BBB" in message
