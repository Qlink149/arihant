# Future `created_at` audit + Today's New Leads follow-ups

**Date:** 2026-09-04  
**Method:** Read-only Mongo against prod `DB_NAME=arihant_crm` via [`backend/scripts/audit_future_created_at.py`](../backend/scripts/audit_future_created_at.py). **No writes.**

Related client report: Dashboard **Today's New Leads** showed leads that were not newly created.

---

## 1. Audit results

| Metric | Count |
|--------|------:|
| `created_at_dt > now` | **6** |
| Future `created_at` string only (no `created_at_dt`) | 0 |
| **Total future-dated leads in CRM** | **6** |

All 6 share:

- ObjectId generation day **2026-05-22** (bulk import cluster)
- Project **ECR - Reserve 16**
- `updated_at` **before** `created_at` (impossible chronology → bad date fields)
- Statuses: Unqualified (3), Gone Cold (3)
- Sources: aurum analytica (5), Facebook (1)

| Name | `created_at_dt` (UTC) | Days ahead (as of audit) | Status |
|------|----------------------|--------------------------|--------|
| K Rajasekar | 2026-12-01 | ~88 | Unqualified |
| S v Sridhar | 2026-11-01 | ~58 | Gone Cold |
| ASHWIN KUMAR | 2026-11-01 | ~58 | Unqualified |
| Nishanth Gangadharan C | 2026-10-01 | ~27 | Gone Cold |
| K Sandeep Narayan | 2026-10-01 | ~27 | Unqualified |
| Swathi | 2026-10-01 | ~27 | Gone Cold |

Re-run anytime:

```bash
cd backend
python scripts/audit_future_created_at.py --limit 50
```

---

## 2. Code fix already applied (metric clamp)

`_todays_leads_clause` create branch is now closed on the upper side:

`created_at_dt` / `created_at` ∈ **`[now − 24h, now]`**

Future-dated rows no longer match **Today's New Leads** even before data repair. Re-enquiry branch (#48) unchanged.

Dashboard copy/tooltip aligned to: *Created last 24h or re-enquired today*.

---

## 3. Data repair — applied 2026-09-04

**Approved by owner:** set `created_at` / `created_at_dt` from **earliest `context_updates` note timestamp** (no CSV).

| Lead | Old `created_at` | New `created_at` |
|------|------------------|------------------|
| K Rajasekar | 2026-12-01 | **2026-01-21T11:58:29+00:00** |
| S v Sridhar | 2026-11-01 | **2026-01-21T11:58:29+00:00** |
| ASHWIN KUMAR | 2026-11-01 | **2026-01-21T11:58:29+00:00** |
| Nishanth Gangadharan C | 2026-10-01 | **2026-01-21T11:58:28+00:00** |
| K Sandeep Narayan | 2026-10-01 | **2026-01-21T11:58:29+00:00** |
| Swathi | 2026-10-01 | **2026-01-21T11:58:29+00:00** |

- Only those 6 ObjectIds; `updated_at` / status / ownership untouched  
- Post-repair: `future_total=0`; Today's leads dropped **20 → 14** (13 true creates + 1 re-enquiry)

---

## 4. Junk / Unqualified / Gone Cold policy (confirmed)

**Decision: keep counting them in Today's New Leads.**

| Status | Still in tile? | Rationale |
|--------|----------------|-----------|
| Junk | Yes | Fresh intake that sales already marked junk is still “today's new” for ops visibility |
| Unqualified | Yes | Same — Action Today is intake awareness, not pipeline quality |
| Gone Cold | Yes | Can appear via re-enquiry (#48) or (before clamp) bad dates; re-enquiries should stay visible |

Excluding these statuses would hide work and conflict with #48 (re-enquired cold leads). If the client later wants an “actionable only” tile, add a **separate** metric — do not silently narrow `todays_leads`.

---

## 5. What fixed the client “not new” complaint

1. **6 future-dated imports** — metric clamp (immediate); data repair (optional cleanup).
2. **1 re-enquiry** — intentional #48; copy now says so.
3. **Remaining ~13** — genuine recent creates (including statuses sales may dislike).
