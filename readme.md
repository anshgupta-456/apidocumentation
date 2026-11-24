# API Contract Validator

**Automatic schema-drift detection, explanation and documentation patching for FastAPI.**

The validator sits next to your API, records real traffic, and continuously compares what your
endpoints *actually* send and receive with what your OpenAPI contract *says* they do. When the two
drift apart it tells you exactly what changed, why it matters, and gives you a ready-to-apply
OpenAPI patch plus matching Pydantic models.

```
 real requests ─► LoggingMiddleware ─► api_logs ─► Schema inference ─┐
                                                                     ├─► Drift engine ─► Drift events ─► Dashboard
 FastAPI app ───► OpenAPI extraction ─► openapi_specs (versioned) ───┘        │
                                                                              └─► Explanation (Groq or rule-based)
                                                                              └─► OpenAPI patch + Pydantic models
```

---

## Highlights

| Area | What you get |
| --- | --- |
| **Dashboard** | Contract health score, KPI tiles, interactive traffic / latency charts (24h · 7d · 30d), status-code breakdown, live auto-refresh, light/dark mode, mobile layout |
| **Endpoint pages** | Per-operation traffic, latency, status codes, field-by-field *contract vs. reality* table, drift history and recent requests |
| **API playground** | Send real requests from the browser with path/query params and example bodies generated from the spec; replay any captured request |
| **Command palette** | `Ctrl K` to jump to any page, endpoint or action; `g d`, `g e`, `g x`… shortcuts |
| **Deep drift detection** | Nested objects, arrays, top-level lists, `$ref`/`allOf`/`anyOf`, nullable & required checks, integer ⊂ number |
| **Request *and* response drift** | Detects undocumented fields clients send, missing required fields, wrong types — not only response changes |
| **Path templates** | `/api/users/42` is matched to `/api/users/{user_id}` automatically |
| **Event lifecycle** | `open → acknowledged → resolved / ignored`, notes, bulk actions, de-duplication (`seen 5×`) |
| **Explanations** | Groq LLaMA 3.1 when `GROQ_API_KEY` is set, deterministic rule-based engine otherwise — works fully offline |
| **Patches** | Valid OpenAPI fragment derived from observed traffic + generated Pydantic models; one-click apply to `openapi.generated.json` |
| **Spec versioning** | Snapshots stored only when the spec changes, version diff with **breaking-change** detection |
| **Automation** | Scheduled drift scans, log retention, Slack/Discord/Teams webhook alerts, built-in keep-alive so free hosting never sleeps |
| **Security** | Optional login (signed HttpOnly cookie, rate-limited), `X-API-Key` for scripts, sensitive fields masked before logs are stored |
| **Deploy anywhere** | Dockerfile, Render blueprint, Procfile, `postgres://` URLs handled, health check, GitHub Actions CI |
| **Portable** | PostgreSQL (JSONB/UUID) in production, SQLite with zero setup locally; existing DBs are migrated automatically |
| **Tested** | 39 pytest tests (SQLite + PostgreSQL in CI) covering the engine, auth, alerts, retention, keep-alive, the API and every UI page |

---

## Hosting

The backend serves the dashboard too, so you deploy **one service + one PostgreSQL database**.
Set `DATABASE_URL`, `ADMIN_PASSWORD` and `SECRET_KEY` on your host. Step-by-step guides for
Render, Railway, Docker and Fly.io are in **[DEPLOYMENT.md](DEPLOYMENT.md)**.

---

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt

