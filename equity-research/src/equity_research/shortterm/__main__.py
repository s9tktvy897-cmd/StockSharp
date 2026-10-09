"""``python -m equity_research.shortterm {scan,catalysts,evaluate} [options]``

scan       daily run: data check, out-of-sample tests, backtest, top 10, prediction log and report
catalysts  new 8-K filings from the SEC live feed
evaluate   compare logged predictions with what happened since"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

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
        p.add_argument("--stooq", action="store_true", help="download daily bars from Stooq (secondary source)")
        p.add_argument("--tickers", help="comma-separated tickers (default: all NYSE/Nasdaq in the SEC list)")
        p.add_argument("--max-tickers", type=int)
        p.add_argument("--no-sec", action="store_true", help="skip SEC 8-K catalysts")
        p.add_argument("--output-dir", type=Path, default=REPORTS)
        p.add_argument("--context", type=Path, help="Markdown with sourced web context (each bullet: URL + date)")
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
    data = load(tickers, args.bars_dir, args.stooq, not args.no_sec, sources, args.max_tickers)
    if args.command == "evaluate":
        result = predictions.evaluate(predictions.read(PREDICTIONS), data.bars, config)
        for h, v in result.items():
            print(f"{h}d: {v}")
        return

    scan_time = datetime.now(timezone.utc)
    result = engine.run(data.bars, data.filings, config, data.names, data.bars_source, scan_time)
    live, live_names = _live_filings(sources, 24, data.missing)
    code = _git_revision()
    gates = {h: o.gate.passed for h, o in result.oos.items()}
    log_path = predictions.log(result.candidates, scan_time, code, PREDICTIONS, gates)
    check = predictions.evaluate(predictions.read(PREDICTIONS), data.bars, config) if data.bars else None
    text = report.render(result, live, {**data.names, **live_names}, data.missing, check, code, data.timing)
    if args.context:
        text += "\n" + "\n".join(context.section(context.load(args.context), "8"))
    path = report.write(text, args.output_dir, scan_time)
    print(f"report written: {path}")
    print(f"candidates: {len(result.candidates)}" + (f"; logged to {log_path}" if log_path else ""))
    for note in result.notes + data.missing[:5]:
        print(f"note: {note}")


if __name__ == "__main__":
    main()
