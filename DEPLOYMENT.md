# Deploying API Contract Validator

**You deploy one service.** The FastAPI backend also serves the dashboard (`/ui`), the
login page and the static files, so there is no separate frontend to host. You need:

| Piece | What to use | Why |
| --- | --- | --- |
| Web service | Render, Railway, Fly.io, Koyeb, any VPS or Docker host | Runs `uvicorn app.main:app` |
| PostgreSQL | [Neon](https://neon.tech) or [Supabase](https://supabase.com) (free tiers, no expiry) or your host's Postgres | Hosted containers wipe their disk on every redeploy, so the SQLite fallback would lose your data |
| Secrets | `ADMIN_PASSWORD`, `SECRET_KEY` | Without a password anyone with the URL can see and delete your data |

> Run **one instance / one worker**. The scheduler (auto-scan, retention) and the demo
> user store live in the process.

---

## Option A — Render (easiest, free tier)

1. **Create a database.** Sign up at neon.tech → *Create project* → copy the connection
   string (`postgresql://user:password@host/dbname?sslmode=require`).
2. **Push this repository to GitHub** (already done if you are reading this there).
3. On [render.com](https://render.com): **New → Blueprint** → pick the repository.
   Render reads `render.yaml` and asks for:
   - `DATABASE_URL` → the Neon connection string
   - `ADMIN_PASSWORD` → a strong password for the dashboard
   - `GROQ_API_KEY` → optional (leave empty for the built-in rule-based explanations)

   `SECRET_KEY` is generated automatically.
4. Click **Apply**. After the build finishes open `https://<your-service>.onrender.com/ui`
   and sign in as `admin` with your password.
5. Optional: set `PUBLIC_BASE_URL=https://<your-service>.onrender.com` and
   `ALERT_WEBHOOK_URL=<slack/discord webhook>` in *Environment* to get alerts with links.

> The free Render plan sleeps after ~15 minutes without traffic; the first request then
> takes ~30 s. Scheduled scans only run while the service is awake.

Manual setup instead of a blueprint: *New → Web Service* →
Build command `pip install -r requirements.txt`, Start command
`uvicorn app.main:app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips="*"`,
Health check path `/health`, then add the environment variables above.

## Option B — Railway

1. *New project → Deploy from GitHub repo*. Railway detects the `Dockerfile` (or the `Procfile`).
2. *New → Database → PostgreSQL*, then in the web service add a variable
   `DATABASE_URL = ${{Postgres.DATABASE_URL}}` (the `postgres://` prefix is handled automatically).
3. Add `ADMIN_PASSWORD` and `SECRET_KEY`, then *Settings → Networking → Generate domain*.

## Option C — Any server with Docker

```bash
docker build -t api-contract-validator .
docker run -d --name acv -p 8000:8000 --restart unless-stopped \
  -e DATABASE_URL="postgresql://user:pass@db-host:5432/acv" \
  -e ADMIN_PASSWORD="change-me" \
  -e SECRET_KEY="$(openssl rand -hex 32)" \
  api-contract-validator
```

Put a reverse proxy with HTTPS in front (Caddy: `your.domain { reverse_proxy localhost:8000 }`).
The container already runs uvicorn with `--proxy-headers`, so secure cookies work behind the proxy.

## Option D — Fly.io

```bash
fly launch --no-deploy          # detects the Dockerfile, choose a region
fly secrets set ADMIN_PASSWORD=change-me SECRET_KEY=$(openssl rand -hex 32) DATABASE_URL=postgresql://...
fly deploy
```

---

## Environment variables

| Variable | Required when hosting | Default | Purpose |
| --- | --- | --- | --- |
| `DATABASE_URL` | **yes** | SQLite file | PostgreSQL URL (`postgres://` or `postgresql://`) |
| `ADMIN_PASSWORD` | **yes** | – | Enables login for the dashboard and management API |
| `SECRET_KEY` | recommended | derived from password | Signs session cookies |
| `ADMIN_USERNAME` | no | `admin` | Login name |
| `ADMIN_API_KEY` | no | – | Lets scripts/CI call the management API with `X-API-Key` |
| `GROQ_API_KEY` | no | – | LLM explanations (rule-based engine otherwise) |
| `AUTO_SCAN_INTERVAL_MINUTES` | no | `0` (off) | Scheduled drift scans |
| `LOG_RETENTION_DAYS` | no | `30` | Delete captured traffic older than N days (0 = keep) |
| `ALERT_WEBHOOK_URL` | no | – | Slack / Discord / Teams webhook for new drift |
| `ALERT_MIN_SEVERITY` | no | `high` | `low`, `medium` or `high` |
| `PUBLIC_BASE_URL` | no | – | Used for links in alerts |
| `LOG_INCLUDE_PREFIXES` | no | `/api/` | Which paths are captured |
| `REDACT_FIELDS` | no | password, token, … | JSON keys masked before logs are stored |
| `DEMO_ENABLED` | no | `true` | Show the demo traffic generator |
| `CORS_ORIGINS` | no | – | Only if another website calls this API from the browser |

## After deploying

- `GET /health` should return `{"status": "ok", "database": "ok", ...}`.
- Open **Settings** in the dashboard: the *Production checklist* shows what is still missing.
- Point real clients at the `/api/...` routes (or add your own routes under `/api/`) — that
  traffic is what the validator learns from.
- Scripts can use the API with `curl -H "X-API-Key: $ADMIN_API_KEY" https://host/stats`.
