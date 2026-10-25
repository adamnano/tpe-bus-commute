"""Build the panel of commute mornings from purchased history + the free daily collector.

Sources
  data/hist/a2_YYYY-MM-DD.csv     TDX historical stop events (purchased days; local only, summarised
                                  into data/panel/history_trips.parquet + history_meta.json)
  data/live/a2_YYYY-MM-DD.ndjson  collector snapshots (latest event per bus, every 30-60 s)

For every working day with complete departure coverage it records when you would reach Farglory:
  rule       first 5250 (to Farglory) or 1841 leaving Songshan Airport 07:25-07:43, else a taxi
  only_0730  first 5250 leaving from 07:25
  only_0755  first 5250 leaving from 07:50
A missed arrival event (e.g. the Mac slept) is estimated from the nearest recorded stop plus the
historical median time from that stop to the destination; such rows have arrival_inferred = 1.

Output: data/panel/mornings.csv (date, strategy, mode, arrive_min, source, arrival_inferred)
Usage:  uv run python build_panel.py
"""
from __future__ import annotations

import glob
import json
from pathlib import Path

import pandas as pd

import trips as tr
from tdx import ROOT

OUT = ROOT / "data" / "panel"
TAXI_ARRIVE_MIN = 517.6  # median simulated 07:50 taxi arrival (taxi_model.py), ~08:38
WINDOW = ("07:25:00", "07:43:00")
DEST_SEQ = {"THB525001": 29, "THB5250A1": 31, "THB184101": 25, "THB1841A1": 25}


def load_hist() -> pd.DataFrame:
    d = tr.load()
    d["source"] = "history"
    return d


def load_live() -> tuple[pd.DataFrame, dict]:
    frames, coverage = [], {}
    for f in sorted(glob.glob(str(ROOT / "data/live/a2_*.ndjson"))):
        day = Path(f).stem[3:]
        rows = [json.loads(line) for line in open(f)]
        if not rows:
            continue
        x = pd.DataFrame(rows)
        polled = pd.to_datetime(x.PolledAt).dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
        # a poll counts as coverage only if the feed returned some 5250 bus (5250B runs every ~10 min);
        # on 2026-10-23 TDX returned no 5250 at all, which is missing data, not a no-bus morning
        coverage[day] = polled[x.RouteUID == "THB5250"].drop_duplicates().sort_values()
        x["StopNameZh_tw"] = x.StopName.map(lambda s: s["Zh_tw"])
        x["A2EventType"] = x.A2EventType.map({0: "離站", 1: "進站"})
        for c in ["GPSTime", "TripStartTime"]:
            x[c] = pd.to_datetime(x[c], utc=True).dt.tz_convert("Asia/Taipei").dt.tz_localize(None)
        x = x[x.SubRouteUID.isin(tr.DEST)]
        x = x.drop_duplicates(["PlateNumb", "TripStartTime", "StopSequence", "A2EventType", "GPSTime"])
        frames.append(x[["PlateNumb", "RouteUID", "SubRouteUID", "StopSequence", "StopNameZh_tw",
                         "A2EventType", "GPSTime", "TripStartTime"]])
    d = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if len(d):
        d["source"] = "live"
    return d, coverage


def departure_window_covered(polls: pd.Series, day: pd.Timestamp) -> bool:
    """True when the feed showed 5250 buses through 07:20-07:45 without a gap > 3 min."""
    a, b = day + pd.Timedelta("07:20:00"), day + pd.Timedelta("07:45:00")
    p = polls[(polls >= a - pd.Timedelta("3min")) & (polls <= b + pd.Timedelta("3min"))]
    if len(p) == 0 or p.min() > a + pd.Timedelta("3min") or p.max() < b - pd.Timedelta("3min"):
        return False
    return bool((p.diff().dropna() <= pd.Timedelta("3min")).all())


def stop_offsets(events: pd.DataFrame) -> dict:
    """Median minutes from each stop (any event) to the destination arrival, per sub-route."""
    out = {}
    for sub, dseq in DEST_SEQ.items():
        e = events[events.SubRouteUID == sub]
        arr = e[(e.StopSequence == dseq) & (e.A2EventType == "進站")].groupby(["PlateNumb", "TripStartTime"]).GPSTime.min()
        at = e.groupby(["PlateNumb", "TripStartTime", "StopSequence"]).GPSTime.min().reset_index()
        at = at.join(arr.rename("arr"), on=["PlateNumb", "TripStartTime"]).dropna()
        at["delta"] = (at.arr - at.GPSTime).dt.total_seconds() / 60
        out[sub] = at.groupby("StopSequence").delta.median().to_dict()
    return out


