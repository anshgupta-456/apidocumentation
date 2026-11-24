from typing import List, Optional

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=100, examples=["Ada Lovelace"])
    age: Optional[int] = Field(None, ge=0, le=150, examples=[36])
    email: Optional[str] = Field(None, max_length=200, examples=["ada@example.com"])


class UserUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    age: Optional[int] = Field(None, ge=0, le=150)
    email: Optional[str] = Field(None, max_length=200)


class UserResponse(BaseModel):
    id: int
    name: str
    age: Optional[int] = None
    email: Optional[str] = None


class ProductResponse(BaseModel):
    id: int
    name: str
    price: float
    in_stock: bool
    tags: List[str] = []
