"""Gates, ranking, and a full offline pipeline run against a stubbed network."""

from __future__ import annotations

from datetime import date


from buffett.analysis.quality import assess_quality
from buffett.analysis.screen import (
    Candidate,
    apply_gates,
    compute_price_stats,
    rank_score,
    run_screen,
)
from buffett.analysis.valuation import value_company
from buffett.config import Config, load_config
from buffett.fixtures import (
    FixtureFiler,
    FixtureHttpClient,
    facts_from_years,
    make_company,
    steady_compounder,
    value_trap,
)

TODAY = date(2026, 8, 17)


def _analyse(company, cfg: Config):
    lookback = max(cfg.gates.min_years_history, 5)
    quality = assess_quality(company, lookback, cfg.valuation.fallback_tax_rate)
    valuation = value_company(company, quality, cfg.valuation, lookback, 0.0, {})
    gate = apply_gates(company, quality, valuation, cfg)
    return quality, valuation, gate


def test_cheap_compounder_clears_every_gate():
    cfg = Config()
    company = make_company(
        "GOOD", years=steady_compounder(), last_close=12.0, shares_outstanding=930e6
    )
    _, valuation, gate = _analyse(company, cfg)

    assert gate.passed, gate.failures
    assert valuation.margin_of_safety >= cfg.valuation.min_margin_of_safety


def test_the_same_business_fails_on_price_alone_when_expensive():
    cfg = Config()
    company = make_company(
        "GOOD", years=steady_compounder(), last_close=400.0, shares_outstanding=930e6
    )
    _, _, gate = _analyse(company, cfg)

    assert not gate.passed
    assert any("margin of safety" in reason for reason in gate.failures)


def test_value_trap_is_rejected_for_business_reasons_not_price():
    cfg = Config()
    company = make_company(
        "BAD", years=value_trap(), last_close=4.0, shares_outstanding=500e6
    )
    _, _, gate = _analyse(company, cfg)

    assert not gate.passed
    joined = " | ".join(gate.failures)
    # Dilution, weak returns or thin cash flow, not just an unattractive price.
    assert any(
        term in joined
        for term in ("share count", "return on", "free cash flow", "Piotroski")
    )


def test_small_caps_are_excluded():
    cfg = Config()
    cfg.universe.min_market_cap_usd = 50e9
    company = make_company(
        "GOOD", years=steady_compounder(), last_close=12.0, shares_outstanding=930e6
    )
    _, _, gate = _analyse(company, cfg)

    assert not gate.passed
    assert any("market cap" in reason for reason in gate.failures)


def test_excluded_sector_is_outside_the_circle_of_competence():
    cfg = Config()
    cfg.universe.exclude_sectors = ["Energy"]
    company = make_company(
        "OIL", sector="Energy", years=steady_compounder(),
        last_close=12.0, shares_outstanding=930e6,
    )
    _, _, gate = _analyse(company, cfg)

    assert not gate.passed
    assert any("circle of competence" in reason for reason in gate.failures)


def test_leverage_gates_are_waived_for_a_lender():
    cfg = Config()
    years = steady_compounder()
    # Leverage a bank would carry as a matter of course.
    for year in years:
        year.long_term_debt = year.revenue * 3.0
        year.interest_expense = year.revenue * 0.12

    bank = make_company(
        "BANK", sector="Financials", years=years, last_close=12.0, shares_outstanding=930e6
    )
    operating = make_company(
        "MFG", sector="Industrials", years=years, last_close=12.0, shares_outstanding=930e6
    )

    _, _, bank_gate = _analyse(bank, cfg)
    _, _, operating_gate = _analyse(operating, cfg)

    assert any("waived" in note for note in bank_gate.waived)
    assert not any("debt to equity" in reason for reason in bank_gate.failures)
    # The identical balance sheet in an operating company does fail.
    assert any("debt to equity" in reason for reason in operating_gate.failures)


