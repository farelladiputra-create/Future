# Buffett agent

A value-investing screener and nightly briefing for US equities. Runs at 21:00
Asia/Jakarta, reads audited annual filings, values every name four different
ways, sizes positions with fractional Kelly, and writes you a memo in Buffett's
voice about what it found.

The design premise is that the hard part is not finding cheap stocks. It is
avoiding the cheap ones that deserve to be cheap, and then not betting too much
on the ones that don't. Most evenings the honest answer is "nothing to buy", and
the report says so plainly rather than manufacturing a recommendation.

## What it does each night

```
S&P 500 universe
      │
      ▼
SEC EDGAR companyfacts (XBRL)          Yahoo / Stooq daily closes
  10 years of 10-K income statement,     5 years of adjusted closes
  balance sheet, cash flow                    │
      │                                       │
      └───────────────┬───────────────────────┘
                      ▼
             Quality assessment
   Piotroski F · Altman Z · Beneish M · ROIC · dividend record
                      │
                      ▼
          Intrinsic value, four ways
   discounted owner earnings · earnings power value
   normalised multiple · Graham number
                      │
                      ▼
              Hard quality gates
   fail any one and the name is never recommended, at any price
                      │
                      ▼
        Margin of safety vs the blend
                      │
                      ▼
        Fractional Kelly position size
   then sector caps, total-exposure cap, tranche schedule
                      │
                      ▼
            Claude Opus 5 memo
   business quality, moat, what would make the thesis wrong
                      │
                      ▼
   Markdown + HTML + JSON reports, Telegram push, email
```

## Quick start

See it work with no API keys and no network:

```bash
pip install -r requirements.txt
python -m buffett.run --offline --print-summary --output-dir /tmp/demo
open /tmp/demo/latest.html
```

That runs the entire pipeline against four synthetic filers: two that clear
every gate at different discounts, one quality business priced too richly, and
one value trap. It exercises the report, the watchlist, and the rejection
reasons.

Then a real run against a handful of names:

```bash
export SEC_USER_AGENT="Your Name your@email.com"   # SEC requires a real contact
python -m buffett.run --tickers KO,PG,JNJ,UNH,BRK-B
```

And the full universe:

```bash
python -m buffett.run
```

The first full run fetches a few hundred EDGAR documents and takes a few
minutes. Everything is cached under `.cache/`, so later runs mostly re-fetch
prices only.

## Setting up the 21:00 Jakarta schedule

`.github/workflows/daily-brief.yml` is already wired for it. Jakarta is UTC+7
with no daylight saving, so 21:00 JKT is always 14:00 UTC:

```yaml
- cron: "0 14 * * 2-6"
```

**Tuesday through Saturday, not Monday through Friday.** At 21:00 JKT the New
York close has not happened yet that day: it lands at 20:00 UTC in summer and
21:00 UTC in winter, both after the 14:00 UTC run. So a Tuesday run reads
Monday's close, a Saturday run reads Friday's, and a Monday run would only
re-read the Friday close that Saturday already covered. `tests/test_schedule.py`
pins this so an edit cannot silently break it.

To enable it, push to GitHub and set the repository secrets below. The workflow
commits each report back to `reports/` and also uploads it as an artifact.

Running it on your own machine instead:

```cron
0 21 * * 2-6  cd /path/to/repo && /usr/bin/python3 -m buffett.run >> run.log 2>&1
```

Local cron uses your machine's clock, so `21` is already Jakarta time if the
machine is set to WIB. No conversion needed, unlike the GitHub Actions cron.

## Environment variables

Only `SEC_USER_AGENT` is genuinely required. Everything else degrades quietly:
no Anthropic key means no memo but the full quantitative report still ships, and
no Telegram token means it writes files without pushing.

| Variable | Purpose |
|---|---|
| `SEC_USER_AGENT` | Your name and email. SEC blocks clients that do not identify themselves. |
| `ANTHROPIC_API_KEY` | Enables the Buffett memo layer. Without it, `agent.enabled` turns itself off. |
| `PORTFOLIO_EQUITY_USD` | Overrides `portfolio.equity_usd` so your real position size never sits in a committed file. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Nightly push to your phone. Message `@BotFather` to create a bot, send it one message, then read the chat id from `getUpdates`. |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `REPORT_EMAIL_TO` | Emails the full HTML brief. Port 587 uses STARTTLS, anything else uses SSL. |
| `BUFFETT_MODEL` | Override the memo model. Defaults to `claude-opus-5`. |
| `BUFFETT_DISABLE_AGENT=1` | Skip the memo without removing the key. |

## The method

### Owner earnings, not net income

Buffett's 1986 letter defines owner earnings as reported earnings plus
depreciation and other non-cash charges, less the capitalised expenditure the
business requires to maintain its competitive position. The engine builds this
as cash flow from operations less *maintenance* capex, separating maintenance
from growth capex using Greenwald's decomposition: the PP&E intensity of the
business applied to the revenue it added is growth spend, and what remains is
what the business must spend to stand still.

For lenders and property owners this construction is meaningless, since their
real reinvestment runs through the loan book rather than PP&E. Those filers fall
back to net income and the report says so.

### Four valuations, and the spread between them is the signal

| Method | What it assumes |
|---|---|
| Discounted owner earnings | Growth fades linearly from a haircut historical rate to 2.5% over ten years |
| Earnings power value (Greenwald) | Zero growth, ever. Normalised operating margin capitalised at the discount rate |
| Normalised multiple | The filer's own long-run median P/E, capped at Graham's 15x |
| Graham number | `sqrt(22.5 x EPS x book value per share)` |

