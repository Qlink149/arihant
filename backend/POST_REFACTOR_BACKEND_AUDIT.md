# Post-Refactor Backend Audit

Read-only audit of the refactored backend (May 2026). Use this map before implementing the Vercel Cron SLA Engine. yooo yooooo

## Executive summary

The refactor landed under **`backend/crm/`**, not `backend/app/`. The package name is intentional (`backend/crm/__init__.py`: *"named crm — not app, to avoid Vercel path conflicts"*).

| Expected path | Actual status |
|---------------|---------------|
| `backend/app/` | **Does not exist** |
| `api/`, `core/`, `models/`, `services/` | **Present** under `backend/crm/` |
| `core/database.py` | **Does not exist** — DB is in `backend/crm/core/state.py` |
| `main.py` | `backend/crm/main.py`; Vercel entry: `backend/index.py` |

**Implication for Vercel Cron SLA Engine:** `main.py` still runs an hourly `asyncio` reminder loop on startup. That pattern does not survive serverless cold starts; cron should call a dedicated HTTP handler (similar to `process_reminders` in `backend/crm/api/v1/endpoints/reminders.py`) instead of relying on the background task.

---

## 1. Current directory structure

### Active layout (`backend/crm/`)

```
backend/
├── index.py                 # ASGI entry: from crm.main import app
├── vercel.json
├── requirements.txt
├── tests/
├── scripts/, seed_db*.py, import_leads.py
└── crm/
    ├── main.py              # FastAPI app + startup/shutdown + reminder scheduler
    ├── api/
    │   └── v1/
    │       ├── router.py    # Aggregates all endpoint routers
    │       └── endpoints/   # 22 route modules (auth, leads, tasks, reminders, …)
    ├── core/
    │   ├── state.py         # Mongo client, db, JWT, indexes, auth deps
    │   └── platform_ops.py  # Platform operator guards
    ├── models/
    │   └── schemas/         # Pydantic models (lead, user, campaign, …)
    ├── services/
    │   ├── lead_service.py
    │   ├── assignment_service.py
    │   ├── whatsapp_service.py
    │   ├── lead_search.py
    │   ├── context_updates.py
    │   ├── ai_lead_regen.py
    │   └── ai_service.py
    ├── utils/helpers.py
    ├── constants/lead_kpi.py
    └── routers/             # LEGACY: only __init__.py + stale __pycache__
```

### Confirmed packages

- **`api/`** — Yes. Mounted at `/api` via `backend/crm/api/v1/router.py`.
- **`core/`** — Yes. Shared runtime state, not a thin `database.py` module.
- **`models/`** — Yes. Pydantic under `models/schemas/`.
- **`services/`** — Yes. Domain logic for leads, assignment, WhatsApp, AI, search.

### `main.py` and background scheduler

**Location:** `backend/crm/main.py`

**Still contains `_reminder_scheduler` and `asyncio.sleep()`:**

```python
async def _reminder_scheduler():
    while True:
        try:
            await asyncio.sleep(3600)
            await process_reminders()
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Reminder scheduler error: {e}")
            await asyncio.sleep(60)

@app.on_event("startup")
async def startup_event():
    ...
    reminder_task = asyncio.create_task(_reminder_scheduler())
    asyncio.create_task(process_reminders())  # also runs once at startup
```

**Duplicate helper (unused by `main.py`):** `backend/crm/core/state.py` (lines ~322–337) defines `reminder_scheduler(process_reminders_func)` with the same hourly `asyncio.sleep(3600)` pattern. Only `main.py` wires the live task today.

### Legacy `crm/routers/`

Pre-refactor router **source files were removed**; the folder only has `__init__.py` plus orphaned `.pyc` under `__pycache__/`. Nothing imports `crm.routers` — all routes go through `crm.api.v1.endpoints.*`.

---

## 2. Database and connection management

### Where MongoDB is initialized

**File:** `backend/crm/core/state.py` (not `core/database.py`)

```python
# MongoDB connection
mongo_url = os.environ["MONGO_URL"]
client = AsyncIOMotorClient(mongo_url)
db = client[os.environ["DB_NAME"]]
```

