# Playwright E2E (Change Tracker) — disposable DB only

**Agents:** also read [docs/AI_TESTING_AND_PLANNING.md](../../docs/AI_TESTING_AND_PLANNING.md) before running or extending these tests.

**Never** point these tests at production Mongo (`DB_NAME=arihant_crm`) or `https://arihant-api.claraai.tech`.

Your machine’s `backend/.env` may already be production — E2E **ignores** that file and requires `backend/.env.e2e`.

## One-time setup

```bash
# 1) Disposable Mongo — either local mongod / Docker, OR a dedicated Atlas *test* cluster
#    Never reuse the production cluster DB_NAME arihant_crm.

# 2) Env (copy example, then set MONGO_URL in the private file)
cp backend/env.e2e.example backend/.env.e2e
# Edit backend/.env.e2e → MONGO_URL=...  DB_NAME=arihant_crm_e2e  ENVIRONMENT=e2e

# 3) Seed Admin + Rep + Manager + GM (Shariff)
cd backend
set E2E_ENV_FILE=.env.e2e   # PowerShell: $env:E2E_ENV_FILE=".env.e2e"
python scripts/seed_e2e_users.py

# 4) Start API with .env.e2e only (example: load dotenv in shell, then uvicorn)
# PowerShell:
Get-Content .env.e2e | ForEach-Object {
  if ($_ -match '^\s*#' -or $_ -notmatch '=') { return }
  $k,$v = $_.Split('=',2); Set-Item -Path "Env:$k" -Value $v
}
$env:PYTHONPATH="."
uvicorn crm.main:app --host 127.0.0.1 --port 8000

# 5) Frontend pointed at local API
cd ../frontend
# .env.local: VITE_BACKEND_URL=http://127.0.0.1:8000
npm install
npx playwright install chromium
npm run start   # :3000
```

## Run

```bash
cd frontend
# Safety-only (no API needed beyond config assert):
npm run test:e2e:safety

# Full tracker suite (API + UI + Mongo e2e required):
npm run test:e2e
```

Cleanup runs automatically in `afterAll` via `scripts/e2e_cleanup.py` (tagged `e2e_run_id` / `E2E_*` only).

Manual cleanup:

```bash
cd backend
$env:E2E_ENV_FILE=".env.e2e"
python scripts/e2e_cleanup.py --run-id <uuid>
```

## Safety rails

- `E2E_DB_NAME` / `DB_NAME` must be `arihant_crm_e2e` (or `arihant_crm_test`)
- `ENVIRONMENT` must be `development` | `test` | `e2e`
- API URL must be localhost / 127.0.0.1
- Blocked hosts: `arihant-api.claraai.tech`, Emergent preview
- Outbound WhatsApp is intercepted in the browser (`mockWati.cjs`); keep `WHATSAPP_PROVIDER=disabled` in `.env.e2e`
- Synthetic phones are random (avoids live smoke phone `9116914178`)

## Phone note

`+919116914178` is the live Meta smoke phone. Do **not** use it against production. On `arihant_crm_e2e` only, you may set `E2E_PHONE` if you need that MSISDN for manual checks.
