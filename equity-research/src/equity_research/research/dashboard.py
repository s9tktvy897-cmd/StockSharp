"""Self-contained HTML dashboard of the research run and the prediction ledger. Four evidence
levels are kept apart: historical backtest (development period), out-of-sample holdout, paper
trading on new data (the ledger) and live trading (none: not authorised)."""

from __future__ import annotations

import html
import json

STYLE = """
/* Layout: a verdict strip, four evidence lanes side by side, then the strategy table and one chart panel. */
:root {
  --bg: #f4f6f9; --surface: #ffffff; --ink: #18212c; --muted: #5a6574; --line: #d9dfe8;
  --accent: #2c5b88; --good: #2b7a4b; --warn: #9a6400; --bad: #b03636; --chip: #e9eef5;
  --f-display: "IBM Plex Sans Condensed", "Arial Narrow", system-ui, sans-serif;
  --f-body: "IBM Plex Sans", system-ui, -apple-system, "Segoe UI", sans-serif;
  --f-data: "IBM Plex Mono", ui-monospace, "SFMono-Regular", Menlo, monospace;
}
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) {
  --bg: #0e131a; --surface: #151c25; --ink: #e5ebf2; --muted: #97a2b2; --line: #263241;
  --accent: #7eaedf; --good: #5bc387; --warn: #e2a845; --bad: #ee7676; --chip: #1e2835; color-scheme: dark } }
:root[data-theme="dark"] {
  --bg: #0e131a; --surface: #151c25; --ink: #e5ebf2; --muted: #97a2b2; --line: #263241;
  --accent: #7eaedf; --good: #5bc387; --warn: #e2a845; --bad: #ee7676; --chip: #1e2835; color-scheme: dark }
body { background: var(--bg); color: var(--ink); font: 15px/1.5 var(--f-body); }
.wrap { max-width: 1180px; margin: 0 auto; padding-inline: 16px; padding-block: 24px 48px; display: grid; gap: 24px; }
h1, h2, h3 { font-family: var(--f-display); text-wrap: balance; margin: 0; }
h1 { font-size: 1.9rem; font-weight: 600; letter-spacing: .01em; }
h2 { font-size: 1.2rem; font-weight: 600; }
.sub { color: var(--muted); margin: 4px 0 0; max-width: 70ch; }
.verdict { display: flex; flex-wrap: wrap; gap: 12px 24px; align-items: center; padding: 16px; background: var(--surface);
  border: 1px solid var(--line); border-radius: 6px; }
.verdict .big { font-family: var(--f-display); font-size: 1.5rem; font-weight: 700; letter-spacing: .02em; }
.lanes { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.lane { background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 14px; display: grid; gap: 6px; min-width: 0; }
.lane .label { font-size: .72rem; text-transform: uppercase; letter-spacing: .08em; color: var(--muted); }
.lane .value { font-family: var(--f-data); font-size: 1.25rem; font-variant-numeric: tabular-nums; }
.lane p { margin: 0; color: var(--muted); font-size: .88rem; }
.pill { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: .74rem; font-weight: 600;
  letter-spacing: .03em; background: var(--chip); color: var(--ink); white-space: nowrap; }
.pill.bad { color: var(--bad); } .pill.warn { color: var(--warn); } .pill.good { color: var(--good); }
.panel { background: var(--surface); border: 1px solid var(--line); border-radius: 6px; padding: 16px; display: grid; gap: 12px; min-width: 0; }
.scroll { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: .86rem; }
th, td { text-align: right; padding: 6px 8px; border-bottom: 1px solid var(--line); white-space: nowrap; }
th:first-child, td:first-child, th:nth-child(2), td:nth-child(2) { text-align: left; }
th { font-weight: 600; color: var(--muted); font-size: .76rem; text-transform: uppercase; letter-spacing: .05em; }
td { font-family: var(--f-data); font-variant-numeric: tabular-nums; }
td:first-child { font-family: var(--f-body); }
tbody tr { cursor: pointer; }
tbody tr:hover, tbody tr[aria-selected="true"] { background: var(--chip); }
tbody tr:focus-visible { outline: 2px solid var(--accent); outline-offset: -2px; }
.neg { color: var(--bad); } .pos { color: var(--good); }
.charts { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
svg { width: 100%; height: auto; display: block; }
svg text { fill: var(--muted); font: 11px var(--f-data); }
.grid line { stroke: var(--line); }
.legend { display: flex; flex-wrap: wrap; gap: 16px; font-size: .82rem; color: var(--muted); }
.swatch { display: inline-block; width: 18px; height: 3px; vertical-align: middle; margin-right: 6px; }
ul.notes { margin: 0; padding-left: 18px; color: var(--muted); font-size: .88rem; display: grid; gap: 4px; }
@media (prefers-reduced-motion: no-preference) { tbody tr { transition: background .12s; } }
"""

