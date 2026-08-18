"""Markdown report: the version that gets committed, piped, and pasted.

Opens with the basis (source, window, what the percentages are against), then
summary, then actions, then the data. Limitations at the bottom. No figure
appears without a source or a stated derivation.
"""

from __future__ import annotations

from datetime import date

from ..agent.memo import Memo
from ..analysis.screen import Candidate, ScreenResult
from ..config import Config
from .format import (
    MISSING,
    conviction_label,
    day,
    multiple,
    number,
    percent,
    signed_percent,
    usd,
    usd_compact,
    verdict_label,
    zone_label,
)


def render(
    result: ScreenResult, memo: Memo, cfg: Config, run_at: date | None = None
) -> str:
    run_at = run_at or result.run_date
    lines: list[str] = []
    top = result.candidates[: cfg.report.top_n]

    lines += _header(result, cfg, run_at)
    lines += _summary(result, memo, cfg, top)
    lines += _actions(result, memo, top, cfg)
    lines += _ranking_table(top)

    for index, candidate in enumerate(top, start=1):
        lines += _detail(candidate, memo, cfg, index)

    lines += _watchlist(result, cfg)
    lines += _limitations(result, memo, cfg)
    return "\n".join(lines).rstrip() + "\n"


# ---- sections ----------------------------------------------------------


def _header(result: ScreenResult, cfg: Config, run_at: date) -> list[str]:
    return [
        f"# Laporan Malam Value Investing · {day(run_at)}",
        "",
        f"**Basis data:** laporan keuangan tahunan dari SEC EDGAR (XBRL, form 10-K), "
        f"harga penutupan pasar AS per {day(result.price_as_of)}. "
        f"{result.universe_size} simbol masuk universe, {result.analysed} berhasil "
        f"diparse. Semua persentase dihitung terhadap nilai intrinsik blended, "
        f"bukan terhadap harga.",
        "",
        f"**Portofolio dasar:** {usd(cfg.portfolio.equity_usd, 0)} dengan "
        f"{percent(cfg.portfolio.cash_reserve, 0)} disisakan sebagai kas. "
        f"Sizing pakai {percent(cfg.kelly.fraction, 0)} Kelly, batas per posisi "
        f"{percent(cfg.kelly.max_position, 0)}.",
        "",
    ]


def _summary(
    result: ScreenResult, memo: Memo, cfg: Config, top: list[Candidate]
) -> list[str]:
    lines = ["## Ringkasan", ""]

    if not result.candidates:
        lines += [
            f"Tidak ada satu pun nama yang lolos semua gate malam ini. "
            f"{len(result.rejected)} nama ditolak, {len(result.errors)} gagal diambil. "
            f"Gate yang paling sering gagal: margin of safety minimum "
            f"{percent(cfg.valuation.min_margin_of_safety, 0)}.",
            "",
        ]
        if memo.market_note:
            lines += [memo.market_note, ""]
        return lines

    best = top[0]
    total_weight = sum(c.sizing.target_weight or 0.0 for c in top if c.sizing.actionable)
    total_usd = sum(c.sizing.target_usd or 0.0 for c in top if c.sizing.actionable)

    lines += [
        f"{len(result.candidates)} nama lolos semua gate kualitas dan margin of "
        f"safety. Teratas: **{best.ticker}** ({best.company.name}) dengan MOS "
        f"{percent(best.valuation.margin_of_safety)} dan skor kualitas "
        f"{number(best.quality.score, 1)}/100. "
        f"Total alokasi yang disarankan {percent(total_weight)} dari sleeve "
        f"({usd(total_usd, 0)}).",
        "",
    ]
    if memo.market_note:
        lines += [memo.market_note, ""]
    return lines


