import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import LoginRequired, require_admin
from app.config import BASE_DIR, settings
from app.database.session import init_db
from app.middleware.logging_middleware import LoggingMiddleware
from app.routes.auth_routes import router as auth_router
from app.routes.demo_routes import demo_router
from app.routes.demo_routes import router as demo_api_router
from app.routes.drift_routes import router as drift_router
from app.routes.openapi_routes import router as openapi_router
from app.routes.patch_routes import router as patch_router
from app.routes.traffic_routes import public_router as system_public_router
from app.routes.traffic_routes import router as traffic_router
from app.services.job_service import scheduler
from app.ui.ui_routes import public_router as ui_public_router
from app.ui.ui_routes import router as ui_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("api_contract_validator")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    logger.info(
        "API Contract Validator %s ready | db=%s | ai=%s | auth=%s | monitoring=%s",
        settings.VERSION,
        settings.database_backend,
        "groq" if settings.ai_available else "rule-based",
        "on" if settings.auth_enabled else "OFF (set ADMIN_PASSWORD before exposing publicly)",
        ", ".join(settings.LOG_INCLUDE_PREFIXES),
    )
    task = asyncio.create_task(scheduler(app))
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.VERSION,
    description=(
        "Monitors real API traffic, detects schema drift against the OpenAPI contract, "
        "explains it and generates OpenAPI + backend patches. Dashboard: **/ui**.\n\n"
        "When `ADMIN_PASSWORD` is set, management endpoints require a dashboard session "
        "or an `X-API-Key` header."
    ),
    lifespan=lifespan,
)

app.add_middleware(LoggingMiddleware)
app.add_middleware(GZipMiddleware, minimum_size=1024)
if settings.CORS_ORIGINS:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.CORS_ORIGINS),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(LoginRequired)
async def login_required_handler(request: Request, exc: LoginRequired):
    return RedirectResponse(url=f"/ui/login?next={quote(exc.next_url, safe='')}", status_code=303)


app.mount("/static", StaticFiles(directory=BASE_DIR / "ui" / "static"), name="static")

admin_only = [Depends(require_admin)]

# Public: the monitored business API, health, auth and the login page.
app.include_router(demo_api_router)
app.include_router(system_public_router)
app.include_router(auth_router)
app.include_router(ui_public_router)

# Protected management API + dashboard.
if settings.DEMO_ENABLED:
    app.include_router(demo_router, dependencies=admin_only)
app.include_router(drift_router, dependencies=admin_only)
app.include_router(openapi_router, dependencies=admin_only)
app.include_router(patch_router, dependencies=admin_only)
app.include_router(traffic_router, dependencies=admin_only)
app.include_router(ui_router)


@app.get("/", include_in_schema=False)
def root():
    return RedirectResponse(url="/ui")
