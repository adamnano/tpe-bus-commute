"""Rebuild individual trips from historical A2 stop events (data/hist/a2_*.csv).

One row per trip: route, sub-route, plate, actual departure from 松山機場 (stop 1),
arrival at the destination stop for our commute:
  - 5250 / 5250A  -> 遠雄加值園區 (Farglory Value-Added Zone)
  - 1841 / 1841A  -> 樹仔坡 (Shuzaipo), then a walk to Farglory (WALK_MIN, assumed)
Output: data/trips.parquet
"""
from __future__ import annotations

import glob

import pandas as pd

from tdx import ROOT

ORIGIN = "松山機場"
DEST = {"THB525001": "遠雄加值園區", "THB5250A1": "遠雄加值園區",
        "THB184101": "樹仔坡", "THB1841A1": "樹仔坡"}
WALK_MIN = {"遠雄加值園區": 0, "樹仔坡": 10}  # ~650 m straight line; walking route not verified


def load() -> pd.DataFrame:
    frames = [pd.read_csv(f) for f in sorted(glob.glob(str(ROOT / "data/hist/a2_*.csv")))]
    d = pd.concat(frames, ignore_index=True)
    d = d[d.SubRouteUID.isin(DEST)]
    for c in ["GPSTime", "TripStartTime"]:
        d[c] = pd.to_datetime(d[c], utc=True).dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
    return d


def build(d: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (sub, plate, start), g in d.groupby(["SubRouteUID", "PlateNumb", "TripStartTime"]):
        dest = DEST[sub]
        dep = g[(g.StopNameZh_tw == ORIGIN) & (g.A2EventType == "離站")].GPSTime.min()
        arr = g[(g.StopNameZh_tw == dest) & (g.A2EventType == "進站")].GPSTime.min()
        if pd.isna(arr):  # missed arrival event: fall back to departure event at the stop
            arr = g[(g.StopNameZh_tw == dest) & (g.A2EventType == "離站")].GPSTime.min()
        rows.append({
            "route": sub[3:7], "sub_route": sub, "plate": plate,
            "trip_start": start, "dep_origin": dep if pd.notna(dep) else start,
            "arr_dest": arr, "dest": dest, "walk_min": WALK_MIN[dest], "n_events": len(g),
        })
    t = pd.DataFrame(rows)
    t["date"] = t.dep_origin.dt.normalize()
    t["ride_min"] = (t.arr_dest - t.dep_origin).dt.total_seconds() / 60
    t["at_farglory"] = t.arr_dest + pd.to_timedelta(t.walk_min, unit="min")
    return t.sort_values("dep_origin").reset_index(drop=True)


if __name__ == "__main__":
    trips = build(load())
    trips.to_parquet(ROOT / "data" / "trips.parquet", index=False)
    print(trips.groupby("sub_route").agg(trips=("plate", "size"), days=("date", "nunique"),
                                         no_arrival=("arr_dest", lambda s: s.isna().sum())))
