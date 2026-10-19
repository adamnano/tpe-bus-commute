# Songshan Airport → Farglory commute (bus 5250)

Measures how reliably highway bus **5250** (and backup **1841**) gets a commuter from Taipei Songshan
Airport to the **Farglory Value-Added Zone** (遠雄加值園區) by 09:00, and tests a simple rule:

> Take the first 5250 or 1841 that leaves Songshan Airport between 07:25 and 07:43; otherwise take a taxi.

- `collect.yml` (GitHub Actions) polls TDX live stop events every weekday 07:15–09:15 Taipei time
  (every 30 s until 08:00, then every 60 s) into `data/live/`, then rebuilds `data/panel/mornings.csv`.
- `build_panel.py` turns history + live data into one row per morning and approach.
- `taxi_model.py` / `freeway_m04a.py` estimate taxi reliability from 5 years of Freeway Bureau gantry data.

Data source: 交通部 TDX 運輸資料流通服務平臺 (Transport Data eXchange, MOTC), and 交通部高速公路局 TDCS.
Purchased TDX history is summarised in `data/panel/history_trips.parquet`; the raw files are not included.
