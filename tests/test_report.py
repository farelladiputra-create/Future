"""Report rendering: formatting conventions, escaping, and the house rules.

The brand rules are enforced here rather than by eye: no em dashes anywhere, no
fabricated zeros where data is missing, Indonesian number separators, and a
basis line naming the source and window up front.
"""

from __future__ import annotations

from datetime import date

from buffett.agent.memo import Memo, Verdict
from buffett.analysis.kelly import size_position
from buffett.analysis.quality import assess_quality
from buffett.analysis.screen import (
    Candidate,
    ScreenResult,
    apply_gates,
    compute_price_stats,
    rank_score,
)
from buffett.analysis.valuation import value_company
from buffett.config import Config
from buffett.fixtures import make_company, steady_compounder, value_trap
from buffett.notify import summary
from buffett.report import format as fmt
from buffett.report import html as html_report
from buffett.report import markdown as md_report

TODAY = date(2026, 8, 17)
EM_DASH = "—"


def _candidate(
    ticker: str, pe: float = 7.0, years=None, sector="Industrials"
) -> Candidate:
    """Build a candidate priced at a given multiple of its own final-year EPS.

    Deriving the price from the fixture's own earnings keeps the share count and
    the per-share figures consistent, which an absolute price would not.
    """
    cfg = Config()
    years = years or steady_compounder()
    shares = years[-1].diluted_shares or 1_000e6
    price = round((years[-1].eps_diluted or 1.0) * pe, 2)
    company = make_company(
        ticker,
        name=f"{ticker} Holdings",
        sector=sector,
        years=years,
        last_close=price,
        shares_outstanding=shares,
    )
    quality = assess_quality(company, 6, cfg.valuation.fallback_tax_rate)
    stats = compute_price_stats(company)
    valuation = value_company(company, quality, cfg.valuation, 6, stats.volatility, {})
    candidate = Candidate(
        company=company,
        quality=quality,
        valuation=valuation,
        sizing=size_position(
            valuation, quality, cfg.kelly, cfg.portfolio, cfg.tranches, TODAY
        ),
        gate=apply_gates(company, quality, valuation, cfg),
        price_stats=stats,
    )
    candidate.rank_score = rank_score(candidate, cfg)
    return candidate


def _result(candidates, rejected=()) -> ScreenResult:
    result = ScreenResult(run_date=TODAY, universe_size=503, analysed=498)
    result.candidates = list(candidates)
    result.rejected = list(rejected)
    result.price_as_of = date(2026, 8, 15)
    return result


def _memo() -> Memo:
    return Memo(
        market_note="Pasar sedang mahal, pilihan yang murah tinggal sedikit.",
        discipline_note="Jangan memaksa beli hanya karena layar ini menemukan sesuatu.",
        verdicts=[
            Verdict(
                ticker="CMPD",
                verdict="buy",
                business_in_one_line="Menjual komponen industri dengan margin stabil.",
                moat="ROIC di atas 30% selama enam tahun.",
                why_it_is_cheap="Sentimen sektor, bukan penurunan earning power.",
                what_would_make_me_wrong=["Margin turun di bawah 20%."],
                questions_before_buying=["Siapa pelanggan terbesarnya?"],
                sizing_comment="Ukuran wajar, tapi jangan ditambah di atas ini.",
                conviction="high",
            )
        ],
        model="claude-opus-5",
        available=True,
    )


# ---- formatting --------------------------------------------------------


def test_indonesian_number_separators():
    assert fmt.number(1234567.891) == "1.234.567,89"
    assert fmt.number(0.5) == "0,50"
    assert fmt.number(-1234.5) == "-1.234,50"
    assert fmt.number(1000, 0) == "1.000"


def test_missing_values_render_as_text_not_zero():
    for rendered in (
        fmt.number(None), fmt.percent(None), fmt.usd(None),
        fmt.multiple(None), fmt.usd_compact(None), fmt.day(None),
        fmt.signed_percent(None),
    ):
        assert rendered == fmt.MISSING
        assert "0" not in rendered


def test_percent_and_signed_percent():
    assert fmt.percent(0.1234) == "12,3%"
    assert fmt.signed_percent(0.05) == "+5,0%"
    assert fmt.signed_percent(-0.05) == "-5,0%"


def test_compact_usd_uses_finance_suffixes():
    assert fmt.usd_compact(12_340_000_000) == "US$ 12,34 B"
    assert fmt.usd_compact(4_500_000) == "US$ 4,50 M"


def test_infinite_coverage_reads_as_no_debt_burden():
    assert fmt.multiple(float("inf")) == "tanpa beban bunga"


def test_dates_use_indonesian_short_months():
    assert fmt.day(date(2026, 8, 17)) == "17 Agu 2026"
    assert fmt.day(date(2026, 5, 1)) == "1 Mei 2026"
    assert fmt.day(date(2026, 12, 31)) == "31 Des 2026"


def test_truncate_cuts_in_code_not_in_css():
    assert fmt.truncate("a" * 40, 34).endswith("…")
    assert len(fmt.truncate("a" * 40, 34)) == 34
    assert fmt.truncate("short", 34) == "short"


# ---- markdown ----------------------------------------------------------


