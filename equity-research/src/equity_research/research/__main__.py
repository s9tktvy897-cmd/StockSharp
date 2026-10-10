"""``python -m equity_research.research run`` -- the pre-registered research run on real data."""

from __future__ import annotations

import argparse
import json
import time
from datetime import date
from pathlib import Path

from equity_research.data.yahoo import SOURCE, YahooPrices
from equity_research.report.markdown import _git_revision
from equity_research import ledger as ledger_mod
from equity_research.research import dashboard, experiment, protocol, report
from equity_research.shortterm.bars import validate
from equity_research.shortterm.sources import ShortTermSources

ROOT = Path(__file__).resolve().parents[3]


def load_inputs(cache: Path, max_tickers: int, use_sec: bool, log=print, years: int = 10) -> experiment.Inputs:
    sources = ShortTermSources()
    listings = sources.listings()
    tickers = sorted(listings)[:max_tickers] if max_tickers else sorted(listings)
    prices = YahooPrices(cache, years=years)
    bars, missing = prices.bars(list(experiment.BENCHMARK_TICKERS[:1]) + tickers)
    spy = bars.pop("SPY")
    for t in experiment.BENCHMARK_TICKERS:
        bars.pop(t, None)
    excluded = {t: p for t, b in bars.items() if (p := validate(b))}
    notes = [f"Yahoo: geen koersen voor {len(missing)} van {len(tickers)} tickers"] if missing else []
    split_like = sum(any("possible unadjusted split" in x for x in p) for p in excluded.values())
    notes.append(f"{len(excluded)} aandelen uitgesloten wegens datafouten, waarvan {split_like} met een koerssprong "
                 "die op een niet-verwerkte split lijkt (uitsluiting op basis van de hele historie: mogelijke bias)")
    filings, sectors = (None, {})
    if use_sec:
        filings, failed, t0 = {}, 0, time.time()
        for k, t in enumerate(bars):
            try:
                c = sources.company(listings[t], full_history=True, max_age=None)
            except Exception:  # noqa: BLE001 -- counted and reported, never filled in
                failed += 1
                continue
            filings[t] = c.filings
            if c.sic:
                sectors[t] = c.sic[:2]
            if k % 1000 == 0:
                log(f"SEC {k}/{len(bars)} ({time.time() - t0:.0f}s)")
        notes.append(f"SEC: 8-K's en SIC voor {len(filings)} aandelen; {failed} niet op te halen")
    return experiment.Inputs(bars, spy, filings, sectors, excluded, notes)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m equity_research.research")
    sub = parser.add_subparsers(dest="command", required=True)
    dash = sub.add_parser("dashboard", help="rebuild the dashboard from a research JSON and the ledger")
    dash.add_argument("json", type=Path)
    dash.add_argument("--ledger", type=Path, default=ROOT / "ledger" / "ledger.jsonl")
    dash.add_argument("--output", type=Path, default=ROOT / "reports" / "research" / "dashboard.html")
    sig = sub.add_parser("signals", help="log today's paper trades of PAPER TRADING CANDIDATE strategies")
    sig.add_argument("--research", type=Path, help="research JSON (default: the newest in reports/research)")
    sig.add_argument("--cache", type=Path, default=ROOT / "data" / "cache")
    sig.add_argument("--ledger", type=Path, default=ROOT / "ledger" / "ledger.jsonl")
    run = sub.add_parser("run")
    run.add_argument("--cache", type=Path, default=ROOT / "data" / "cache_research")
    run.add_argument("--max-tickers", type=int, default=0)
    run.add_argument("--no-sec", action="store_true")
    run.add_argument("--output-dir", type=Path, default=ROOT / "reports" / "research")
    run.add_argument("--ledger", type=Path, default=ROOT / "ledger" / "ledger.jsonl")
    args = parser.parse_args(argv)
    if args.command == "signals":
        from datetime import datetime, timezone
        from equity_research.research import signals
        found = sorted((ROOT / "reports" / "research").glob("research_*.json"))
        path = args.research or (found[-1] if found else None)
        research = json.loads(path.read_text(encoding="utf-8")) if path else {"variants": []}
        tradable = signals.candidates(research)
        if not tradable:
            print(f"NO TRADE: no strategy has status PAPER TRADING CANDIDATE in {path or 'any research run'}; "
                  "nothing is paper-traded")
            return
        inputs = load_inputs(args.cache, 0, True, years=5)
        prepared = experiment.prepare(inputs)
        ids = {t: f"CIK{l.cik}" for t, l in ShortTermSources().listings().items()}
        logged = signals.log_paper_trades(research, prepared, ledger_mod.Ledger(args.ledger), _git_revision(),
                                          datetime.now(timezone.utc), ids)
        print(f"paper trades logged: {logged}")
        return
    if args.command == "dashboard":
        write_dashboard(json.loads(args.json.read_text(encoding="utf-8")), args.ledger, args.output)
        return

    inputs = load_inputs(args.cache, args.max_tickers, not args.no_sec)
    result = experiment.run_all(inputs)
    js = experiment.to_json(result, inputs)
    today = date.today().isoformat()
    meta = {"date": today, "code": _git_revision(), "bars_source": SOURCE, "tickers": len(inputs.universe),
            "sec": "gebruikt" if inputs.filings is not None else "niet gebruikt",
            "dev_end": result["prepared"].dev_end.isoformat(), "protocol_commit": "54dc774"}
    js["meta"] = meta
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / f"research_{today}.json").write_text(json.dumps(js, indent=1), encoding="utf-8")
    path = args.output_dir / f"research_{today}.md"
    path.write_text(report.render(js, meta), encoding="utf-8")
    print(f"report written: {path}")
    write_dashboard(js, args.ledger, args.output_dir / "dashboard.html")


def write_dashboard(js: dict, ledger_path: Path, output: Path) -> None:
    book = ledger_mod.Ledger(ledger_path)
    open_rows = [{"ticker": r["payload"]["ticker"], "strategy": r["payload"]["strategy"],
                  "signal_date": r["payload"]["signal_date"], "horizon": r["payload"]["horizon"],
                  "status": book.status(r["id"])} for r in book.predictions()
                 if book.status(r["id"]) in ("OPEN", "FILLED")]
    output.parent.mkdir(parents=True, exist_ok=True)
    research = output.parent
    latest = lambda pattern: (json.loads(sorted(research.glob(pattern))[-1].read_text(encoding="utf-8"))
                              if list(research.glob(pattern)) else None)
    output.write_text(dashboard.render(js, book.summary(), open_rows, not book.verify(),
                                       latest("after_open_hourly_*.json"), latest("holding_period_*.json")),
                      encoding="utf-8")
    print(f"dashboard written: {output}")


if __name__ == "__main__":
    main()
