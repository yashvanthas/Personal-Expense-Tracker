# Expense Tracker

A multi-user Flask expense tracker with a browser dashboard, a JSON API, monthly budgets, and spending analytics. Accounts are password protected; transactions and budgets are isolated by account. SQLite is used locally and PostgreSQL is configured for Render.

## Run locally

Requirements: Python 3.10 or later.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-dev.txt
python -m flask --app app db upgrade
python app.py
```

Open `http://127.0.0.1:5000` and create an account. By default, the database is `instance\expenses.db`. Existing installations should copy that file to a safe location before running the migration; the migration keeps old rows but leaves them unassigned until you import them into an account.

Set `SECRET_KEY` to a stable, private value when running outside local development. Set `DATABASE_URL` to use another SQLAlchemy database URL. `postgres://` and `postgresql://` URLs are normalized to the Psycopg 3 driver.

## Accounts and privacy

Public registration is enabled. Passwords are stored as secure hashes, registration and login have per-IP rate limits, browser forms and API mutations use CSRF protection, and session cookies use `HttpOnly` and `SameSite=Lax`. HTTPS deployments set `SESSION_COOKIE_SECURE=true`. Do not reuse passwords.

Every transaction, budget, category list, export, backup, and analytics query is scoped to the signed-in account. API requests without a session receive `401`; browser pages redirect to sign-in. Account backups are versioned JSON files and restoring one replaces only the signed-in account's transactions and budgets.

Email verification, password reset, and account deletion are not included. Add those flows before using the app for a public service that requires account recovery or verified email ownership.

## API

All `/api/...` endpoints require a signed-in session. Browser API mutations must include the CSRF token in the `X-CSRFToken` header. The dashboard handles this automatically.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/transactions` | List this account's transactions; supports search, type, category, date range, limit, and offset |
| `POST` | `/api/transactions` | Create a transaction |
| `GET` | `/api/transactions/<id>` | Retrieve one of this account's transactions |
| `PUT` / `PATCH` | `/api/transactions/<id>` | Replace or update a transaction |
| `DELETE` | `/api/transactions/<id>` | Delete a transaction |
| `GET` | `/api/categories` | List this account's categories |
| `GET` | `/api/transactions/export-preview` | Preview filtered CSV rows |
| `GET` | `/api/transactions/export.csv` | Download filtered CSV |
| `POST` | `/api/transactions/import/preview` | Preview a CSV or `.xlsx` upload (multipart field `file`) |
| `POST` | `/api/transactions/import` | Validate and import valid CSV or `.xlsx` rows (multipart field `file`) |
| `GET` | `/api/budgets` | List monthly category budgets and spending status |
| `POST` | `/api/budgets` | Create or update a category budget |
| `DELETE` | `/api/budgets/<id>` | Delete a budget |
| `GET` | `/api/analytics/monthly` | Monthly income, expense, and net totals |
| `GET` | `/api/analytics/categories` | Expense totals by category |
| `GET` | `/api/analytics/period` | Date-range totals and daily/category summaries |
| `GET` | `/api/analytics/trends` | Monthly trends and Plotly chart data |
| `GET` | `/api/backup` | Download this account's JSON backup |
| `POST` | `/api/backup/restore` | Restore a JSON backup (multipart field `backup`) |
| `GET` | `/health` | Deployment health check |

Amounts must be positive with up to two decimal places. Transaction types are `income` or `expense`; dates use `YYYY-MM-DD`; budget months use `YYYY-MM`.

The dashboard's **Import Excel** action previews CSV and `.xlsx` transaction rows before saving. Date, amount, and category columns are required; type defaults to `expense` when no type column is mapped, and description is optional. Common header names are detected automatically, and the preview lets you adjust the column mapping. Invalid rows are reported with their spreadsheet row numbers. Exact duplicate transactions in the account or repeated in the uploaded file are skipped. Imports are limited to 10 MB and 5,000 data rows; valid rows are inserted together without replacing existing account data.

## Import data from the previous SQLite app

The migration keeps the old SQLite transactions and budgets in place but does not expose unassigned legacy records to accounts. First create an account on the destination database, then import into that empty account:

```powershell
python -m flask --app app import-legacy-data `
  --email you@example.com `
  --source "C:\path\to\your\old\instance\expenses.db"
```

The importer reads the source database and copies its transactions and budgets into the selected account. It does not modify the source. It refuses to import into an account that already has transactions or budgets. For a Render-hosted PostgreSQL database, set `DATABASE_URL` to Render's **external** database URL and run this command on your computer, where the old SQLite file is available. Keep the database URL private and remove it from the shell environment after importing.

## Deploy to Render

1. Push this project to a GitHub repository.
2. In Render, create a Blueprint from the repository and review the PostgreSQL plan and pricing before confirming. The included free PostgreSQL plan may expire; upgrade it or choose a paid plan for persistent production data.
3. Render runs `flask --app app db upgrade` before Gunicorn starts. The Blueprint generates a private `SECRET_KEY` and enables secure session cookies.
4. Wait for `/health` to report `{"status":"ok"}`, then open the service URL and create your account.
5. To migrate existing local data, follow the import procedure above after the database and app are deployed.

For production, retain the generated `SECRET_KEY`, configure HTTPS, and set `RATELIMIT_STORAGE_URI` to a shared Redis-compatible service before using multiple web workers or instances. The default in-memory rate-limit store is process-local. Configure database backups and monitor the Render database's plan/expiry separately; account JSON backups are an additional user-controlled backup.

## Tests

```powershell
python -m pytest -q
```
