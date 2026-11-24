"""Request bodies for the validator's own management API."""
from typing import Literal, Optional

from pydantic import BaseModel, Field


class DriftStatusUpdate(BaseModel):
    status: Optional[Literal["open", "acknowledged", "resolved", "ignored"]] = None
    notes: Optional[str] = Field(None, max_length=5000)


class ScanRequest(BaseModel):
    save: bool = True
    use_ai: bool = True
