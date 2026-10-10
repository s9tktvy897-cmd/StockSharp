"""``python -m equity_research.shortterm {scan,catalysts,evaluate} [options]``

scan       daily run: data check, out-of-sample tests, backtest, top 10, prediction log and report
catalysts  new 8-K filings from the SEC live feed
evaluate   compare logged predictions with what happened since"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

from equity_research import ledger as ledger_mod
from equity_research.report import context
from equity_research.report.markdown import _git_revision
from equity_research.shortterm import catalysts as cat
from equity_research.shortterm import engine, predictions, report
from equity_research.shortterm.config import Config
from equity_research.shortterm.sources import ShortTermSources, load
from equity_research.valuation.run import FETCH_ERRORS

ROOT = Path(__file__).resolve().parents[3]
REPORTS = ROOT / "reports" / "shortterm"
PREDICTIONS = ROOT / "predictions"
LEDGER = ROOT / "ledger" / "ledger.jsonl"


def log_to_ledger(result, path: Path, code: str, scan_time: datetime, listings: dict) -> int:
    """Every candidate becomes an immutable ledger record. The short-term ranking has not passed the
    research protocol, so these are predictions to score, not paper trades."""
    book = ledger_mod.Ledger(path)
    n = 0
    panel = result.panel
    latest = {panel.tickers[i]: float(panel.dollar_volume[i]) for i in range(len(panel.dates))
              if len(panel.dates) and panel.dates[i] == result.latest_date}
    for c in result.candidates:
        h = result.ranking_horizon or max(result.config.horizons)
        p = ledger_mod.Prediction(
            ticker=c.ticker, security_id=f"CIK{listings[c.ticker].cik}" if c.ticker in listings else "",
            strategy=result.ranking_code or "SHORTTERM_SCANNER_UNVALIDATED", horizon=h, model_version=code,
            dataset_version=f"{result.bars_source} up to {c.last_date}", signal_date=c.last_date, direction="long",
            expected_return=c.score if result.ranking_code == "SHORTTERM_EXPECTED_RETURN" else None,
            probabilities={"hit_10pct": c.probability.get(h), "drop_10pct": c.drop_probability.get(h)},
            expected_cost_per_side=result.config.costs.per_side(latest.get(c.ticker, 0.0)),
            paper_trade=False, strategy_status="RESEARCH ONLY (not validated by the research protocol)")
        try:
            book.add(p, scan_time)
            n += 1
        except ValueError:
            pass  # already logged by an earlier run for the same signal date
    return n


def evaluate_ledger(path: Path, bars: dict, config: Config) -> dict:
    from equity_research.shortterm.features import rolling
    book = ledger_mod.Ledger(path)

    def cost(ticker, i):
        b = bars[ticker]
        dv = rolling(b.close * b.volume, 20, lambda x, axis: x.mean(axis=axis))
        return config.costs.per_side(float(dv[i - 1]) if i and dv[i - 1] == dv[i - 1] else 0.0)

    changed = book.evaluate(bars, datetime.now(timezone.utc), cost)
    return {"changed": changed, "summary": book.summary(), "problems": book.verify()}


def _live_filings(sources: ShortTermSources, hours: int, missing: list[str]) -> tuple[list, dict]:
    names = {}
    try:
        listings = sources.listings()
        by_cik = {}
        for l in sorted(listings.values(), key=lambda l: (len(l.ticker), l.ticker)):
            by_cik.setdefault(l.cik, l)  # prefer the common stock (shortest ticker) over warrants/units
        filings = sources.current_8k(datetime.now(timezone.utc) - timedelta(hours=hours))
        out = []
        for f in filings:
            listing = by_cik.get(f.cik)
            ticker = listing.ticker if listing else ""
            if listing:
                names[ticker] = listing.name
            out.append(cat.Filing(ticker, f.cik, f.accession, f.form, f.items, f.accepted, f.url))
        return out, names
    except FETCH_ERRORS as error:
        missing.append(f"SEC live feed: {error}")
        return [], names


def _todays_opens(tickers: list[str], day) -> dict[str, float]:
    """First 5-minute bar of the regular session today (Yahoo, secondary)."""
    import yfinance
    out = {}
    for k in range(0, len(tickers), 200):
        chunk = tickers[k:k + 200]
        frame = yfinance.download([t.replace(".", "-") for t in chunk], period="1d", interval="5m", group_by="ticker",
                                  progress=False, auto_adjust=False, prepost=False, threads=True)
        if frame is None or frame.empty:
            continue
        for t in chunk:
            sym = t.replace(".", "-")
            try:
                part = frame[sym]["Open"].dropna()
            except KeyError:
                continue
            part = part[[ts.tz_convert(cat.NEW_YORK).date() == day for ts in part.index]]
            if len(part):
                out[t] = float(part.iloc[0])
    return out


def run_opening(args, sources: ShortTermSources, config: Config) -> None:
    import json as _json
    from equity_research.data.yahoo import YahooPrices
    from equity_research.shortterm import opening
    from equity_research.shortterm.features import rolling

    now_et = datetime.now(timezone.utc).astimezone(cat.NEW_YORK)
    if not args.any_time and not (now_et.weekday() < 5 and (9, 35) <= (now_et.hour, now_et.minute) <= (11, 0)):
        print(f"outside the 09:35-11:00 ET window ({now_et:%Y-%m-%d %H:%M} ET): nothing to do")
        return
    missing: list[str] = []
    listings = sources.listings()
    tickers = sorted(listings)[:args.max_tickers] if args.max_tickers else sorted(listings)
    bars, problems = YahooPrices(Path(__file__).resolve().parents[3] / "data" / "cache").bars(tickers)
    if problems:
        missing.append(f"Yahoo dagkoersen: {len(problems)} tickers zonder data")
    today = now_et.date()
    liquid = {}
    for t, b in bars.items():
        past = [i for i, d in enumerate(b.dates) if d < today]
        if len(past) < 21:
            continue
        i = past[-1]
        dv = float(rolling(b.close * b.volume, 20, lambda x, axis: x.mean(axis=axis))[i])
        if b.traded_close[i] >= config.min_price and dv >= config.min_dollar_volume:
            liquid[t] = (i, dv)
    opens = _todays_opens(sorted(liquid), today)
    if not opens:
        missing.append("Yahoo: geen openingskoersen van vandaag (markt dicht of bron niet bereikbaar)")
    since = datetime.combine(max(bars[t].dates[i] for t, (i, _) in liquid.items()) if liquid else today,
                             datetime.min.time().replace(hour=16), cat.NEW_YORK).astimezone(timezone.utc)
    try:
        filings = sources.current_8k(since)
    except FETCH_ERRORS as error:
        filings, _ = [], missing.append(f"SEC live feed: {error}")
    by_cik = {}
    for l in listings.values():
        by_cik.setdefault(l.cik, l.ticker)
    news = {}
    for f in filings:
        t = by_cik.get(f.cik)
        if t:
            news.setdefault(t, []).append(f.items)
    situations = []
    for t, open_price in opens.items():
        i, dv = liquid[t]
        b = bars[t]
        prev = float(b.close[i])
        move = float(b.close[i] / b.close[i - 1] - 1) if i else 0.0
        situations.append(opening.Situation(t, listings[t].name, prev, open_price, move,
                                            opening.news_label(news.get(t, [])), dv))
    research = ROOT / "reports" / "research"
    load = lambda pattern: (_json.loads(sorted(research.glob(pattern))[-1].read_text(encoding="utf-8"))
                            if list(research.glob(pattern)) else None)
    hourly, daily = load("after_open_hourly_*.json"), load("after_open_daily_*.json")
    if hourly is None and daily is None:
        missing.append("geen onderzoeksresultaten na de opening gevonden in reports/research")
    decision = opening.decide(situations, hourly, daily)
    text = opening.render(decision, today, opening.RiskPlan(), missing)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    path = args.output_dir / f"opening_{today}.md"
    path.write_text(text, encoding="utf-8")
    book = ledger_mod.Ledger(args.ledger)
    logged = 0
    code = _git_revision()
    for group, rows in (("validated", decision.tradable), ("watch", decision.watch)):
        for s, ev in rows:
            signal_day = bars[s.ticker].dates[liquid[s.ticker][0]]
            try:
                book.add(ledger_mod.Prediction(
                    ticker=s.ticker, security_id=f"CIK{listings[s.ticker].cik}", strategy="OPENING_" + group.upper(),
                    horizon=1, model_version=code, dataset_version=f"open {today} (Yahoo 5m), daily bars to {signal_day}",
                    signal_date=signal_day, direction="long",
                    expected_return=max(e.mean_net for e in ev) if ev else None,
                    probabilities={"peak_5": max((e.p_peak_5 or 0) for e in ev), "low_5": max((e.p_low_5 or 0) for e in ev)},
                    expected_cost_per_side=config.costs.per_side(s.dollar_volume), paper_trade=group == "validated",
                    strategy_status="validated" if group == "validated" else "RESEARCH ONLY (watch list)",
                    target=0.05, stop=0.05), datetime.now(timezone.utc))
                logged += 1
            except ValueError:
                pass
    print(f"opening scan written: {path}; decision {decision.verdict}; {len(situations)} stocks with an open; "
          f"{logged} ledger records")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m equity_research.shortterm")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("scan", "evaluate"):
        p = sub.add_parser(name)
        p.add_argument("--bars-dir", type=Path, help="directory with <TICKER>.csv (Date,Open,High,Low,Close,Volume)")
        p.add_argument("--yahoo", action="store_true", help="daily bars from Yahoo Finance (default price source)")
        p.add_argument("--stooq", action="store_true", help="daily bars from Stooq (secondary source)")
        p.add_argument("--tickers", help="comma-separated tickers (default: all NYSE/Nasdaq in the SEC list)")
        p.add_argument("--max-tickers", type=int, default=0, help="0 = every NYSE/Nasdaq listing")
        p.add_argument("--no-sec", action="store_true", help="skip SEC 8-K catalysts")
        p.add_argument("--output-dir", type=Path, default=REPORTS)
        p.add_argument("--context", type=Path, help="Markdown with sourced web context (each bullet: URL + date)")
        p.add_argument("--ledger", type=Path, default=LEDGER, help="immutable prediction ledger (JSON lines)")
    o = sub.add_parser("opening", help="morning scan after the US open (watch list + ledger; NO TRADE unless validated)")
    o.add_argument("--ledger", type=Path, default=LEDGER)
    o.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "opening")
    o.add_argument("--max-tickers", type=int, default=0)
    o.add_argument("--any-time", action="store_true", help="skip the 09:35-11:00 ET window check (testing)")
    c = sub.add_parser("catalysts")
    c.add_argument("--hours", type=int, default=24)
    args = parser.parse_args(argv)

    sources = ShortTermSources()
    config = Config()
    if args.command == "opening":
        run_opening(args, sources, config)
        return
    if args.command == "catalysts":
        missing: list[str] = []
        filings, names = _live_filings(sources, args.hours, missing)
        for f in filings:
            print(f"{f.accepted_et:%Y-%m-%d %H:%M} ET  {f.ticker or '-':<6} {cat.describe(f.items):<15} "
                  f"{cat.item_text(f.items)[:70]:<70} {f.url}")
        for m in missing:
            print(f"missing: {m}")
        return

    tickers = [t.strip() for t in args.tickers.split(",")] if args.tickers else None
    use_yahoo = args.yahoo or not (args.bars_dir or args.stooq)
    data = load(tickers, args.bars_dir, args.stooq, not args.no_sec, sources, args.max_tickers, use_yahoo=use_yahoo)
    if args.command == "evaluate":
        result = predictions.evaluate(predictions.read(PREDICTIONS), data.bars, config)
        for h, v in result.items():
            print(f"{h}d: {v}")
        check = evaluate_ledger(args.ledger, data.bars, config)
        print(f"ledger {args.ledger}: new records {check['changed']}")
        for group, s in check["summary"].items():
            print(f"  {group}: {s}")
        print("  integrity: " + ("ok (hash chain intact)" if not check["problems"] else "; ".join(check["problems"])))
        return

    scan_time = datetime.now(timezone.utc)
    result = engine.run(data.bars, data.filings, config, data.names, data.bars_source, scan_time)
    live, live_names = _live_filings(sources, 24, data.missing)
    code = _git_revision()
    gates = {h: o.gate.passed for h, o in result.oos.items()}
    log_path = predictions.log(result.candidates, scan_time, code, PREDICTIONS, gates)
    try:
        listings = sources.listings()
    except FETCH_ERRORS:
        listings = {}
    logged = log_to_ledger(result, args.ledger, code, scan_time, listings)
    check = predictions.evaluate(predictions.read(PREDICTIONS), data.bars, config) if data.bars else None
    text = report.render(result, live, {**data.names, **live_names}, data.missing, check, code, data.timing)
    if args.context:
        text += "\n" + "\n".join(context.section(context.load(args.context), "8"))
    path = report.write(text, args.output_dir, scan_time)
    print(f"report written: {path}")
    print(f"candidates: {len(result.candidates)}" + (f"; logged to {log_path}" if log_path else "")
          + f"; {logged} new ledger records in {args.ledger}")
    for note in result.notes + data.missing[:5]:
        print(f"note: {note}")


if __name__ == "__main__":
    main()
