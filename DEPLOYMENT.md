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

> **Sleeping is handled for you.** The free Render plan sleeps after 15 minutes without
> traffic. The app pings its own public URL (`RENDER_EXTERNAL_URL`, set by Render) every
> 10 minutes, so it stays awake and scheduled scans keep running. See
> [Keeping a free instance awake](#keeping-a-free-instance-awake) for limits and the backup bot.

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
| `KEEP_ALIVE_URL` | no | `RENDER_EXTERNAL_URL` | Public URL the app pings to stay awake (automatic on Render) |
| `KEEP_ALIVE_INTERVAL_MINUTES` | no | `10` | Ping interval; keep it under 15 on Render, `0` turns it off |
| `DEMO_ENABLED` | no | `true` | Show the demo traffic generator |
| `CORS_ORIGINS` | no | – | Only if another website calls this API from the browser |

## Keeping a free instance awake

Free web services on Render sleep after **15 minutes** without incoming requests and take
about a minute to wake up. Two layers keep this app awake:

1. **Built-in pinger (automatic).** A background job requests `<your-url>/health/live` every
   10 minutes. On Render the URL comes from `RENDER_EXTERNAL_URL`, so nothing needs to be
   configured; on other hosts set `KEEP_ALIVE_URL`. Its status is shown on the **Settings** page.
2. **GitHub Actions backup bot (optional).** `.github/workflows/keep-alive.yml` pings the same
   URL every 10 minutes from outside, which also wakes the service if it ever fell asleep. Enable
   it in GitHub: *Settings → Secrets and variables → Actions → Variables → New repository variable*
   named `KEEP_ALIVE_URL` with your Render URL. (Free for public repositories. GitHub may delay
   scheduled runs and disables them after 60 days without commits; re-enable from the *Actions* tab.)

Things to know:

- **Render free hours:** 750 instance hours per workspace per month. One always-on service uses
  ~744, so this only fits if it is your *only* free web service. A second always-on free service
  would run out of hours and be suspended until the next month.
- **Database stays cheap:** pings and Render's health check use `/health/live`, which never
  touches the database, so Neon can still scale to zero between real requests and scheduled jobs.
- To turn the keep-alive off, set `KEEP_ALIVE_INTERVAL_MINUTES=0`.

## After deploying

- `GET /health` should return `{"status": "ok", "database": "ok", ...}` (`/health/live` is the lightweight, database-free check).
- Open **Settings** in the dashboard: the *Production checklist* shows what is still missing.
- Point real clients at the `/api/...` routes (or add your own routes under `/api/`) — that
  traffic is what the validator learns from.
- Scripts can use the API with `curl -H "X-API-Key: $ADMIN_API_KEY" https://host/stats`.
