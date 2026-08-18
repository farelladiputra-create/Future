"""The short form: what fits on a phone screen at 9 PM.

Notification channels have hard length limits, so this is a genuine summary
rather than a truncated report. It carries the decision (buy what, how much, at
what price) and nothing else.
"""

from __future__ import annotations

from ..agent.memo import Memo
from ..analysis.screen import ScreenResult
from ..config import Config
from ..report.format import day, percent, usd, verdict_label

# Telegram caps a message at 4096 characters.
MAX_LENGTH = 3800


def build(result: ScreenResult, memo: Memo, cfg: Config) -> str:
    top = result.candidates[: cfg.report.top_n]
    lines = [
        f"*Laporan Value Investing · {day(result.run_date)}*",
        f"Harga per {day(result.price_as_of)} · "
        f"{result.analysed}/{result.universe_size} simbol terparse",
        "",
    ]

    if not top:
        lines += [
            "Tidak ada nama yang lolos gate malam ini.",
            f"{len(result.rejected)} ditolak, {len(result.errors)} gagal diambil.",
            "Tidak ada aksi beli. Kas tetap di tempat.",
        ]
        if memo.market_note:
            lines += ["", memo.market_note]
        return _clip("\n".join(lines))

    actionable = [c for c in top if c.sizing.actionable]
    total_weight = sum(c.sizing.target_weight or 0.0 for c in actionable)
    total_usd = sum(c.sizing.target_usd or 0.0 for c in actionable)

    lines.append(
        f"{len(result.candidates)} lolos gate · alokasi total "
        f"{percent(total_weight)} sleeve ({usd(total_usd, 0)})"
    )
    lines.append("")

    for index, candidate in enumerate(top, start=1):
        v, s = candidate.valuation, candidate.sizing
        verdict = memo.verdict_for(candidate.ticker)
        tag = f" · {verdict_label(verdict.verdict)}" if verdict else ""
        lines.append(
            f"*{index}. {candidate.ticker}* ({candidate.sector}){tag}\n"
            f"  harga {usd(v.price)} · nilai {usd(v.iv_base)} · "
            f"MOS {percent(v.margin_of_safety)}\n"
            f"  kualitas {candidate.quality.score:.0f}/100 · "
            f"skor {candidate.rank_score:.0f}"
        )
        if s.actionable and s.tranches:
            first = s.tranches[0]
            lines.append(
                f"  beli {usd(first.usd_amount, 0)} (~{first.shares} lbr) "
                f"di {usd(first.trigger_price)} atau lebih murah\n"
                f"  target posisi {percent(s.target_weight)} sleeve"
            )
        else:
            lines.append("  tidak diambil posisi")
        lines.append("")

    if memo.discipline_note:
        lines += [f"_{memo.discipline_note}_", ""]

    lines.append("Rincian lengkap ada di laporan HTML dan Markdown.")
    return _clip("\n".join(lines))


def _clip(text: str) -> str:
    if len(text) <= MAX_LENGTH:
        return text
    return text[: MAX_LENGTH - 40].rstrip() + "\n\n[dipotong, lihat laporan lengkap]"
