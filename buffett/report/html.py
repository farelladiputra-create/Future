"""Self-contained HTML brief in the Jarvis Slate visual system.

One file, no external assets, opens by double-click. Light palette committed to
deliberately, with every colour painted explicitly rather than inherited. Every
figure traces to the screen output; anything unavailable renders as muted "tidak
ada info" rather than a zero or a red cross.
"""

from __future__ import annotations

from datetime import date
from html import escape

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
    truncate,
    usd,
    usd_compact,
    verdict_label,
    zone_label,
)

# Brand-derived sequential ramp, light-safe.
RAMP = (
    "#003781", "#1B4E96", "#3465AB", "#4E7CBF", "#6893D3",
    "#83AAE2", "#9FC0EE", "#BCD5F6", "#D8E7FB",
)

STYLE = """
:root{
  --bg:#EEF2F7; --surface:#FFFFFF;
  --ink:#0F1B2D; --ink2:#44546A; --ink3:#8494A8;
  --line:#D8E0EA; --muted-x:#B9C3D0;
  --brand:#003781;
  --gold:#FFD35C; --gold-ink:#4A3600;
  --green:#0B7A3E; --green-tint:#DFF2E5;
  --amber:#9A6B00; --amber-tint:#FBF0D9;
  --red:#B3261E; --red-tint:#FBE3E1;
  --r-lg:16px; --r-md:12px; --r-sm:14px;
}
*{box-sizing:border-box;}
body{
  margin:0; background:var(--bg); color:var(--ink2);
  font-family:'DejaVu Sans',-apple-system,'Segoe UI',Arial,sans-serif;
  font-size:19px; line-height:1.55;
}
.page{max-width:1500px; margin:0 auto; padding:48px;}
h1{font-size:40px; line-height:1.15; font-weight:bold; color:var(--ink); margin:0 0 8px;}
h2{font-size:26px; font-weight:bold; color:var(--ink); margin:48px 0 8px;}
h3{font-size:20px; font-weight:bold; color:var(--ink); margin:32px 0 8px;}
h4{font-size:17px; font-weight:bold; color:var(--ink); margin:24px 0 8px;}
p{margin:0 0 16px;}
.sub{font-size:19px; color:var(--ink2); margin:0 0 8px;}
.basis{font-size:15.5px; color:var(--ink3); margin:0 0 32px; max-width:1100px;}
.section-note{font-size:15.5px; color:var(--ink3); margin:0 0 24px;}
.label{
  font-size:14px; color:var(--ink3); text-transform:uppercase;
  letter-spacing:.6px; font-weight:normal;
}
.num{font-variant-numeric:tabular-nums;}
.muted{color:var(--ink3);}

/* KPI strip: fixed rows so a two-line label never pushes siblings out of line. */
.kpis{display:grid; grid-template-columns:repeat(5,1fr); gap:16px; margin:0 0 32px;}
.kpi{
  background:var(--surface); border:1px solid var(--line); border-radius:var(--r-sm);
  padding:24px; display:grid; grid-template-rows:20px 46px 20px; row-gap:8px;
}
.kpi.primary{border:2px solid var(--brand);}
.kpi .value{
  font-size:38px; font-weight:bold; color:var(--ink);
  font-variant-numeric:tabular-nums; line-height:1;
  align-self:center; white-space:nowrap;
}
.kpi .foot{font-size:13px; color:var(--ink3);}

.card{
  background:var(--surface); border:1px solid var(--line);
  border-radius:var(--r-lg); padding:32px; margin:0 0 24px;
}
.card.primary{border:2px solid var(--brand);}
.card-head{
  display:flex; justify-content:space-between; align-items:flex-start;
  gap:24px; margin:0 0 24px; flex-wrap:wrap;
}
.card-head .who{display:flex; flex-direction:column; gap:4px;}
.card-head .ticker{font-size:26px; font-weight:bold; color:var(--ink);}
.card-head .name{font-size:15.5px; color:var(--ink3);}

.pill{
  display:inline-block; border-radius:999px; padding:4px 16px;
  font-size:14px; font-weight:bold; letter-spacing:.6px; text-transform:uppercase;
}
.pill.buy{background:var(--green-tint); color:var(--green);}
.pill.watch{background:var(--amber-tint); color:var(--amber);}
.pill.pass{background:var(--red-tint); color:var(--red);}
.pill.neutral{background:var(--bg); color:var(--ink2);}

.scroll{overflow-x:auto;}
table{border-collapse:collapse; width:100%; font-size:17px;}
th{
  text-align:left; font-size:14px; color:var(--ink3); font-weight:normal;
  text-transform:uppercase; letter-spacing:.6px;
  padding:8px 16px 8px 0; border-bottom:1px solid var(--line); white-space:nowrap;
}
td{
  padding:16px 16px 16px 0; border-bottom:1px solid var(--line);
  color:var(--ink2); vertical-align:top;
}
tr:last-child td{border-bottom:none;}
th.r,td.r{text-align:right; font-variant-numeric:tabular-nums;}
td.strong{color:var(--ink); font-weight:bold;}
td:last-child,th:last-child{padding-right:0;}

.bar-wrap{display:flex; flex-direction:column; gap:4px; min-width:160px;}
.bar{height:10px; background:var(--bg); border-radius:6px; overflow:hidden;}
.bar span{display:block; height:100%; border-radius:6px; background:var(--brand);}

.grid2{display:grid; grid-template-columns:1fr 1fr; gap:32px;}
.grid3{display:grid; grid-template-columns:repeat(3,1fr); gap:24px;}

.insight{
  background:var(--surface); border:1px solid var(--line);
  border-left:3px solid var(--brand); border-radius:var(--r-md);
  padding:24px; margin:0 0 16px;
}
.insight.good{border-left-color:var(--green);}
.insight.watch{border-left-color:var(--amber);}
.insight.bad{border-left-color:var(--red);}
.insight h4{margin:0 0 8px;}
.insight .stat{
  font-size:26px; font-weight:bold; color:var(--ink);
  font-variant-numeric:tabular-nums; margin:0 0 8px;
}
.insight .action{
  margin:16px 0 0; padding-top:16px; border-top:1px solid var(--line);
  font-weight:bold; color:var(--ink);
}

.flags{margin:0; padding-left:24px;}
.flags li{margin:0 0 8px;}

.limits{
  background:var(--amber-tint); border:1px solid var(--line);
  border-radius:var(--r-md); padding:24px; margin:32px 0 0;
}
.limits h2{margin:0 0 16px; font-size:20px;}
.limits ul{margin:0; padding-left:24px;}
.limits li{margin:0 0 8px; font-size:17px; color:var(--ink2);}

footer{
  margin:48px 0 0; padding-top:24px; border-top:1px solid var(--line);
  font-size:13px; color:var(--ink3);
}
footer p{margin:0 0 8px;}

@media (max-width:1100px){
  .page{padding:24px;}
  .kpis{grid-template-columns:repeat(2,1fr);}
  .grid2,.grid3{grid-template-columns:1fr;}
  h1{font-size:32px;}
}
"""


