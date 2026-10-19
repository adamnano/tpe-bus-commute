"""Free-tier live collector for 5250 + 1841 stop events (TDX A2), weekday mornings.

One request covers both routes (InterCity A2 filtered to THB5250 and THB1841) and is appended,
stamped with the poll time, to data/live/a2_YYYY-MM-DD.ndjson.

Schedule (Taipei time):
  07:15-08:00  every 30 s   departures from Songshan Airport around the 07:30 slot (what matters most)
  08:00-09:15  every 60 s   arrivals at Farglory / Shuzaipo (can be inferred if one is missed)
Budget: 90 + 75 = 165 calls per weekday, ~3,600 a month: inside the free 3 points (~4,500 calls).

At start it warns (Mac notification) if running on battery: a closed MacBook sleeps on battery
even with an external monitor, which stops collection.

Run by launchd at 07:14 on weekdays (see launchd/com.tpebus.collect5250.plist), or manually:
    python3 collect_5250.py            # runs until END, then exits
    python3 collect_5250.py --once     # single poll (for testing)
"""
from __future__ import annotations

import datetime as dt
import json
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

from tdx import ROOT, request

TZ = ZoneInfo("Asia/Taipei")
START, SLOW, END = dt.time(7, 15), dt.time(8, 0), dt.time(9, 15)
PATH = "/api/basic/v2/Bus/RealTimeNearStop/InterCity"
PARAMS = {"$filter": "RouteUID eq 'THB5250' or RouteUID eq 'THB1841'"}
OUT = ROOT / "data" / "live"


def log_error(msg: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with open(OUT / "errors.log", "a") as f:
        f.write(f"{dt.datetime.now(TZ).isoformat()} {msg}\n")


def poll() -> int:
    now = dt.datetime.now(TZ)
    status, _, body = request(PATH, PARAMS)
    OUT.mkdir(parents=True, exist_ok=True)
    if status != 200:
        log_error(f"HTTP {status} {body[:200]!r}")
        return 0
    records = json.loads(body)
    with open(OUT / f"a2_{now:%Y-%m-%d}.ndjson", "a") as f:
        for r in records:
            f.write(json.dumps({"PolledAt": now.isoformat(timespec="seconds"), **r},
                               ensure_ascii=False) + "\n")
    return len(records)


def warn_if_on_battery() -> None:
    try:
        ps = subprocess.run(["pmset", "-g", "ps"], capture_output=True, text=True).stdout
    except OSError:
        return
    if "Battery Power" in ps:
        log_error("started on battery: a closed lid will put the Mac to sleep and stop collection")
        subprocess.run(["osascript", "-e",
                        'display notification "Plug in the charger until 09:15, or closing the lid stops '
                        'the bus data collection." with title "5250 / 1841 collector"'])


def main() -> None:
    if "--once" in sys.argv:
        print(f"{poll()} records")
        return
    if dt.datetime.now(TZ).weekday() >= 5:
        return  # weekends: nothing to do
    warn_if_on_battery()
    while dt.datetime.now(TZ).time() < START:
        time.sleep(15)
    while (now := dt.datetime.now(TZ).time()) < END:
        period = 60 if now >= SLOW else 30
        t0 = time.monotonic()
        try:
            poll()
        except Exception as e:  # network blips must not kill the morning run
            log_error(f"{type(e).__name__}: {e}")
        time.sleep(max(0, period - (time.monotonic() - t0)))


if __name__ == "__main__":
    main()