def test_missing_data_fails_the_gate_rather_than_passing_quietly():
    cfg = Config()
    years = steady_compounder(count=6)
    for year in years:
        year.cfo = None
        year.capex = None
    company = make_company("THIN", years=years, last_close=12.0, shares_outstanding=930e6)
    _, _, gate = _analyse(company, cfg)

    assert not gate.passed
    joined = " | ".join(gate.failures)
    assert "line items" in joined or "free cash flow" in joined


def test_too_few_years_of_history_fails():
    cfg = Config()
    company = make_company(
        "NEW", years=steady_compounder(count=3), last_close=12.0, shares_outstanding=930e6
    )
    _, _, gate = _analyse(company, cfg)

    assert not gate.passed
    assert any("annual periods on file" in reason for reason in gate.failures)


def test_rank_score_is_bounded_and_rewards_cheapness():
    cfg = Config()
    cheap = make_company(
        "CHEAP", years=steady_compounder(), last_close=10.0, shares_outstanding=930e6
    )
    dearer = make_company(
        "DEAR", years=steady_compounder(), last_close=22.0, shares_outstanding=930e6
    )

    scores = []
    for company in (cheap, dearer):
        quality, valuation, gate = _analyse(company, cfg)
        candidate = Candidate(
            company=company, quality=quality, valuation=valuation,
            sizing=None, gate=gate, price_stats=compute_price_stats(company),
        )
        score = rank_score(candidate, cfg)
        assert 0.0 <= score <= 100.0
        scores.append(score)

    assert scores[0] > scores[1]


# ---- offline end-to-end -------------------------------------------------


def test_full_pipeline_runs_offline_and_separates_good_from_bad():
    """End to end with no network: fixtures in, ranked candidates out."""
    filers = [
        FixtureFiler(
            ticker="GOOD",
            cik="0000000001",
            facts=facts_from_years(steady_compounder(), 930e6),
            sic="3570",  # Information Technology
            price=12.0,
        ),
        FixtureFiler(
            ticker="BAD",
            cik="0000000002",
            facts=facts_from_years(value_trap(), 500e6),
            sic="3310",  # Materials
            price=4.0,
        ),
    ]
    client = FixtureHttpClient(filers)
    cfg = load_config()
    cfg.data.max_workers = 1

    result = run_screen(client, cfg, ["GOOD", "BAD"], today=TODAY)

    assert result.errors == {}
    assert result.analysed == 2
    assert [c.ticker for c in result.candidates] == ["GOOD"]
    assert [c.ticker for c in result.rejected] == ["BAD"]

    winner = result.candidates[0]
    assert winner.company.sector == "Information Technology"
    assert winner.valuation.margin_of_safety > 0
    assert winner.sizing.actionable
    assert winner.sizing.tranches
    assert winner.rank_score > 0
    assert result.price_as_of is not None


def test_unknown_symbols_are_reported_not_silently_dropped():
    client = FixtureHttpClient(
        [
            FixtureFiler(
                ticker="GOOD",
                cik="0000000001",
                facts=facts_from_years(steady_compounder(), 930e6),
                sic="3570",
                price=12.0,
            )
        ]
    )
    cfg = load_config()
    cfg.data.max_workers = 1

    result = run_screen(client, cfg, ["GOOD", "NOPE"], today=TODAY)

    assert "NOPE" in result.errors
    assert "no CIK" in result.errors["NOPE"]
    assert result.analysed == 1


def test_portfolio_caps_are_applied_across_the_ranked_book():
    """Several identical cheap names in one sector must be trimmed together."""
    filers = [
        FixtureFiler(
            ticker=f"G{index}",
            cik=f"000000000{index + 1}",
            facts=facts_from_years(steady_compounder(), 930e6),
            sic="3570",
            price=12.0,
        )
        for index in range(4)
    ]
    cfg = load_config()
    cfg.data.max_workers = 1

    result = run_screen(
        FixtureHttpClient(filers), cfg, [f.ticker for f in filers], today=TODAY
    )

    assert len(result.candidates) == 4
    exposure = sum(c.sizing.target_weight for c in result.candidates)
    assert exposure <= cfg.kelly.max_sector_exposure + 1e-6
    assert result.portfolio_messages
