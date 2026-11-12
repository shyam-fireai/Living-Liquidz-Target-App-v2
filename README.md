# Living Liquidz Target App

Internal Streamlit app for viewing, uploading and editing sales targets stored in ClickHouse.

- **Branch Wise Monthly Target**: monthly targets per branch and series. Saving these also
  regenerates the daily targets (see [Daily split rule](#daily-split-rule)).
- **Brand Wise Monthly Target**: monthly quantity targets per branch, series and item.
- **Date & Branch Wise Target**: daily targets. Read-only in the UI; generated from the monthly table.

What users can do:

- **Dashboard**: summary cards (rows, branches, totals over *all* matching rows), cascading
  filters with removable chips, a paged table ("Showing 201–400 of N", page size 200 / 500 /
  1,000 / 5,000 / All, Previous / Next; paging is done by ClickHouse), and CSV/Excel export of
  every matching row (the CSV can be edited and uploaded again).
- **Upload** (CSV): every row is validated at once (missing values, bad dates, month not the 1st,
  non-numeric/negative/too-large numbers, duplicate keys, unknown branches as warnings), then a
  preview shows new / updated / unchanged rows and the daily split before anything is saved.
  Only rows that change are written.
- **Edit**: inline editing (key columns included), a highlighted old -> new review, the same
  validation as uploads, and protection against overwriting another row's key. Changing a key
  replaces the old row (and its daily targets) on save.
- **History**: who uploaded / edited what and when, from the audit log, in IST. Filters by date,
  action, user and table; selecting an edit shows exactly which cells changed (old -> new).

Users log in with their FireAI account; only e-mails in `ALLOWED_EMAILS` are admitted. Every login,
upload, edit and error is written to the `target_system_audit_logs` table.

---

## Quick start (deployment)

```bash
# 1. Create the tables once (skip if they already exist)
clickhouse-client --host <host> --secure --user <admin> --password --database living_liquid_mv \
  --multiquery < db/schema.sql

# 2. Configure: copy .env.example to .env and fill it in (never commit .env)
cp .env.example .env

# 3. Build and run
docker build -t living-liquidz-targets .
docker run -d --name living-liquidz-targets --restart unless-stopped \
  -p 8501:8501 --env-file .env living-liquidz-targets
```

The app listens on port **8501**. Health check: `GET /_stcore/health` returns `ok`.

If configuration is missing or invalid, the app starts but shows a page listing exactly which
settings to fix (values are never displayed), and the same list is logged at `ERROR` level.

---

## Configuration

Every setting can come from three places; the first one that has a value wins:

1. **Streamlit secrets** (`st.secrets`): the Secrets box on Streamlit Community Cloud, or a local
   `.streamlit/secrets.toml` (template: `.streamlit/secrets.toml.example`). Same names as the
   environment variables below; the database settings may also go in a `[data_clickhouse]` table.
2. **Environment variables** (Docker / servers; template: `.env.example`).
3. **`secrets.json`** in the project directory (local development; template: `secrets.example.json`).
   `LL_SECRETS_PATH` can point to a `secrets.json` elsewhere.

`ALLOWED_EMAILS` may be a comma-separated string or, in TOML, a list of strings.

| Environment variable | secrets.json key | Required | Description |
|---|---|---|---|
| `CLICKHOUSE_HOST` | `data_clickhouse.host` | yes | ClickHouse host |
| `CLICKHOUSE_PORT` | `data_clickhouse.port` | no (8123) | HTTP(S) port, usually 8443 with TLS |
| `CLICKHOUSE_USER` | `data_clickhouse.username` | yes | App database user (see [privileges](#database)) |
| `CLICKHOUSE_PASSWORD` | `data_clickhouse.password` | no | Password for that user |
| `CLICKHOUSE_DATABASE` | `data_clickhouse.database` | yes | e.g. `living_liquid_mv` |
| `CLICKHOUSE_SECURE` | `data_clickhouse.secure` | no (false) | `true` to use TLS |
| `FIREAI_BASE_URL` | `FIREAI_BASE_URL` | yes | FireAI auth API base URL |
| `FIREAI_API_KEY` | `FIREAI_API_KEY` | yes | FireAI API key |
| `ALLOWED_EMAILS` | `ALLOWED_EMAILS` | yes | Comma-separated e-mails allowed to log in |
| `COOKIE_SECRET` | `COOKIE_SECRET` | yes | ≥ 32 random characters, **unique per environment**. Signs login sessions; changing it logs everyone out. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `SESSION_HOURS` | `SESSION_HOURS` | no (1) | How long a login lasts |

`auth_clickhouse` in older `secrets.json` files is not used by the app.

---

## Deploying to Streamlit Community Cloud

1. On [share.streamlit.io](https://share.streamlit.io) create an app from this repository:
   branch `development` (or `main`), main file `app.py`. Under **Advanced settings** choose
   **Python 3.11**. Dependencies are installed from `requirements.txt`.
2. In **Settings → Secrets**, paste the contents of `.streamlit/secrets.toml.example` and replace
   every placeholder. Use a newly generated `COOKIE_SECRET` for this deployment.
3. Save. The app restarts. If anything is still missing it shows which setting to fix (values are
   never displayed).

Notes:
- The ClickHouse server must accept connections from the internet (Streamlit Cloud has no fixed
  IP), over TLS: `CLICKHOUSE_SECURE = true`, usually port 8443.
- The tables must already exist (see [Database](#database)).
- Never commit `.streamlit/secrets.toml`, `secrets.json` or `.env`; they are gitignored.

---

## Database

Schema: [`db/schema.sql`](db/schema.sql). Target tables use `ReplacingMergeTree(version)`:

- Saving a row **inserts a new version** (`version` = Unix time); reads use `FINAL`, so the newest
  version of each key wins. There are no in-place updates for normal saves.
- Rows are never deleted by the app. When an edit changes a row's key (month / branch / series ...),
  the old key is retired with `ALTER TABLE ... UPDATE is_active = 0` (run with `mutations_sync = 1`).
  All reads filter `is_active = 1`.
- Values are `Decimal(10, 2)`: maximum 99,999,999.99 per cell.

Privileges needed by the app user (`CLICKHOUSE_USER`), least privilege:

```sql
GRANT SELECT, INSERT, ALTER UPDATE ON living_liquid_mv.branch_wise_monthly_target TO <app_user>;
GRANT SELECT, INSERT, ALTER UPDATE ON living_liquid_mv.brand_wise_monthly_target  TO <app_user>;
GRANT SELECT, INSERT, ALTER UPDATE ON living_liquid_mv.date_branch_wise_target    TO <app_user>;
GRANT SELECT, INSERT              ON living_liquid_mv.target_system_audit_logs    TO <app_user>;
```

---

## Daily split rule

When Branch Wise Monthly Target rows are uploaded or edited, each monthly `target_value1..5` is
split over the days of that month: **Mon–Thu weight 3, Fri–Sun weight 5**. Each day is rounded to
2 decimals and the last day absorbs the rounding remainder, so the daily values always add up
**exactly** to the monthly value. Daily incentives are 0. Implemented in `services/targets.py`
(`month_weights`, `distribute_target`) and covered by tests.

Save order (`services.targets.save_targets`), chosen so a failure never loses data:
1. insert the monthly rows; on failure nothing else happens;
2. regenerate and insert the daily rows; on failure the user is told to save again;
3. retire old keys changed by an edit (skipping keys that the new rows re-use).

---

## Project layout

```
app.py              entry point: page config, settings check, login, table picker, routing
config.py           table metadata (single source of truth) + settings loading/validation
auth.py             FireAI login, session cookies, logout
db/
  client.py         ClickHouse client (one per process)
  repository.py     all queries; values always passed as ClickHouse parameters
  audit.py          audit log: writes (never raise) and History reads
  cache.py          per-table cache invalidation (see Operations)
  schema.sql        table definitions
services/
  targets.py        daily split + save_targets (business rules)
  validation.py     CSV reading and input normalisation
  session.py        HMAC-signed session tokens
  changes.py        upload preview: new / updated / unchanged
  edits.py          edit validation (key collisions, replaced keys)
  history.py        audit entries -> readable summaries, IST times, old/new diffs
  export.py         CSV / Excel export
ui/                 theme CSS, header, sidebar filters, number formatting
views/              dashboard.py, edit.py, upload.py, history.py (screens)
tests/              pytest unit tests
```

Security notes: SQL values are always bound parameters, and table/column names come only from
`config.TABLES`. Session cookies carry `"<expiry>.<HMAC-SHA256(email|expiry)>"` and are verified on
every restore. Secrets are never logged or baked into the Docker image (`.dockerignore`).

---

## Operations

- **Logs**: stdout, format `time LEVEL module: message`.
- **Audit trail**: `target_system_audit_logs` (who, what, when, before/after values for edits),
  shown in the app on the **History** page. Timestamps are stored as DateTime (UTC on the
  server) and displayed in IST.
- **Caching**: reads are cached for 60 s (filter lists 5 min). Every write made *through the app*
  bumps a per-table data version (`db/cache.py`), so the changed table is refreshed immediately
  for every user of that app process, and other tables stay cached. Changes made *outside* the app
  (scripts, direct SQL) and, with several replicas, changes made on *another replica* appear
  after the cache TTL (at most 60 s).
- **Scaling**: Streamlit keeps a websocket per browser tab. Behind a load balancer, enable
  **sticky sessions** and **websocket upgrades**. All replicas must share the same `COOKIE_SECRET`.
- **Reverse proxy** (nginx example):

  ```nginx
  location / {
      proxy_pass http://127.0.0.1:8501;
      proxy_http_version 1.1;
      proxy_set_header Upgrade $http_upgrade;
      proxy_set_header Connection "upgrade";
      proxy_set_header Host $host;
      proxy_read_timeout 86400;
  }
  ```
  Serve the app over HTTPS only.

---

## Development

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (Linux/macOS: source venv/bin/activate)
pip install -r requirements-dev.txt
cp secrets.example.json secrets.json   # then fill it in
streamlit run app.py
```

Checks (also run by GitHub Actions on every push, see `.github/workflows/ci.yml`):

```bash
ruff check . && ruff format --check . && pytest -q
```

Dependencies are pinned in `requirements.txt`; upgrade deliberately and re-run the tests.
