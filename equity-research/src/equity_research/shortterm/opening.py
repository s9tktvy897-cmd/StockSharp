"""Morning scanner, run shortly after the US open (09:35-11:00 ET).

For every liquid stock it determines today's situation (opening gap versus the previous close, SEC 8-Ks
filed since that close, size of yesterday's move, price, volatility) and attaches what the research
studies measured for that situation after the open: how often the high of the day reached +5%, how often
the low reached -5%, how often the close ended above the open, and the net result of fixed exit rules.

A situation is only marked tradable when its historical result was positive after costs, significant
after the multiple-testing correction AND positive in the holdout. Otherwise the decision is NO TRADE and
the stocks form a watch list that is tracked in the prediction ledger as unvalidated predictions (never as
paper trades), so that the forward record builds up. Nothing here sends an order or says "buy"."""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

GAP_BUCKETS = ((-1.0, -0.10, "< -10%"), (-0.10, -0.03, "-10..-3%"), (-0.03, 0.03, "-3..+3%"),
               (0.03, 0.10, "+3..+10%"), (0.10, 0.20, "+10..+20%"), (0.20, math.inf, "> +20%"))
MOVE_BUCKETS = ((-1.0, -0.10, "< -10%"), (-0.10, -0.03, "-10..-3%"), (-0.03, 0.03, "-3..+3%"),
                (0.03, 0.10, "+3..+10%"), (0.10, math.inf, "> +10%"))
EARNINGS, DEAL = {"2.02"}, {"1.01", "2.01"}


def bucket(x: float, buckets) -> str:
    for lo, hi, label in buckets:
        if lo <= x < hi:
            return label
    return ""


def news_label(items_since_close: list[tuple[str, ...]]) -> str:
    """Same categories as the studies: earnings 8-K, deal 8-K, other 8-K or no 8-K."""
    codes = {c for items in items_since_close for c in items}
    if codes & EARNINGS:
        return "earnings 8-K"
    if codes & DEAL:
        return "deal 8-K"
    return "other 8-K" if items_since_close else "no 8-K"


@dataclass(frozen=True)
class Situation:
    ticker: str
    name: str
    prev_close: float
    open: float
    move_yesterday: float
    news: str
    dollar_volume: float

    @property
    def gap(self) -> float:
        return self.open / self.prev_close - 1

    def cells(self) -> dict[str, str]:
        """The study conditions this stock falls into today (keys as in the study JSON files)."""
        return {"opening gap": bucket(self.gap, GAP_BUCKETS),
                "news before the open (8-K)": self.news,
                "move on the day before": bucket(self.move_yesterday, MOVE_BUCKETS)}


@dataclass
class Evidence:
    condition: str
    value: str
    n: int
    p_peak_5: float | None
    p_low_5: float | None
    p_close_above_open: float | None
    best_rule: str
    mean_net: float
    ci: tuple[float, float]
    significant: bool
    holdout: float | None
    source: str

    @property
    def tradable(self) -> bool:
        return self.significant and self.mean_net > 0 and self.ci[0] > 0 and (self.holdout or 0) > 0


def _index(study: dict) -> dict[tuple[str, str], dict]:
    return {(r["condition"], r["value"]): r for r in study.get("results", [])}


# condition names differ slightly between the daily and the hourly study
DAILY_NAMES = {"opening gap": "opening gap (known just after the open)",
               "news before the open (8-K)": "news before the open (8-K overnight)",
               "move on the day before": "move on the signal day"}


def evidence(situation: Situation, hourly: dict | None, daily: dict | None) -> list[Evidence]:
    out = []
    h_index, d_index = _index(hourly or {}), _index(daily or {})
    for condition, value in situation.cells().items():
        if not value:
            continue
        r = h_index.get((condition, value))
        if r:
            key, best = max(r["rules"].items(), key=lambda kv: kv[1]["mean_net"])
            halves = best.get("halves", {})
            out.append(Evidence(condition, value, r["n"], r.get("p_peak_5"), r.get("p_low_5"),
                                r.get("p_close_above_open", None), key, best["mean_net"], tuple(best["ci"]),
                                bool(best.get("significant_holm")), halves.get("2025-10..2026-10"),
                                "uurkoersen okt 2024 – okt 2026"))
        r = d_index.get((DAILY_NAMES.get(condition, condition), value))
        if r:
            key, best = max(r["rules"].items(), key=lambda kv: kv[1]["mean_net"])
            out.append(Evidence(condition, value, r["n"], r.get("p_up5_intraday"), r.get("p_down5_intraday"),
                                r.get("p_close_above_open"), key, best["mean_net"], tuple(best["ci"]),
                                bool(best.get("significant_holm")), best.get("holdout_mean_net"),
                                "dagkoersen 2017 – 2025 (holdout apart)"))
    return out


