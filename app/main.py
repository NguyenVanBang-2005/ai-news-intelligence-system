import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session, sessionmaker

from app.api.router import api_router
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.config import settings
from app.core.security_headers import SecurityHeadersMiddleware
from app.db.session import get_session_factory, session_factory_database_label
from app.services import model_preload
from app.services.ai_jobs import fail_interrupted_jobs

STATIC_DIR = Path(__file__).parent / "static"
SEARCH_PAGE = STATIC_DIR / "index.html"
ADMIN_PAGE = STATIC_DIR / "admin" / "index.html"

# uvicorn configures its own loggers only; "uvicorn.error" is the one that prints INFO
# lines (an app logger would need its own handler for INFO to appear).
startup_logger = logging.getLogger("uvicorn.error")


def startup_session_factory(fastapi_app: FastAPI) -> sessionmaker[Session]:
    """The session factory requests use, honouring dependency overrides (tests)."""
    provider = fastapi_app.dependency_overrides.get(get_session_factory, get_session_factory)
    return provider()


@asynccontextmanager
async def lifespan(fastapi_app: FastAPI) -> AsyncIterator[None]:
    """Before serving, fail AI jobs a previous run left unfinished; with AI_PRELOAD_MODEL,
    start loading the search model without delaying startup. Logs the database in use
    (password masked), so a missing DATABASE_URL is noticed at once."""
    session_factory = startup_session_factory(fastapi_app)
    startup_logger.info("Database: %s", session_factory_database_label(session_factory))
    fail_interrupted_jobs(session_factory)
    if settings.ai_preload_model:
        model_preload.embedding_model.start_background_load()
    yield


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Backend MVP for collecting and analyzing AI news.",
    lifespan=lifespan,
)
app.include_router(api_router, prefix=settings.api_v1_prefix)
# Files of app/static only; html=False, so no index pages and no directory listing.
# The UI routes pages with URL hashes (#/search, #/topics, #/sources), not server routes.
app.mount("/static", StaticFiles(directory=STATIC_DIR, html=False), name="static")
# Public endpoints only; admin endpoints are already behind the token.
app.add_middleware(
    BodySizeLimitMiddleware,
    paths={f"{settings.api_v1_prefix}/ai/search"},
    max_bytes=lambda: settings.ai_search_max_body_bytes,
)
# Added last so it wraps everything, including the body limit's 413 replies.
app.add_middleware(SecurityHeadersMiddleware)


@app.get("/", include_in_schema=False)
def search_page() -> FileResponse:
    """The news search page. The API itself is documented at /docs."""
    return FileResponse(SEARCH_PAGE)


@app.get("/admin/", include_in_schema=False)
def admin_page() -> FileResponse:
    """The admin dashboard. The page itself is public; its API calls need an admin session."""
    return FileResponse(ADMIN_PAGE)
