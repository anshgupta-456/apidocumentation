from fastapi import FastAPI
from app.middleware.logging_middleware import LoggingMiddleware
from app.database.session import engine
from app.database.base import Base
from app.routes.openapi_routes import router as openapi_router
from app.schemas.user_schema import UserCreate
from app.schemas.user_schema import UserResponse
from app.schemas.user_schema import UserCreate
app = FastAPI(title=" API Contract Validator")
app.include_router(openapi_router)
# creating database tables on startup
Base.metadata.create_all(bind=engine)

# adding logging middleware
app.add_middleware(LoggingMiddleware)


# Sameple Business endpoints
# @app.post("/api/users")
# async def create_user(user:dict):
#     return{
#         "id":1,
#         "name":user.get("name"),
#         "age":user.get("age")
#     }
@app.post("/api/users", response_model=UserResponse)
def create_user(user: UserCreate):
    saved_user = {
        "id": 1,
        "name": user.name,
        "age": user.age
    }
    return saved_user

# @app.get("/api/users/{user_id}")
# async def get_user(user_id:int):
#     return{
#         "id": user_id,
#         "name": "Ansh",
#         "age": 21
#     }
@app.get("/api/users/{user_id}", response_model=UserResponse)
def get_user(user_id: int):
    return {
        "id": user_id,
        "name": "Random User",
        "age": 22
    }
