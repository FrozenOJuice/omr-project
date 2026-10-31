from contextlib import asynccontextmanager
import logging

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException

from core.settings import settings
import db.base  # Register the complete SQLAlchemy model graph.
from db.session import check_database_connection
from db.session import close_database_connections
from dependencies.storage_dep import get_storage_repo
from errors.exceptions import AppError
from errors.handler import app_error_handler
from errors.handler import global_exception_handler
from errors.handler import http_exception_handler
from errors.handler import validation_exception_handler
from middleware.request_logging import log_request
from middleware.request_id import add_request_id
from routers.admin_router import router as admin_router
from routers.auth_router import router as auth_router
from routers.course_router import router as course_router
from routers.health_router import router as health_router
from routers.exam_router import router as exam_router
from routers.student_router import router as student_router
from routers.professor_router import router as professor_router
from routers.exam_template_router import router as exam_template_router
from routers.exam_generator_router import router as exam_generator_router
from routers.scan_router import router as scan_router
from routers.exam_answer_key_router import router as exam_answer_key_router
from routers.grading_router import router as grading_router
from routers.review_request_router import router as review_request_router
from routers.notification_router import router as notification_router
from routers.canvas_router import router as canvas_router
from routers.retention_policy_router import router as retention_policy_router
from routers.academic_term_router import router as academic_term_router
from routers.site_branding_router import router as site_branding_router

logging.basicConfig(
    level=logging.INFO,
    format="level=%(levelname)s logger=%(name)s %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s", settings.app_name)
    await check_database_connection()
    logger.info("Database connection verified")
    if settings.frontend_origin:
        # Browsers never send a trailing slash in the Origin header, so a
        # configured origin that has one would silently never match and
        # leave direct-to-storage requests (e.g. presigned chunk uploads)
        # blocked by CORS with no error anywhere in this flow.
        origin = settings.frontend_origin.rstrip("/")
        try:
            get_storage_repo().configure_cors(origin)
            logger.info("Storage bucket CORS configured for %s", origin)
        except Exception:
            logger.exception("Failed to configure storage bucket CORS")
    try:
        yield
    finally:
        logger.info("Shutting down %s", settings.app_name)
        await close_database_connections()
        logger.info("Database connections closed")


app = FastAPI(title=settings.app_name, lifespan=lifespan)

# Exception Handlers
app.add_exception_handler(AppError, app_error_handler)
app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, global_exception_handler)

# Middleware
app.middleware("http")(log_request)
app.middleware("http")(add_request_id)

# Routers
app.include_router(auth_router)
app.include_router(course_router)
app.include_router(admin_router)
app.include_router(health_router)
app.include_router(exam_router)
app.include_router(student_router)
app.include_router(professor_router)
app.include_router(exam_template_router)
app.include_router(exam_generator_router)
app.include_router(scan_router)
app.include_router(exam_answer_key_router)
app.include_router(grading_router)
app.include_router(review_request_router)
app.include_router(notification_router)
app.include_router(canvas_router)
app.include_router(retention_policy_router)
app.include_router(academic_term_router)
app.include_router(site_branding_router)

@app.get("/api/health/live")
async def liveness():
    return {"status": "ok"}


@app.get("/api/health/ready")
async def readiness():
    await check_database_connection()
    return {"status": "ready"}


@app.get("/api/health")
async def health():
    return await readiness()


@app.get("/api/db-test")
async def db_test():
    await check_database_connection()
    return {"db": "connected"}
