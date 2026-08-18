"""System prompt and dossier construction for the memo layer.

The model's job is judgement, not arithmetic. Every number it sees has already
been computed from audited filings, and the prompt forbids inventing any figure
that is not in the dossier. That constraint matters more than the voice: a memo
that sounds like Buffett while quoting a made-up margin is worse than no memo.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # avoid a circular import at runtime
    from ..analysis.screen import Candidate, ScreenResult

SYSTEM_PROMPT = """\
You are writing an evening investment memo in the voice and method of Warren \
Buffett, for a single private investor who has asked you to think the way he does.

Method, in priority order:
1. Circle of competence. If a business is genuinely hard to understand from the \
data provided, say so and pass. Passing is a respectable answer and most \
evenings it is the right one.
2. Business quality first, price second. A wonderful business at a fair price \
beats a fair business at a wonderful price. A statistically cheap company with \
deteriorating accounts is a value trap, not a bargain.
3. Margin of safety. You are being paid to avoid permanent loss of capital, not \
to be clever. If the discount is thin, say the discount is thin.
4. Long holding periods. Assume the position is held for years, and judge the \
business on whether its earning power will still be intact then.
5. Owner's mindset. Read the numbers as a part-owner would: what happens to \
cash, what happens to the share count, and what management does with retained \
earnings.

Voice: plain, direct, concrete. Short sentences. Homely analogies are welcome \
where they clarify. No jargon for its own sake, no hedging that carries no \
information, no hype. Be willing to say "I don't know" and "this is outside \
what I can judge from these filings".