**Exported symbols used app-wide:** `client`, `db`, plus auth (`get_current_user`, `oauth2_scheme`), indexes (`ensure_db_indexes`), seeding (`seed_default_alert_configs`), env config, and helpers (`iso_utc_now`, `utc_now`, `coerce_datetime`).

### How endpoints/services get `db`

**Pattern:** direct module-level import — no DI container, no `get_db()` dependency.

```python
from crm.core.state import db, get_current_user, iso_utc_now, utc_now
```

| Consumer | Import |
|----------|--------|
| `api/v1/endpoints/tasks.py` | `from crm.core.state import db, ...` |
| `api/v1/endpoints/analytics.py` | `from crm.core.state import db, ...` |
| `services/lead_service.py` | `from crm.core.state import db, resolve_project_id, ...` |
| `core/platform_ops.py` | `from crm.core.state import db, ...` |

**Startup/shutdown:** `main.py` calls `ensure_db_indexes()` on startup and `client.close()` on shutdown.

**Index strategy (leads):** indexes on both string and BSON date fields, e.g. `(project_id, updated_at)` and `(assigned_user_id, updated_at_dt)` in `ensure_db_indexes()`.

---

## 3. Lead schema and data types

### Pydantic location

**Primary file:** `backend/crm/models/schemas/lead_schemas.py`

**Re-export:** `backend/crm/models/schemas/__init__.py` exports `LeadBase`, `LeadCreate`, `LeadResponse`, `LeadUpdatePatch`.

### Schema snippets

**`LeadBase` — includes both status fields:**

```python
class LeadBase(BaseModel):
    first_name: str
    last_name: str
    phone: Optional[str] = None
    email: Optional[str] = None
    project: Optional[str] = None
    project_id: Optional[str] = None
    pipeline_category: Optional[str] = None
    lead_status: Optional[str] = "Open"
    lead_source: Optional[str] = None
    original_fw_status: Optional[str] = None
    is_rnr: bool = False
    # ... additional profile fields ...
```

**`LeadResponse` — API-facing dates (Pydantic only exposes `created_at` / `updated_at` as `datetime`, not `_dt` siblings):**

```python
class LeadResponse(LeadBase):
    model_config = ConfigDict(extra="ignore")
    id: str
    normalized_phone: Optional[str] = None
    temperature: str = "Warm"
    intent: str = "Unknown"
    vip: bool = False
    assigned_to: Optional[str] = None
    # ... AI fields ...
    context_updates: List[dict] = []
    created_at: datetime
    updated_at: datetime
```

### MongoDB document field conventions (runtime / seed)

**Dual timestamp pattern** (used consistently in writes):

| Field | Type in MongoDB | Purpose |
|-------|-----------------|---------|
| `created_at` | ISO **string** (`iso_utc_now()`) | Legacy queries, API coercion |
| `created_at_dt` | **BSON `datetime`** (UTC) | Sorting, aggregation, SLA cutoffs |
| `updated_at` | ISO **string** | Same as above |
| `updated_at_dt` | **BSON `datetime`** | Preferred for stale/RNR/dormant logic |

**Write example** from `lead_service.create_lead`:

```python
"created_at": now_iso,
"created_at_dt": now_dt,
"updated_at": now_iso,
"updated_at_dt": now_dt,
```

**Context entries** also use `timestamp` (string) + `timestamp_dt` (datetime).

**Canonical seed shape** (`seed_db_v2.py`):

```python
"lead_status": lead_status,
"lead_source": lead_source,
"original_fw_status": fw_status or None,
"created_at": created_iso,
"created_at_dt": created_dt,
"updated_at": updated_iso,
"updated_at_dt": updated_dt,
```

### `lead_status` vs `original_fw_status`

| Field | In Pydantic | In MongoDB usage |
|-------|-------------|------------------|
| `lead_status` | Yes (`LeadBase`, default `"Open"`) | CRM-normalized status; filters, KPIs, reminders |
| `original_fw_status` | Yes (`LeadBase`, optional) | Raw Freshworks label preserved at seed; analytics aggregations |

