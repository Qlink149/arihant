# Arihant CRM

Monorepo: React frontend + FastAPI backend.

## Structure

```
├── backend/                 # API — Vercel project root
│   ├── index.py             # ASGI entry (re-exports crm.main:app)
│   ├── crm/                 # Application package (not named "app" — avoids Vercel conflicts)
│   │   ├── main.py
│   │   ├── core/state.py
│   │   ├── routers/
│   │   ├── services/
│   │   └── constants/
│   ├── requirements.txt
│   └── pyproject.toml       # dependencies + [tool.vercel] entrypoint
│
└── frontend/                # Web — separate Vercel project
```

## Local development

**Backend** (from `backend/`):

```bash
cp env.example .env
pip install -r requirements.txt
uvicorn crm.main:app --reload --port 8000
```

**Frontend** (from `frontend/`):

```bash
# VITE_BACKEND_URL=http://localhost:8000
npm install
npm run dev
```

## Vercel — backend project

| Setting | Value |
|---------|--------|
| Root Directory | `backend` |
| Framework Preset | **FastAPI** |
| Build Command | *(leave empty)* |
| Install Command | *(leave empty — uses `vercel.json` / `pyproject.toml`)* |
| Output Directory | *(leave empty)* |

**Do not** use legacy `builds` + `api.py` — the new Vercel Python runtime skips pip install for that setup.

**Environment variables:** `MONGO_URL`, `DB_NAME`, `SECRET_KEY`, `CORS_ORIGINS`

**Test:** `https://<api-url>/api/health` and `/api/docs`

## Vercel — frontend project

| Setting | Value |
|---------|--------|
| Root Directory | `frontend` |
| Env | `VITE_BACKEND_URL=https://<api-url>` |
