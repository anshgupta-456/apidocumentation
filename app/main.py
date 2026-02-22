from fastapi import FastAPI
from app.middleware.logging_middleware import LoggingMiddleware
from app.database.session import engine
from app.database.base import Base
from app.routes.openapi_routes import router as openapi_router

app = FastAPI(title=" API Contract Validator")
app.include_router(openapi_router)
# creating database tables on startup
Base.metadata.create_all(bind=engine)

# adding logging middleware
app.add_middleware(LoggingMiddleware)


# Sameple Business endpoints
@app.post("/api/users")
async def create_user(user:dict):
    return{
        "id":1,
        "name":user.get("name"),
        "age":user.get("age")
    }

@app.get("/api/users/{user_id}")
async def get_user(user_id:int):
    return{
        "id": user_id,
        "name": "Ansh",
        "age": 21
    }