**Note:** `LeadUpdatePatch` can update `lead_status` but **not** `original_fw_status` (FW label is provenance, not user-editable in patch).

### Response normalization

Before `LeadResponse(**lead)`, `normalize_lead_for_response` in `lead_service.py` coerces string dates via `coerce_datetime()` from `utils/helpers.py`. Pydantic never declares `updated_at_dt`; it remains in Mongo but is ignored on response via `extra="ignore"` on `LeadResponse`.

### SLA-relevant query helpers

Endpoints like `alerts.py` and `analytics.py` implement **fallback logic**: prefer `updated_at_dt`, else legacy `updated_at` string/date. Same pattern for `created_at_dt` / `created_at`.

---

## 4. Service layer verification

### `lead_service.py`

**Exists:** `backend/crm/services/lead_service.py`

**Functions:** `create_lead`, `list_leads`, `get_lead_by_id`, `update_lead`, `import_csv`, `merge_leads`, plus `normalize_lead_for_response`.

**Leads API is thin** — `api/v1/endpoints/leads.py` delegates all CRUD/upload/merge to `lead_service`; **no direct `db.leads` calls in that router**.

### Other extracted services

| Service | Router delegation |
|---------|-------------------|
| `assignment_service.py` | `assignment_rules.py` |
| `whatsapp_service.py` | `whatsapp.py` |
| `lead_search.py` | Used by `lead_service.list_leads` |
| `context_updates.py` | Dedupe helper for leads |
| `ai_lead_regen.py` | Called from leads GET (background refresh) |

### Where MongoDB writes still live (hybrid migration)

**Lead CRUD:** writes in **`lead_service`** (`insert_one`, `update_one` with `$set`).

**Still in API endpoints (not services):**

| Endpoint module | Collections / operations |
|---------------|-------------------------|
| `tasks.py` | `db.leads.update_one`, `db.tasks.insert_one/update_one` |
| `reminders.py` | `db.leads.find`, `db.reminders`, `db.notifications`, `process_reminders()` |
| `auth.py` | `db.users.insert_one/update_one` |
| `campaigns.py` | `db.campaigns`, `db.leads.update_one` |
| `call_summary.py` | `db.leads.update_one` |
| `transfers.py` | `db.leads.update_one` |
| `activity.py` | `db.user_activity`, lead aggregates |
| `notifications.py` | `db.leads.find`, `db.users`, `db.notifications` |
| `analytics.py` | read-heavy `db.leads` aggregations |
| `my_dashboard.py` | read-only `db.leads` |
| `platform_ops.py` | `db.users`, audit collection |

**Services with writes:** `lead_service`, `assignment_service`, `whatsapp_service`, `ai_lead_regen` — not a full “all writes in services” boundary yet.

---

## 5. SLA / Vercel Cron readiness

1. **Entrypoint:** `backend/index.py` → `crm.main:app`. `vercel.json` has no `crons` array yet.
2. **Existing batch logic:** `reminders.py` exports `process_reminders()` — natural target to expose via a secured cron route instead of `main.py`'s infinite loop.
3. **Date fields for SLA rules:** implement against **`updated_at_dt`** first, with legacy fallback matching `analytics.py` / `alerts.py` patterns.
4. **Status fields:** use **`lead_status`** for business rules; **`original_fw_status`** for FW/RNR label matching where needed (`constants/lead_kpi.py`, analytics `$group`).

---

## 6. Quick reference paths

| Concern | Path |
|---------|------|
| FastAPI app | `backend/crm/main.py` |
| Vercel ASGI | `backend/index.py` |
| Mongo `db` | `backend/crm/core/state.py` |
| Lead Pydantic | `backend/crm/models/schemas/lead_schemas.py` |
| Lead writes | `backend/crm/services/lead_service.py` |
| API mount | `backend/crm/api/v1/router.py` |
| Reminder engine | `backend/crm/api/v1/endpoints/reminders.py` |

---

*Generated as a read-only audit. No application code was modified.*
