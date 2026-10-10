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
    c = sub.add_parser("catalysts")
    c.add_argument("--hours", type=int, default=24)
    args = parser.parse_args(argv)

    sources = ShortTermSources()
    config = Config()
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
