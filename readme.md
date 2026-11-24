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
| **Dashboard** | Web UI at `/ui`: KPIs, 7-day traffic chart, open drift by severity, busiest endpoints, light/dark mode |
| **Deep drift detection** | Nested objects, arrays, top-level lists, `$ref`/`allOf`/`anyOf`, nullable & required checks, integer ⊂ number |
| **Request *and* response drift** | Detects undocumented fields clients send, missing required fields, wrong types — not only response changes |
| **Path templates** | `/api/users/42` is matched to `/api/users/{user_id}` automatically |
| **Smart severity** | Only real contract violations are reported (an optional field that is always present is *not* drift) |
| **Event lifecycle** | `open → acknowledged → resolved / ignored`, notes, de-duplication (`seen 5×`) instead of duplicate events |
| **Explanations** | Groq LLaMA 3.1 when `GROQ_API_KEY` is set, deterministic rule-based engine otherwise — works fully offline |
| **Patches** | Valid OpenAPI fragment derived from observed traffic + generated Pydantic models; one-click apply to `openapi.generated.json` |
| **Spec versioning** | Snapshots stored only when the spec changes, version diff with **breaking-change** detection, download any version |
| **Traffic explorer** | Browse/filter captured requests with request & response bodies, clear logs per endpoint |
| **Coverage** | Documented vs. observed endpoints, error rate, average/p95 latency |
| **Exports** | Drift events as CSV or JSON |
| **Demo mode** | One click generates realistic traffic, including a legacy endpoint that really drifts |
| **Portable** | PostgreSQL (JSONB/UUID) in production, SQLite with zero setup locally; existing DBs are migrated automatically |
| **Tested** | 21 pytest tests covering the engine, the API and every UI page |

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

### Run the tests

```bash
pytest -q
```

---

## Configuration (`.env`)

| Variable | Default | Description |
| --- | --- | --- |
| `DATABASE_URL` | `sqlite:///./api_validator.db` | Any SQLAlchemy URL, e.g. `postgresql://user:pass@host/db` |
| `GROQ_API_KEY` | – | Enables AI explanations |
| `AI_MODEL` | `llama-3.1-8b-instant` | Groq model |
| `AI_ENABLED` | `true` | Set `false` to force the rule-based engine |
| `LOG_INCLUDE_PREFIXES` | `/api/` | Comma-separated path prefixes that are captured |
| `LOG_MAX_BODY_BYTES` | `65536` | Larger bodies are not stored |
| `INFERENCE_SAMPLE_LIMIT` | `500` | Most recent samples used per endpoint |
| `GENERATED_SPEC_PATH` | `openapi.generated.json` | Output of "Apply patch" |
| `CORS_ORIGINS` | – | Comma-separated allowed origins |

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

### Traffic & system
| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/health` | Database + explanation engine status |
| `GET` | `/stats` | Dashboard numbers |
| `GET` | `/endpoints?all=` | Coverage, traffic, error rate, latency, open drift per endpoint |
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
├── main.py                          # app setup, middleware, routers, static files
├── config.py                        # environment-driven settings
├── database/
│   ├── base.py
│   ├── models.py                    # ApiLog, InferredSchema, OpenAPISpec, DriftEvents
│   └── session.py                   # engine, get_db dependency, auto-migration
├── middleware/
│   └── logging_middleware.py        # pure ASGI traffic capture (streaming-safe)
├── routes/
│   ├── demo_routes.py               # monitored demo API + traffic generator
│   ├── drift_routes.py              # detection, scan, events, export
│   ├── openapi_routes.py            # snapshots, versions, diff, download
│   ├── patch_routes.py              # patch retrieval / apply
│   └── traffic_routes.py            # health, stats, endpoints, logs
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
│   └── traffic_service.py           # coverage, stats, log queries
├── utils/
│   └── schema_utils.py              # flattened field-path helpers
└── ui/
    ├── ui_routes.py
    ├── static/                      # app.css, app.js (no build step)
    └── templates/                   # dashboard, endpoints, drifts, drift detail, openapi, logs
tests/                               # pytest suite
```