def _e(value: object) -> str:
    return escape(str(value), quote=True)


def _bar(fraction: float | None, ceiling: float = 0.60) -> str:
    """A proportional bar. Renders empty when the value is unavailable."""
    if fraction is None:
        return '<div class="bar"><span style="width:0"></span></div>'
    width = max(0.0, min(1.0, fraction / ceiling)) * 100
    return f'<div class="bar"><span style="width:{width:.1f}%"></span></div>'


def render(
    result: ScreenResult, memo: Memo, cfg: Config, run_at: date | None = None
) -> str:
    run_at = run_at or result.run_date
    top = result.candidates[: cfg.report.top_n]
    body = [
        _head(result, cfg, run_at),
        _kpis(result, cfg, top),
    ]
    if memo.market_note or memo.discipline_note:
        body.append(_memo_notes(memo))
    if top:
        body.append(_ranking(top))
        body.append(_details(top, memo, cfg))
    else:
        body.append(_empty_state(result, cfg))
    body.append(_watchlist(result, cfg))
    body.append(_limits(result, memo, cfg))
    body.append(_footer(result, cfg))

    return (
        "<!doctype html>\n<html lang=\"id\">\n<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>Laporan Value Investing {_e(day(run_at))}</title>\n"
        f"<style>{STYLE}</style>\n</head>\n<body>\n"
        f'<div class="page">\n{"".join(body)}\n</div>\n</body>\n</html>\n'
    )