SCRIPT = r"""
const D = JSON.parse(document.getElementById('data').textContent);
const pct = (x, d = 2) => x == null ? '–' : (x * 100).toFixed(d).replace('.', ',') + '%';
const num = (x, d = 2) => x == null ? '–' : x.toFixed(d).replace('.', ',');
const cls = x => x == null ? '' : (x < 0 ? 'neg' : x > 0 ? 'pos' : '');
const STATUS = {'REJECTED': 'bad', 'RESEARCH ONLY': 'warn', 'PAPER TRADING CANDIDATE': 'good', 'PAPER TRADING VALIDATED': 'good'};
const order = ['PAPER TRADING VALIDATED', 'PAPER TRADING CANDIDATE', 'RESEARCH ONLY', 'REJECTED'];
const rows = [...D.variants].sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status) || (b.dev.sharpe ?? -9) - (a.dev.sharpe ?? -9));
const body = document.getElementById('rows');
rows.forEach((r, i) => {
  const tr = document.createElement('tr');
  tr.tabIndex = 0;
  tr.innerHTML = `<td>${r.variant}</td><td><span class="pill ${STATUS[r.status]}">${r.status}</span></td>
    <td>${r.dev.trade_trades ?? 0}</td><td class="${cls(r.dev.trade_expected_value)}">${pct(r.dev.trade_expected_value)}</td>
    <td>${pct(r.trade_ci[0])} – ${pct(r.trade_ci[1])}</td><td class="${cls(r.dev.sharpe)}">${num(r.dev.sharpe)}</td>
    <td class="neg">${pct(r.dev.max_drawdown, 1)}</td><td class="${cls(r.dev_2x.mean_daily)}">${pct(r.dev_2x.mean_daily, 3)}</td>
    <td class="${cls(r.holdout.trade_expected_value)}">${pct(r.holdout.trade_expected_value)}</td>
    <td class="${cls(r.holdout.sharpe)}">${num(r.holdout.sharpe)}</td>`;
  tr.addEventListener('click', () => select(i));
  tr.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); select(i); } });
  body.appendChild(tr);
});
function line(points, x, y) { return points.map((p, k) => (k ? 'L' : 'M') + x(p[0]).toFixed(1) + ',' + y(p[1]).toFixed(1)).join(''); }
function chart(el, series, opts) {
  const W = 560, H = 220, L = 52, R = 12, T = 12, B = 26;
  const all = series.flatMap(s => s.points);
  if (!all.length) { el.innerHTML = '<text x="12" y="24">Geen data</text>'; return; }
  const t = s => Date.parse(s);
  const x0 = Math.min(...all.map(p => t(p[0]))), x1 = Math.max(...all.map(p => t(p[0])));
  let y0 = Math.min(...all.map(p => p[1])), y1 = Math.max(...all.map(p => p[1]));
  if (opts.zero) { y1 = Math.max(y1, 0); }
  const pad = (y1 - y0) * 0.06 || 0.01; y0 -= pad; y1 += pad;
  const x = v => L + (t(v) - x0) / Math.max(x1 - x0, 1) * (W - L - R);
  const y = v => T + (y1 - v) / (y1 - y0) * (H - T - B);
  const ticks = 4, grid = [];
  for (let k = 0; k <= ticks; k++) {
    const v = y0 + (y1 - y0) * k / ticks;
    grid.push(`<line x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"></line><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${opts.fmt(v)}</text>`);
  }
  const years = [];
  for (let yr = new Date(x0).getUTCFullYear() + 1; yr <= new Date(x1).getUTCFullYear(); yr++) {
    const d = yr + '-01-01'; years.push(`<text x="${x(d)}" y="${H - 8}" text-anchor="middle">${yr}</text>`);
  }
  el.setAttribute('viewBox', `0 0 ${W} ${H}`);
  el.innerHTML = `<g class="grid">${grid.join('')}</g>${years.join('')}` + series.map(s =>
    `<path d="${line(s.points, x, y)}" fill="none" stroke="${s.color}" stroke-width="${s.width || 1.6}" ${s.dash ? 'stroke-dasharray="4 3"' : ''}></path>`).join('');
}
function rebase(points, start) {
  const from = points.filter(p => p[0] >= start);
  if (!from.length) return [];
  const b = from[0][1]; return from.map(p => [p[0], p[1] / b]);
}
function drawdown(points) { let peak = -Infinity; return points.map(p => { peak = Math.max(peak, p[1]); return [p[0], p[1] / peak - 1]; }); }
const css = getComputedStyle(document.documentElement);
const color = n => css.getPropertyValue(n).trim();
function select(i) {
  [...body.children].forEach((tr, k) => tr.setAttribute('aria-selected', k === i ? 'true' : 'false'));
  const r = rows[i];
  document.getElementById('sel').textContent = r.variant + ' — ' + r.status;
  const dev = r.curve, hold = r.holdout_curve;
  const last = dev.length ? dev[dev.length - 1][1] : 1;
  const joined = dev.concat(hold.map(p => [p[0], p[1] * last]));
  const spy = rebase(D.spy_curve, joined.length ? joined[0][0] : '');
  chart(document.getElementById('eq'), [
    {points: spy, color: color('--muted'), dash: true, width: 1.2},
    {points: dev, color: color('--accent')},
    {points: hold.map(p => [p[0], p[1] * last]), color: color('--warn')}], {fmt: v => num(v, 2)});
  chart(document.getElementById('dd'), [{points: drawdown(joined), color: color('--bad')}], {fmt: v => pct(v, 0), zero: true});
}
select(0);
"""


