# AI testing & planning playbook (Arihant CRM)

Cursor agents: read this before E2E, live smoke, tracker verification, or any DB write that is not clearly a user-owned local/dev disposable database.

Humans: same checklist when running Playwright or spinning a test API.

---

## 1. Environments (hard rules)

| Target | Allowed writes? | Notes |
|--------|-----------------|-------|
| Production `DB_NAME=arihant_crm` / `arihant-api.claraai.tech` | **No** for E2E/create/nudge/bulk/webhook/WA send | Live users |
| Disposable `DB_NAME=arihant_crm_e2e` + `ENVIRONMENT=e2e` | **Yes** | Atlas test cluster or local Mongo |
| CI `arihant_crm_test` | Unit/integration only as wired | Ephemeral |

**Machine trap:** `backend/.env` on this project often points at **production**. E2E must use `backend/.env.e2e` only.

**Start API safely (PowerShell):**

```powershell
cd backend
Get-Content .env.e2e | ForEach-Object {
  $line = $_.Trim()
  if (-not $line -or $line.StartsWith('#')) { return }
  $i = $line.IndexOf('=')
  if ($i -lt 1) { return }
  Set-Item -Path ("Env:" + $line.Substring(0,$i).Trim()) -Value $line.Substring($i+1).Trim()
}
if ($env:DB_NAME -ne 'arihant_crm_e2e') { throw 'REFUSE: not e2e DB' }
$env:PYTHONPATH = '.'
python -m uvicorn crm.main:app --host 127.0.0.1 --port 8000
```

`load_dotenv(backend/.env)` does **not** override vars already set — so pre-loading `.env.e2e` is mandatory.

Frontend: `frontend/.env.local` → `VITE_BACKEND_URL=http://127.0.0.1:8000`  
CORS in `.env.e2e` must include **both** `http://127.0.0.1:3000` and `http://localhost:3000`.

Seed users: `python scripts/seed_e2e_users.py` with `E2E_ENV_FILE=.env.e2e`  
→ Admin `full_name=Admin` + `e2e-admin@arihant.local` / Rep `e2e-rep@arihant.local`

---

## 2. Playwright layout

| Path | Role |
|------|------|
| `frontend/playwright.config.js` | Loads `.env.e2e` with **override**; refuses live hosts |
| `frontend/e2e/helpers/safety.cjs` | Fail-closed env/DB/URL checks |
| `frontend/e2e/helpers/api.cjs` | Login, create tagged leads, cleanup via Python |
| `frontend/e2e/helpers/watiWebhook.cjs` | Local synthetic inbound only |
| `frontend/e2e/helpers/mockWati.cjs` | Intercept templates + send (no live WATI) |
| `frontend/e2e/helpers/auth.cjs` | UI form login (AuthContext) |
| `frontend/e2e/tracker-26-36.spec.js` | Tracker 26–36 coverage |
| `backend/scripts/e2e_cleanup.py` | Cascade delete by `e2e_run_id` / `E2E_*` |
| `backend/scripts/e2e_fixtures.py` | Notifications, notes, timeline patches |

```bash
cd frontend
npm run test:e2e:safety   # no stack needed beyond config
npm run test:e2e          # needs API :8000 + Vite :3000 + e2e Mongo
```

---

## 3. Lessons learned (do not regress)

1. **Sticky header stacking:** `fixed z-50` *inside* `sticky z-30` header loses to a sibling `fixed z-40` overlay. Render notification panel as a **sibling of the overlay**, not inside the header.
2. **CORS:** Browser login fails with “Invalid credentials” if OPTIONS fails — check origins, not only password.
3. **Session invalidation:** Each `/auth/login` sets `current_session_id` and kills prior tokens. Refresh API token after UI login; don’t spam login (rate limit). E2E/dev login limit is raised to `60/minute`.
4. **Radix Checkbox:** Use `getByRole('checkbox')`, not `input[type=checkbox]`.
5. **Controlled Dialog:** Setting `open` via button may not call `onOpenChange` — call `fetchWaTemplates()` (or equivalent) in the open button handler.
6. **WATI webhook:** WATI-shaped POSTs to `/api/whatsapp/webhook` are processed even if `WHATSAPP_PROVIDER=disabled`. Never aim at prod.
7. **Phone:** Prefer random `91…` MSISDNs. `+919116914178` is the live Meta smoke phone.
8. **Cleanup:** No `DELETE /leads/{id}` API — use tagged cascade scripts only. Never `clear_dev_data.py` against unknown DB.

---

## 4. How to add tests for the next tracker batch

For each new tracker row:

1. **Classify:** read-only UI / DB write / notification / WA / external (Meta/WATI).
2. **Unit first** if pure logic (filters, parsers, services).
3. **Playwright** if UI wiring matters — extend `frontend/e2e/` with the same safety helpers; tag data with `e2e_run_id`.
4. **Mock** any outbound WATI/Meta in the browser or keep provider disabled.
5. **Assert cleanup** in `afterAll` via `cleanupRun(phones)`.
6. Run full `npm run test:e2e` on e2e stack before calling the batch done.

Suggested new spec naming: `frontend/e2e/tracker-<from>-<to>.spec.js` (or fold into one suite if small).

---

## 5. Making plans better (what the AI must take care of)

When the user pastes tracker rows or asks for a plan:

### Must include

- **Verified root cause** in code (file + why), not guesswork.
- **Data isolation** strategy (e2e DB / mocks) — default: reuse this playbook.
- **Side effects:** who gets notified, ownership changes, timeline writes, soft-dedupe on phone.
- **Cleanup** for every create path.
- **Test plan:** unit files + Playwright cases + manual smoke if anything cannot be automated safely.
- **Implementation order** that unblocks tests early (e.g. data flags before dashboard tiles).
- **Out of scope** explicitly (Option B reports, prod writes, etc.).

### Must avoid

- “We’ll carefully test on production.”
- Unscoped `delete_many` / wiping leads.
- Plans that leave A vs B product choices open when they block implementation — ask 1–2 critical questions first, then lock one approach.
- Editing the user’s plan file when they said not to.
- Claiming “verified” without running unit and/or e2e on disposable DB.

### After implementation

- Run relevant `pytest` unit suites.
- Run Playwright against e2e stack when UI changed.
- Summarize what passed; note anything still manual-only.

---

## 6. Next tracker batch

Yes — paste the next change-tracker rows (screenshot or text). The agent should:

1. Analyze against the codebase (like 26–36).
2. Produce a plan that **reuses** this E2E harness.
3. Implement only after you approve.
4. Extend Playwright + cleanup tags for the new rows.

Do **not** start writing to production while planning or implementing.
