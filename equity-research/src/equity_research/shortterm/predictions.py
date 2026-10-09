"""Prediction log (JSON lines, one file per signal date) and its later evaluation against the
bars that came after. Evaluated with the same outcome definition as the backtest."""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np

from equity_research.shortterm import labels
from equity_research.shortterm.bars import Bars
from equity_research.shortterm.config import Config
from equity_research.shortterm.evaluation import brier


def log(candidates, scan_time: datetime, code_version: str, directory: Path, gates: dict[int, bool]) -> Path | None:
    if not candidates:
        return None
    directory.mkdir(parents=True, exist_ok=True)
    signal_date = candidates[0].last_date
    path = directory / f"{signal_date.isoformat()}.jsonl"
    with path.open("w", encoding="utf-8") as handle:
        for c in candidates:
            handle.write(json.dumps({
                "scan_time": scan_time.isoformat(), "signal_date": signal_date.isoformat(), "ticker": c.ticker,
                "rank": c.rank, "score": c.score, "last_close": c.last_close, "price_source": c.source,
                "entry": "open of the next trading day",
                "probability": {str(h): p for h, p in c.probability.items()},
                "gate_passed": {str(h): v for h, v in gates.items()}, "code": code_version,
            }) + "\n")
    return path


def read(directory: Path) -> list[dict]:
    rows = []
    for path in sorted(Path(directory).glob("*.jsonl")):
        rows += [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return rows


def evaluate(records: list[dict], universe: dict[str, Bars], config: Config) -> dict:
    """Realized outcomes for logged picks whose horizon has passed."""
    out = {h: {"evaluated": 0, "hits": 0, "drops": 0, "pending": 0, "missing_bars": 0, "pairs": []}
           for h in config.horizons}
    for record in records:
        bars = universe.get(record["ticker"])
        signal = date.fromisoformat(record["signal_date"])
        for h in config.horizons:
            stats = out[h]
            if bars is None or signal not in set(bars.dates):
                stats["missing_bars"] += 1
                continue
            i = list(bars.dates).index(signal)
            outcome = labels.compute(bars, config)[h]
            if not np.isfinite(outcome["hit"][i]):
                stats["pending"] += 1
                continue
            stats["evaluated"] += 1
            stats["hits"] += int(outcome["hit"][i])
            stats["drops"] += int(outcome["drop"][i])
            p = record.get("probability", {}).get(str(h))
            if p is not None:
                stats["pairs"].append((p, outcome["hit"][i]))
    for stats in out.values():
        pairs = stats.pop("pairs")
        stats["hit_rate"] = stats["hits"] / stats["evaluated"] if stats["evaluated"] else None
        if pairs:
            p, y = np.array(pairs).T
            stats["mean_probability"], stats["brier"] = float(p.mean()), brier(p, y)
    return out
