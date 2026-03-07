API Contract Validator — Automatic Schema Drift Detection & Documentation Update.

A FastAPI-based system that monitors real API behavior, detects schema drift, generates AI explanations, and produces actionable OpenAPI & backend patches automatically.

This project helps ensure your API always stays aligned with real-world usage by continuously comparing:

✔ Actual runtime requests/responses
vs
✔ Your documented OpenAPI contract

🚀 Features Implemented So Far
✅ 1. OpenAPI Specification Extraction

Extracts the full OpenAPI schema directly from the running FastAPI application.

Resolves $ref references for accurate schema parsing.

Stores:

Original OpenAPI specification

Normalized paths

Extracted version hash

Timestamp

Helps track documentation changes over time.

Endpoint:
GET /extract-openapi

✅ 2. Runtime Schema Inference

Captures real request & response bodies (via LoggingMiddleware).

Builds a normalized runtime schema model:

Field types

Nullable detection

Required field inference (presence_percent == 100%)

Provides an accurate reflection of real API usage patterns.

✅ 3. Schema Drift Detection Engine

A powerful engine that compares:

Expected (OpenAPI)	Runtime (Actual API Behavior)

Detection categories include:

Missing fields

Extra undocumented fields

Type mismatches

Nullable drifts

Required field inconsistencies

Endpoint:
GET /detect-drift/{endpoint}

✅ 4. AI-Generated Drift Explanation

Every drift event receives an automatically generated AI explanation including:

Summary

Cause

Impact

Required documentation fixes

Required backend fixes

Severity classification (low/medium/high)

Powered by Groq LLaMA-3.1-8B.

✅ 5. Drift Event Storage in Database

We store each drift event in the database with:

Endpoint

Method

Severity

Drift details (JSON)

AI explanation

OpenAPI patch

Backend patch

Timestamp

Endpoints:
GET /drift-events
GET /drift-events/{id}

✅ 6. AI Patch Generation (OpenAPI + Backend)

When drift is detected, the system automatically generates:

🔹 OpenAPI Patch

Suggests modifications to keep documentation aligned with reality.

🔹 Backend Patch

Suggests code-level fixes such as:

Marking fields required

Adjusting Pydantic schema

Adding/removing fields

Generated patches are saved into patches.json for later application.

✅ 7. Patch Retrieval API

Retrieve any saved patch via:

Endpoint:
POST /patch/apply?endpoint=/api/users&method=POST

This returns the generated fix (OpenAPI + backend patch).

✅ 8. Sample Business API (Demo Data)

Simple user endpoints for testing:

POST /api/users

GET /api/users/{user_id}

Uses in-memory database (users_db) and incremental ID generator.

📂 Project Structure
app/
  ├── routes/
  │     ├── drift_routes.py
  │     ├── drift_view_routes.py
  │     ├── openapi_routes.py
  │     ├── patch_routes.py
  ├── services/
  │     ├── drift_detection_service.py
  │     ├── openapi_extraction_service.py
  │     ├── ai_explanation_service.py
  │     ├── ai_patch_service.py
  ├── middleware/
  │     └── logging_middleware.py
  ├── database/
  │     ├── base.py
  │     ├── models.py
  │     ├── session.py
  ├── schemas/
        └── user_schema.py
main.py
patches.json
🧪 How to Test the System
1️⃣ Extract OpenAPI Spec
GET /extract-openapi
2️⃣ Trigger Drift

Make a POST request missing required fields, e.g.:

POST /api/users
{
  "age": 21
}
3️⃣ Detect Drift
GET /detect-drift/api/users
4️⃣ View Drift History
GET /drift-events
5️⃣ Retrieve AI Patch
POST /patch/apply?endpoint=/api/users&method=POST




You now have the core engine of a real-world API Documentation Automation System.
