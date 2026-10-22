from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse

from app.api.router import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Backend MVP for collecting and analyzing AI news.",
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


SEARCH_PAGE = Path(__file__).parent / "static" / "index.html"


@app.get("/", include_in_schema=False)
def search_page() -> FileResponse:
    """The news search page. The API itself is documented at /docs."""
    return FileResponse(SEARCH_PAGE)

