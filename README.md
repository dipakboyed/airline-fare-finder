# airline-fare-finder

Config-driven "cheapest fare finder". Given trip constraints (route, date window,
trip length, cabins, preferred airlines, max stops), it finds the best fare per
cabin, remembers previous runs, and **emails you when fares drop** — all on a
daily GitHub Actions schedule, no machine required.

Case #1 ships ready to go: **SEA &rarr; CCU**, next 3 weeks, 10&ndash;20 day trip,
Economy / Premium Economy / Business, on Singapore / Emirates / Qatar (each offers
a genuine 1-stop routing via SIN / DXB / DOH).

## How it works

1. **Google Flights** (via [`fast-flights`](https://pypi.org/project/fast-flights/))
   sweeps the full date matrix for free — the breadth scanner.
2. **Amadeus** (Self-Service, free tier) authoritatively confirms the cheapest
   candidates per cabin, capped by a per-run quota guard.
3. Best fare per cabin **prefers Amadeus** when available, else Google.
4. Results are snapshotted under `data/`; the next run diffs against them to
   detect **drops** and **deals** (fares at/under your target price).
5. Email is sent per your `alert_policy` (default: **only on drops**).

## Add a new trip (no code changes)

Drop a YAML into `config/searches/`. It is picked up automatically.

```yaml
name: sea-nrt
origin: SEA
destination: NRT
max_stops: 1
depart_window: { from: today, to: +30d }   # relative (+Nd) or ISO dates
trip_length_days: [7, 14]
cabins: [ECONOMY, BUSINESS]
preferred_airlines: [NH, JL]
passengers: 1
currency: USD
target_price_usd: 900
alert_policy: only_drops        # only_drops | every_run | only_target | every_run_plus_drops
sampling: { depart_step_days: 1, trip_length_step_days: 2 }
amadeus_max_calls_per_run: 15   # free-tier quota guard (~2000 calls/month)
```

See `config/searches/sea-ccu.yaml` for the shipped example.

## Run locally

```powershell
python -m venv .venv
.\.venv\Scripts\pip install -r requirements.txt

# Option A: copy the template and fill in your keys (.env is gitignored)
copy .env.example .env   # then edit .env

# Option B: set env vars inline
$env:AMADEUS_CLIENT_ID="..."; $env:AMADEUS_CLIENT_SECRET="..."

# Dry run (no persistence, prints a summary + writes report.html):
python -m farefinder run --config config/searches/sea-ccu.yaml --dry-run
```

Without Amadeus creds it still runs Google-only (results marked unverified).

## Scheduling & email (GitHub Actions)

- **`fares-daily.yml`** — daily cron. Runs the search, commits fare history back,
  and emails you only when the `alert_policy` condition is met.
- **`ci.yml`** — PR/push lane. Runs the mocked test suite (fast, no network).
- **`drift-weekly.yml`** — weekly live contract test against the real APIs;
  emails an alert if a provider parser breaks (schema drift / outage).

### Required repository secrets

| Secret | What |
|---|---|
| `AMADEUS_CLIENT_ID` / `AMADEUS_CLIENT_SECRET` | Free production key from [developers.amadeus.com](https://developers.amadeus.com) |
| `MAIL_USERNAME` | Gmail address that sends the report |
| `MAIL_PASSWORD` | Gmail **app password** (not your account password) |
| `MAIL_TO` | Where reports are delivered |

Add them under **Settings &rarr; Secrets and variables &rarr; Actions**. Nothing
sensitive is ever committed.

Or set them all interactively (hidden input, optional local `.env`):

```powershell
.\scripts\set-secrets.ps1 -WriteEnv
```

`AMADEUS_ENV` (optional secret) selects `test` vs `production`; it defaults to
`production` in the workflows if unset.

## Testing

```powershell
.\.venv\Scripts\pip install -r requirements-dev.txt
.\.venv\Scripts\pytest -q -m "not live"   # fast, mocked/fixtures
.\.venv\Scripts\pytest -q -m live         # live smoke (needs creds/opt-in)
```

The suite validates parsers against recorded fixtures and **ground-truths**
Amadeus output against the raw API response. Live smoke + weekly drift catch
upstream schema changes.

## Layout

```
config/searches/     trip configs (add YAML = add trip)
src/farefinder/      config, models, dates, providers/, search, history, report, __main__ (CLI)
data/                fare-history snapshots (committed by the daily job)
tests/               fixtures + unit/contract/live tests
.github/workflows/   ci, fares-daily, drift-weekly
```
