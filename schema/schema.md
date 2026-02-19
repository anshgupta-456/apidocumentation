##### using postgre sql

## table: api_logs(storing raw traffic)
#### column     Type
#### id UUID (Primary Key)
#### endpoint TEXT (NOT NULL)
#### method TEXT (NOT NULL)
#### request_json JSONB
#### response_json JSONB
#### status_code INT
#### latency_ms INT
#### api_version TEXT
#### created_at TIMESTAMP (DEFAULT NOW())


## Table: inferred_schemas(aggregated runtime schema)

#### Column     Type
#### id UUID (Primary Key)
#### endpoint TEXT (NOT NULL)
#### method TEXT (NOT NULL)
#### schema_json JSONB (NOT NULL)
#### sample_size INT (NOT NULL)
#### schema_hash TEXT (NOT NULL)
#### computed_at TIMESTAMP (DEFAULT NOW())

## table: drift_events(detected contract violations)
#### Column     Type
#### id UUID (Primary Key)
#### endpoint TEXT (NOT NULL)
#### method TEXT (NOT NULL)
#### severity TEXT (CHECK: 'low', 'medium', 'high', 'critical')
#### drift_detail JSONB (NOT NULL)
#### expected_schema_hash TEXT
#### observed_schema_hash TEXT
#### openapi_version TEXT
#### ai_explanation TEXT
#### status TEXT (DEFAULT 'open')
#### detected_at TIMESTAMP (DEFAULT NOW())
#### resolved_at TIMESTAMP


## Table: openai version
#### Column Type
#### id UUID (Primary Key)
#### version TEXT (NOT NULL)
#### spec_json JSONB (NOT NULL)
#### spec_hash TEXT (NOT NULL)
#### created_at TIMESTAMP (DEFAULT NOW())