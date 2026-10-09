"""``equity-research <command> <TICKER> [options]``: one entry point for the module CLIs.

Commands: data, fundamentals, valuation, risk, analyze (writes the report), shortterm (scan, catalysts,
evaluate), backtest (point-in-time replay of the long-term screens)."""

from __future__ import annotations

import sys
from importlib import import_module

COMMANDS = {
    "data": "equity_research.data.__main__",
    "fundamentals": "equity_research.fundamentals.__main__",
    "valuation": "equity_research.valuation.__main__",
    "risk": "equity_research.risk.__main__",
    "analyze": "equity_research.report.__main__",
    "shortterm": "equity_research.shortterm.__main__",
    "backtest": "equity_research.backtest.__main__",
}


def main(argv: list[str] | None = None) -> None:
    argv = sys.argv[1:] if argv is None else argv
    if not argv or argv[0] not in COMMANDS:
        raise SystemExit(f"usage: equity-research {{{','.join(COMMANDS)}}} TICKER [options] | "
                         "equity-research shortterm {scan,catalysts,evaluate} [options]")
    import_module(COMMANDS[argv[0]]).main(argv[1:])


if __name__ == "__main__":
    main()
