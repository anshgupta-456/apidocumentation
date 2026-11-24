"""Sample business API that the validator monitors, plus a demo traffic generator.

`/api/users` is a well-behaved API. `/api/products` simulates a legacy endpoint whose real
responses no longer match its documented model, so drift can be demonstrated instantly.
"""
import random
import threading
from typing import List

import httpx
from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app.schemas.user_schema import ProductResponse, UserCreate, UserResponse, UserUpdate

router = APIRouter(prefix="/api", tags=["Demo business API"])
demo_router = APIRouter(prefix="/demo", tags=["Demo"])

_lock = threading.Lock()
users_db: List[dict] = []
_next_id = {"value": 1}

# Legacy data: the documented ProductResponse says price is a non-null float and there
# is no `discount_percent` / `supplier` field - reality disagrees.
PRODUCTS = [
    {"id": 1, "name": "Mechanical Keyboard", "price": 89.99, "in_stock": True, "tags": ["hardware"],
     "discount_percent": 10, "supplier": {"name": "KeyCo", "country": "DE"}},
    {"id": 2, "name": "USB-C Hub", "price": 34.5, "in_stock": False, "tags": ["hardware", "usb"],
     "discount_percent": 0, "supplier": {"name": "PortMax", "country": "US"}},
    {"id": 3, "name": "Legacy Mouse", "price": "19.99", "in_stock": True, "tags": [],
     "discount_percent": 5, "supplier": {"name": "OldTech", "country": "UK"}},
    {"id": 4, "name": "Monitor Arm", "price": None, "in_stock": True, "tags": ["desk"],
     "discount_percent": 0, "supplier": {"name": "DeskPro", "country": "US"}},
]


def _find_user(user_id: int) -> dict:
    for user in users_db:
        if user["id"] == user_id:
            return user
    raise HTTPException(status_code=404, detail="User not found")


@router.post("/users", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
def create_user(user: UserCreate):
    with _lock:
        saved = {"id": _next_id["value"], **user.model_dump()}
        users_db.append(saved)
        _next_id["value"] += 1
    return saved


@router.get("/users", response_model=List[UserResponse])
def list_users(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)):
    return users_db[offset : offset + limit]


@router.get("/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int):
    return _find_user(user_id)


@router.put("/users/{user_id}", response_model=UserResponse)
def update_user(user_id: int, payload: UserUpdate):
    with _lock:
        user = _find_user(user_id)
        user.update(payload.model_dump(exclude_unset=True))
    return user


@router.delete("/users/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_user(user_id: int):
    with _lock:
        users_db.remove(_find_user(user_id))
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/products", response_model=List[ProductResponse])
def list_products():
    # Returning a JSONResponse bypasses response_model validation -> real drift.
    return JSONResponse(PRODUCTS)


@router.get("/products/{product_id}", response_model=ProductResponse)
def get_product(product_id: int):
    for product in PRODUCTS:
        if product["id"] == product_id:
            return JSONResponse(product)
    raise HTTPException(status_code=404, detail="Product not found")


@demo_router.post("/traffic")
async def generate_demo_traffic(request: Request, requests: int = Query(30, ge=1, le=500)):
    """Send realistic (and partly misbehaving) traffic through the monitored API."""
    names = ["Ada", "Linus", "Grace", "Alan", "Margaret", "Dennis", "Barbara", "Ken"]
    transport = httpx.ASGITransport(app=request.app)
    counts = {"sent": 0, "success": 0, "client_errors": 0}

    async with httpx.AsyncClient(transport=transport, base_url="http://demo.local") as client:
        for i in range(requests):
            roll = random.random()
            if roll < 0.30:
                body = {"name": random.choice(names), "age": random.randint(18, 70)}
                if random.random() < 0.4:
                    body["email"] = f"{body['name'].lower()}@example.com"
                if random.random() < 0.25:
                    body["nickname"] = body["name"][:3]  # undocumented field clients send
                resp = await client.post("/api/users", json=body)
            elif roll < 0.38:
                resp = await client.post("/api/users", json={"age": random.randint(18, 70)})  # missing name
            elif roll < 0.55:
                resp = await client.get(f"/api/users/{random.randint(1, max(2, len(users_db) + 1))}")
            elif roll < 0.62:
                resp = await client.get("/api/users")
            elif roll < 0.85:
                resp = await client.get(f"/api/products/{random.randint(1, 4)}")
            else:
                resp = await client.get("/api/products")
            counts["sent"] += 1
            if resp.status_code < 400:
                counts["success"] += 1
            else:
                counts["client_errors"] += 1

    return {"message": f"Generated {counts['sent']} demo requests", **counts}