def _actions(
    result: ScreenResult, memo: Memo, top: list[Candidate], cfg: Config
) -> list[str]:
    lines = ["## Rencana Aksi", ""]
    actionable = [c for c in top if c.sizing.actionable]

    if not actionable:
        lines += [
            "- Tidak ada aksi beli malam ini. Kas tetap di tempat.",
            "- Baca ulang bagian Watchlist untuk tahu apa yang hampir lolos dan kenapa gagal.",
            "",
        ]
        if memo.discipline_note:
            lines += [f"> {memo.discipline_note}", ""]
        return lines

    for candidate in actionable:
        first = candidate.sizing.tranches[0] if candidate.sizing.tranches else None
        verdict = memo.verdict_for(candidate.ticker)
        tag = f" · memo: {verdict_label(verdict.verdict)}" if verdict else ""
        if first:
            lines.append(
                f"- **{candidate.ticker}**: beli tranche 1 sebesar "
                f"{usd(first.usd_amount, 0)} (~{first.shares} lembar) di harga "
                f"{usd(first.trigger_price)} atau lebih murah. Target total posisi "
                f"{percent(candidate.sizing.target_weight)} sleeve{tag}."
            )
        else:
            lines.append(
                f"- **{candidate.ticker}**: target "
                f"{percent(candidate.sizing.target_weight)} sleeve{tag}."
            )

    for message in result.portfolio_messages:
        lines.append(f"- Penyesuaian portofolio: {message}.")

    lines.append("")
    if memo.discipline_note:
        lines += [f"> {memo.discipline_note}", ""]
    return lines


def _ranking_table(top: list[Candidate]) -> list[str]:
    if not top:
        return []
    lines = [
        "## Peringkat Kandidat",
        "",
        "| # | Ticker | Sektor | Harga | Nilai Intrinsik | MOS | Kualitas | P/E | PBV | Div Yield | Alokasi | Skor |",
        "|---|--------|--------|------:|----------------:|----:|---------:|----:|----:|----------:|--------:|-----:|",
    ]
    for index, c in enumerate(top, start=1):
        lines.append(
            "| {i} | {ticker} | {sector} | {price} | {iv} | {mos} | {quality} | "
            "{pe} | {pbv} | {dy} | {alloc} | {score} |".format(
                i=index,
                ticker=c.ticker,
                sector=c.sector,
                price=usd(c.valuation.price),
                iv=usd(c.valuation.iv_base),
                mos=percent(c.valuation.margin_of_safety),
                quality=number(c.quality.score, 1),
                pe=multiple(c.valuation.pe_trailing),
                pbv=multiple(c.valuation.pbv),
                dy=percent(c.quality.dividend.yield_pct),
                alloc=percent(c.sizing.target_weight)
                if c.sizing.actionable
                else "tidak diambil",
                score=number(c.rank_score, 1),
            )
        )
    lines.append("")
    return lines


