from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "AI News Intelligence API"
    app_env: str = "development"
    database_url: str = "sqlite:///./data/news.db"
    api_v1_prefix: str = "/api/v1"
    request_timeout_seconds: float = 15
    max_feed_items: int = 50

    # AI configuration
    embedding_model_name: str = (
        "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
    )
    ai_min_documents: int = 10
    ai_batch_size: int = 500
    duplicate_similarity_threshold: float = 0.92

    article_max_download_bytes: int = 5_000_000
    article_max_redirects: int = 3

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