# ---- sections ----------------------------------------------------------


def _head(result: ScreenResult, cfg: Config, run_at: date) -> str:
    return f"""
<h1>Laporan Malam Value Investing</h1>
<p class="sub">Saham AS · {_e(day(run_at))} · disiapkan untuk keputusan besok pagi</p>
<p class="basis">
Basis data: laporan keuangan tahunan SEC EDGAR (XBRL, form 10-K) dan harga
penutupan pasar AS per {_e(day(result.price_as_of))}.
{result.universe_size} simbol masuk universe, {result.analysed} berhasil diparse.
Semua persentase margin of safety dihitung terhadap nilai intrinsik blended,
bukan terhadap harga. Portofolio dasar {_e(usd(cfg.portfolio.equity_usd, 0))}
dengan {_e(percent(cfg.portfolio.cash_reserve, 0))} disisakan kas.
</p>
"""


def _kpis(result: ScreenResult, cfg: Config, top: list[Candidate]) -> str:
    actionable = [c for c in top if c.sizing.actionable]
    total_weight = sum(c.sizing.target_weight or 0.0 for c in actionable)
    total_usd = sum(c.sizing.target_usd or 0.0 for c in actionable)
    best_mos = top[0].valuation.margin_of_safety if top else None
    best_ticker = top[0].ticker if top else MISSING
    investable = cfg.portfolio.equity_usd * (1 - cfg.portfolio.cash_reserve)
    idle = investable - total_usd

    cards = [
        (
            "Lolos semua gate",
            str(len(result.candidates)),
            f"dari {result.analysed} yang terparse",
            True,
        ),
        (
            "MOS tertinggi",
            percent(best_mos),
            f"{best_ticker}, terhadap nilai intrinsik",
            False,
        ),
        (
            "Alokasi disarankan",
            percent(total_weight),
            f"{usd(total_usd, 0)} dari sleeve",
            False,
        ),
        (
            "Belum terpakai",
            percent(idle / investable if investable else None),
            f"{usd(idle, 0)} tetap kas",
            False,
        ),
        (
            "Ditolak gate",
            str(len(result.rejected)),
            f"{len(result.errors)} gagal diambil",
            False,
        ),
    ]

    html = ['<div class="kpis">']
    for label, value, foot, primary in cards:
        html.append(
            f'<div class="kpi{" primary" if primary else ""}">'
            f'<div class="label">{_e(label)}</div>'
            f'<div class="value">{_e(value)}</div>'
            f'<div class="foot">{_e(foot)}</div>'
            "</div>"
        )
    html.append("</div>")
    return "".join(html)


def _memo_notes(memo: Memo) -> str:
    blocks = ["<h2>Bacaan Malam Ini</h2>", '<p class="section-note">Penilaian kualitatif dari model, di atas angka yang sudah dihitung.</p>']
    if memo.market_note:
        blocks.append(
            f'<div class="insight"><h4>Kondisi pasar</h4><p>{_e(memo.market_note)}</p></div>'
        )
    if memo.discipline_note:
        blocks.append(
            f'<div class="insight watch"><h4>Disiplin</h4>'
            f'<p>{_e(memo.discipline_note)}</p></div>'
        )
    return "".join(blocks)


