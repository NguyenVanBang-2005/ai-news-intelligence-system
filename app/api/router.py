from fastapi import APIRouter

from app.api.routes import ai, articles, health, ingestion, sources, topics

api_router = APIRouter()
api_router.include_router(ai.router)
api_router.include_router(health.router)
api_router.include_router(sources.router)
api_router.include_router(articles.router)
api_router.include_router(topics.router)
api_router.include_router(ingestion.router)