def test_markdown_opens_with_the_basis_and_carries_every_section():
    cfg = Config()
    candidates = [_candidate("CMPD")]
    text = md_report.render(_result(candidates), _memo(), cfg, TODAY)

    assert "**Basis data:**" in text
    assert "SEC EDGAR" in text
    assert "15 Agu 2026" in text  # price as-of date
    for heading in (
        "## Ringkasan", "## Rencana Aksi", "## Peringkat Kandidat",
        "### Valuasi", "### Kualitas Bisnis", "### Sizing Kelly",
        "### Catatan Buffett", "## Batasan",
    ):
        assert heading in text, heading


def test_markdown_has_no_em_dashes():
    cfg = Config()
    text = md_report.render(_result([_candidate("CMPD")]), _memo(), cfg, TODAY)
    assert EM_DASH not in text


def test_markdown_empty_state_says_no_action():
    cfg = Config()
    rejected = [_candidate("TRAP", 9.0, years=value_trap())]
    text = md_report.render(_result([], rejected), Memo(error="no key"), cfg, TODAY)

    assert "Tidak ada satu pun nama yang lolos" in text
    assert "Tidak ada aksi beli" in text
    assert "## Watchlist" in text


def test_markdown_reports_the_tranche_schedule_with_prices_and_dates():
    cfg = Config()
    candidate = _candidate("CMPD")
    assert candidate.sizing.actionable
    text = md_report.render(_result([candidate]), _memo(), cfg, TODAY)

    assert "beli sekarang" in text
    assert "tetap beli per" in text
    for tranche in candidate.sizing.tranches:
        assert fmt.usd(tranche.trigger_price) in text


def test_markdown_names_the_missing_memo_in_the_limitations():
    cfg = Config()
    text = md_report.render(
        _result([_candidate("CMPD")]), Memo(error="tidak ada API key"), cfg, TODAY
    )
    assert "tidak ada API key" in text


# ---- html --------------------------------------------------------------


def test_html_is_self_contained_and_well_formed():
    cfg = Config()
    page = html_report.render(_result([_candidate("CMPD")]), _memo(), cfg, TODAY)

    assert page.startswith("<!doctype html>")
    assert page.rstrip().endswith("</html>")
    # No external requests of any kind.
    for marker in ("http://", "https://", "<script", "localStorage"):
        assert marker not in page, marker


def test_html_has_no_em_dashes():
    cfg = Config()
    page = html_report.render(_result([_candidate("CMPD")]), _memo(), cfg, TODAY)
    assert EM_DASH not in page


def test_html_paints_background_and_ink_explicitly():
    cfg = Config()
    page = html_report.render(_result([_candidate("CMPD")]), _memo(), cfg, TODAY)
    assert "background:var(--bg)" in page
    assert "--ink:#0F1B2D" in page
    # No drop shadows, per the house rules.
    assert "box-shadow" not in page


def test_html_kpi_cards_share_one_fixed_row_template():
    """Fixed rows are what keep sibling cards aligned when labels wrap."""
    cfg = Config()
    page = html_report.render(_result([_candidate("CMPD")]), _memo(), cfg, TODAY)
    assert "grid-template-rows:20px 46px 20px" in page


def test_html_escapes_company_names():
    cfg = Config()
    candidate = _candidate("EVIL")
    candidate.company.name = '<script>alert("x")</script> & Co'
    page = html_report.render(_result([candidate]), _memo(), cfg, TODAY)

    assert "<script>alert" not in page
    assert "&lt;script&gt;" in page or "&amp;" in page


def test_html_marks_the_top_candidate_with_the_brand_border():
    cfg = Config()
    page = html_report.render(
        _result([_candidate("AAA"), _candidate("BBB", 7.5)]), _memo(), cfg, TODAY
    )
    assert 'class="card primary"' in page
    assert "--brand:#003781" in page


def test_html_empty_state_renders_without_a_ranking_table():
    cfg = Config()
    page = html_report.render(_result([]), Memo(error="no key"), cfg, TODAY)
    assert "Tidak Ada Kandidat Malam Ini" in page
    assert "Peringkat Kandidat" not in page


def test_html_always_carries_the_limitations_and_footer():
    cfg = Config()
    page = html_report.render(_result([_candidate("CMPD")]), _memo(), cfg, TODAY)
    assert "Batasan" in page
    assert "Bukan nasihat investasi" in page
    assert "SEC EDGAR companyfacts" in page


def test_wide_tables_scroll_inside_their_own_container():
    cfg = Config()
    page = html_report.render(_result([_candidate("CMPD")]), _memo(), cfg, TODAY)
    assert "overflow-x:auto" in page
    assert 'class="scroll"' in page


# ---- notification summary ---------------------------------------------


def test_summary_fits_the_telegram_limit():
    cfg = Config()
    many = [_candidate(f"T{i}") for i in range(5)]
    text = summary.build(_result(many), _memo(), cfg)

    assert len(text) <= summary.MAX_LENGTH
    assert EM_DASH not in text


def test_summary_leads_with_the_decision():
    cfg = Config()
    candidate = _candidate("CMPD")
    text = summary.build(_result([candidate]), _memo(), cfg)

    assert "CMPD" in text
    assert "beli" in text
    assert fmt.percent(candidate.valuation.margin_of_safety) in text


def test_summary_says_nothing_to_do_when_the_screen_is_empty():
    cfg = Config()
    text = summary.build(_result([]), Memo(error="no key"), cfg)
    assert "Tidak ada aksi beli" in text