def _detail(candidate: Candidate, memo: Memo, cfg: Config, index: int) -> list[str]:
    v, q, s = candidate.valuation, candidate.quality, candidate.sizing
    stats, dividend = candidate.price_stats, q.dividend
    latest = candidate.company.latest

    lines = [
        f"## [{index}] {candidate.ticker} · {candidate.company.name}",
        "",
        f"{candidate.sector} · kapitalisasi pasar {usd_compact(candidate.company.market_cap)} · "
        f"{q.years_available} tahun buku terparse · "
        f"tutup buku terakhir {day(latest.period_end) if latest else MISSING}",
        "",
        "### Valuasi",
        "",
        "| Metode | Nilai per lembar |",
        "|--------|-----------------:|",
        f"| Discounted owner earnings (DCF) | {usd(v.iv_dcf)} |",
        f"| Earnings power value (tanpa growth) | {usd(v.iv_epv)} |",
        f"| Multiple ternormalisasi | {usd(v.iv_multiple)} |",
        f"| Graham number | {usd(v.iv_graham)} |",
        f"| Book value | {usd(v.iv_book)} |",
        f"| **Blended base case** | **{usd(v.iv_base)}** |",
        f"| Lantai bear case | {usd(v.iv_bear)} |",
        f"| Bull case | {usd(v.iv_bull)} |",
        "",
        f"Harga sekarang {usd(v.price)}, jadi **margin of safety "
        f"{percent(v.margin_of_safety)}** dan potensi naik ke base case "
        f"{percent(v.upside)}. Kesepakatan antar metode "
        f"{number(v.confidence, 2)} (1,0 = rapat, 0,2 = lebar). "
        f"Discount rate {percent(v.discount_rate)}, growth tahap satu "
        f"{percent(v.growth_stage1)} meluruh ke {percent(v.terminal_growth)}.",
        "",
        "### Kualitas Bisnis",
        "",
        "| Metrik | Nilai |",
        "|--------|------:|",
        f"| Skor kualitas komposit | {number(q.score, 1)} / 100 |",
        f"| Piotroski F-Score | {q.piotroski_f if q.piotroski_f is not None else MISSING} / 9 |",
        f"| Altman Z-Score | {number(q.altman_z)} ({zone_label(q.altman_zone)}) |",
        f"| Beneish M-Score | {number(q.beneish_m)} (batas {cfg.gates.max_beneish_m}) |",
        f"| ROE rata-rata | {percent(q.avg_roe)} |",
        f"| ROIC rata-rata | {percent(q.avg_roic)} |",
        f"| Margin operasi | {percent(q.operating_margin_latest)} |",
        f"| Pertumbuhan revenue | {percent(q.revenue_cagr)} |",
        f"| Pertumbuhan EPS | {percent(q.eps_cagr)} |",
        f"| Perubahan jumlah saham per tahun | {signed_percent(q.share_count_cagr)} |",
        f"| Debt to equity | {multiple(q.debt_to_equity)} |",
        f"| Interest coverage | {multiple(q.interest_coverage)} |",
        f"| Tahun laba positif | {q.positive_earnings_years} dari {q.years_available} |",
        f"| Tahun FCF positif | {q.positive_fcf_years} dari {q.years_available} |",
        "",
        "### Dividen",
        "",
        f"Yield {percent(dividend.yield_pct)}, dividen per lembar "
        f"{usd(dividend.dps_latest)}, payout ratio "
        f"{percent(dividend.payout_ratio)}. Sudah "
        f"{dividend.paying_years} tahun berturut bayar, "
        f"{dividend.growth_years} tahun berturut naik. "
        f"Ditutup free cash flow: "
        f"{'ya' if dividend.covered_by_fcf else 'tidak' if dividend.covered_by_fcf is False else MISSING}.",
        "",
        "### Harga",
        "",
        f"Rentang 52 minggu {usd(stats.week52_low)} sampai {usd(stats.week52_high)}, "
        f"turun {percent(stats.drawdown_from_high)} dari puncak, "
        f"return setahun {signed_percent(stats.return_1y)}, "
        f"volatilitas tahunan {percent(stats.volatility)}.",
        "",
        "### Sizing Kelly",
        "",
    ]

    if s.actionable:
        lines += [
            f"Probabilitas menang yang dimodelkan {percent(s.win_probability)}, "
            f"upside {percent(s.upside)} lawan potensi rugi permanen "
            f"{percent(s.downside)} (rasio {number(s.odds, 2)}). "
            f"Kelly penuh {percent(s.kelly_full)}, dipakai "
            f"{percent(cfg.kelly.fraction, 0)} Kelly jadi "
            f"**{percent(s.target_weight)} dari sleeve = {usd(s.target_usd, 0)}**."
            + (f" Dibatasi oleh: {s.capped_by}." if s.capped_by else ""),
            "",
            "| Tranche | Jumlah | Harga trigger | MOS di harga itu | Lembar | Kalau harga tidak turun |",
            "|--------:|-------:|--------------:|-----------------:|-------:|------------------------|",
        ]
        for tranche in s.tranches:
            timing = (
                "beli sekarang"
                if tranche.is_immediate
                else f"tetap beli per {day(tranche.fallback_date)}"
            )
            lines.append(
                f"| {tranche.index} | {usd(tranche.usd_amount, 0)} | "
                f"{usd(tranche.trigger_price)} | "
                f"{percent(tranche.target_margin_of_safety)} | "
                f"{tranche.shares} | {timing} |"
            )
        lines.append("")
    else:
        reason = s.notes[0] if s.notes else "tidak ada alasan tercatat"
        lines += [f"Tidak diambil posisi: {reason}.", ""]

    if q.flags:
        lines += ["### Peringatan", ""]
        lines += [f"- {flag}" for flag in q.flags]
        lines.append("")

    verdict = memo.verdict_for(candidate.ticker)
    if verdict:
        lines += [
            "### Catatan Buffett",
            "",
            f"**Putusan: {verdict_label(verdict.verdict)}** "
            f"(keyakinan {conviction_label(verdict.conviction)})",
            "",
            f"*Bisnisnya:* {verdict.business_in_one_line}",
            "",
            f"*Moat:* {verdict.moat}",
            "",
            f"*Kenapa murah:* {verdict.why_it_is_cheap}",
            "",
            f"*Soal sizing:* {verdict.sizing_comment}",
            "",
        ]
        if verdict.what_would_make_me_wrong:
            lines += ["*Yang bisa membuat tesis ini salah:*", ""]
            lines += [f"- {item}" for item in verdict.what_would_make_me_wrong]
            lines.append("")
        if verdict.questions_before_buying:
            lines += ["*Yang harus dicek sendiri sebelum beli:*", ""]
            lines += [f"- {item}" for item in verdict.questions_before_buying]
            lines.append("")

    notes = list(v.notes) + list(candidate.company.notes) + list(candidate.gate.waived)
    if notes:
        lines += ["### Catatan metode", ""]
        lines += [f"- {note}" for note in notes]
        lines.append("")

    return lines


