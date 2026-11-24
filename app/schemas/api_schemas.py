"""Request bodies for the validator's own management API."""
import uuid
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


class DriftStatusUpdate(BaseModel):
    status: Optional[Literal["open", "acknowledged", "resolved", "ignored"]] = None
    notes: Optional[str] = Field(None, max_length=5000)


class BulkDriftUpdate(BaseModel):
    ids: List[uuid.UUID] = Field(..., min_length=1, max_length=500)
    status: Optional[Literal["open", "acknowledged", "resolved", "ignored"]] = None
    delete: bool = False


class ScanRequest(BaseModel):
    save: bool = True
    use_ai: bool = True
