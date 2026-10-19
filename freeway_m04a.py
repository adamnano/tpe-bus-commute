"""Download Freeway Bureau TDCS M04A (5-min gantry-to-gantry travel times) for the 5250 corridor.

M04A rows: TimeInterval, GantryFrom, GantryTo, VehicleType, SpaceMeanSpeed-based TravelTime (s), Count.
Corridor = National Freeway 1 southbound, 01F0153S -> 01F0532S (km 15.3 -> 53.2): from before the
Diding/Yuanshan entrances near Songshan Airport to past the Airport System interchange (km ~52) where
taxis turn onto toll-free Freeway 2 (no gantries). The 5250/1841 bus section (Taipei IC -> Nankan,
01F0248S -> 01F0492S) is a subset.
VehicleType: 31 small car, 32 small truck, 41 bus, 42 large truck, 5 trailer.

Archive: daily tarballs M04A_YYYYMMDD.tar.gz (since 2021-06-22) for older days, per-5-minute CSVs
in YYYYMMDD/HH/ folders for roughly the last month.

Usage: uv run python freeway_m04a.py 2026-07-18 2026-10-17
Output: data/freeway/m04a_YYYYMMDD.parquet (one file per day; already-done days are skipped).
"""
from __future__ import annotations

import datetime as dt
import io
import sys
import tarfile
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

import pandas as pd

from tdx import ROOT, SSL_CTX

BASE = "https://tisvcloud.freeway.gov.tw/history/TDCS/M04A"
CORRIDOR = ["01F0153S", "01F0182S", "01F0248S", "01F0264S", "01F0293S", "01F0339S", "01F0376S",
            "01F0413S", "01F0467S", "01F0492S", "01F0511S", "01F0532S"]
LINKS = {f"{a}>{b}" for a, b in zip(CORRIDOR, CORRIDOR[1:])}
VEHICLES = {31, 41}
COLS = ["time", "gantry_from", "gantry_to", "vehicle_type", "travel_time_s", "count"]
OUT = ROOT / "data" / "freeway"


def _fetch(url: str, retries: int = 3) -> bytes | None:
    for i in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=60, context=SSL_CTX) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
    return None


def _filter(csv_bytes: bytes) -> pd.DataFrame:
    df = pd.read_csv(io.BytesIO(csv_bytes), header=None, names=COLS)
    link = df.gantry_from + ">" + df.gantry_to
    return df[link.isin(LINKS) & df.vehicle_type.isin(VEHICLES)]


def day_frames(day: dt.date) -> list[pd.DataFrame]:
    ymd = f"{day:%Y%m%d}"
    tar = _fetch(f"{BASE}/M04A_{ymd}.tar.gz")
    if tar is not None:
        frames = []
        with tarfile.open(fileobj=io.BytesIO(tar)) as t:
            for m in t.getmembers():
                if m.isfile() and m.name.endswith(".csv"):
                    frames.append(_filter(t.extractfile(m).read()))
        return frames
    # recent days: one CSV per 5-minute interval
    urls = [f"{BASE}/{ymd}/{h:02d}/TDCS_M04A_{ymd}_{h:02d}{m:02d}00.csv"
            for h in range(24) for m in range(0, 60, 5)]
    with ThreadPoolExecutor(8) as ex:
        blobs = list(ex.map(_fetch, urls))
    return [_filter(b) for b in blobs if b]


def do_day(day: dt.date) -> None:
    path = OUT / f"m04a_{day:%Y%m%d}.parquet"
    if path.exists():
        return
    frames = day_frames(day)
    if frames:
        df = pd.concat(frames, ignore_index=True)
        df["time"] = pd.to_datetime(df["time"])
        df.to_parquet(path, index=False)
        print(f"{day} {len(df)} rows", flush=True)
    else:
        print(f"{day} MISSING", flush=True)


def main() -> None:
    start, end = (dt.date.fromisoformat(a) for a in sys.argv[1:3])
    OUT.mkdir(parents=True, exist_ok=True)
    days = [start + dt.timedelta(n) for n in range((end - start).days + 1)]
    with ThreadPoolExecutor(4) as ex:  # 4 days in parallel; be gentle with the server
        list(ex.map(do_day, days))


if __name__ == "__main__":
    main()