def _ranking(top: list[Candidate]) -> str:
    rows = []
    for index, c in enumerate(top, start=1):
        v, q = c.valuation, c.quality
        alloc = (
            percent(c.sizing.target_weight)
            if c.sizing.actionable
            else f'<span class="muted">{MISSING}</span>'
        )
        rows.append(
            f"<tr>"
            f'<td class="r num">{index}</td>'
            f'<td class="strong">{_e(c.ticker)}</td>'
            f"<td>{_e(truncate(c.company.name, 28))}</td>"
            f"<td>{_e(c.sector)}</td>"
            f'<td class="r num">{_e(usd(v.price))}</td>'
            f'<td class="r num">{_e(usd(v.iv_base))}</td>'
            f'<td><div class="bar-wrap">'
            f'<span class="num">{_e(percent(v.margin_of_safety))}</span>'
            f"{_bar(v.margin_of_safety)}</div></td>"
            f'<td class="r num">{_e(number(q.score, 1))}</td>'
            f'<td class="r num">{_e(multiple(v.pe_trailing))}</td>'
            f'<td class="r num">{_e(multiple(v.pbv))}</td>'
            f'<td class="r num">{_e(percent(q.dividend.yield_pct))}</td>'
            f'<td class="r num">{alloc}</td>'
            f'<td class="r num strong">{_e(number(c.rank_score, 1))}</td>'
            f"</tr>"
        )

    return f"""
<h2>Peringkat Kandidat</h2>
<p class="section-note">
Diurutkan dari skor komposit tertinggi. Skor menggabungkan margin of safety,
kualitas bisnis, kesepakatan antar metode valuasi, dan rekam dividen.
Bar menunjukkan margin of safety relatif terhadap batas 60%.
</p>
<div class="card"><div class="scroll"><table>
<thead><tr>
<th class="r">#</th><th>Ticker</th><th>Nama</th><th>Sektor</th>
<th class="r">Harga</th><th class="r">Nilai Intrinsik</th><th>Margin of Safety</th>
<th class="r">Kualitas</th><th class="r">P/E</th><th class="r">PBV</th>
<th class="r">Div Yield</th><th class="r">Alokasi</th><th class="r">Skor</th>
</tr></thead>
<tbody>{"".join(rows)}</tbody>
</table></div></div>
"""


def _details(top: list[Candidate], memo: Memo, cfg: Config) -> str:
    blocks = [
        "<h2>Rincian per Nama</h2>",
        '<p class="section-note">Nama teratas diberi garis brand. Angka yang tidak '
        "tersedia di filing ditulis apa adanya, tidak diisi tebakan.</p>",
    ]
    for index, candidate in enumerate(top, start=1):
        blocks.append(_detail_card(candidate, memo, cfg, primary=index == 1))
    return "".join(blocks)