def _after_open_html(hourly: dict | None, holding: dict | None) -> str:
    """Two exploratory sections: the day's high after the open (hourly bars) and the holding period."""
    pct = lambda x, d=1: "–" if x is None else f"{x * 100:.{d}f}%".replace(".", ",")
    out = ""
    if hourly:
        rows = {(r["condition"], r["value"]): r for r in hourly.get("results", [])}
        allr = rows.get(("all", "all stock-days"))
        if allr:
            big = allr.get("peak_hour_share_if_peak_5", {})
            hours = "".join(f"<tr><td>{html.escape(k)}</td><td></td><td>{pct(v)}</td><td>{pct(big.get(k))}</td></tr>"
                            for k, v in allr["peak_hour_share"].items())
            out += ("<section class=\"panel\"><h2>Wanneer valt de hoogste koers na de opening?</h2>"
                    f"<p class=\"sub\">Uurkoersen {html.escape(hourly.get('period_from', ''))} tot nu, "
                    + f"{hourly.get('stock_days', 0):,}".replace(",", ".")
                    + f" aandeel-dagen. Verkennend; {hourly.get('trials', 0)} combinaties getoetst, "
                    "geen enkele significant positief na correctie.</p>"
                    + "<div class=\"scroll\"><table><thead><tr><th>Uur (New York)</th><th></th><th>Alle dagen</th>"
                    "<th>Dagen met piek ≥ +5%</th></tr></thead><tbody>" + hours + "</tbody></table></div>")
        picks = [("all", "all stock-days"), ("news before the open (8-K)", "earnings 8-K"), ("opening gap", "-10..-3%"),
                 ("opening gap", "< -10%"), ("opening gap", "+10..+20%"), ("opening gap", "> +20%"),
                 ("daily volatility (20d)", "> 8%")]
        body = ""
        for key in picks:
            r = rows.get(key)
            if not r:
                continue
            name, best = max(r["rules"].items(), key=lambda kv: kv[1]["mean_net"])
            body += (f"<tr><td>{html.escape(key[1] if key[0] == 'all' else key[0] + ': ' + key[1])}</td><td></td>"
                     f"<td>{pct(r['p_peak_5'])}</td><td>{pct(r['p_low_5'])}</td><td>{pct(r['median_peak'], 2)}</td>"
                     f"<td>{pct(r['giveback_after_peak'], 2)}</td><td>{html.escape(name)}</td>"
                     f"<td class=\"{'neg' if best['mean_net'] < 0 else 'pos'}\">{pct(best['mean_net'], 2)}</td></tr>")
        out += ("<h3>Kans op +5% en −5% na de opening, en wat een vaste regel oplevert (na kosten)</h3>"
                "<div class=\"scroll\"><table><thead><tr><th>Situatie</th><th></th><th>Piek ≥ +5%</th><th>Dal ≤ −5%</th>"
                "<th>Mediane piek</th><th>Terugval tot slot</th><th>Beste regel</th><th>Netto/trade</th></tr></thead>"
                f"<tbody>{body}</tbody></table></div></section>")
    if holding:
        body = ""
        for name in ("all eligible stock-days (random) | development", "SPY | development",
                     "momentum 12-1 top 10 per day | development", "earnings drift top 10 per day | development",
                     "SPY | holdout"):
            for h, d in holding.get(name, {}).items():
                if h in ("1", "20", "120", "250") and d.get("n"):
                    label = name.replace("all eligible stock-days (random)", "willekeurig aandeel").replace(
                        " | development", "").replace(" | holdout", " (holdout)").replace(" top 10 per day", " top-10")
                    body += (f"<tr><td>{html.escape(label)}, {h} dagen</td><td></td><td>{pct(d['mean'], 2)}</td>"
                             f"<td>{pct(d['median'], 2)}</td><td>{pct(d['p_ge_5'])}</td><td>{pct(d['p_loss'])}</td></tr>")
        out += ("<section class=\"panel\"><h2>Hoe lang aanhouden voor gemiddeld +5%?</h2>"
                "<p class=\"sub\">Instap op de opening, uitstap op het slot na h handelsdagen, na kosten. Een hoog gemiddelde "
                "met een negatieve mediaan betekent dat de typische trade verliest.</p>"
                "<div class=\"scroll\"><table><thead><tr><th>Wat en hoe lang</th><th></th><th>Gemiddeld</th><th>Mediaan</th>"
                f"<th>Kans ≥ +5%</th><th>Kans op verlies</th></tr></thead><tbody>{body}</tbody></table></div></section>")
    return out


