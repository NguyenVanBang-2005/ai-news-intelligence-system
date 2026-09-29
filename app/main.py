from fastapi import FastAPI

from app.api.router import api_router
from app.core.config import settings

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="Backend MVP for collecting and analyzing AI news.",
)
app.include_router(api_router, prefix=settings.api_v1_prefix)


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"name": settings.app_name, "docs": "/docs"}