def _detail_card(
    candidate: Candidate, memo: Memo, cfg: Config, *, primary: bool
) -> str:
    v, q, s = candidate.valuation, candidate.quality, candidate.sizing
    stats, dividend = candidate.price_stats, q.dividend
    verdict = memo.verdict_for(candidate.ticker)

    pill_class = {"buy": "buy", "watch": "watch", "pass": "pass"}.get(
        verdict.verdict if verdict else "", "neutral"
    )
    pill_text = (
        f"{verdict_label(verdict.verdict)} · keyakinan {conviction_label(verdict.conviction)}"
        if verdict
        else "tanpa catatan model"
    )

    valuation_rows = "".join(
        f'<tr><td>{_e(label)}</td><td class="r num">{_e(usd(value))}</td></tr>'
        for label, value in (
            ("Discounted owner earnings", v.iv_dcf),
            ("Earnings power value", v.iv_epv),
            ("Multiple ternormalisasi", v.iv_multiple),
            ("Graham number", v.iv_graham),
            ("Book value", v.iv_book),
            ("Lantai bear case", v.iv_bear),
            ("Bull case", v.iv_bull),
        )
    )

    quality_rows = "".join(
        f'<tr><td>{_e(label)}</td><td class="r num">{_e(value)}</td></tr>'
        for label, value in (
            ("Skor kualitas komposit", f"{number(q.score, 1)} / 100"),
            (
                "Piotroski F-Score",
                f"{q.piotroski_f} / 9" if q.piotroski_f is not None else MISSING,
            ),
            ("Altman Z-Score", f"{number(q.altman_z)} ({zone_label(q.altman_zone)})"),
            ("Beneish M-Score", number(q.beneish_m)),
            ("ROE rata-rata", percent(q.avg_roe)),
            ("ROIC rata-rata", percent(q.avg_roic)),
            ("Margin operasi", percent(q.operating_margin_latest)),
            ("Pertumbuhan revenue", percent(q.revenue_cagr)),
            ("Pertumbuhan EPS", percent(q.eps_cagr)),
            ("Perubahan jumlah saham", signed_percent(q.share_count_cagr)),
            ("Debt to equity", multiple(q.debt_to_equity)),
            ("Interest coverage", multiple(q.interest_coverage)),
            (
                "Tahun laba positif",
                f"{q.positive_earnings_years} dari {q.years_available}",
            ),
            ("Tahun FCF positif", f"{q.positive_fcf_years} dari {q.years_available}"),
            ("Dividend yield", percent(dividend.yield_pct)),
            ("Payout ratio", percent(dividend.payout_ratio)),
            ("Tahun berturut bayar dividen", str(dividend.paying_years)),
            (
                "Rentang 52 minggu",
                f"{usd(stats.week52_low)} sampai {usd(stats.week52_high)}",
            ),
            ("Turun dari puncak", percent(stats.drawdown_from_high)),
            ("Volatilitas tahunan", percent(stats.volatility)),
        )
    )

    sizing_html = _sizing_block(s, cfg)
    flags_html = (
        '<div class="insight bad"><h4>Peringatan dari screen</h4><ul class="flags">'
        + "".join(f"<li>{_e(flag)}</li>" for flag in q.flags)
        + "</ul></div>"
        if q.flags
        else ""
    )
    memo_html = _memo_block(verdict) if verdict else ""

    return f"""
<div class="card{" primary" if primary else ""}">
  <div class="card-head">
    <div class="who">
      <span class="ticker">{_e(candidate.ticker)}</span>
      <span class="name">{_e(candidate.company.name)} · {_e(candidate.sector)}
        · kapitalisasi {_e(usd_compact(candidate.company.market_cap))}</span>
    </div>
    <span class="pill {pill_class}">{_e(pill_text)}</span>
  </div>

  <div class="grid3">
    <div class="insight">
      <h4>Margin of safety</h4>
      <div class="stat">{_e(percent(v.margin_of_safety))}</div>
      <p>Harga {_e(usd(v.price))} lawan nilai intrinsik blended
         {_e(usd(v.iv_base))}. Potensi naik {_e(percent(v.upside))}.</p>
    </div>
    <div class="insight">
      <h4>Kesepakatan antar metode</h4>
      <div class="stat">{_e(number(v.confidence, 2))}</div>
      <p>1,0 berarti empat metode valuasi sepakat, 0,2 berarti sebarannya lebar.
         Sebaran lebar otomatis memperkecil ukuran posisi.</p>
    </div>
    <div class="insight">
      <h4>Skor kualitas</h4>
      <div class="stat">{_e(number(q.score, 1))}</div>
      <p>Dari 100. Menggabungkan Piotroski, ROIC, konsistensi ROE,
         kekuatan neraca, dan integritas akuntansi.</p>
    </div>
  </div>

  <div class="grid2">
    <div>
      <h4>Estimasi nilai per lembar</h4>
      <div class="scroll"><table>
        <thead><tr><th>Metode</th><th class="r">Nilai</th></tr></thead>
        <tbody>{valuation_rows}
        <tr><td class="strong">Blended base case</td>
            <td class="r num strong">{_e(usd(v.iv_base))}</td></tr>
        </tbody>
      </table></div>
      <p class="section-note">Discount rate {_e(percent(v.discount_rate))},
      growth tahap satu {_e(percent(v.growth_stage1))} meluruh ke
      {_e(percent(v.terminal_growth))} selama {cfg.valuation.stage1_years} tahun.
      Owner earnings ternormalisasi
      {_e(usd_compact(v.owner_earnings_base))}.</p>
    </div>
    <div>
      <h4>Kualitas dan neraca</h4>
      <div class="scroll"><table>
        <thead><tr><th>Metrik</th><th class="r">Nilai</th></tr></thead>
        <tbody>{quality_rows}</tbody>
      </table></div>
    </div>
  </div>

  {sizing_html}
  {flags_html}
  {memo_html}
</div>
"""


