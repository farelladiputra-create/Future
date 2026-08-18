"""Entry point: screen, value, size, write, notify.

    python -m buffett.run                  # live run against the configured universe
    python -m buffett.run --offline        # synthetic universe, no network at all
    python -m buffett.run --tickers KO,PG  # screen a handful of names
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from .agent.memo import Memo, write_memo
from .analysis.screen import Candidate, ScreenResult, run_screen
from .config import Config, load_config
from .data.universe import build_universe
from .net import HttpClient
from .notify import email_report, summary, telegram
from .report import html as html_report
from .report import markdown as md_report

log = logging.getLogger("buffett")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="buffett",
        description="Value-investing screen and evening briefing for US equities.",
    )
    parser.add_argument("--config", default="config.toml", help="path to config.toml")
    parser.add_argument(
        "--tickers",
        help="comma-separated symbols to screen instead of the configured universe",
    )
    parser.add_argument(
        "--limit", type=int, help="cap the universe size for a quick run"
    )
    parser.add_argument(
        "--offline",
        action="store_true",
        help="run against synthetic filers with no network access",
    )
    parser.add_argument(
        "--no-agent", action="store_true", help="skip the Claude memo layer"
    )
    parser.add_argument(
        "--no-notify", action="store_true", help="write reports but send nothing"
    )
    parser.add_argument("--output-dir", help="override report.output_dir")
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="print the short notification text to stdout",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    # Third-party chatter drowns out the run log otherwise.
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    try:
        cfg = load_config(args.config)
    except (ValueError, OSError) as exc:
        log.error("config problem: %s", exc)
        return 2

    if args.no_agent:
        cfg.agent.enabled = False
    if args.output_dir:
        cfg.report.output_dir = args.output_dir
    if args.limit:
        cfg.universe.max_tickers = args.limit

    run_at = _local_today(cfg)
    log.info("run date %s (%s)", run_at, cfg.schedule.timezone)

    try:
        client, tickers = _prepare(cfg, args)
    except Exception as exc:  # noqa: BLE001
        log.error("could not assemble the universe: %s", exc)
        return 1

    log.info("screening %d symbols", len(tickers))
    try:
        result = run_screen(client, cfg, tickers, today=run_at)
    except Exception as exc:  # noqa: BLE001
        log.exception("screen failed")
        log.error("%s", exc)
        return 1

    log.info(
        "%d passed, %d rejected, %d errors",
        len(result.candidates),
        len(result.rejected),
        len(result.errors),
    )

    top = result.candidates[: cfg.agent.memo_candidates]
    memo = write_memo(result, top, cfg.agent, cfg.report.language)
    if not memo.available:
        log.info("memo unavailable: %s", memo.error)

    paths = _write_reports(result, memo, cfg, run_at)
    for path in paths:
        log.info("wrote %s", path)

    short = summary.build(result, memo, cfg)
    if args.print_summary:
        print(short)

    if not args.no_notify:
        _notify(short, result, memo, cfg, run_at)

    return 0


# ---- wiring ------------------------------------------------------------


def _local_today(cfg: Config) -> date:
    """Today in the configured timezone, not the server's."""
    try:
        return datetime.now(ZoneInfo(cfg.schedule.timezone)).date()
    except Exception:  # noqa: BLE001 - a bad tz must not stop the run
        log.warning("unknown timezone %s, using system date", cfg.schedule.timezone)
        return date.today()


def _prepare(cfg: Config, args: argparse.Namespace) -> tuple[Any, list[str]]:
    """Build the HTTP client and the ticker list."""
    if args.offline:
        from .fixtures import FixtureHttpClient, demo_filers

        filers = demo_filers()
        log.info("offline mode: %d synthetic filers", len(filers))
        return FixtureHttpClient(filers), [f.ticker for f in filers]

    client = HttpClient(
        cache_dir=cfg.data.cache_dir,
        cache_ttl_hours=cfg.data.cache_ttl_hours,
        user_agent=cfg.data.sec_user_agent,
        timeout=cfg.data.request_timeout,
        max_retries=cfg.data.max_retries,
    )

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = build_universe(client, cfg.universe)

    if not tickers:
        raise ValueError("universe is empty")
    return client, tickers


