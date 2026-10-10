"""Fundamental factor validation on a point-in-time selected universe (see the chat for the design)."""
import sys, json, time
from datetime import date
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from equity_research.backtest import fundamental as fb
from equity_research.backtest.__main__ import render
from equity_research.data.yahoo import YahooPrices
from equity_research.data.sec_edgar import SecEdgar
from equity_research.data.http import HttpClient, user_agent_from_env
from equity_research.data.cache import DiskCache
from equity_research.data.__main__ import CACHE_DIR
from equity_research.shortterm.sources import ShortTermSources
from equity_research.report.markdown import _git_revision

out = Path(sys.argv[1])
listings = ShortTermSources().listings()
prices = YahooPrices(Path(__file__).resolve().parents[1] / "data" / "cache_research", years=10)
bars, _ = prices.bars(sorted(listings))
first = date(2017, 4, 28)
liquid = {}
for t, b in bars.items():
    if len(b) and b.dates[0] <= date(2016, 12, 30):
        i = int(np.searchsorted(np.array([d.toordinal() for d in b.dates]), first.toordinal(), side="right")) - 1
        if i >= 20:
            liquid[t] = float(np.mean(b.close[i - 19:i + 1] * b.volume[i - 19:i + 1]))
ranked = sorted(liquid, key=lambda t: -liquid[t])
top = ranked[:300]
rng = np.random.default_rng(20261010)
rest = [t for t in ranked[300:] if liquid[t] >= 1e6]
sample = sorted(top + list(rng.choice(rest, size=min(300, len(rest)), replace=False)))
print("universe", len(sample), "of", len(liquid), flush=True)
edgar = SecEdgar(HttpClient(user_agent_from_env()), DiskCache(CACHE_DIR))
rebalances = [date(y, 4, 30) for y in range(2017, 2026)]
obs, missing, t0 = [], [], time.time()
for k, t in enumerate(sample):
    try:
        cik = edgar.cik_for_ticker(t)
        sic, facts = edgar.profile(cik).sic, edgar.company_facts(cik)
    except Exception as e:  # noqa
        missing.append(f"SEC {t}: {str(e)[:80]}")
        continue
    for d in rebalances:
        try:
            o = fb.observe(t, sic, facts, bars.get(t), d, 365)
        except Exception as e:  # noqa
            missing.append(f"{t} {d}: {str(e)[:80]}")
            o = None
        if o:
            obs.append(o)
    if k % 50 == 0:
        print(k, len(obs), round(time.time() - t0), flush=True)
universe = (f"{len(sample)} aandelen, point-in-time gekozen: genoteerd vóór 2017, de 300 hoogste 20-daagse dollaromzet "
            f"op 2017-04-28 plus 300 willekeurige (seed 20261010) met >= 1 mln USD/dag; Yahoo Finance (secundair)")
text = render(obs, rebalances, 365, universe, missing, _git_revision())
out.write_text(text, encoding="utf-8")
print("written", out, len(obs), "observations;", len(missing), "missing", flush=True)
