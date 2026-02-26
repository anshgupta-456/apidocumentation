from fastapi import FastAPI
# from app.services.drift_detection_service import SchemaDriftService
# from app.services.ai_explanation_service import AIExplanationService
from app.middleware.logging_middleware import LoggingMiddleware
from app.database.session import SessionLocal, engine
from app.database.base import Base
from app.routes.openapi_routes import router as openapi_router
from app.schemas.user_schema import UserCreate
from app.schemas.user_schema import UserResponse
from app.schemas.user_schema import UserCreate
from app.routes.drift_routes import router as drift_router
from app.routes.drift_view_routes import router as drift_view_router
from app.ui.ui_routes import router as ui_router

app = FastAPI(title=" API Contract Validator")
app.include_router(openapi_router)
app.include_router(drift_router)
app.include_router(drift_view_router)
app.include_router(ui_router)
# creating database tables on startup
Base.metadata.create_all(bind=engine)

# adding logging middleware
app.add_middleware(LoggingMiddleware)
users_db = []
user_id_counter = 1

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
    global user_id_counter
    saved_user = {
        "id": user_id_counter,
        "name": user.name,
        "age": user.age
    }
    users_db.append(saved_user)
    user_id_counter += 1
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
    # return {
    #     "id": user_id,
    #     "name": "Random User",
    #     "age": 22
    # }
    for user in users_db:
        if user ["id"] == user_id:
            return user
    return {"detail": "User not found"}