def resolve_output_dir(cfg: Config) -> Path:
    """Absolute output directory.

    The workspace convention is that paths are built from the workspace root and
    the working directory is never assumed, so a relative `output_dir` is joined
    onto `workspace_root` when one is configured. An absolute `output_dir` wins
    outright, which is what pathlib does when joining onto one.
    """
    base = Path(cfg.report.output_dir).expanduser()
    root = cfg.report.workspace_root
    if root:
        base = Path(root).expanduser() / base
    return base.resolve()


def _write_reports(
    result: ScreenResult, memo: Memo, cfg: Config, run_at: date
) -> list[Path]:
    output_dir = resolve_output_dir(cfg)
    output_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{run_at.isoformat()}-{cfg.report.slug}"
    written: list[Path] = []

    if cfg.report.write_markdown:
        path = output_dir / f"{stem}.md"
        path.write_text(md_report.render(result, memo, cfg, run_at), encoding="utf-8")
        written.append(path)

    if cfg.report.write_html:
        path = output_dir / f"{stem}.html"
        path.write_text(html_report.render(result, memo, cfg, run_at), encoding="utf-8")
        written.append(path)
        # A stable filename makes bookmarking the latest brief possible. It
        # carries the slug too, so several agents can share an outputs folder.
        latest = output_dir / f"latest-{cfg.report.slug}.html"
        latest.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
        written.append(latest)

    if cfg.report.write_json:
        path = output_dir / f"{stem}.json"
        path.write_text(
            json.dumps(_as_json(result, memo, cfg), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        written.append(path)

    return written


def _as_json(result: ScreenResult, memo: Memo, cfg: Config) -> dict[str, Any]:
    """Machine-readable output. Excludes the raw price series, which is bulky."""
    return {
        "run_date": result.run_date.isoformat(),
        "price_as_of": result.price_as_of.isoformat() if result.price_as_of else None,
        "universe_size": result.universe_size,
        "analysed": result.analysed,
        "portfolio": asdict(cfg.portfolio),
        "portfolio_messages": result.portfolio_messages,
        "candidates": [_candidate_json(c) for c in result.candidates],
        "rejected": [_candidate_json(c) for c in result.rejected],
        "errors": result.errors,
        "memo": memo.to_dict(),
    }


def _candidate_json(candidate: Candidate) -> dict[str, Any]:
    company = candidate.company
    latest = company.latest
    return {
        "ticker": candidate.ticker,
        "name": company.name,
        "cik": company.cik,
        "sector": company.sector,
        "market_cap": company.market_cap,
        "rank_score": candidate.rank_score,
        "latest_period_end": latest.period_end.isoformat() if latest else None,
        "data_completeness": round(company.completeness(), 3),
        "gate": asdict(candidate.gate),
        "quality": asdict(candidate.quality),
        "valuation": asdict(candidate.valuation),
        "sizing": _sizing_json(candidate.sizing),
        "price_stats": {
            **{
                k: v
                for k, v in asdict(candidate.price_stats).items()
                if k != "as_of"
            },
            "as_of": candidate.price_stats.as_of.isoformat()
            if candidate.price_stats.as_of
            else None,
        },
        "notes": company.notes,
    }


def _sizing_json(sizing: Any) -> dict[str, Any]:
    payload = asdict(sizing)
    payload["tranches"] = [
        {**t, "fallback_date": t["fallback_date"].isoformat()}
        for t in payload.get("tranches", [])
    ]
    return payload


def _notify(
    short: str, result: ScreenResult, memo: Memo, cfg: Config, run_at: date
) -> None:
    if telegram.send(short):
        log.info("telegram sent")

    subject = (
        f"Value screen {run_at.isoformat()}: "
        f"{len(result.candidates)} kandidat lolos gate"
    )
    if email_report.send(
        subject, short, html_report.render(result, memo, cfg, run_at)
    ):
        log.info("email sent")


if __name__ == "__main__":
    sys.exit(main())
