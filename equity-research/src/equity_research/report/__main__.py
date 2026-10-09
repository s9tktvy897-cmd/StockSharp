"""``python -m equity_research.report AAPL [valuation options]`` -- write the full analysis to
``reports/<TICKER>_<YYYY-MM-DD>.md`` (sections follow CLAUDE.md, section 2)."""

from __future__ import annotations

import argparse
from datetime import date
from pathlib import Path

from equity_research.fundamentals import checks
from equity_research.report.markdown import render, write_report
from equity_research.risk.assess import assess
from equity_research.valuation.run import Sources, add_market_arguments, run

REPORTS_DIR = Path(__file__).resolve().parents[3] / "reports"


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m equity_research.report")
    add_market_arguments(parser)
    parser.add_argument("--output-dir", type=Path, default=REPORTS_DIR)
    args = parser.parse_args(argv)
    sources = Sources.live()
    r = run(args, sources)
    results = checks.run_all(r.st)
    path = write_report(render(r, assess(r, sources), results, generated=date.today()), r.ticker, r.today,
                        args.output_dir)
    failed = [c for c in results if c.passed is False]
    print(f"report written: {path}")
    print(f"consistency checks: {sum(c.passed is True for c in results)} of {len(results)} passed"
          + (f", FAILED: {', '.join(f'{c.name} {c.period_end}' for c in failed)}" if failed else ""))
    if r.missing:
        print(f"missing sources: {len(r.missing)} (see section 3 of the report)")


if __name__ == "__main__":
    main()
