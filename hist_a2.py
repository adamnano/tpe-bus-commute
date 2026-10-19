"""Download TDX historical InterCity A2 (stop arrive/depart events), keep only our routes.

COSTS POINTS: about 17 points (~343 MB) per day, the whole country's InterCity buses. The archive
can't be filtered server-side, so we stream it and keep only the routes we study.

Usage:
    uv run python hist_a2.py --meta 2026-09-14 2026-10-16   # sizes only (cheap: 10 calls/point)
    uv run python hist_a2.py 2026-09-14 2026-10-16          # download (expensive)
Output: data/hist/a2_YYYY-MM-DD.csv (one file per day; already-done days are skipped).
"""
from __future__ import annotations

import csv
import datetime as dt
import gzip
import io
import sys
import urllib.parse
import urllib.request

from tdx import BASE, ROOT, SSL_CTX, request, token

PATH = "/api/historical/v2/Historical/Bus/RealTimeNearStop/InterCity"
ROUTES = {"THB5250", "THB1841", "THB1842", "THB1961", "THB1819"}
OUT = ROOT / "data" / "hist"


def days(a: str, b: str, weekdays_only: bool = True):
    d, end = dt.date.fromisoformat(a), dt.date.fromisoformat(b)
    while d <= end:
        if not weekdays_only or d.weekday() < 5:
            yield d
        d += dt.timedelta(days=1)


def meta(day: dt.date) -> str:
    status, _, body = request(PATH, {"Dates": day.isoformat(), "Meta": "true"})
    return f"{day} {status} {body.decode('utf-8-sig').strip()}"


def download(day: dt.date) -> int:
    path = OUT / f"a2_{day}.csv"
    if path.exists():
        return -1
    url = f"{BASE}{PATH}?" + urllib.parse.urlencode({"Dates": day.isoformat(), "$format": "CSV"}, safe="$")
    req = urllib.request.Request(url, headers={"authorization": f"Bearer {token()}",
                                               "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=600, context=SSL_CTX) as r:
        raw = gzip.GzipFile(fileobj=r) if r.headers.get("Content-Encoding") == "gzip" else r
        reader = csv.reader(io.TextIOWrapper(raw, encoding="utf-8-sig", newline=""))
        header = next(reader)
        col = header.index("RouteUID")
        tmp = path.with_suffix(".part")
        n = 0
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(header)
            for row in reader:
                if row[col] in ROUTES:
                    w.writerow(row)
                    n += 1
    tmp.rename(path)
    return n


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    OUT.mkdir(parents=True, exist_ok=True)
    for day in days(*args):
        if "--meta" in sys.argv:
            print(meta(day), flush=True)
        else:
            print(f"{day} kept {download(day)} rows", flush=True)


if __name__ == "__main__":
    main()