cp .env.example .env               # optional - defaults work out of the box
uvicorn app.main:app --reload
```

Open **http://localhost:8000/ui** and click **Generate demo traffic → Scan all endpoints**.
Interactive API docs live at **/docs**.

Without `DATABASE_URL` the app uses a local SQLite file (`api_validator.db`).
Without `GROQ_API_KEY` explanations come from the built-in rule-based engine.
Without `ADMIN_PASSWORD` the dashboard is open (fine locally — always set it when hosting).

### Run the tests

```bash
pytest -q
```

---

## Configuration

All settings are environment variables — see [`.env.example`](.env.example) and the table in
[DEPLOYMENT.md](DEPLOYMENT.md#environment-variables). The **Settings** page in the dashboard
shows the active configuration and a production checklist.

---

## API reference

### Drift detection
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/detect-drift/{endpoint}?method=&save=&use_ai=` | Analyse one endpoint (all methods with traffic when `method` is omitted) |
| `POST` | `/drift/scan` | Analyse every endpoint that has traffic. Body: `{"save": true, "use_ai": true}` |
| `GET` | `/drift-events?severity=&status=&endpoint=&method=&limit=&offset=` | Paginated, filterable list (`status=active` = open + acknowledged) |
| `GET` | `/drift-events/export?format=csv\|json` | Download events |
| `GET` | `/drift-events/{id}` | Full event: issues, explanation, patches, schemas |
| `PATCH` | `/drift-events/{id}` | `{"status": "resolved", "notes": "..."}` |
| `POST` | `/drift-events/bulk` | `{"ids": [...], "status": "resolved"}` or `{"ids": [...], "delete": true}` |
| `DELETE` | `/drift-events/{id}` | Delete an event |

### Patches
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/patch/{event_id}` | OpenAPI patch + backend (Pydantic) patch |
| `POST` | `/patch/apply?event_id=` | Merge the patch into the live spec → `openapi.generated.json` (also accepts `?endpoint=&method=`) |
| `GET` | `/patch/generated-spec` | Download the generated spec |

### OpenAPI versions
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/extract-openapi` | Snapshot the live spec (stored only if changed, returns a diff vs. the previous version) |
| `GET` | `/openapi-specs` | List versions |
| `GET` | `/openapi-specs/{id\|latest}` | Version detail |
| `GET` | `/openapi-specs/{id}/download` | Raw spec JSON |
| `GET` | `/openapi-specs/diff?base=&target=` | Diff two versions (`target` defaults to the live spec) |

### Auth
| Method | Path | Description |
| --- | --- | --- |
| `POST` | `/auth/login` | `{"username", "password"}` → session cookie |
| `POST` | `/auth/logout` | Clear the session |
| `GET` | `/auth/me` | Current user |

When `ADMIN_PASSWORD` is set every endpoint below (except `/health` and the monitored `/api/...`
routes) needs a session cookie or `X-API-Key: <ADMIN_API_KEY>`.

### Traffic & system
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Database + explanation engine status (public) |
| `GET` | `/health/live` | Liveness probe without database access (public; used by keep-alive and health checks) |
| `GET` | `/stats?range=24h\|7d\|30d` | Dashboard numbers, time series, status codes, health score |
| `GET` | `/endpoints?all=` | Coverage, traffic, error rate, latency, open drift per endpoint |
| `GET` | `/endpoints/detail?path=&method=&range=` | One operation: traffic, latency, schema comparison, drift history |
| `GET` | `/playground/operations?all=` | Request templates generated from the spec |
| `GET` | `/system/config` | Active (non-secret) configuration and background job status |
| `POST` | `/system/scan` | Run the scheduled scan now |
| `POST` | `/system/cleanup?days=` | Delete old captured traffic |
| `POST` | `/alerts/test` | Send a test webhook alert |
| `GET` | `/api-logs?endpoint=&method=&status=success\|error\|<code>` | Captured traffic |
| `GET` | `/api-logs/{id}` | One captured request |
| `DELETE` | `/api-logs?endpoint=&method=` | Clear captured traffic |

### Demo business API (monitored)
| Method | Path | Notes |
| --- | --- | --- |
| `POST` | `/api/users` | Create user (`name` required, `age`, `email` optional) |
| `GET` | `/api/users` | List users |
| `GET` / `PUT` / `DELETE` | `/api/users/{user_id}` | Read / update / delete (proper 404s) |
| `GET` | `/api/products`, `/api/products/{product_id}` | *Legacy* endpoints whose real payload drifts from `ProductResponse` |
| `POST` | `/demo/traffic?requests=60` | Generate realistic traffic (including misbehaving clients) |

