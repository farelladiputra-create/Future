"""Configuration: TOML file over dataclass defaults, with env-var overrides.

Every threshold the engine uses is declared here. Nothing is hard-coded deeper
in the pipeline, so tuning the strategy never means editing analysis code.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any


@dataclass
class UniverseConfig:
    # "sp500" pulls the current S&P 500 constituents; "inline" uses `tickers`.
    source: str = "sp500"
    tickers: list[str] = field(default_factory=list)
    # Hard cap on names screened per run, keeps the nightly job bounded.
    max_tickers: int = 520
    min_market_cap_usd: float = 2_000_000_000.0
    # Buffett's circle of competence: sectors he has consistently refused to
    # underwrite. Empty list screens everything.
    exclude_sectors: list[str] = field(default_factory=list)
    exclude_tickers: list[str] = field(default_factory=list)


@dataclass
class GateConfig:
    """Pass/fail quality gates. A name failing any gate is never recommended."""

    min_years_history: int = 5
    # Consistent earning power: how many of the last `min_years_history` years
    # must show positive net income.
    min_positive_earnings_years: int = 5
    min_positive_fcf_years: int = 4
    min_avg_roe: float = 0.12
    min_avg_roic: float = 0.09
    max_debt_to_equity: float = 1.5
    min_interest_coverage: float = 5.0
    min_piotroski_f: int = 5
    min_altman_z: float = 1.81
    # Beneish M above this suggests earnings manipulation; Buffett walks away.
    max_beneish_m: float = -1.78
    # Reject names diluting shareholders faster than this per year.
    max_share_growth: float = 0.02
    # Skip anything whose data coverage is too thin to underwrite honestly.
    min_data_completeness: float = 0.70


@dataclass
class ValuationConfig:
    risk_free_rate: float = 0.042
    equity_risk_premium: float = 0.050
    discount_rate_floor: float = 0.08
    discount_rate_cap: float = 0.16
    terminal_growth: float = 0.025
    stage1_years: int = 10
    # Cap and haircut applied to historical owner-earnings growth. Optimism is
    # the expensive input in any DCF, so it is throttled twice.
    growth_cap: float = 0.10
    growth_floor: float = -0.02
    growth_haircut: float = 0.75
    # Graham's ceiling multiple for a defensive investor.
    max_normalized_pe: float = 15.0
    # Weights for blending intrinsic-value estimates into the base case.
    weight_dcf: float = 0.40
    weight_epv: float = 0.30
    weight_multiple: float = 0.20
    weight_graham: float = 0.10
    # Minimum margin of safety before a name is actionable at all.
    min_margin_of_safety: float = 0.25
    # Statutory-ish blended tax rate used when a filer's effective rate is
    # unusable (negative pretax income, one-off credits).
    fallback_tax_rate: float = 0.21


@dataclass
class KellyConfig:
    # Half Kelly by default: inputs here are estimates, not known odds, and
    # full Kelly on estimated parameters is how accounts get wrecked.
    fraction: float = 0.50
    max_position: float = 0.20
    min_position: float = 0.02
    max_sector_exposure: float = 0.35
    # Bounds on the modelled win probability. No screen earns more confidence
    # than this ceiling.
    p_floor: float = 0.35
    p_ceiling: float = 0.80
    # Floor on assumed permanent-loss severity in the bear case.
    min_downside: float = 0.10
    max_downside: float = 0.60


@dataclass
class RankConfig:
    """Weights for the composite ranking score, in points out of 100.

    Margin of safety leads because it is what the request asks for first, but
    quality carries nearly as much: a cheap bad business is how value investors
    actually lose money.
    """

    weight_margin_of_safety: float = 40.0
    weight_quality: float = 30.0
    weight_confidence: float = 15.0
    weight_dividend: float = 15.0
    # Margin of safety at which the ranking stops awarding extra credit.
    mos_saturation: float = 0.60
    # Dividend yield at which the dividend component maxes out.
    dividend_saturation: float = 0.045


@dataclass
class PortfolioConfig:
    equity_usd: float = 100_000.0
    # Share of the sleeve deliberately left in cash. Buffett's "always be able
    # to buy more" reserve.
    cash_reserve: float = 0.20
    # For display only. Set from a rate you actually looked up; the engine will
    # not invent an FX rate.
    usd_to_idr: float | None = None


@dataclass
class TrancheConfig:
    # Fractions of the target position deployed per tranche.
    splits: list[float] = field(default_factory=lambda: [0.50, 0.30, 0.20])
    # Extra margin of safety (in percentage points of intrinsic value) required
    # to trigger tranches 2..n on price weakness.
    mos_steps: list[float] = field(default_factory=lambda: [0.00, 0.10, 0.20])
    # If the price never falls to the next trigger, deploy anyway after this
    # many calendar days so capital is not idle indefinitely.
    time_spacing_days: int = 30


@dataclass
class AgentConfig:
    model: str = "claude-opus-5"
    max_tokens: int = 4000
    # Names sent to the model for a full qualitative memo.
    memo_candidates: int = 5
    enabled: bool = True


@dataclass
class ReportConfig:
    top_n: int = 5
    watchlist_n: int = 12
    output_dir: str = "reports"
    write_html: bool = True
    write_markdown: bool = True
    write_json: bool = True
    language: str = "id"


@dataclass
class ScheduleConfig:
    timezone: str = "Asia/Jakarta"
    hour: int = 21
    minute: int = 0


@dataclass
class DataConfig:
    # SEC requires a real contact string in the User-Agent. Set this.
    sec_user_agent: str = "buffett-agent (set contact via SEC_USER_AGENT env)"
    cache_dir: str = ".cache"
    cache_ttl_hours: float = 20.0
    price_history_days: int = 1900
    max_workers: int = 6
    request_timeout: float = 30.0
    max_retries: int = 4


@dataclass
class Config:
    universe: UniverseConfig = field(default_factory=UniverseConfig)
    gates: GateConfig = field(default_factory=GateConfig)
    valuation: ValuationConfig = field(default_factory=ValuationConfig)
    kelly: KellyConfig = field(default_factory=KellyConfig)
    rank: RankConfig = field(default_factory=RankConfig)
    portfolio: PortfolioConfig = field(default_factory=PortfolioConfig)
    tranches: TrancheConfig = field(default_factory=TrancheConfig)
    agent: AgentConfig = field(default_factory=AgentConfig)
    report: ReportConfig = field(default_factory=ReportConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    data: DataConfig = field(default_factory=DataConfig)


def _apply(target: Any, values: dict[str, Any], path: str = "") -> None:
    """Recursively overlay a dict onto a dataclass instance, type-checking keys."""
    valid = {f.name: f for f in fields(target)}
    for key, value in values.items():
        if key not in valid:
            raise ValueError(f"unknown config key: {path}{key}")
        current = getattr(target, key)
        if is_dataclass(current) and isinstance(value, dict):
            _apply(current, value, f"{path}{key}.")
        else:
            setattr(target, key, value)


def load_config(path: str | Path | None = None) -> Config:
    """Load config.toml if present, then apply env-var overrides for secrets."""
    cfg = Config()

    candidate = Path(path) if path else Path("config.toml")
    if candidate.exists():
        with candidate.open("rb") as handle:
            _apply(cfg, tomllib.load(handle))

    # Secrets and CI-supplied values never live in the TOML file.
    if ua := os.environ.get("SEC_USER_AGENT"):
        cfg.data.sec_user_agent = ua
    if equity := os.environ.get("PORTFOLIO_EQUITY_USD"):
        cfg.portfolio.equity_usd = float(equity)
    if model := os.environ.get("BUFFETT_MODEL"):
        cfg.agent.model = model
    if os.environ.get("BUFFETT_DISABLE_AGENT") == "1":
        cfg.agent.enabled = False
    if not os.environ.get("ANTHROPIC_API_KEY"):
        # No key means no memo layer; the quantitative report still ships.
        cfg.agent.enabled = False

    _validate(cfg)
    return cfg


def _validate(cfg: Config) -> None:
    v, k, t = cfg.valuation, cfg.kelly, cfg.tranches
    if v.terminal_growth >= v.discount_rate_floor:
        raise ValueError("terminal_growth must stay below discount_rate_floor")
    if v.stage1_years < 2:
        raise ValueError("stage1_years must be at least 2")
    if not 0 < k.fraction <= 1:
        raise ValueError("kelly.fraction must be in (0, 1]")
    if not 0 <= k.p_floor < k.p_ceiling <= 1:
        raise ValueError("kelly p_floor must be below p_ceiling, both in [0, 1]")
    if len(t.splits) != len(t.mos_steps):
        raise ValueError("tranches.splits and tranches.mos_steps must be the same length")
    if abs(sum(t.splits) - 1.0) > 1e-6:
        raise ValueError("tranches.splits must sum to 1.0")
    if not 0 <= cfg.portfolio.cash_reserve < 1:
        raise ValueError("portfolio.cash_reserve must be in [0, 1)")
    weights = v.weight_dcf + v.weight_epv + v.weight_multiple + v.weight_graham
    if abs(weights - 1.0) > 1e-6:
        raise ValueError("valuation blend weights must sum to 1.0")
