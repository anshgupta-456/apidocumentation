import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.config import BASE_DIR, settings
from app.database.session import init_db
from app.middleware.logging_middleware import LoggingMiddleware
from app.routes.demo_routes import demo_router
from app.routes.demo_routes import router as demo_api_router
from app.routes.drift_routes import router as drift_router
from app.routes.openapi_routes import router as openapi_router
from app.routes.patch_routes import router as patch_router
from app.routes.traffic_routes import router as traffic_router
from app.ui.ui_routes import router as ui_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("api_contract_validator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(
        "API Contract Validator %s ready | db=%s | ai=%s | monitoring=%s",
        settings.VERSION,
        settings.DATABASE_URL.split(":", 1)[0],
        "groq" if settings.ai_available else "rule-based",
        ", ".join(settings.LOG_INCLUDE_PREFIXES),
    )
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=(
        "Monitors real API traffic, detects schema drift against the OpenAPI contract, "
        "explains it and generates OpenAPI + backend patches. Dashboard: **/ui**"
    ),
    lifespan=lifespan,
)

app.add_middleware(LoggingMiddleware)
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.CORS_ORIGINS),
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.mount("/static", StaticFiles(directory=BASE_DIR / "ui" / "static"), name="static")

app.include_router(demo_api_router)
app.include_router(demo_router)
app.include_router(drift_router)
app.include_router(openapi_router)
app.include_router(patch_router)
app.include_router(traffic_router)
app.include_router(ui_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui")