Hard rules, which override the voice:
- Use ONLY the figures in the dossier. Never state a number that is not there, \
never estimate one, and never round in a way that changes its meaning.
- The dossier contains no news, no management commentary and no competitive \
detail. Do not pretend otherwise. Where your judgement would need information \
the dossier lacks, name the missing information as a question the investor must \
answer before buying.
- Where a metric is marked unavailable, treat it as unknown, not as zero or \
average.
- Do not recommend a position size. Sizing has already been computed by a \
fractional Kelly rule; your job is to say whether the reasoning behind it holds \
and to flag anything that should make it smaller.
- Never claim certainty about the future. Say what would have to be true.
"""

LANGUAGE_INSTRUCTIONS = {
    "id": (
        "Write the prose in natural Bahasa Indonesia, the way a sharp Indonesian "
        "investor would actually write to himself. Keep finance and accounting "
        "terms in English where that is normal usage (margin of safety, free cash "
        "flow, payout ratio, moat, owner earnings, book value). Do not translate "
        "ticker symbols or metric names. Avoid stiff or textbook phrasing."
    ),
    "en": "Write the prose in plain English.",
}


def _pct(value: float | None, digits: int = 1) -> str:
    return "unavailable" if value is None else f"{value * 100:.{digits}f}%"


def _num(value: float | None, digits: int = 2) -> str:
    return "unavailable" if value is None else f"{value:,.{digits}f}"


def _money(value: float | None) -> str:
    if value is None:
        return "unavailable"
    for cutoff, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(value) >= cutoff:
            return f"${value / cutoff:,.2f}{suffix}"
    return f"${value:,.0f}"


def _multiple(value: float | None) -> str:
    if value is None:
        return "unavailable"
    if value == float("inf"):
        return "no debt service"
    return f"{value:.2f}x"


def dossier_for(candidate: "Candidate") -> str:
    """A complete, plainly labelled fact sheet for one company."""
    company, quality, valuation, sizing = (
        candidate.company,
        candidate.quality,
        candidate.valuation,
        candidate.sizing,
    )
    stats, dividend = candidate.price_stats, quality.dividend
    latest = company.latest

    lines: list[str] = [
        f"=== {company.ticker}: {company.name} ===",
        f"Sector: {company.sector} (SIC {company.sic or 'unknown'})",
        f"Market capitalisation: {_money(company.market_cap)}",
        f"Price: {_num(valuation.price)} as of {stats.as_of or 'unknown'} "
        f"(source: {stats.source or 'unavailable'})",
        f"Annual periods parsed from 10-K filings: {quality.years_available}",
        f"Latest fiscal period ends: {latest.period_end if latest else 'unknown'}",
        "",
        "-- Valuation",
        f"Intrinsic value per share, blended base case: {_num(valuation.iv_base)}",
        f"  discounted owner earnings: {_num(valuation.iv_dcf)}",
        f"  earnings power value (zero growth): {_num(valuation.iv_epv)}",
        f"  normalised multiple: {_num(valuation.iv_multiple)}",
        f"  Graham number: {_num(valuation.iv_graham)}",
        f"  book value per share: {_num(valuation.iv_book)}",
        f"Bear-case floor per share: {_num(valuation.iv_bear)}",
        f"Bull case per share: {_num(valuation.iv_bull)}",
        f"MARGIN OF SAFETY: {_pct(valuation.margin_of_safety)}",
        f"Upside to base case: {_pct(valuation.upside)}",
        f"Agreement between methods (1.0 = tight, 0.2 = wide): "
        f"{_num(valuation.confidence, 2)}",
        f"Discount rate used: {_pct(valuation.discount_rate)}",
        f"Stage-one growth assumed: {_pct(valuation.growth_stage1)}, "
        f"fading to {_pct(valuation.terminal_growth)}",
        f"Owner earnings, normalised: {_money(valuation.owner_earnings_base)} "
        f"({_num(valuation.owner_earnings_per_share)} per share)",
        f"Historical owner earnings growth: {_pct(valuation.owner_earnings_growth)}",
        "",
        "-- Multiples",
        f"P/E trailing: {_multiple(valuation.pe_trailing)}",
        f"P/E on normalised earnings: {_multiple(valuation.pe_normalized)}",
        f"Own long-run median P/E: {_multiple(valuation.pe_hist_median)}",
        f"P/B: {_multiple(valuation.pbv)}",
        f"P/tangible book: {_multiple(valuation.ptbv)}",
        f"P/S: {_multiple(valuation.ps)}",
        f"EV/EBIT: {_multiple(valuation.ev_ebit)}",
        f"Free cash flow yield: {_pct(valuation.fcf_yield)}",
        f"Earnings yield: {_pct(valuation.earnings_yield)}",
        f"Owner earnings yield: {_pct(valuation.owner_earnings_yield)}",
        "",
        "-- Business quality",
        f"Composite quality score: {_num(quality.score, 1)} of 100",
        f"Piotroski F-Score: {quality.piotroski_f if quality.piotroski_f is not None else 'unavailable'} of 9"
        f" (decision-grade: {quality.piotroski_reliable})",
        f"Altman Z-Score: {_num(quality.altman_z)} ({quality.altman_zone})",
        f"Beneish M-Score: {_num(quality.beneish_m)} "
        f"(decision-grade: {quality.beneish_reliable}; "
        f"above -1.78 suggests earnings manipulation)",
        f"Average return on equity: {_pct(quality.avg_roe)}",
        f"Average return on invested capital: {_pct(quality.avg_roic)}",
        f"Return on equity variability (lower is steadier): "
        f"{_num(quality.roe_stability, 2)}",
        f"Gross margin latest: {_pct(quality.gross_margin_latest)}",
        f"Operating margin latest: {_pct(quality.operating_margin_latest)}",
        f"Revenue growth: {_pct(quality.revenue_cagr)}",
        f"Earnings per share growth: {_pct(quality.eps_cagr)}",
        f"Diluted share count change per year: {_pct(quality.share_count_cagr)}",
        f"Profitable years: {quality.positive_earnings_years} of {quality.years_available}",
        f"Positive free cash flow years: {quality.positive_fcf_years} of "
        f"{quality.years_available}",
        "",
        "-- Balance sheet",
        f"Debt to equity: {_multiple(quality.debt_to_equity)}",
        f"Net debt to EBIT: {_multiple(quality.net_debt_to_ebit)}",
        f"Interest coverage: {_multiple(quality.interest_coverage)}",
        f"Current ratio: {_multiple(quality.current_ratio)}",
        f"Net cash position: {_money(latest.net_cash if latest else None)}",
        "",
        "-- Dividend",
        f"Yield: {_pct(dividend.yield_pct)}",
        f"Dividend per share: {_num(dividend.dps_latest)}",
        f"Payout ratio: {_pct(dividend.payout_ratio)}",
        f"Consecutive paying years in the parsed history: {dividend.paying_years}",
        f"Consecutive increases: {dividend.growth_years}",
        f"Dividend growth: {_pct(dividend.dps_cagr)}",
        f"Covered by free cash flow: {dividend.covered_by_fcf}",
        "",
        "-- Price behaviour",
        f"52-week range: {_num(stats.week52_low)} to {_num(stats.week52_high)}",
        f"Decline from 52-week high: {_pct(stats.drawdown_from_high)}",
        f"One-year price change: {_pct(stats.return_1y)}",
        f"Annualised volatility: {_pct(stats.volatility)}",
        "",
        "-- Sizing already computed (fractional Kelly)",
        f"Modelled win probability: {_pct(sizing.win_probability)}",
        f"Upside if right: {_pct(sizing.upside)}, "
        f"loss to bear floor if wrong: {_pct(sizing.downside)}",
        f"Full Kelly stake: {_pct(sizing.kelly_full)}",
        f"Stake after halving and caps: {_pct(sizing.target_weight)} of the "
        f"invested sleeve, {_money(sizing.target_usd)}",
        f"Constraint that bound: {sizing.capped_by or 'none'}",
    ]

    if sizing.tranches:
        lines.append("Entry schedule:")
        for tranche in sizing.tranches:
            timing = "now" if tranche.is_immediate else f"or by {tranche.fallback_date}"
            lines.append(
                f"  tranche {tranche.index}: {_money(tranche.usd_amount)} "
                f"({tranche.fraction * 100:.0f}%) at {_num(tranche.trigger_price)} "
                f"or better, which is a {_pct(tranche.target_margin_of_safety)} "
                f"margin of safety, {timing}"
            )

    if quality.flags:
        lines.append("")
        lines.append("-- Flags raised by the screen")
        lines.extend(f"  - {flag}" for flag in quality.flags)

    notes = list(valuation.notes) + list(company.notes) + list(sizing.notes)
    if notes:
        lines.append("")
        lines.append("-- Method notes and data caveats")
        lines.extend(f"  - {note}" for note in notes)

    if candidate.gate.waived:
        lines.append("")
        lines.append("-- Gates waived for this filer")
        lines.extend(f"  - {item}" for item in candidate.gate.waived)

    return "\n".join(lines)


def build_user_message(
    result: "ScreenResult", candidates: list["Candidate"], language: str
) -> str:
    """The full evening briefing request sent to the model."""
    language_note = LANGUAGE_INSTRUCTIONS.get(language, LANGUAGE_INSTRUCTIONS["en"])

    header = [
        f"Screen run date: {result.run_date}.",
        f"Prices as of: {result.price_as_of or 'unknown'} "
        "(US markets, most recent completed session).",
        f"Universe screened: {result.universe_size} symbols, "
        f"{result.analysed} with filings parsed successfully.",
        f"Passed every quality and margin-of-safety gate: {len(result.candidates)}.",
        f"Rejected: {len(result.rejected)}.",
        "",
        language_note,
        "",
        "Below are the candidates that survived the screen, best-ranked first. "
        "For each, give your judgement. Then give one short note on the screen as "
        "a whole and one note on discipline for this investor tonight.",
        "",
    ]

    if not candidates:
        header.append(
            "No candidate cleared the gates tonight. Say so plainly, explain what "
            "that usually means, and tell the investor what to do with the "
            "evening instead. Return an empty verdict list."
        )
        if result.rejected:
            header.append("")
            header.append(
                "For context, the closest names and why each was turned down:"
            )
            for candidate in result.rejected[:8]:
                reasons = "; ".join(candidate.gate.failures[:3])
                header.append(f"  - {candidate.ticker} ({candidate.sector}): {reasons}")
        return "\n".join(header)

    body = [dossier_for(candidate) for candidate in candidates]
    if result.portfolio_messages:
        body.append("=== Portfolio-level adjustments applied ===")
        body.extend(f"  - {message}" for message in result.portfolio_messages)

    return "\n".join(header) + "\n\n" + "\n\n".join(body)


# Structured-output schema. Forcing the memo into a fixed shape means the report
# renderer never has to parse prose, and a malformed memo fails loudly at the API
# boundary instead of silently producing an empty section.
#
# Structured outputs require `additionalProperties: false` on every object and
# every property listed in `required`, so there are no optional fields here.
MEMO_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "market_note": {
            "type": "string",
            "description": (
                "Two or three sentences on what tonight's screen output says about "
                "the market. No predictions."
            ),
        },
        "discipline_note": {
            "type": "string",
            "description": (
                "One or two sentences of plain advice on temperament for this "
                "investor tonight: what not to do."
            ),
        },
        "verdicts": {
            "type": "array",
            "description": (
                "One entry per candidate supplied, in the order given. Empty when "
                "no candidate cleared the screen."
            ),
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "ticker": {"type": "string"},
                    "verdict": {
                        "type": "string",
                        "enum": ["buy", "watch", "pass"],
                        "description": (
                            "buy only if you would put your own money in at the "
                            "stated price; watch if the business is good but "
                            "something is unresolved; pass otherwise."
                        ),
                    },
                    "business_in_one_line": {
                        "type": "string",
                        "description": (
                            "What this company does and how it makes money, in one "
                            "sentence, from the dossier only."
                        ),
                    },
                    "moat": {
                        "type": "string",
                        "description": (
                            "What the returns on capital in the dossier suggest "
                            "about durable advantage, and how confident that "
                            "inference can be. Say so if the data cannot tell you."
                        ),
                    },
                    "why_it_is_cheap": {
                        "type": "string",
                        "description": (
                            "The most likely reason the market is pricing it here, "
                            "based only on the figures given."
                        ),
                    },
                    "what_would_make_me_wrong": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "Two to four specific, checkable things that would break "
                            "the thesis, including information the dossier lacks."
                        ),
                    },
                    "questions_before_buying": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "What the investor must go and find out, since the "
                            "dossier has no news or management commentary."
                        ),
                    },
                    "sizing_comment": {
                        "type": "string",
                        "description": (
                            "Whether the computed Kelly stake looks sane given the "
                            "business, and whether it should be smaller. Do not "
                            "propose a number."
                        ),
                    },
                    "conviction": {"type": "string", "enum": ["high", "medium", "low"]},
                },
                "required": [
                    "ticker",
                    "verdict",
                    "business_in_one_line",
                    "moat",
                    "why_it_is_cheap",
                    "what_would_make_me_wrong",
                    "questions_before_buying",
                    "sizing_comment",
                    "conviction",
                ],
            },
        },
    },
    "required": ["market_note", "discipline_note", "verdicts"],
}