def infer_missing(trips: pd.DataFrame, events: pd.DataFrame, offsets: dict) -> pd.DataFrame:
    trips = trips.copy()
    trips["arrival_inferred"] = 0
    for i, t in trips[trips.arr_dest.isna()].iterrows():
        e = events[(events.SubRouteUID == t.sub_route) & (events.PlateNumb == t.plate) & (events.TripStartTime == t.trip_start)]
        e = e[e.StopSequence.isin(offsets.get(t.sub_route, {}))]
        if e.empty:
            continue
        dseq = DEST_SEQ[t.sub_route]
        e = e.assign(dist=(e.StopSequence - dseq).abs()).sort_values(["dist", "GPSTime"])
        best = e.iloc[0]
        trips.at[i, "arr_dest"] = (best.GPSTime + pd.Timedelta(minutes=offsets[t.sub_route][best.StopSequence])).round("s")
        trips.at[i, "arrival_inferred"] = 1
    trips["at_farglory"] = trips.arr_dest + pd.to_timedelta(trips.walk_min, unit="min")
    return trips


def workdays() -> set:
    c = pd.read_csv(ROOT / "data/calendar/workdays.csv", parse_dates=["date"])
    return set(c.loc[c.is_holiday == 0, "date"])


def mornings(trips: pd.DataFrame, days: list[tuple[pd.Timestamp, str]]) -> pd.DataFrame:
    mins = lambda ts, d: round((ts - d).total_seconds() / 60, 1)
    rows = []
    for d, source in days:
        t = trips[(trips.date == d) & trips.arr_dest.notna()]
        w = t[(t.dep_origin >= d + pd.Timedelta(WINDOW[0])) & (t.dep_origin <= d + pd.Timedelta(WINDOW[1]))].sort_values("dep_origin")
        if len(w):
            r = w.iloc[0]
            rows.append(dict(date=d, strategy="rule", mode=r.route, arrive_min=mins(r.at_farglory, d), arrival_inferred=r.arrival_inferred))
        else:
            rows.append(dict(date=d, strategy="rule", mode="taxi", arrive_min=TAXI_ARRIVE_MIN, arrival_inferred=1))
        for name, start in [("only_0730", "07:25:00"), ("only_0755", "07:50:00")]:
            b = t[(t.route == "5250") & (t.dep_origin >= d + pd.Timedelta(start))].sort_values("dep_origin")
            if len(b):
                r = b.iloc[0]
                rows.append(dict(date=d, strategy=name, mode="5250", arrive_min=mins(r.at_farglory, d), arrival_inferred=r.arrival_inferred))
        for r in rows[-3:]:
            r["source"] = source
    m = pd.DataFrame(rows).sort_values(["date", "strategy"])
    m["date"] = m.date.dt.strftime("%Y-%m-%d")
    return m[["date", "strategy", "mode", "arrive_min", "source", "arrival_inferred"]]


HIST_TRIPS = OUT / "history_trips.parquet"    # trip summaries derived from the purchased days
HIST_META = OUT / "history_meta.json"         # those days + stop-to-destination offsets


def history() -> tuple[pd.DataFrame, dict, set]:
    """Purchased history as trip summaries. Rebuilt from data/hist when it exists locally;
    otherwise (e.g. on GitHub, where the raw purchased files are not published) read back."""
    if glob.glob(str(ROOT / "data/hist/a2_*.csv")):
        hist = load_hist()
        offsets = stop_offsets(hist)
        th = infer_missing(tr.build(hist), hist, offsets)
        days = sorted(Path(f).stem[3:] for f in glob.glob(str(ROOT / "data/hist/a2_*.csv")))
        OUT.mkdir(parents=True, exist_ok=True)
        th.to_parquet(HIST_TRIPS, index=False)
        HIST_META.write_text(json.dumps({"days": days, "offsets": offsets}, ensure_ascii=False, indent=1))
    else:
        th = pd.read_parquet(HIST_TRIPS)
        meta = json.loads(HIST_META.read_text())
        days, offsets = meta["days"], meta["offsets"]
    offsets = {sub: {int(k): v for k, v in o.items()} for sub, o in offsets.items()}
    return th, offsets, {pd.Timestamp(d) for d in days}


def main() -> None:
    th, offsets, hist_days = history()
    live, coverage = load_live()
    parts = [th]
    if len(live):
        parts.append(infer_missing(tr.build(live), live, offsets))
    t = pd.concat(parts, ignore_index=True)
    wd = workdays()
    days = [(d, "history") for d in sorted(hist_days) if d in wd]
    skipped = []
    for day, polls in coverage.items():
        d = pd.Timestamp(day)
        if d in hist_days or d not in wd:
            continue
        if departure_window_covered(polls, d):
            days.append((d, "live"))
        else:
            skipped.append(day)
    m = mornings(t, sorted(days))
    OUT.mkdir(parents=True, exist_ok=True)
    m.to_csv(OUT / "mornings.csv", index=False)
    r = m[m.strategy == "rule"]
    print(f"{r.date.nunique()} mornings ({(r.source == 'live').sum()} live), "
          f"rule on time {(r.arrive_min <= 540).sum()}/{len(r)}, taxi days {(r['mode'] == 'taxi').sum()}, "
          f"inferred arrivals {int(m.arrival_inferred.sum())}; skipped (no 5250 data 07:20-07:45): {skipped or 'none'}")


if __name__ == "__main__":
    main()