def trade_plan(open_price: float, target: float = 0.05, stop: float = 0.05) -> dict:
    """Limit and stop levels for a paper position bought at the open (a stop is not a guaranteed price)."""
    return {"entry": open_price, "limit": round(open_price * (1 + target), 4), "stop": round(open_price * (1 - stop), 4),
            "target": target, "stop_fraction": stop}


@dataclass(frozen=True)
class RiskPlan:
    """Personal rules of a disciplined day trader. They limit losses; they do not create an edge."""
    account: float = 10_000.0
    risk_per_trade: float = 0.01      # lose at most 1% of the account if the stop is hit
    max_trades_per_day: int = 3
    daily_loss_limit: float = 0.03    # stop for the day after -3%
    stop_after_losses: int = 3        # stop for the day after three losses in a row

    def position_value(self, stop_fraction: float) -> float:
        return self.account * self.risk_per_trade / stop_fraction if stop_fraction > 0 else 0.0


@dataclass
class Decision:
    tradable: list[tuple[Situation, list[Evidence]]] = field(default_factory=list)
    watch: list[tuple[Situation, list[Evidence]]] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        return "PAPER TRADE (validated situation)" if self.tradable else "NO TRADE"


def decide(situations: list[Situation], hourly: dict | None, daily: dict | None, watch_size: int = 10) -> Decision:
    d = Decision()
    scored = []
    for s in situations:
        ev = evidence(s, hourly, daily)
        if any(e.tradable for e in ev):
            d.tradable.append((s, ev))
        elif ev:
            # watch list: the situations that historically lost the least after costs
            scored.append((max(e.mean_net for e in ev), s, ev))
    scored.sort(key=lambda x: -x[0])
    d.watch = [(s, ev) for _, s, ev in scored[:watch_size]]
    return d


def _p(x, digits=1):
    return "–" if x is None else f"{x * 100:.{digits}f}%".replace(".", ",")


def render(decision: Decision, day: date, risk: RiskPlan, missing: list[str]) -> str:
    L = [f"# Ochtendscan na de opening — {day}", "",
         "> Geen beleggingsadvies en geen koopsignaal. Historische kansen zijn geen garantie. Er wordt niets "
         "gehandeld; alles wordt als voorspelling in het register bijgehouden.", "",
         f"**Beslissing: {decision.verdict}**", ""]
    if not decision.tradable:
        L += ["Geen enkele situatie had in het onderzoek een positief resultaat na kosten dat significant was na "
              "correctie én positief bleef in de holdout. Daarom geen trade. De lijst hieronder zijn de situaties die "
              "historisch het minst verloren; ze worden gevolgd, niet gehandeld.", ""]
    for title, rows in (("Toegestaan (gevalideerd)", decision.tradable), ("Volglijst (niet gevalideerd)", decision.watch)):
        if not rows:
            continue
        L += [f"## {title}", "", "| Aandeel | Gap | 8-K | Situatie | +5% gehaald | −5% geraakt | Slot > opening | "
              "Beste regel netto (95%-BI) | Holdout | Bron |", "|---|---|---|---|---|---|---|---|---|---|"]
        for s, ev in rows:
            best = max(ev, key=lambda e: e.mean_net)
            L.append(f"| {s.ticker} {s.name[:24]} | {_p(s.gap)} | {s.news} | {best.condition}: {best.value} | "
                     f"{_p(best.p_peak_5)} | {_p(best.p_low_5)} | {_p(best.p_close_above_open)} | {best.best_rule}: "
                     f"{_p(best.mean_net, 2)} ({_p(best.ci[0], 2)} – {_p(best.ci[1], 2)}) | {_p(best.holdout, 2)} | {best.source} |")
        L.append("")
    plan_value = risk.position_value(0.05)
    L += ["## Risicoplan (vaste regels)", "",
          f"- Rekening {risk.account:,.0f}; maximaal {_p(risk.risk_per_trade, 0)} risico per trade → bij een stop van 5% "
          f"een positie van hoogstens {plan_value:,.0f}.".replace(",", "."),
          f"- Hoogstens {risk.max_trades_per_day} trades per dag; stoppen na {_p(risk.daily_loss_limit, 0)} dagverlies of "
          f"{risk.stop_after_losses} verliezen op rij.",
          "- Een stop is geen gegarandeerde prijs: bij een koersgat wordt lager gevuld.", ""]
    if missing:
        L += ["## Ontbrekend", ""] + [f"- {m}" for m in missing] + [""]
    return "\n".join(L)