def _watchlist(result: ScreenResult, cfg: Config) -> list[str]:
    watchlist = result.rejected[: cfg.report.watchlist_n]
    if not watchlist:
        return []
    lines = [
        "## Watchlist: hampir lolos, tapi gagal gate",
        "",
        "| Ticker | Sektor | Skor | MOS | Kualitas | Gate yang gagal |",
        "|--------|--------|-----:|----:|---------:|-----------------|",
    ]
    for c in watchlist:
        reasons = "; ".join(c.gate.failures[:2]) or MISSING
        lines.append(
            f"| {c.ticker} | {c.sector} | {number(c.rank_score, 1)} | "
            f"{percent(c.valuation.margin_of_safety)} | "
            f"{number(c.quality.score, 1)} | {reasons} |"
        )
    lines.append("")
    return lines


def _limitations(result: ScreenResult, memo: Memo, cfg: Config) -> list[str]:
    lines = ["## Batasan", ""]

    lines += [
        "- Semua angka fundamental berasal dari XBRL 10-K. Filer yang menandai "
        "elemen secara tidak standar bisa punya baris yang kosong; itu tampil "
        f"sebagai \"{MISSING}\", tidak pernah diisi angka tebakan.",
        "- Nilai intrinsik adalah estimasi, bukan fakta. Empat metode dipakai "
        "supaya sebarannya kelihatan. Sebaran yang lebar berarti angkanya lemah, "
        "dan itu sudah memperkecil ukuran posisi lewat Kelly.",
        "- Probabilitas menang di Kelly adalah keluaran model dari margin of "
        "safety, kualitas, dan kesepakatan antar metode. Itu bukan frekuensi "
        "historis dan tidak boleh dibaca begitu.",
        "- Screener ini tidak membaca berita, transkrip earnings call, atau "
        "komentar manajemen. Risiko yang hanya muncul di sana tidak akan terlihat "
        "di sini.",
        "- Harga adalah penutupan sesi AS terakhir, bukan harga real-time.",
    ]

    if result.errors:
        sample = ", ".join(list(result.errors)[:8])
        lines.append(
            f"- {len(result.errors)} simbol gagal diambil dan tidak ikut dinilai: {sample}."
        )
    if not memo.available:
        lines.append(f"- Catatan Buffett tidak tersedia malam ini: {memo.error}.")
    if cfg.portfolio.usd_to_idr is None:
        lines.append(
            "- Semua angka dalam USD. Konversi ke rupiah tidak ditampilkan karena "
            "kurs belum diisi di config (portfolio.usd_to_idr)."
        )

    lines += [
        "",
        "---",
        "",
        f"Sumber: SEC EDGAR companyfacts API dan riwayat harga harian. "
        f"Dijalankan {day(result.run_date)} pukul {cfg.schedule.hour:02d}:"
        f"{cfg.schedule.minute:02d} {cfg.schedule.timezone}. "
        f"Bukan nasihat investasi; ini alat riset, keputusan tetap milikmu.",
        "",
    ]
    return lines
