"""EDGAR XBRL parsing: period alignment, restatements, concept backfill."""

from __future__ import annotations

from datetime import date

from buffett.data.edgar import DURATION_CONCEPTS, parse_companyfacts
from buffett.fixtures import build_companyfacts

# The element the fixture builder tags revenue under: the head of the priority
# list, which is what a modern filer actually uses.
PRIMARY_REVENUE = DURATION_CONCEPTS["revenue"][0]


def _year(end: str, **overrides):
    row = {
        "end": end,
        "revenue": 1000.0,
        "net_income": 100.0,
        "assets": 2000.0,
        "equity": 1200.0,
        "cfo": 150.0,
        "capex": 50.0,
        "diluted_shares": 10.0,
    }
    row.update(overrides)
    return row


def test_parses_annual_periods_oldest_first():
    payload = build_companyfacts(
        [_year("2023-12-31", revenue=900.0), _year("2024-12-31", revenue=1000.0)]
    )
    years, _ = parse_companyfacts(payload)

    assert [y.period_end for y in years] == [date(2023, 12, 31), date(2024, 12, 31)]
    assert years[0].revenue == 900.0
    assert years[1].revenue == 1000.0
    assert years[1].label == 2024


def test_balance_sheet_instants_align_to_income_statement_periods():
    payload = build_companyfacts([_year("2024-12-31", assets=2500.0, equity=1500.0)])
    years, _ = parse_companyfacts(payload)

    assert years[0].assets == 2500.0
    assert years[0].equity == 1500.0
    # Liabilities were never tagged, so the accounting identity fills them.
    assert years[0].liabilities == 1000.0


def test_quarterly_facts_are_ignored():
    payload = build_companyfacts([_year("2024-12-31")])
    quarter = {
        "start": "2024-10-01",
        "end": "2024-12-31",
        "val": 250.0,
        "form": "10-Q",
        "filed": "2025-01-20",
        "fy": 2024,
        "fp": "Q4",
    }
    payload["facts"]["us-gaap"][PRIMARY_REVENUE]["units"]["USD"].append(quarter)

    years, _ = parse_companyfacts(payload)
    # The annual figure survives; the 90-day period is filtered out.
    assert len(years) == 1
    assert years[0].revenue == 1000.0


def test_latest_filing_wins_for_restated_periods():
    payload = build_companyfacts([_year("2024-12-31", revenue=1000.0)])
    restated = {
        "start": "2024-01-02",
        "end": "2024-12-31",
        "val": 1100.0,
        "form": "10-K",
        "filed": "2026-02-15",  # filed later than the original
        "fy": 2024,
        "fp": "FY",
    }
    payload["facts"]["us-gaap"][PRIMARY_REVENUE]["units"]["USD"].append(restated)

    years, _ = parse_companyfacts(payload)
    assert years[0].revenue == 1100.0


def test_later_concepts_backfill_years_the_first_one_misses():
    """A filer that switched revenue elements mid-history keeps a full series."""
    payload = build_companyfacts(
        [_year("2023-12-31"), _year("2024-12-31")]
    )
    usd = payload["facts"]["us-gaap"]
    # Drop 2023 from the primary element and re-tag that year under a
    # lower-priority one, as a filer that changed elements mid-history would.
    facts = usd[PRIMARY_REVENUE]["units"]["USD"]
    usd[PRIMARY_REVENUE]["units"]["USD"] = [
        f for f in facts if f["end"] != "2023-12-31"
    ]
    usd["Revenues"] = {
        "units": {
            "USD": [
                {
                    "start": "2023-01-01",
                    "end": "2023-12-31",
                    "val": 880.0,
                    "form": "10-K",
                    "filed": "2024-02-14",
                    "fy": 2023,
                    "fp": "FY",
                }
            ]
        }
    }

    years, _ = parse_companyfacts(payload)
    assert len(years) == 2
    assert years[0].revenue == 880.0
    assert years[1].revenue == 1000.0


def test_dei_cover_page_shares_are_returned():
    payload = build_companyfacts([_year("2024-12-31")], dei_shares=12.5)
    _, shares = parse_companyfacts(payload)
    assert shares == 12.5


def test_eps_is_derived_when_untagged():
    payload = build_companyfacts(
        [_year("2024-12-31", net_income=500.0, diluted_shares=100.0)]
    )
    years, _ = parse_companyfacts(payload)
    assert years[0].eps_diluted == 5.0


def test_53_week_fiscal_year_still_parses():
    """Retail calendars run 52 or 53 weeks, not exactly 365 days."""
    payload = build_companyfacts([_year("2025-02-01")])
    facts = payload["facts"]["us-gaap"][PRIMARY_REVENUE]["units"]["USD"]
    facts[0]["start"] = "2024-01-28"  # 370 days
    years, _ = parse_companyfacts(payload)
    assert len(years) == 1


def test_no_annual_data_returns_empty():
    years, shares = parse_companyfacts({"facts": {"us-gaap": {}}})
    assert years == []
    assert shares is None


def test_two_period_ends_inside_one_year_collapse_to_one():
    """A transition period must not be counted as a second fiscal year."""
    payload = build_companyfacts(
        [_year("2024-12-31"), _year("2024-06-30", revenue=480.0)]
    )
    years, _ = parse_companyfacts(payload)
    # Anchors cluster newest-first, so the December period is kept.
    assert len(years) == 1
    assert years[0].period_end == date(2024, 12, 31)
