from datetime import datetime
import uuid
from sqlalchemy import Column, String, Integer, Text, TIMESTAMP
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.sql import func
from app.database.base import Base

class ApiLog(Base):
    __tablename__="api_logs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint = Column(Text, nullable=False)
    method = Column(Text, nullable=False)
    request_json = Column(JSONB)
    response_json = Column(JSONB)
    status_code = Column(Integer)
    latency_ms = Column(Integer)
    api_version = Column(Text)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
class InferredSchema(Base):
    __tablename__ = "inferred_schemas"
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    endpoint = Column(Text, nullable=False)
    method = Column(Text, nullable=False)
    schema_json = Column(JSONB, nullable=False)
    sample_size = Column(Integer, nullable=False)
    schema_hash = Column(Text, nullable=False)
    computed_At = Column(TIMESTAMP(timezone=True), server_default=func.now())

class OpenAPISpec(Base):
    __tablename__ = "openapi_specs"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version_hash = Column(Text, nullable=False)
    spec_json = Column(JSONB, nullable=False)
    normalized_paths = Column(JSONB, nullable=False)
    extracted_at = Column(TIMESTAMP(timezone=True), server_default=func.now())
class DriftEvents(Base):
    __tablename__ = "drift_events"
    id= Column(UUID(as_uuid=True),primary_key=True, default=uuid.uuid4)
    endpoint = Column(Text, nullable=False)
    severity = Column(Text, nullable=False)
    drift_detail = Column(JSONB, nullable=False)
    ai_explanation = Column(Text, nullable=False)
    detected_at = Column(TIMESTAMP(timezone=True), default=datetime.utcnow)