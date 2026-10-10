"""Hourly bars (regular session) from Yahoo Finance for the research universe, last ~730 days."""
import gzip, sys, time, json
from pathlib import Path
import yfinance as yf
from datetime import date, timedelta
START = (date.today() - timedelta(days=728)).isoformat()
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
tickers = json.load(open(sys.argv[2]))
todo = [t for t in tickers if not (out / f"{t}.csv.gz").exists()]
print("todo", len(todo), flush=True)
t0 = time.time()
for k in range(0, len(todo), 50):
    chunk = todo[k:k + 50]
    syms = [t.replace(".", "-") for t in chunk]
    for attempt in range(3):
        try:
            d = yf.download(syms, start=START, interval="1h", group_by="ticker", progress=False, auto_adjust=False,
                            prepost=False, threads=True)
            break
        except Exception as e:  # noqa
            print("retry", e, flush=True); time.sleep(10 * (attempt + 1)); d = None
    if d is None or d.empty:
        continue
    for t, s in zip(chunk, syms):
        try:
            part = d[s][["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "High", "Low", "Close"])
        except KeyError:
            continue
        if part.empty:
            continue
        idx = part.index.tz_convert("America/New_York")
        lines = ["Datetime,Open,High,Low,Close,Volume"] + [
            f"{ts.isoformat()},{float(o)!r},{float(h)!r},{float(l)!r},{float(c)!r},{float(v)!r}" for ts, (o, h, l, c, v) in zip(idx, part.to_numpy(float))]
        (out / f"{t}.csv.gz").write_bytes(gzip.compress("\n".join(lines).encode()))
    print(k + len(chunk), round(time.time() - t0), flush=True)
    time.sleep(1)
print("done", flush=True)
