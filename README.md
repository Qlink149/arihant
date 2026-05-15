# Arihant CRM

Monorepo: React frontend + FastAPI backend.

## Structure

```
├── backend/                 # API (deploy this folder to Vercel)
│   ├── app/                 # Application code
│   │   ├── main.py          # FastAPI entry — `app.main:app`
│   │   ├── core/state.py    # DB, auth, models
│   │   ├── routers/
│   │   ├── services/
│   │   └── constants/
│   ├── scripts/             # One-off maintenance
│   ├── tests/
│   ├── csv/                 # Seed data
│   ├── requirements.txt
│   └── pyproject.toml       # Vercel entrypoint
│
└── frontend/                # React app (deploy as separate Vercel project)
    └── src/
```

## Local development

**Backend** (from `backend/`):

```bash
cp env.example .env      # then edit MONGO_URL, DB_NAME, SECRET_KEY
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

**Frontend** (from `frontend/`):

```bash
# .env: REACT_APP_BACKEND_URL=http://localhost:8000
npm install
npm start
```

## Vercel (two projects, same repo)

| Project  | Root Directory | Notes |
|----------|----------------|--------|
| API      | `backend`      | Env: `MONGO_URL`, `DB_NAME`, `SECRET_KEY`, `CORS_ORIGINS` |
| Web      | `frontend`     | Env: `REACT_APP_BACKEND_URL` = API URL |

Test API: `https://<api>/api/health` and `https://<api>/api/docs`
