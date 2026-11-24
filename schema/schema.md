# Database schema

PostgreSQL in production (UUID + JSONB), SQLite for local development (same models, portable types).
New columns are added to existing databases automatically on startup.

## api_logs — raw captured traffic
| Column | Type | Notes |
| --- | --- | --- |
| id | UUID (PK) | |
| endpoint | TEXT NOT NULL | concrete path, e.g. `/api/users/3` |
| route_path | TEXT | route template, e.g. `/api/users/{user_id}` |
| method | TEXT NOT NULL | |
| request_json | JSONB | parsed request body |
| response_json | JSONB | parsed JSON response body |
| status_code | INT | |
| latency_ms | INT | |
| api_version | TEXT | from `X-API-Version`, default `v1` |
| client_ip | TEXT | |
| user_agent | TEXT | |
| created_at | TIMESTAMPTZ | default now() |

## inferred_schemas — aggregated runtime schema (stored when it changes)
| Column | Type | Notes |
| --- | --- | --- |
| id | UUID (PK) | |
| endpoint | TEXT NOT NULL | route template |
| method | TEXT NOT NULL | |
| location | VARCHAR(20) | `request` or `response` |
| schema_json | JSONB NOT NULL | flattened field statistics |
| sample_size | INT NOT NULL | |
| schema_hash | TEXT NOT NULL | |
| computed_At | TIMESTAMPTZ | |

## openapi_specs — contract versions (stored only when the spec changes)
| Column | Type |
| --- | --- |
| id | UUID (PK) |
| version_hash | TEXT NOT NULL |
| spec_json | JSONB NOT NULL |
| normalized_paths | JSONB NOT NULL |
| extracted_at | TIMESTAMPTZ |

## drift_events — detected contract violations
| Column | Type | Notes |
| --- | --- | --- |
| id | UUID (PK) | |
| endpoint | TEXT NOT NULL | route template |
| method | TEXT NOT NULL | |
| severity | TEXT NOT NULL | `low`, `medium`, `high` |
| drift_detail | JSONB NOT NULL | issues, categorized drift, documented + observed schemas |
| ai_explanation | TEXT NOT NULL | JSON: summary, cause, impact, doc_fix, code_fix, severity |
| openapi_patch | TEXT | JSON OpenAPI fragment |
| backend_patch | TEXT | generated Pydantic models |
| status | VARCHAR(20) | `open`, `acknowledged`, `resolved`, `ignored` |
| issue_count | INT | |
| fingerprint | TEXT | identical drift updates the active event instead of creating a new one |
| occurrences | INT | how many scans observed this drift |
| last_seen_at | TIMESTAMPTZ | |
| resolved_at | TIMESTAMPTZ | |
| ai_provider | VARCHAR(30) | `groq` or `rule-based` |
| notes | TEXT | |
| detected_at | TIMESTAMPTZ | |
