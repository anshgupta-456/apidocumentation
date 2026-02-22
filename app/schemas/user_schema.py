from pydantic import BaseModel
from typing import Optional

class UserCreate(BaseModel):
    name: str
    age: Optional[int] = None

class UserResponse(BaseModel):
    id: int
    name: str
    age: Optional[int] = None