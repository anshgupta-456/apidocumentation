api-contract-validator/
│
├── app/
│   │
│   ├── main.py
│   ├── config.py
│   ├── dependencies.py
│   │
│   ├── middleware/
│   │   └── logging_middleware.py
│   │
│   ├── database/
│   │   ├── session.py
│   │   ├── base.py
│   │   ├── models.py
│   │   └── migrations/
│   │
│   ├── schemas/
│   │   ├── api_log_schema.py
│   │   ├── inferred_schema_schema.py
│   │   └── drift_event_schema.py
│   │
│   ├── services/
│   │   ├── log_service.py
│   │   ├── schema_inference_service.py
│   │   ├── openapi_service.py
│   │   ├── drift_detection_service.py
│   │   ├── drift_scoring_service.py
│   │   ├── ai_doc_service.py
│   │   ├── spec_update_service.py
│   │   └── alert_service.py
│   │
│   ├── jobs/
│   │   └── drift_analysis_job.py
│   │
│   ├── api/
│   │   ├── business_routes.py
│   │   └── admin_routes.py
│   │
│   └── utils/
│       ├── json_utils.py
│       ├── hashing_utils.py
│       └── normalization_utils.py
│
├── tests/
│
├── alembic/
│
├── requirements.txt
├── .env
└── README.md