The blend is the base case. The spread between the three going-concern methods
becomes a `confidence` figure, which then throttles position size: when the
methods disagree violently, the valuation is a guess dressed as a number, and
Kelly sizes it down automatically.

Graham's number and book value are deliberately conservative *floors*, so they
are excluded from the dispersion calculation. Including them would peg every
growing business at minimum confidence for structural rather than informational
reasons.

### Forensic accounting before valuation

Three published scores do most of the gatekeeping:

- **Piotroski F-Score** (0 to 9) grades nine signals of improving financial
  strength: profitability, cash-flow quality, leverage, liquidity, dilution,
  margins, asset turnover.
- **Altman Z-Score** estimates distance from bankruptcy. Below 1.81 is the
  distress zone.
- **Beneish M-Score** flags the accounting profile typical of earnings
  manipulation. Above `-1.78` is a walk-away, not a discount.

Each is computed only from what the filer actually tagged, and each reports
whether it had enough real inputs to be decision-grade. A score assembled mostly
from neutral defaults is discarded rather than acted on.

For banks and property owners, the leverage and Altman gates are waived, because
borrowing is the product and Altman was calibrated on manufacturers. The report
lists every waiver.

### Position sizing: fractional Kelly with a partial-loss correction

The textbook Kelly stake, `f* = (p·b − q)/b`, assumes a losing bet forfeits the
entire stake. An equity position does not: a thesis that fails usually leaves the
shares worth something. Maximising `p·ln(1 + f·g) + q·ln(1 − f·l)` for gain
fraction `g` and loss fraction `l` gives the form used here:

```
f* = (p·g − q·l) / (g·l) = p/l − q/g
```

which collapses to the textbook version when `l = 1`. The distinction is not
academic: with 100% upside and 50% downside at `p = 0.6`, the textbook form says
stake 40% while the correct figure is 80%. Partial-loss Kelly is far more
aggressive than most people expect, which is exactly why the caps below are not
optional.

- `g` is the gap to the blended intrinsic value.
- `l` is the drop to the bear-case floor, being the most pessimistic
  going-concern estimate. Tangible book joins the candidates only when the
  balance sheet is the story: a book-value business, or an Altman score outside
  the safe zone. An asset-light compounder trades permanently above tangible
  book, so treating it as the downside would price in a loss the business is not
  exposed to.
- `p` is a **model output**, not a measured frequency: a linear map from margin
  of safety, quality score, and valuation confidence, hard-bounded to
  `[0.35, 0.80]`. No screen earns more confidence than that ceiling.

Then: half Kelly by default, a 20% per-position cap, a 35% per-sector cap, and a
total-exposure cap so ten independently-sized bets cannot add up to more than the
sleeve. `tests/test_kelly.py` verifies that `f*` really does maximise expected
log growth, and that half Kelly keeps most of the growth for materially less
risk.

### How much, at what interval

Each position is split into tranches triggered by a *widening* margin of safety
rather than by the calendar:

| Tranche | Share | Trigger |
|---|---|---|
| 1 | 50% | Today's price |
| 2 | 30% | A price giving 10 more points of margin of safety |
| 3 | 20% | A price giving 20 more points |

Every trigger is reported as a concrete limit price. If the market never
obliges, each tranche deploys anyway on a fallback date 30 days apart, so
capital is not held hostage to a dip that never comes. Both the price and the
date appear in the report.

## Configuration

Everything lives in `config.toml`; nothing is hard-coded deeper in the pipeline.
The knobs that change behaviour most:

| Setting | Effect |
|---|---|
| `valuation.min_margin_of_safety` | The discount demanded before a name is actionable. Lower it and you will see more names, most of which you should not buy. |
| `kelly.fraction` | 0.5 is half Kelly. Raising it toward 1.0 raises both growth and ruin risk. |
| `kelly.max_position` | The cap that usually binds, because partial-loss Kelly is aggressive. |
| `gates.*` | Hard quality filters. Loosening these is how value traps get in. |
| `universe.exclude_sectors` | Your circle of competence, as an explicit boundary. |
| `report.language` | `id` for Bahasa Indonesia, `en` for English. |

## What it deliberately does not do

- **No news, transcripts, or management commentary.** Risks that only show up
  there are invisible to it, and the memo is instructed to name the questions
  you must go and answer yourself rather than pretend otherwise.
- **No intraday or real-time prices.** It reads the last completed session.
- **No guessed numbers.** A line item the filer did not tag renders as "tidak
  ada info", never as zero and never as a sector average. Where a fallback *is*
  used, the report names it.
- **No claim that `p` is a real probability.** It is a model output from a
  transparent linear map, documented as such everywhere it appears.

## Tests

```bash
pip install pytest
python -m pytest tests/ -q
```

105 tests, no network required. They cover the EDGAR parser against
restatements, concept migration and 53-week fiscal years; every forensic score
against hand-computed values; the DCF against an independent recomputation;
Kelly's optimality property; the gates; the schedule arithmetic; and one full
end-to-end pipeline run against fixtures.

## Not investment advice

This is a research tool. It reads public filings and does arithmetic on them.
Every intrinsic value in it is an estimate, the win probabilities are model
outputs, and the decisions and their consequences are yours.
