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