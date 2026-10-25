# CLAUDE.md

Commute study: how reliably highway bus **5250** (Yatung, TDX `InterCity`, RouteUID `THB5250`) gets a
commuter from **Songshan Airport** (松山機場, stop 1) to **Farglory Value-Added Zone** (遠雄加值園區,
stop 29 on sub-route `THB525001`) by **09:00** on weekdays. Backup bus **1841** (Kuo-Kuang, `THB1841`)
stops at Shuzaipo (樹仔坡, ~650 m away; a 10-minute walk is assumed).

The rule under test: **take the first 5250 (to Farglory) or 1841 that leaves Songshan Airport between
07:25 and 07:43; otherwise take a taxi.** 5250B/5250C turn off at 長榮 and never serve Farglory.

## Pipeline

| Step | Where | What |
| --- | --- | --- |
| Collect | GitHub Actions `.github/workflows/collect.yml` (working days; three crons 20:10, 20:50, 21:30 UTC Sun–Thu = 04:10–05:30 Taipei, because GitHub starts scheduled runs up to ~2.5 h late or drops them) | `collect_5250.py` polls TDX live A2 for 5250+1841 in one request: 07:15–08:00 every 30 s, 08:00–09:15 every 60 s → `data/live/a2_YYYY-MM-DD.ndjson` |
| Build | same workflow | `build_panel.py` → `data/panel/mornings.csv` (one row per working day × approach: `rule`, `only_0730`, `only_0755`) |
| Publish | Claude cloud routine "Farglory plan refresh" (weekdays 10:00 Taipei) | Uploads `mornings.csv` to the dashboard's `datasets/mornings` |

Dashboard: https://claude.ai/artifact/TwMTNqcxcFBKaBrYxJPYgq ("Farglory Commute Plan", Dashboard
type). The page source is edited through the artifact store (`files/index.html`), not this repo. Every
figure on it comes from a dataset or a `dash.calc`; don't hard-code numbers in the page.

## Files

- `tdx.py`: stdlib TDX client (token cache, `request`, `get`). Reads `TDX_CLIENT_ID`/`TDX_CLIENT_SECRET` from `.env` or the environment.
- `trips.py`: rebuilds trips from A2 stop events (departure from 松山機場, arrival at the destination stop).
- `build_panel.py`: merges history + live into the panel; skips live days without 5250 data in the 07:20–07:45 departure window (collector off, or TDX feed outage as on 2026-10-23); estimates missed arrivals from neighbouring stops (`arrival_inferred = 1`).
- `hist_a2.py`: downloads purchased TDX historical A2 (**costs points**; `--meta` only checks sizes).
- `freeway_m04a.py`, `taxi_model.py`: Freeway Bureau TDCS M04A gantry travel times (Freeway 1 km 15–53, since 2021-06-22) and the 07:50 taxi simulation.
- `data/calendar/workdays.csv`: official government working-day calendar (holidays = `is_holiday 2`).

## Commands

```bash
uv run python build_panel.py                     # rebuild the panel
uv run python collect_5250.py --once             # one live poll (test)
uv run python taxi_model.py                      # taxi reliability, 5 years
uv run python freeway_m04a.py 2026-10-01 2026-10-17
uv run python hist_a2.py --meta 2026-09-01 2026-09-01   # size only
gh workflow run collect.yml -f test=true         # quick test of the GitHub collector
```

## Rules

- **TDX budget**: the free Basic plan gives 3 points/month (≈4,500 basic calls, 5 calls/min). Basic calls cost 1 point per 1,500 calls or 150 MB; **historical calls cost 1 point per 10 calls or 20 MB**, and one day of InterCity A2 is ~343 MB ≈ 17 points (whole country, no server-side route filter: `$filter`/`$select` are ignored). The collector uses ~3,600 calls/month; don't add polling that pushes past ~4,500. The same TDX account is shared with `~/dev/urban_clustering`.
- **Never publish** `.env`, `.tdx_token.json`, or the purchased raw history `data/hist/` (summarised into `data/panel/history_trips.parquet` instead). `.gitignore` whitelists only `data/live/`, `data/panel/`, `data/calendar/`.
- TLS: some Taiwanese government certificates fail Python 3.13's strict X.509 check; use `tdx.SSL_CTX` for any `urllib` call to TDX, tisvcloud or dgpa.
- Times: everything is Asia/Taipei; GitHub cron is UTC. A2 `A2EventType` is `進站`/`離站` in history CSVs and `1`/`0` in live JSON.
- Data attribution: 交通部 TDX 運輸資料流通服務平臺 and 交通部高速公路局 TDCS.
- The GitHub Action commits data to `main`; pull before pushing local changes.
