from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.router import api_router
from app.core.body_limit import BodySizeLimitMiddleware
from app.core.config import settings
from app.core.security_headers import SecurityHeadersMiddleware

STATIC_DIR = Path(__file__).parent / "static"
SEARCH_PAGE = STATIC_DIR / "index.html"

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Backend MVP for collecting and analyzing AI news.",
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