---

## How drift is classified

| Location | Issue | Severity |
| --- | --- | --- |
| response | type mismatch, unexpected `null`, required field missing | **high** |
| response | undocumented field | medium |
| response | documented optional field never returned | low |
| request | undocumented field sent by clients, required field omitted, wrong type, unexpected `null` | medium |
| endpoint | traffic on a route that is not in the spec / body without a documented schema | medium |

Allowed behaviour (optional field always present, nullable field never null, optional request
field never sent) is **not** reported. Error responses (4xx/5xx) are excluded from response
inference so `{"detail": ...}` bodies never show up as drift.

---

## Try it manually

```bash
# 1. a well-behaved request and two misbehaving ones
curl -X POST localhost:8000/api/users -H "Content-Type: application/json" -d '{"name": "Ada", "age": 36}'
curl -X POST localhost:8000/api/users -H "Content-Type: application/json" -d '{"name": "Bob", "nickname": "B"}'
curl -X POST localhost:8000/api/users -H "Content-Type: application/json" -d '{"age": 21}'

# 2. hit the legacy endpoint
curl localhost:8000/api/products/3

# 3. detect drift
curl "localhost:8000/detect-drift/api/users?method=POST"
curl -X POST localhost:8000/drift/scan

# 4. review and apply
curl "localhost:8000/drift-events?status=active"
curl -X POST "localhost:8000/patch/apply?event_id=<id>"
```

---

## Project structure

```
app/
├── main.py                          # app setup, middleware, routers, auth wiring, scheduler
├── config.py                        # environment-driven settings
├── auth.py                          # optional login: signed session cookie, API key, rate limit
├── database/
│   ├── base.py
│   ├── models.py                    # ApiLog, InferredSchema, OpenAPISpec, DriftEvents
│   └── session.py                   # engine, get_db dependency, auto-migration
├── middleware/
│   └── logging_middleware.py        # pure ASGI traffic capture (streaming-safe)
├── routes/
│   ├── auth_routes.py               # login / logout / me
│   ├── demo_routes.py               # monitored demo API + traffic generator
│   ├── drift_routes.py              # detection, scan, events, export
│   ├── openapi_routes.py            # snapshots, versions, diff, download
│   ├── patch_routes.py              # patch retrieval / apply
│   └── traffic_routes.py            # health, stats, endpoints, playground, logs, system jobs
├── schemas/
│   ├── api_schemas.py
│   └── user_schema.py
├── services/
│   ├── schema_inference_service.py  # runtime schema from traffic (nested + arrays)
│   ├── openapi_extraction_service.py# documented schema from the spec ($ref/anyOf/allOf)
│   ├── drift_detection_service.py   # comparison, severity, de-duplication, scans
│   ├── ai_explanation_service.py    # Groq + rule-based fallback
│   ├── patch_generation_service.py  # OpenAPI patch + Pydantic model generation
│   ├── openapi_patch_service.py     # merge patch into spec
│   ├── spec_diff_service.py         # version diff + breaking changes
│   ├── traffic_service.py           # coverage, time series, endpoint detail, log queries
│   ├── playground_service.py        # request templates + example bodies from the spec
│   ├── alert_service.py             # webhook alerts
│   └── job_service.py               # scheduled scans + log retention
├── utils/
│   └── schema_utils.py              # flattened field-path helpers
└── ui/
    ├── ui_routes.py
    ├── static/                      # app.css, app.js (no build step)
    └── templates/                   # dashboard, endpoints, endpoint, drifts, playground, settings, login…
tests/                               # pytest suite
Dockerfile · render.yaml · Procfile  # deployment
DEPLOYMENT.md                        # hosting guide
```