def _sizing_block(sizing, cfg: Config) -> str:
    if not sizing.actionable:
        reason = sizing.notes[0] if sizing.notes else "tidak ada alasan tercatat"
        return (
            f'<div class="insight watch"><h4>Tidak diambil posisi</h4>'
            f"<p>{_e(reason)}</p></div>"
        )

    rows = "".join(
        f"<tr>"
        f'<td class="r num">{t.index}</td>'
        f'<td class="r num">{_e(usd(t.usd_amount, 0))}</td>'
        f'<td class="r num">{_e(usd(t.trigger_price))}</td>'
        f'<td class="r num">{_e(percent(t.target_margin_of_safety))}</td>'
        f'<td class="r num">{t.shares}</td>'
        f"<td>{'beli sekarang' if t.is_immediate else f'tetap beli per {day(t.fallback_date)}'}</td>"
        f"</tr>"
        for t in sizing.tranches
    )

    return f"""
<h4>Ukuran posisi dan jadwal masuk</h4>
<div class="insight good">
  <div class="stat">{_e(percent(sizing.target_weight))} sleeve
    · {_e(usd(sizing.target_usd, 0))}</div>
  <p>Probabilitas menang yang dimodelkan {_e(percent(sizing.win_probability))},
     upside {_e(percent(sizing.upside))} lawan potensi rugi permanen
     {_e(percent(sizing.downside))} (rasio {_e(number(sizing.odds, 2))}).
     Kelly penuh {_e(percent(sizing.kelly_full))}, dipakai
     {_e(percent(cfg.kelly.fraction, 0))} Kelly karena parameternya estimasi,
     bukan peluang yang diketahui.
     {("Dibatasi oleh: " + _e(str(sizing.capped_by)) + ".") if sizing.capped_by else ""}</p>
  <div class="scroll"><table>
    <thead><tr>
      <th class="r">Tranche</th><th class="r">Jumlah</th><th class="r">Harga trigger</th>
      <th class="r">MOS di harga itu</th><th class="r">Lembar</th><th>Kalau harga tidak turun</th>
    </tr></thead>
    <tbody>{rows}</tbody>
  </table></div>
  <p class="action">Tranche satu dieksekusi di harga sekarang. Tranche berikutnya
  menunggu harga yang memberi margin of safety lebih lebar, dan kalau tidak
  pernah datang, tetap masuk di tanggal jatuh temponya supaya kas tidak
  menganggur selamanya.</p>
</div>
"""


def _memo_block(verdict) -> str:
    wrong = "".join(
        f"<li>{_e(item)}</li>" for item in verdict.what_would_make_me_wrong
    )
    questions = "".join(
        f"<li>{_e(item)}</li>" for item in verdict.questions_before_buying
    )
    return f"""
<h4>Catatan Buffett</h4>
<div class="insight">
  <p><strong>Bisnisnya.</strong> {_e(verdict.business_in_one_line)}</p>
  <p><strong>Moat.</strong> {_e(verdict.moat)}</p>
  <p><strong>Kenapa murah.</strong> {_e(verdict.why_it_is_cheap)}</p>
  <p><strong>Soal sizing.</strong> {_e(verdict.sizing_comment)}</p>
  <div class="grid2">
    <div><h4>Yang bisa membuat tesis ini salah</h4>
      <ul class="flags">{wrong}</ul></div>
    <div><h4>Yang harus dicek sendiri sebelum beli</h4>
      <ul class="flags">{questions}</ul></div>
  </div>
</div>
"""


def _empty_state(result: ScreenResult, cfg: Config) -> str:
    return f"""
<h2>Tidak Ada Kandidat Malam Ini</h2>
<div class="card">
  <p>Tidak ada satu pun nama yang lolos semua gate. {len(result.rejected)} nama
  ditolak dan {len(result.errors)} gagal diambil. Gate valuasi menuntut margin of
  safety minimal {_e(percent(cfg.valuation.min_margin_of_safety, 0))} terhadap
  nilai intrinsik blended.</p>
  <p class="action">Tidak ada aksi beli. Kas tetap di tempat. Ini keluaran yang
  normal dan sehat untuk screener value: kebanyakan malam memang tidak ada yang
  layak dibeli.</p>
</div>
"""


