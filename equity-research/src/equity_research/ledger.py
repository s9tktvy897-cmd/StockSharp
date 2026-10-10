"""Immutable prediction ledger: an append-only JSON-lines file in which every record carries the
hash of the previous one (a hash chain), so any later edit of a past record is detected by
``verify``. A prediction is never changed; its fill, exit, expiry or cancellation are new records.

Statuses: OPEN (logged, not yet filled), FILLED (simulated entry at the next open), CLOSED (exit at
the close of the horizon day, net of costs), EXPIRED (no exit bar long after the planned exit),
CANCELLED (no bar to enter on), INVALID (unusable record; kept, never dropped).

A prediction with ``paper_trade`` False is scored (did the direction come true?) but is not a paper
trade; only strategies with status PAPER TRADING CANDIDATE are paper-traded. These are simulated
fills on real, later market data -- no order is ever sent to a broker."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

GENESIS = "0" * 64
CANCEL_AFTER_DAYS = 30
EXPIRE_GRACE_DAYS = 10


@dataclass(frozen=True)
class Prediction:
    ticker: str
    security_id: str          # permanent id where known (SEC CIK)
    strategy: str
    horizon: int              # trading days; entry at the next open, exit at the close of day h
    model_version: str        # code commit
    dataset_version: str
    signal_date: date
    direction: str            # "long"
    expected_return: float | None
    probabilities: dict = field(default_factory=dict)
    expected_cost_per_side: float | None = None
    paper_trade: bool = False
    strategy_status: str = ""
    target: float | None = None   # +target limit exit (fraction of the entry price), checked day by day
    stop: float | None = None     # stop exit; a gap below it fills at that open, never a guaranteed price

    @property
    def id(self) -> str:
        return f"{self.signal_date.isoformat()}:{self.strategy}:{self.horizon}d:{self.ticker}"


def _target_or_stop(bars, first: int, last: int, entry_open: float, target: float | None, stop: float | None):
    """(bar index, raw exit price, reason) of the first target or stop between ``first`` and ``last``; None if
    neither. A later day opening beyond a level fills at that open; within one daily bar the stop counts first."""
    if target is None and stop is None:
        return None
    up = entry_open * (1 + target) if target is not None else None
    down = entry_open * (1 - stop) if stop is not None else None
    for j in range(first, last + 1):
        if j > first:
            if down is not None and bars.open[j] <= down:
                return j, float(bars.open[j]), "stop (gap below)"
            if up is not None and bars.open[j] >= up:
                return j, float(bars.open[j]), "target (gap above)"
        if down is not None and bars.low[j] <= down:
            return j, down, "stop"
        if up is not None and bars.high[j] >= up:
            return j, up, "target"
    return None


def _hash(prev: str, record: dict) -> str:
    body = json.dumps({k: v for k, v in record.items() if k != "hash"}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev + body).encode()).hexdigest()


class Ledger:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.records: list[dict] = []
        if self.path.exists():
            self.records = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()]

    # --- writing ------------------------------------------------------------------------------
    def _append(self, kind: str, pid: str, payload: dict, now: datetime) -> None:
        prev = self.records[-1]["hash"] if self.records else GENESIS
        record = {"seq": len(self.records), "time": now.isoformat(), "type": kind, "id": pid, "payload": payload,
                  "prev": prev}
        record["hash"] = _hash(prev, record)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")
        self.records.append(record)

    def add(self, p: Prediction, now: datetime) -> str:
        if any(r["type"] == "PREDICTION" and r["id"] == p.id for r in self.records):
            raise ValueError(f"prediction {p.id} is already in the ledger")
        payload = asdict(p) | {"signal_date": p.signal_date.isoformat()}
        self._append("PREDICTION", p.id, payload, now)
        return p.id

    # --- reading ------------------------------------------------------------------------------
    def verify(self) -> list[str]:
        problems, prev = [], GENESIS
        for i, r in enumerate(self.records):
            if r.get("seq") != i:
                problems.append(f"record {i}: sequence {r.get('seq')}")
            if r.get("prev") != prev:
                problems.append(f"record {i}: previous hash does not match")
            if _hash(prev, r) != r.get("hash"):
                problems.append(f"record {i}: content changed after it was written")
            prev = r.get("hash", "")
        return problems

    def events(self, pid: str) -> list[dict]:
        return [r for r in self.records if r["id"] == pid]

    def status(self, pid: str) -> str:
        kinds = [r["type"] for r in self.events(pid)]
        for k in ("INVALID", "CANCELLED", "EXPIRED", "CLOSED", "FILLED"):
            if k in kinds:
                return k
        return "OPEN" if kinds else "UNKNOWN"

    def predictions(self) -> list[dict]:
        return [r for r in self.records if r["type"] == "PREDICTION"]

    # --- evaluation ---------------------------------------------------------------------------
    def evaluate(self, universe: dict, now: datetime, cost_per_side) -> dict[str, int]:
        """Add FILLED/CLOSED/EXPIRED/CANCELLED/INVALID records where the data now allow it.
        ``cost_per_side(ticker, bar_index)`` gives the modelled cost fraction for that fill."""
        changed: dict[str, int] = {}
        today = now.date()
        for rec in self.predictions():
            pid, p = rec["id"], rec["payload"]
            state = self.status(pid)
            if state not in ("OPEN", "FILLED"):
                continue
            ticker, signal, h = p.get("ticker"), date.fromisoformat(p["signal_date"]), int(p.get("horizon", 0))
            if not ticker or h < 1:
                self._append("INVALID", pid, {"reason": "missing ticker or horizon"}, now)
                changed["INVALID"] = changed.get("INVALID", 0) + 1
                continue
            bars = universe.get(ticker)
            after = [] if bars is None else [i for i, d in enumerate(bars.dates) if d > signal]
            if not after:
                if (today - signal).days > CANCEL_AFTER_DAYS:
                    self._append("CANCELLED", pid, {"reason": "no bar to enter on (halt, delisting or missing data)"}, now)
                    changed["CANCELLED"] = changed.get("CANCELLED", 0) + 1
                continue
            entry = after[0]
            if state == "OPEN":
                c = float(cost_per_side(ticker, entry))
                self._append("FILLED", pid, {"entry_date": bars.dates[entry].isoformat(),
                                             "entry_price": float(bars.open[entry] * (1 + c)), "cost": c,
                                             "raw_open": float(bars.open[entry]), "simulated": True}, now)
                changed["FILLED"] = changed.get("FILLED", 0) + 1
            fill = next(r for r in self.events(pid) if r["type"] == "FILLED")["payload"]
            exit_i = entry + h - 1
            hit = _target_or_stop(bars, entry, min(exit_i, len(bars) - 1), float(fill["raw_open"]), p.get("target"),
                                  p.get("stop"))
            if hit is not None or exit_i < len(bars):
                j, raw, reason = hit if hit is not None else (exit_i, float(bars.close[exit_i]), "time")
                c = float(cost_per_side(ticker, j))
                price = raw * (1 - c)
                self._append("CLOSED", pid, {"exit_date": bars.dates[j].isoformat(), "exit_price": price, "cost": c,
                                             "raw_exit": raw, "reason": reason,
                                             "net": price / fill["entry_price"] - 1}, now)
                changed["CLOSED"] = changed.get("CLOSED", 0) + 1
            elif (today - date.fromisoformat(fill["entry_date"])).days > int(h * 1.5) + EXPIRE_GRACE_DAYS:
                self._append("EXPIRED", pid, {"reason": "no exit bar long after the planned exit"}, now)
                changed["EXPIRED"] = changed.get("EXPIRED", 0) + 1
        return changed

    def summary(self) -> dict:
        out = {}
        for group, paper in (("predictions", None), ("paper", True)):
            preds = [r for r in self.predictions() if paper is None or r["payload"].get("paper_trade") is True]
            statuses = [self.status(r["id"]) for r in preds]
            nets, pairs = [], []
            for r in preds:
                close = next((e for e in self.events(r["id"]) if e["type"] == "CLOSED"), None)
                if close:
                    net = close["payload"]["net"]
                    nets.append(net)
                    pu = r["payload"].get("probabilities", {}).get("up")
                    if pu is not None:
                        pairs.append((pu, float(net > 0)))
            x = np.array(nets)
            out[group] = {
                "total": len(preds), **{s.lower(): statuses.count(s) for s in
                                        ("OPEN", "FILLED", "CLOSED", "EXPIRED", "CANCELLED", "INVALID")},
                "direction_hit_rate": float(np.mean(x > 0)) if len(x) else None,
                "mean_net": float(x.mean()) if len(x) else None,
                "sum_net": float(x.sum()) if len(x) else None,
                "brier_up": float(np.mean([(p - y) ** 2 for p, y in pairs])) if pairs else None,
            }
        return out


def check_extension(old_path: Path, new_path: Path) -> list[str]:
    """Problems if ``new`` is not ``old`` plus appended records (or has a broken hash chain)."""
    new = Ledger(new_path)
    problems = new.verify()
    if Path(old_path).exists():
        old = Ledger(old_path)
        if len(new.records) < len(old.records) or any(a != b for a, b in zip(old.records, new.records)):
            problems.append("the new ledger does not start with every record of the old one (history rewritten)")
    return problems


def main(argv: list[str] | None = None) -> None:
    import argparse
    import sys
    parser = argparse.ArgumentParser(prog="python -m equity_research.ledger")
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("verify")
    v.add_argument("path", type=Path)
    e = sub.add_parser("check-extension")
    e.add_argument("old", type=Path)
    e.add_argument("new", type=Path)
    s = sub.add_parser("summary")
    s.add_argument("path", type=Path)
    args = parser.parse_args(argv)
    if args.command == "summary":
        print(json.dumps(Ledger(args.path).summary(), indent=1))
        return
    problems = Ledger(args.path).verify() if args.command == "verify" else check_extension(args.old, args.new)
    print("ok" if not problems else "\n".join(problems))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
