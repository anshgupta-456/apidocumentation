##### using postgre sql

## table: api_logs(storing raw traffic)
#### column     Type
#### id         UUID
#### endpoint   TEXT
#### method     TEXT
#### request_json   JSONB
#### response_json  JSONB
#### status_code    INT
#### created_at     TimeStamp


## Table: inferred_schemas(aggregated runtime schema)

#### Column     Type
#### id         UUID
#### endpoint   TEXT
#### method     TEXT
#### schema_json   JSONB
#### computed_at     TimeStamp

## table: drift_events(detected contract violations)
#### Column     Type
## table: api_logs(storing raw traffic)
#### column     Type
#### id         UUID
#### endpoint   TEXT
#### severity     TEXT
#### drift_detail   JSONB
#### ai_explanatuion    Text
#### detected_at     TimeStamp