def _watchlist(result: ScreenResult, cfg: Config) -> str:
    watchlist = result.rejected[: cfg.report.watchlist_n]
    if not watchlist:
        return ""
    rows = "".join(
        f"<tr>"
        f'<td class="strong">{_e(c.ticker)}</td>'
        f"<td>{_e(truncate(c.company.name, 28))}</td>"
        f"<td>{_e(c.sector)}</td>"
        f'<td class="r num">{_e(number(c.rank_score, 1))}</td>'
        f'<td class="r num">{_e(percent(c.valuation.margin_of_safety))}</td>'
        f'<td class="r num">{_e(number(c.quality.score, 1))}</td>'
        f"<td>{_e('; '.join(c.gate.failures[:2]) or MISSING)}</td>"
        f"</tr>"
        for c in watchlist
    )
    return f"""
<h2>Watchlist</h2>
<p class="section-note">Skornya tinggi tapi gagal minimal satu gate. Dipantau,
tidak dibeli. Kolom terakhir menyebut alasan gagalnya.</p>
<div class="card"><div class="scroll"><table>
<thead><tr><th>Ticker</th><th>Nama</th><th>Sektor</th><th class="r">Skor</th>
<th class="r">MOS</th><th class="r">Kualitas</th><th>Gate yang gagal</th></tr></thead>
<tbody>{rows}</tbody>
</table></div></div>
"""


def _limits(result: ScreenResult, memo: Memo, cfg: Config) -> str:
    items = [
        "Semua angka fundamental berasal dari XBRL 10-K. Filer yang menandai elemen "
        f"secara tidak standar bisa punya baris kosong; itu tampil sebagai "
        f"\"{MISSING}\", tidak pernah diisi angka tebakan.",
        "Nilai intrinsik adalah estimasi, bukan fakta. Empat metode dipakai supaya "
        "sebarannya kelihatan, dan sebaran yang lebar sudah otomatis memperkecil "
        "ukuran posisi.",
        "Probabilitas menang di Kelly adalah keluaran model dari margin of safety, "
        "kualitas, dan kesepakatan antar metode. Itu bukan frekuensi historis.",
        "Screener ini tidak membaca berita, transkrip earnings call, atau komentar "
        "manajemen. Risiko yang hanya muncul di sana tidak terlihat di sini.",
        "Harga adalah penutupan sesi AS terakhir, bukan harga real-time.",
    ]
    if result.errors:
        sample = ", ".join(list(result.errors)[:8])
        items.append(
            f"{len(result.errors)} simbol gagal diambil dan tidak ikut dinilai: {sample}."
        )
    if not memo.available:
        items.append(f"Catatan Buffett tidak tersedia malam ini: {memo.error}.")
    if cfg.portfolio.usd_to_idr is None:
        items.append(
            "Semua angka dalam USD. Konversi rupiah tidak ditampilkan karena kurs "
            "belum diisi di config (portfolio.usd_to_idr)."
        )

    return (
        '<div class="limits"><h2>Batasan</h2><ul>'
        + "".join(f"<li>{_e(item)}</li>" for item in items)
        + "</ul></div>"
    )


def _footer(result: ScreenResult, cfg: Config) -> str:
    return f"""
<footer>
  <p>Sumber: SEC EDGAR companyfacts API (laporan keuangan tahunan) dan riwayat
  harga penutupan harian. Harga per {_e(day(result.price_as_of))}.</p>
  <p>Dijalankan {_e(day(result.run_date))} pada jadwal
  {cfg.schedule.hour:02d}:{cfg.schedule.minute:02d} {_e(cfg.schedule.timezone)}.
  Universe {result.universe_size} simbol, {result.analysed} terparse,
  {len(result.errors)} gagal.</p>
  <p>Bukan nasihat investasi. Ini alat riset; keputusan dan risikonya tetap milikmu.</p>
</footer>
"""