def render(js: dict, ledger_summary: dict, open_predictions: list[dict], ledger_ok: bool,
           hourly: dict | None = None, holding: dict | None = None) -> str:
    v = js["variants"]
    statuses = [r["status"] for r in v]
    verdict = ("PAPER TRADING CANDIDATE" if any(s.startswith("PAPER") for s in statuses) else
               "RESEARCH ONLY" if "RESEARCH ONLY" in statuses else "NO PROVEN EDGE")
    tone = {"NO PROVEN EDGE": "bad", "RESEARCH ONLY": "warn"}.get(verdict, "good")
    meta = js.get("meta", {})
    best = max(v, key=lambda r: r["dev"].get("sharpe") or -9) if v else None
    pt = ledger_summary.get("paper", {})
    pr = ledger_summary.get("predictions", {})
    counts = {s: statuses.count(s) for s in ("REJECTED", "RESEARCH ONLY", "PAPER TRADING CANDIDATE", "PAPER TRADING VALIDATED")}

    def pct(x, d=2):
        return "–" if x is None else f"{x * 100:.{d}f}%".replace(".", ",")

    lanes = [
        ("Historische backtest", f"{len(v)} varianten",
         f"Ontwikkelperiode tot {meta.get('dev_end', '?')}. Afgewezen {counts['REJECTED']}, alleen onderzoek "
         f"{counts['RESEARCH ONLY']}. Hoogste Sharpe: {html.escape(best['variant']) if best else '–'} "
         f"({(best['dev'].get('sharpe') or 0):.2f})." if best else ""),
        ("Holdout (buiten de steekproef)", f"{sum(1 for r in v if r['holdout_ok'])} van {len(v)} positief",
         "Vanaf 2025-10-01, eenmalig geëvalueerd; telt alleen mee voor varianten die de ontwikkelcriteria halen."),
        ("Paper trading", f"{pt.get('closed', 0)} gesloten",
         f"Alleen strategieën met status PAPER TRADING CANDIDATE worden paper-getraded. Voorspellingen in het register: "
         f"{pr.get('total', 0)} (open {pr.get('open', 0)}, gevuld {pr.get('filled', 0)}, gesloten {pr.get('closed', 0)}); "
         f"richting goed {pct(pr.get('direction_hit_rate'), 0)}. Hash-keten {'intact' if ledger_ok else 'GEBROKEN'}."),
        ("Live trading", "Niet geautoriseerd",
         "Geen brokerkoppeling, geen echte orders. Vereist aparte, uitdrukkelijke toestemming."),
    ]
    lane_html = "".join(f'<div class="lane"><span class="label">{html.escape(a)}</span><span class="value">{html.escape(b)}</span>'
                        f"<p>{c}</p></div>" for a, b, c in lanes)
    bench = js.get("benchmarks", {})
    bench_rows = "".join(f"<tr><td>{html.escape(k)}</td><td></td><td>{pct(b.get('cagr'), 1)}</td><td>{(b.get('sharpe') or 0):.2f}</td>"
                         f"<td>{pct(b.get('max_drawdown'), 1)}</td></tr>" for k, b in bench.items()
                         if not k.startswith("RANDOM") or "development" in k)
    open_rows = "".join(f"<tr><td>{html.escape(o['ticker'])}</td><td>{html.escape(o['strategy'])}</td><td>{o['signal_date']}</td>"
                        f"<td>{o['horizon']}d</td><td>{html.escape(o['status'])}</td></tr>" for o in open_predictions) \
        or '<tr><td colspan="5">Geen open voorspellingen.</td></tr>'
    notes = "".join(f"<li>{html.escape(n)}</li>" for n in js.get("notes", []))
    data = json.dumps({"variants": v, "spy_curve": js.get("spy_curve", [])}).replace("</", "<\\/")
    return f"""<title>Handelsvoordeel Onderzoek</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans+Condensed:wght@600;700&family=IBM+Plex+Sans:wght@400;600&display=swap">
<style>{STYLE}</style>
<div class="wrap">
  <header>
    <h1>Onderzoek naar een handelsvoordeel</h1>
    <p class="sub">Run van {html.escape(str(meta.get('date', '?')))}, code {html.escape(str(meta.get('code', '?')))}. Historische simulatie met
    realistische uitvoering, kosten en risicolimieten; protocol vooraf vastgelegd. Geen beleggingsadvies en geen garantie.</p>
  </header>
  <section class="verdict" aria-label="Eindoordeel">
    <span class="big">{verdict}</span><span class="pill {tone}">{len(v)} varianten getest, Holm-gecorrigeerd</span>
    <span class="sub">Survivorship bias: alleen huidige noteringen; resultaten zijn daardoor eerder te gunstig.</span>
  </section>
  <section class="lanes" aria-label="Bewijsniveaus">{lane_html}</section>
  <section class="panel">
    <h2>Strategieën (ontwikkelperiode, basiskosten)</h2>
    <p class="sub">Klik een rij voor de vermogens- en drawdowncurve. Netto per trade met 95%-interval geclusterd per signaaldag.</p>
    <div class="scroll"><table>
      <thead><tr><th>Variant</th><th>Status</th><th>Trades</th><th>Netto/trade</th><th>95%-BI</th><th>Sharpe</th>
      <th>Max. DD</th><th>2× kosten/dag</th><th>Holdout/trade</th><th>Holdout Sharpe</th></tr></thead>
      <tbody id="rows"></tbody></table></div>
  </section>
  <section class="panel" aria-live="polite">
    <h2 id="sel"></h2>
    <div class="legend"><span><span class="swatch" style="background: var(--accent)"></span>Ontwikkelperiode</span>
      <span><span class="swatch" style="background: var(--warn)"></span>Holdout</span>
      <span><span class="swatch" style="background: var(--muted)"></span>SPY (zelfde start)</span></div>
    <div class="charts"><div><h3>Vermogen (start = 1)</h3><svg id="eq" role="img" aria-label="Vermogenscurve"></svg></div>
      <div><h3>Drawdown</h3><svg id="dd" role="img" aria-label="Drawdowncurve"></svg></div></div>
  </section>
  <section class="panel">
    <h2>Benchmarks</h2>
    <div class="scroll"><table><thead><tr><th>Benchmark</th><th></th><th>CAGR</th><th>Sharpe</th><th>Max. DD</th></tr></thead>
    <tbody>{bench_rows}</tbody></table></div>
  </section>
  {_after_open_html(hourly, holding)}
  <section class="panel">
    <h2>Open voorspellingen in het register</h2>
    <div class="scroll"><table><thead><tr><th>Ticker</th><th>Strategie</th><th>Signaal</th><th>Horizon</th><th>Status</th></tr></thead>
    <tbody>{open_rows}</tbody></table></div>
  </section>
  <section class="panel">
    <h2>Beperkingen</h2>
    <ul class="notes"><li>Universum = huidige noteringen (geen gedeliste aandelen): survivorship bias.</li>
    <li>Kosten, spread en marktimpact zijn modellen; echte kosten bij kleine, beweeglijke aandelen zijn vaak hoger.</li>
    <li>Yahoo Finance is een onofficiële bron; SEC-data is officieel.</li>{notes}</ul>
  </section>
</div>
<script type="application/json" id="data">{data}</script>
<script>{SCRIPT}</script>
"""
