"""Taxi Songshan Airport -> Farglory Value-Added Zone: travel-time distribution from 5 years of freeway data.

Trip = A (city streets: Songshan Airport -> Freeway 1 southbound, reaching gantry km 18.2)
     + F (Freeway 1, gantry 01F0182S -> 01F0511S, km 18.2 -> 51.1; MEASURED, time-dependent)
     + D (km 51.1 -> Airport System interchange -> toll-free Freeway 2 -> local roads -> Farglory)

A and D have no gantry data, so they are scenario assumptions (minutes). F is simulated by "driving"
through the gantry links: a car entering a link at time t takes that link's 5-minute-average car
(VehicleType 31) travel time for the interval containing t, then moves on to the next link.

Only government working days are used (data/calendar/workdays.csv: holidays excluded, make-up
workdays included).

Usage: uv run python taxi_model.py
"""
from __future__ import annotations

import glob

import numpy as np
import pandas as pd

from tdx import ROOT

LINKS = ["01F0182S>01F0248S", "01F0248S>01F0264S", "01F0264S>01F0293S", "01F0293S>01F0339S",
         "01F0339S>01F0376S", "01F0376S>01F0413S", "01F0413S>01F0467S", "01F0467S>01F0492S",
         "01F0492S>01F0511S"]
SCENARIOS = {"optimistic": (6, 10), "typical": (9, 13), "pessimistic": (14, 18)}  # (A, D) minutes


def load_freeway() -> pd.DataFrame:
    """Matrix of link travel times (s): rows = 5-min timestamps, columns = links, cars only."""
    d = pd.concat(pd.read_parquet(f) for f in sorted(glob.glob(str(ROOT / "data/freeway/m04a_*.parquet"))))
    d = d[d.vehicle_type == 31]
    d["link"] = d.gantry_from + ">" + d.gantry_to
    d = d[d.link.isin(LINKS)]
    m = d.pivot_table(index="time", columns="link", values="travel_time_s", aggfunc="mean")[LINKS]
    m = m.replace(0, np.nan)  # 0 = no vehicles observed in that interval
    full = pd.date_range(m.index.min().normalize(), m.index.max().normalize() + pd.Timedelta("23:55:00"), freq="5min")
    m = m.reindex(full)
    m = m.interpolate(limit=3, limit_area="inside")  # bridge gaps up to 15 min
    return m


def drive(m: pd.DataFrame, start: pd.Timestamp) -> float:
    """Minutes to traverse all freeway links entering at `start`; NaN if data missing."""
    t = start
    for link in LINKS:
        tt = m.at[t.floor("5min"), link] if t.floor("5min") in m.index else np.nan
        if np.isnan(tt):
            return np.nan
        t += pd.Timedelta(seconds=float(tt))
    return (t - start).total_seconds() / 60


def workdays() -> pd.DatetimeIndex:
    c = pd.read_csv(ROOT / "data/calendar/workdays.csv", parse_dates=["date"])
    return pd.DatetimeIndex(c.loc[c.is_holiday == 0, "date"])


def simulate(m: pd.DataFrame, dep: str = "07:50", access_min: float = 9) -> pd.Series:
    days = [d for d in workdays() if d >= m.index.min() and d <= m.index.max()]
    out = {d: drive(m, d + pd.Timedelta(dep + ":00") + pd.Timedelta(minutes=access_min)) for d in days}
    return pd.Series(out, name="freeway_min").dropna()


if __name__ == "__main__":
    m = load_freeway()
    print(f"freeway data {m.index.min():%Y-%m-%d} .. {m.index.max():%Y-%m-%d}")
    for dep in ["07:40", "07:50", "08:00"]:
        f = simulate(m, dep)
        print(f"\n=== taxi leaves Songshan {dep}: {len(f)} working days")
        q = f.quantile([.5, .9, .95, .99, 1]).round(1)
        print("freeway part (min): median {:.1f}  p90 {:.1f}  p95 {:.1f}  p99 {:.1f}  max {:.1f}".format(*q))
        for name, (a, dd) in SCENARIOS.items():
            total = a + f + dd
            arr = pd.Timestamp(dep) + pd.to_timedelta(total, unit="min")
            late = (total > (pd.Timestamp("09:00") - pd.Timestamp(dep)).total_seconds() / 60)
            print(f"  {name:11s} A={a} D={dd}: total median {total.median():.0f} min, p99 {total.quantile(.99):.0f}, "
                  f"max {total.max():.0f} -> late for 09:00 on {late.sum()} of {len(total)} days ({late.mean()*100:.2f}%)")
        print("  worst 8 days (freeway min):", ", ".join(f"{d:%Y-%m-%d %a} {v:.0f}" for d, v in f.nlargest(8).items()))
        f.to_csv(ROOT / f"data/taxi_freeway_{dep.replace(':', '')}.csv")
